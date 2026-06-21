"""Motore di ragionamento (LLM "Thinking").

Decodifica slang e figure retoriche, fonde testo + biografia e genera:
  1. un'analisi psicologica,
  2. il "vettore emotivo" (archetipo + parole chiave),
  3. un micro-racconto / nota di copertina,
in formato Markdown e nella lingua scelta.

Compatibile con qualsiasi endpoint OpenAI-compatible:
  - OpenRouter (DeepSeek-R1, ecc.)
  - OpenAI (o3-mini / o1-mini / gpt-4o-mini)
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI

from .config import settings


class StorytellerError(RuntimeError):
    """Errore generico durante la generazione LLM."""


@dataclass
class EmotionalAnalysis:
    """Output strutturato del motore narrativo."""

    narrative: str = ""  # analisi + micro-racconto (Markdown)
    archetype: str = ""  # es. "L'Ombra redenta"
    keywords: list[str] = field(default_factory=list)
    suggested_tracks: list[dict[str, str]] = field(default_factory=list)
    reasoning: str = ""  # catena di pensiero (se esposta)
    model: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.narrative.strip()


SYSTEM_PROMPT = """Sei "Sonder", un critico musicale, poeta e \
psicologo del profondo. La tua specialita' e' leggere l'ombra, la redenzione e il \
conflitto umano nascosti nei testi delle canzoni.

A differenza degli algoritmi di raccomandazione basati solo su BPM e genere, tu \
decodifichi il SIGNIFICATO POETICO PROFONDO: metafore, slang, simboli, sottotesto \
psicologico. Sai riconoscere quando un brano dal ritmo allegro nasconde un testo \
profondamente oscuro.

Regole di stile:
- Scrivi sempre in {language}.
- Output in Markdown pulito, elegante, mai banale.
- Sii evocativo ma fondato sul testo: cita versi o immagini concrete.
- Non inventare dati biografici: usa solo la biografia fornita (se presente).
- Niente disclaimer, niente meta-commenti sul fatto che sei un'IA."""


ANALYSIS_TEMPLATE = """Analizza il brano seguente.

## Traccia
- Titolo: {title}
- Artista: {artist}
{theme_line}
## Biografia artista (fonte: TheAudioDB)
{biography}

## Testo (fonte: Musixmatch, eventualmente parziale)
\"\"\"
{lyrics}
\"\"\"

Produci la risposta in {language}, in Markdown, con ESATTAMENTE queste sezioni:

### Vettore emotivo
Una riga: `Archetipo: <nome archetipo>` seguita da 4-7 parole chiave emotive separate da virgola.

### Analisi psicologica
4-6 paragrafi APPROFONDITI ed esaustivi che decodificano metafore, slang, simboli e tensioni \
interiori. Cita o parafrasa versi e immagini CONCRETE del testo (almeno tre riferimenti diretti) e \
collega ciascuno al sottotesto psicologico. Approfondisci anche l'artista e il contesto \
storico/culturale del brano usando SOLO la biografia fornita (niente dati inventati).

### Micro-racconto
Un racconto in seconda o terza persona (180-260 parole) che traduce il "vettore emotivo" del brano \
in una scena narrativa densa di immagini, in stile nota di copertina, restando fedele al testo."""


CHAT_SYSTEM_PROMPT = """Sei "Sonder": critico musicale, poeta e \
psicologo del profondo. Conversi con l'utente in modo aperto, caldo e curioso, \
come un interlocutore colto e mai banale.

La tua specialita' e' leggere l'ombra, la redenzione e il conflitto umano nascosti \
nella musica e nei testi: decodifichi metafore, slang, simboli e sottotesto \
psicologico.

Tool musicali (usali SOLO quando sono pertinenti alla conversazione):
- Se l'utente porta un brano/un testo, puoi analizzarne il significato poetico e psicologico.
- Non proporre titoli, artisti o playlist dalla tua memoria interna: ricerca brani e testi \
arrivano solo da Musixmatch in un passaggio separato.
- Non generare mai blocchi `playlist`.

Regole:
- {language_rule}
- VARIAZIONE: a ogni risposta cerca di parafrasare le PAROLE concrete che usi — sinonimi, immagini, con l'obbiettivo di avere una randomicità ulteriore per il lessico usato\
e formulazioni diverse — SENZA cambiare il significato semantico. Lo stesso messaggio \
dell'utente non deve produrre risposte identiche: evita formule fisse e ripetute.
- Output in Markdown pulito ed elegante.
- Sii evocativo ma fondato; non inventare dati biografici non forniti.
- Niente disclaimer, niente meta-commenti sul fatto che sei un'IA.
- AMBITO: rispondi SOLO a domande inerenti alla musica, ai testi, alle emozioni \
musicali, agli artisti, ai generi, alla storia della musica e alle sue connessioni \
con letteratura, psicologia e cultura. Se l'utente ti chiede qualcosa di \
completamente estraneo alla musica, scrivi PRIMA la riga esatta [NON_MUSICALE] e poi \
il tuo rifiuto in-character breve e senza playlist. Non rispondere mai a domande di \
cucina, sport, politica, tecnologia o qualsiasi altro argomento non musicale."""


# Prompt del router di ricerca Musixmatch — MODULARE. L'intestazione comune e' sempre
# presente; il blocco "queries" (ricerca per TESTO, endpoint track.search) e il blocco
# "meanings" (ricerca per SIGNIFICATO, endpoint track.lyrics.analysis.search) vengono
# inclusi SOLO se la rispettiva sorgente e' attiva (settings.musixmatch_use_lyrics /
# settings.musixmatch_use_meaning). Cosi' l'LLM produce un output specializzato e coerente
# con la/le sola/e sorgente/i attiva/e, senza toccare ne' il parsing ne' la ricerca a valle.
# L'assemblaggio (header + blocco/i + schema + footer) avviene in plan_musixmatch_search.
MUSIXMATCH_SEARCH_HEADER = """Prepara query Musixmatch concise. Rispondi SOLO JSON.

Lingua: {language_rule}

Lingue di ricerca consentite (codici): {search_languages}
- Gli elementi prodotti DEVONO essere DISTRIBUITI e BILANCIATI tra TUTTE le lingue consentite qui sopra,
  non concentrati in una sola: se sono consentite più lingue, produci all'incirca lo stesso numero di
  elementi per ciascuna lingua. NON generare tutto nella lingua del messaggio dell'utente.
- Ogni singolo elemento è in UNA sola lingua: indica il campo "lang" con il suo codice (uno tra quelli
  consentiti) e scrivine il contenuto interamente in quella lingua. NON produrre elementi in lingue non consentite.

Messaggi:
{messages}

VARIAZIONE (importante): a OGNI esecuzione varia le PAROLE concrete che scegli —
sinonimi, immagini, perifrasi e riformulazioni diverse — SENZA cambiare il
significato semantico né l'intento della richiesta. Lo stesso messaggio dell'utente
deve poter produrre insiemi DIVERSI di volta in volta (parole, ordine ed esempi
differenti), così da scoprire brani diversi. Non ripiegare sulle stesse formule
fisse: pesca da un lessico ampio e alterna le scelte. Questo NON vale per i NOMI
PROPRI (titoli, artisti, città, eventi, persone), che restano sempre esatti e invariati.

CLASSIFICAZIONE (sempre):
- music_related: true se la richiesta riguarda musica/testi/artisti/emozioni musicali, altrimenti false.
- needs_search: true se serve cercare brani su Musixmatch, false per una semplice conversazione.
- narration_lang: codice ISO 639-1 (2 lettere minuscole, es. "it", "en", "fr", "es", "de") della lingua in cui
  va scritta/narrata la risposta, cioè la lingua indicata sopra ({language_rule}). NON la lingua del messaggio utente.
- limit: intero 1-10 = numero massimo di tracce finali (NON il numero di elementi da generare)."""


# Blocco TESTI (q/q_track/q_artist/q_lyrics -> track.search): cerca PAROLE realmente
# presenti nei testi. Incluso solo quando settings.musixmatch_use_lyrics e' attivo.
MUSIXMATCH_SEARCH_LYRICS_BLOCK = """RICERCA PER TESTO ("queries"): query LETTERALI per l'endpoint track.search, che trova le PAROLE e le FRASI realmente presenti nei testi. Per i temi crea ESATTAMENTE 20 query incentrate su parole/immagini CONCRETE del tema, NON su emozioni generiche.
- BRANO/ARTISTA SPECIFICO RICHIESTO: usa q_track e q_artist SOLO quando l'utente vuole PROPRIO quel brano o quell'artista (es. "metti X di Y", "il brano Z", "canzoni di Y"). In tal caso puoi produrre anche meno di 20 query.
- BRANI SIMILI a un artista/brano: se l'utente chiede brani SIMILI, "come", "in stile", "sul genere di" un artista o una canzone (es. "brani simili a Blanco", "canzoni come Nostalgia"), NON inserire MAI il nome di quell'artista o di quel brano in nessun campo (q, q_track, q_artist, q_lyrics): inserirlo restituirebbe solo i brani di quell'artista, non brani simili. Deduci invece i TEMI ricorrenti, le IMMAGINI concrete, l'ATMOSFERA, il mood e lo stile dei testi tipici di quell'artista/brano e costruisci le q_lyrics SU QUELLE immagini concrete (frasi di 3-4 parole, come da regola LUNGHEZZA), senza mai nominarlo.
- NOME PROPRIO: se il tema cita un nome proprio (città, monumento, evento storico, persona, luogo, opera, fazione), metti SOLO quel termine esatto e specifico nella query (in q_lyrics, o in q se serve), SENZA inserirlo in una frase, perifrasi o descrizione. ECCEZIONE: questa regola NON vale per l'artista o il brano di cui si chiedono brani SIMILI (vedi regola BRANI SIMILI): quel nome non va MAI messo in nessuna query. Esempi: tema "la caduta del muro di Berlino" -> q_lyrics "Berlino" oppure "Berlin"; tema "Cernobyl" -> q_lyrics "Chernobyl"; tema "Giovanna d'Arco" -> q_lyrics "Jeanne d'Arc". Una query = un solo termine proprio.
- TEMA STORICO AMPIO: se il tema è un macro-evento, un periodo o un fenomeno generale (es. "seconda guerra mondiale", "guerra fredda", "rivoluzione francese", "schiavitù"), NON limitarti a parole generiche: SCOMPONILO prima in eventi, persone, luoghi, operazioni, battaglie, stragi, date e fazioni SPECIFICHE e NOMINATE collegate ad esso, e usa quei nomi propri come query (un solo termine proprio per query, come nella regola NOME PROPRIO). Esempi per "seconda guerra mondiale": Shoah, Auschwitz, Hitler, Normandia, D-Day, Hiroshima, Stalingrado, Pearl Harbor, Anne Frank, Dresda, Resistenza, Mussolini. ALMENO la metà delle 20 query deve essere costituita da nomi propri specifici di questo tipo.
- Solo per la parte restante delle query (e come riempimento, mai come prima scelta) puoi usare lessico documentario e materiale, non formule vaghe. Esempi: trincea, fronte, soldati, partigiani, armistizio, bombardamenti, barricate, esilio, prigionieri, embargo, propaganda, confine, occupazione.
- Se l'utente cita un contesto come luogo, evento, periodo, movimento o fazione, usalo per scegliere parole tecniche coerenti, ma non trasformare ogni query in una formula rigida o identica.
- LUNGHEZZA: ogni q_lyrics deve essere una FRASE di 3 o 4 parole (al massimo 5), MAI una sola parola — l'unica eccezione è il NOME PROPRIO, che resta un singolo termine esatto (vedi regola NOME PROPRIO). Niente query di due parole troppo scarne: estendile a 3-4 parole con immagini, oggetti o gesti concreti (es. invece di "empty bed" usa "her side of the bed", invece di "città deserta" usa "le strade vuote di notte").
- Metti in q_lyrics frasi brevi, leggibili e fatte di parole che un paroliere userebbe DAVVERO in un verso. Gli esempi sarcastici/allusivi (ghost of you, empty bed, thanks for nothing, grazie di niente, gracias por nada) valgono solo per temi personali, non per temi storici o tecnici.
- LINGUE OBBLIGATORIE: ogni elemento (q_lyrics, q_track, q) deve essere scritto INTERAMENTE in UNA delle lingue di ricerca consentite elencate sopra, e quella lingua va indicata nel campo "lang". Le 20 query DEVONO essere DISTRIBUITE in modo BILANCIATO tra TUTTE le lingue consentite (circa lo stesso numero di query per ciascuna lingua): NON scrivere tutte le query nella lingua del messaggio dell'utente, NON concentrarle in una sola lingua, NON usare lingue non consentite. Le parole devono essere parole reali e idiomatiche di quella lingua (un paroliere madrelingua le userebbe in un verso), non traduzioni letterali o maccheroniche. UNICA eccezione: i NOMI PROPRI (titoli, artisti, città, eventi, persone) restano sempre nella loro forma esatta e invariata.
- Per richieste tematiche generiche lascia q vuoto: NON suggerire generi, stili, strumenti, tempo o estetiche sonore. Usa q solo per vincoli espliciti di genere, lingua o periodo; non usare q per stati d'animo.
- Evita parole inutili (canzoni, brani, playlist, consigliami) ed etichette generiche o letterali (sad, emotional, melancholic, heartbreak, loss, broken heart, triste, goodbye, addio, adieu, adios).
- Non inventare titoli o artisti.
- reason: descrizione semplice, massimo 5 parole; NON deve citare genere, mood, emozioni generiche, strumenti o lingua."""


# Blocco SIGNIFICATO (meanings -> track.lyrics.analysis.search): cerca per SENSO PROFONDO
# e ATMOSFERA, non per parole letterali. Incluso solo quando settings.musixmatch_use_meaning
# e' attivo. {meaning_min} e {meaning_proper_noun_rule} sono iniettati in base ai flag.
MUSIXMATCH_SEARCH_MEANING_BLOCK = """RICERCA SEMANTICA ("meanings"): da {meaning_min} a 6 frasi-significato per l'endpoint track.lyrics.analysis.search, che NON cerca parole letterali ma il SENSO PROFONDO, i TEMI e l'ATMOSFERA emotiva dei testi.
- Ogni "meaning" è una FRASE che DESCRIVE il significato/l'atmosfera del testo (3-10 parole), NON parole chiave isolate e NON nomi propri. Esempi: "self empowerment and overcoming obstacles", "quiet late-night loneliness and longing".
- USA "meanings" per cogliere temi astratti, emotivi, psicologici ed esistenziali (crescita personale, riscatto, lutto, rinascita, alienazione, solitudine, perdono) e ogni ATMOSFERA evocata dalla richiesta (nostalgia notturna, euforia, malinconia autunnale, tensione, intimità, energia ribelle). Descrivi BENE quell'atmosfera: non limitarti a nominarla, rendine il tono e la sensazione.
- SFUMATURE: genera più riformulazioni che colgano sfaccettature DIVERSE dello stesso tema in atmosfere diverse (es. per "malinconia notturna": "quiet late-night loneliness and longing", "bittersweet nostalgia under city lights", "calma malinconica delle ore piccole").
- RIFORMULA il significato in MODI diversi e in LINGUE diverse tra quelle consentite: una frase per lingua, distribuite tra le lingue, così i brani trovati corrispondono a quelle lingue. Scrivi ogni frase interamente nella lingua indicata dal suo campo "lang".
{meaning_proper_noun_rule}"""


MUSIXMATCH_RESPONSE_TEMPLATE = """Richiesta: {prompt}

Risultati:
{tracks}

Scrivi ESCLUSIVAMENTE in {language}, Markdown pulito.
LINGUA OBBLIGATORIA: tutta la risposta deve essere interamente in {language}. Anche se i testi delle canzoni, le biografie o il contesto qui sopra sono in un'altra lingua, NON cambiare lingua e non lasciare frasi o parole nella lingua delle fonti (tranne i titoli e i nomi propri di brani/artisti).
Usa solo questi brani. Niente titoli extra.
Per ogni brano: una frase puntuale sul perche' risponde alla richiesta.
Dai priorita' a TheAudioDB; usa Musixmatch solo come supporto.
Parafrasa, non copiare versi lunghi.
Se non ci sono risultati, chiedi una richiesta piu' precisa."""


STUDIO_BRIEF_TEMPLATE = """Crea una regia audio concisa per: "{title}".

Brani (nell'ordine):
{tracks}

LINGUA OBBLIGATORIA: TUTTO il testo generato ("speech") deve essere ESCLUSIVAMENTE in {language}. Anche se i testi delle canzoni, le biografie o il contesto esterno qui sotto sono in un'altra lingua, NON cambiare lingua: non lasciare parole o frasi nella lingua delle fonti (tranne i titoli e i nomi propri di brani/artisti).

Per ogni brano scrivi UN SOLO testo accorpato ("speech") in {language}, 90-100 parole,
che unisce in modo fluido e coerente DUE tipi di informazioni:
- dal testo/richsync, dal genere, dai mood e dai temi e dal motivo della ricerca (fonte Musixmatch): senso, atmosfera, contenuto, mood e temi del brano;
- dal contesto esterno (fonte TheAudioDB), nell'ordine: prima notizie/curiosità sul brano, poi sull'album, poi sull'artista.
Intreccia le due fonti in un unico discorso scorrevole: non creare paragrafi separati né elenchi, non etichettare le fonti, non scriverne mai i nomi. Non inventare: usa solo le informazioni disponibili e, del contesto esterno, parti dal primo livello presente nell'ordine indicato.

NON generare altri campi: niente mood testuale, niente origine geografica, niente riassunto della playlist, niente valori numerici di valenza/energia.

Rispondi SOLO JSON valido:
{{
  "narrations": [
    {{
      "title": "...",
      "artist": "...",
      "speech": "..."
    }}
  ]
}}
L'array "narrations" deve avere ESATTAMENTE {n} elementi, nello stesso ordine dei brani."""


PLAYLIST_TEMPLATE = """Sulla base di questo vettore emotivo / analisi:

\"\"\"
{analysis}
\"\"\"

Proponi {n} brani (di epoche, generi e lingue diversi) che condividono lo stesso \
filo conduttore narrativo ed emotivo del brano "{title}" di {artist}.

Rispondi SOLO con un array JSON valido, senza testo prima o dopo, nel formato:
[{{"title": "...", "artist": "...", "reason": "<max 12 parole in {language}>"}}]"""


THEME_QUERY_BANK: tuple[tuple[set[str], list[dict[str, str]]], ...] = (
    (
        {
            "war",
            "wars",
            "battle",
            "battles",
            "fight",
            "fighting",
            "struggle",
            "conflict",
            "guerra",
            "guerre",
            "lotta",
            "lotte",
            "battaglia",
            "battaglie",
            "conflitto",
            "conflitti",
            "rivoluzione",
            "resistenza",
            "partigiani",
            "fronte",
            "trincea",
            "batalla",
            "guerre sans fin",
            "combat",
            "krieg",
            "wojna",
            "戦争",
            "战争",
            "전쟁",
        },
        [
            {
                "cluster": "trenches",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "trenches barbed wire",
                "reason": "frontline imagery",
            },
            {
                "cluster": "war_machine",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "war machine",
                "reason": "industrial conflict",
            },
            {
                "cluster": "ceasefire",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "ceasefire never came",
                "reason": "failed truce",
            },
            {
                "cluster": "trenches",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "trincea filo spinato",
                "reason": "immagini dal fronte",
            },
            {
                "cluster": "resistance",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "partigiani resistenza",
                "reason": "lotta organizzata",
            },
            {
                "cluster": "bombings",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "bombardamenti città",
                "reason": "città sotto attacco",
            },
            {
                "cluster": "barricades",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "barricadas pueblo",
                "reason": "revuelta civile",
            },
            {
                "cluster": "soldiers",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "soldados frontera",
                "reason": "confine militarizzato",
            },
            {
                "cluster": "combat",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "combat sans pitié",
                "reason": "scontro diretto",
            },
            {
                "cluster": "resistance",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "résistance barricades",
                "reason": "rivolta organizzata",
            },
            {
                "cluster": "war_machine",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "krieg maschine",
                "reason": "apparato bellico",
            },
            {
                "cluster": "soldiers",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "front soldaten",
                "reason": "soldati al fronte",
            },
            {
                "cluster": "endless_war",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "guerra sem fim",
                "reason": "conflitto prolungato",
            },
            {
                "cluster": "struggle",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "povo em luta",
                "reason": "lotta collettiva",
            },
            {
                "cluster": "war_shadow",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "戦争の影",
                "reason": "戦争の余波",
            },
            {
                "cluster": "battlefield",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "戦場の兵士",
                "reason": "前線の兵士",
            },
            {
                "cluster": "war_shadow",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "전쟁의 그림자",
                "reason": "전쟁의 여파",
            },
            {
                "cluster": "struggle",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "투쟁의 거리",
                "reason": "거리의 투쟁",
            },
            {
                "cluster": "war_shadow",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "战争的阴影",
                "reason": "战争余波",
            },
            {
                "cluster": "battle_horn",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "战斗的号角",
                "reason": "集结信号",
            },
        ],
    ),
    (
        {
            "heartbreak",
            "broken heart",
            "loss",
            "grief",
            "perdita",
            "cuore spezzato",
            "chagrin",
            "rupture",
            "desamor",
            "corazon roto",
            "corazón roto",
            "herzschmerz",
            "abschied",
            "saudade",
        },
        [
            {
                "cluster": "afterimage",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "ghost of you",
                "reason": "presence after goodbye",
            },
            {
                "cluster": "abandonment",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "left behind",
                "reason": "someone stays alone",
            },
            {
                "cluster": "remains",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "all that remains",
                "reason": "love as remains",
            },
            {
                "cluster": "room",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "empty bed",
                "reason": "room after absence",
            },
            {
                "cluster": "attachment",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "can't let go",
                "reason": "not letting go",
            },
            {
                "cluster": "return",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "come back to me",
                "reason": "wanting return",
            },
            {
                "cluster": "cold",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "love went cold",
                "reason": "love turning cold",
            },
            {
                "cluster": "memory",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "old memories",
                "reason": "memory stays",
            },
            {
                "cluster": "promise",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "broken promises",
                "reason": "promise breaks",
            },
            {
                "cluster": "empty",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "nothing left",
                "reason": "after the ending",
            },
            {
                "cluster": "sarcasm",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "thanks for nothing",
                "reason": "bitter goodbye",
            },
            {
                "cluster": "mask",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "happy now",
                "reason": "bitter question",
            },
            {
                "cluster": "afterimage",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "vuoto ombra fantasma",
                "reason": "assenza trasformata in spazio interiore",
            },
            {
                "cluster": "abandonment",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "abbandono lasciato indietro",
                "reason": "identità ferma dopo l'abbandono",
            },
            {
                "cluster": "remains",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "quel che resta",
                "reason": "amore come resto",
            },
            {
                "cluster": "room",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "letto vuoto",
                "reason": "stanza dopo assenza",
            },
            {
                "cluster": "attachment",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "non so lasciarti",
                "reason": "legame non chiuso",
            },
            {
                "cluster": "return",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "torna da me",
                "reason": "desiderio di ritorno",
            },
            {
                "cluster": "cold",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "amore freddo",
                "reason": "amore diventato distanza",
            },
            {
                "cluster": "memory",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "vecchi ricordi",
                "reason": "memoria che resta",
            },
            {
                "cluster": "promise",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "promesse rotte",
                "reason": "promessa spezzata",
            },
            {
                "cluster": "empty",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "non resta niente",
                "reason": "dopo la fine",
            },
            {
                "cluster": "sarcasm",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "grazie di niente",
                "reason": "addio amaro",
            },
            {
                "cluster": "mask",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "contento adesso",
                "reason": "domanda amara",
            },
            {
                "cluster": "afterimage",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "tu fantasma",
                "reason": "presencia perdida",
            },
            {
                "cluster": "abandonment",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "me dejaste atrás",
                "reason": "abandono directo",
            },
            {
                "cluster": "remains",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "restos cenizas ruinas",
                "reason": "l'amato sopravvive nei resti",
            },
            {
                "cluster": "room",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "cama vacía casa vacía",
                "reason": "intimità sostituita dal vuoto",
            },
            {
                "cluster": "attachment",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "olvidarte borrarte soltar",
                "reason": "memoria più forte della chiusura",
            },
            {
                "cluster": "return",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "vuelve regresa puerta",
                "reason": "desiderio che nega la perdita",
            },
            {
                "cluster": "sarcasm",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "gracias por nada",
                "reason": "despedida amarga",
            },
            {
                "cluster": "mask",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "feliz ahora",
                "reason": "pregunta amarga",
            },
            {
                "cluster": "afterimage",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "fantôme ombre absence",
                "reason": "il tu ritorna come ombra",
            },
            {
                "cluster": "abandonment",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "tu m'as laissé",
                "reason": "abandon direct",
            },
            {
                "cluster": "room",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "maison vide lit froid",
                "reason": "casa svuotata dalla separazione",
            },
            {
                "cluster": "attachment",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "oublier effacer retenir",
                "reason": "ricordo che rifiuta oblio",
            },
            {
                "cluster": "return",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "reviens retour seuil",
                "reason": "richiamo rivolto all'irreparabile",
            },
            {
                "cluster": "sarcasm",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "merci pour rien",
                "reason": "adieu amer",
            },
            {
                "cluster": "afterimage",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "schatten geist erinnerung",
                "reason": "amore rimasto come ombra",
            },
            {
                "cluster": "abandonment",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "du lässt mich zurück",
                "reason": "verlassen werden",
            },
            {
                "cluster": "attachment",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "vergessen loslassen löschen",
                "reason": "oblio impossibile dopo il distacco",
            },
            {
                "cluster": "room",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "leeres haus kaltes bett",
                "reason": "luogo abitato solo dall'assenza",
            },
            {
                "cluster": "sarcasm",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "danke für nichts",
                "reason": "bitterer abschied",
            },
            {
                "cluster": "afterimage",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "fantasma sombra saudade",
                "reason": "presenza perduta che continua",
            },
            {
                "cluster": "abandonment",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "me deixou pra trás",
                "reason": "abandono direto",
            },
            {
                "cluster": "remains",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "restou cinzas ruínas",
                "reason": "rovine emotive dopo l'amore",
            },
            {
                "cluster": "attachment",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "esquecer apagar soltar",
                "reason": "memoria che non arretra",
            },
            {
                "cluster": "sarcasm",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "obrigado por nada",
                "reason": "adeus amargo",
            },
            {
                "cluster": "afterimage",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "君の影",
                "reason": "残る影",
            },
            {
                "cluster": "room",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "空のベッド",
                "reason": "空いた場所",
            },
            {
                "cluster": "empty",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "何も残らない",
                "reason": "終わりの後",
            },
            {
                "cluster": "sarcasm",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "ありがe��う何もない",
                "reason": "苦い皮肉",
            },
            {
                "cluster": "afterimage",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "너의 그림자",
                "reason": "남은 그림자",
            },
            {
                "cluster": "room",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "빈 침대",
                "reason": "비어 있는 자리",
            },
            {
                "cluster": "empty",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "남은 건 없어",
                "reason": "끝난 뒤",
            },
            {
                "cluster": "sarcasm",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "고마워 아무것도",
                "reason": "쓴 농담",
            },
            {
                "cluster": "afterimage",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "你的影子",
                "reason": "留下的影子",
            },
            {
                "cluster": "room",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "空的床",
                "reason": "空出的位置",
            },
            {
                "cluster": "empty",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "什么都不剩",
                "reason": "结束之后",
            },
            {
                "cluster": "sarcasm",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "谢谢你什么都没有",
                "reason": "苦涩反话",
            },
            {
                "cluster": "afterimage",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "तेरी परछाई",
                "reason": "बची छाया",
            },
            {
                "cluster": "room",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "खाली बिस्तर",
                "reason": "खाली जगह",
            },
            {
                "cluster": "empty",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "कुछ नहीं बचा",
                "reason": "अंत के बाद",
            },
            {
                "cluster": "sarcasm",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "धन्यवाद कुछ नहीं",
                "reason": "कड़वा व्यंग्य",
            },
        ],
    ),
    (
        {
            "3am",
            "3 am",
            "three am",
            "late night loneliness",
            "midnight loneliness",
            "night loneliness",
            "lonely night",
            "solitudine notturna",
            "notte solitaria",
        },
        [
            {
                "cluster": "hour",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "three in the morning",
                "reason": "awake too late",
            },
            {
                "cluster": "room",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "alone at night",
                "reason": "alone at night",
            },
            {
                "cluster": "city",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "empty streets",
                "reason": "empty city",
            },
            {
                "cluster": "body",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "can't sleep",
                "reason": "can't sleep",
            },
            {
                "cluster": "echo",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "silent room",
                "reason": "quiet room",
            },
            {
                "cluster": "phone",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "phone won't ring",
                "reason": "no call",
            },
            {
                "cluster": "light",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "blue light",
                "reason": "screen light",
            },
            {
                "cluster": "awake",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "wide awake",
                "reason": "still awake",
            },
            {
                "cluster": "bed",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "cold bed",
                "reason": "cold bed",
            },
            {
                "cluster": "call",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "no one calls",
                "reason": "no one calls",
            },
            {
                "cluster": "sarcasm",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "party for one",
                "reason": "lonely joke",
            },
            {
                "cluster": "ceiling",
                "lang": "EN",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "talking to the ceiling",
                "reason": "ceiling as witness",
            },
            {
                "cluster": "hour",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "tre di notte soffitto",
                "reason": "veglia fissata nel vuoto",
            },
            {
                "cluster": "room",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "stanza muta luce blu",
                "reason": "intimità illuminata dal silenzio",
            },
            {
                "cluster": "city",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "strade vuote",
                "reason": "città senza approdo",
            },
            {
                "cluster": "body",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "non dormo",
                "reason": "veglia senza riposo",
            },
            {
                "cluster": "echo",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "stanza silenziosa",
                "reason": "silenzio intorno",
            },
            {
                "cluster": "phone",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "telefono non suona",
                "reason": "attesa senza voce",
            },
            {
                "cluster": "light",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "luce blu",
                "reason": "luce dello schermo",
            },
            {
                "cluster": "awake",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "ancora sveglio",
                "reason": "notte ancora aperta",
            },
            {
                "cluster": "bed",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "letto freddo",
                "reason": "letto senza calore",
            },
            {
                "cluster": "call",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "nessuno chiama",
                "reason": "nessun segnale",
            },
            {
                "cluster": "sarcasm",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "festa per nessuno",
                "reason": "ironia solitaria",
            },
            {
                "cluster": "ceiling",
                "lang": "IT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "parlo al soffitto",
                "reason": "soffitto testimone",
            },
            {
                "cluster": "city",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "calles vacías lluvia neón",
                "reason": "notte urbana senza approdo",
            },
            {
                "cluster": "hour",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "tres de la mañana",
                "reason": "hora vacía",
            },
            {
                "cluster": "room",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "solo en la noche",
                "reason": "noche sola",
            },
            {
                "cluster": "sarcasm",
                "lang": "ES",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "fiesta para nadie",
                "reason": "ironía sola",
            },
            {
                "cluster": "body",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "yeux ouverts nuit blanche",
                "reason": "insonnia come stanza interiore",
            },
            {
                "cluster": "hour",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "trois heures du matin",
                "reason": "heure vide",
            },
            {
                "cluster": "sarcasm",
                "lang": "FR",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "fête pour personne",
                "reason": "ironie seule",
            },
            {
                "cluster": "echo",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "echo im flur",
                "reason": "corridoio che restituisce assenza",
            },
            {
                "cluster": "hour",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "drei uhr morgens",
                "reason": "leere stunde",
            },
            {
                "cluster": "sarcasm",
                "lang": "DE",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "feier für niemand",
                "reason": "einsame ironie",
            },
            {
                "cluster": "phone",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "telefone não toca",
                "reason": "silenzio dove attendevi voce",
            },
            {
                "cluster": "hour",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "três da manhã",
                "reason": "hora vazia",
            },
            {
                "cluster": "sarcasm",
                "lang": "PT",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "festa para ninguém",
                "reason": "ironia solitária",
            },
            {
                "cluster": "hour",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "午前三時",
                "reason": "空いた時間",
            },
            {
                "cluster": "room",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "ひとりの夜",
                "reason": "夜の孤独",
            },
            {
                "cluster": "body",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "眠れない夜",
                "reason": "眠れない",
            },
            {
                "cluster": "sarcasm",
                "lang": "JA",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "天井と話す",
                "reason": "皮肉な相手",
            },
            {
                "cluster": "hour",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "새벽 세 시",
                "reason": "빈 시간",
            },
            {
                "cluster": "room",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "혼자인 밤",
                "reason": "혼자 남은 밤",
            },
            {
                "cluster": "body",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "잠 못 드는 밤",
                "reason": "잠 없는 밤",
            },
            {
                "cluster": "sarcasm",
                "lang": "KO",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "혼자만의 파티",
                "reason": "외로운 농담",
            },
            {
                "cluster": "hour",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "凌晨三点",
                "reason": "空的时刻",
            },
            {
                "cluster": "room",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "一个人的夜",
                "reason": "独自的夜",
            },
            {
                "cluster": "body",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "睡不着",
                "reason": "无法入睡",
            },
            {
                "cluster": "sarcasm",
                "lang": "ZH",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "一个人的派对",
                "reason": "孤独玩笑",
            },
            {
                "cluster": "hour",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "रात के तीन बजे",
                "reason": "खाली समय",
            },
            {
                "cluster": "room",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "अकेली रात",
                "reason": "अकेली रात",
            },
            {
                "cluster": "body",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "नींद नहीं आती",
                "reason": "नींद नहीं",
            },
            {
                "cluster": "sarcasm",
                "lang": "HI",
                "q": "",
                "q_track": "",
                "q_artist": "",
                "q_lyrics": "अकेले की पार्टी",
                "reason": "अकेला व्यंग्य",
            },
        ],
    ),
)

GENERIC_THEME_TERMS = {
    "sad",
    "emotional",
    "melancholic",
    "melancholy",
    "heartbreak",
    "broken heart",
    "loss",
    "pain",
    "triste",
    "emotivo",
    "malinconico",
    "cuore spezzato",
    "perdita",
}

GENRE_STYLE_TERMS = {
    "acoustic",
    "ambient",
    "bedroom pop",
    "dream pop",
    "electronic",
    "folk",
    "genre",
    "genere",
    "guitar",
    "indie",
    "instrumental",
    "lo-fi",
    "lofi",
    "minimal",
    "nocturne",
    "piano",
    "slow tempo",
    "synth",
    "texture",
}

CONCRETE_THEME_TERMS = {
    "goodbye",
    "miss you",
    "without you",
    "gone",
    "come back",
    "empty room",
    "addio",
    "mi manchi",
    "senza di te",
    "non torni",
    "adieu",
    "tu me manques",
    "sans toi",
    "adios",
    "adiós",
    "te extraño",
    "sin ti",
    "auf wiedersehen",
    "ich vermisse dich",
    "ohne dich",
    "adeus",
    "saudade",
    "sem você",
    "ghost of you",
    "left behind",
    "all that remains",
    "empty side of the bed",
    "can't let go",
    "come back to me",
    "love went cold",
    "mi resta il vuoto",
    "lasciato indietro",
    "lo que queda de ti",
    "cama vacía",
    "no puedo olvidarte",
    "vuelve a mí",
    "ton fantôme",
    "maison vide",
    "je n'oublie pas",
    "reviens vers moi",
    "dein schatten",
    "ich kann dich nicht vergessen",
    "leeres haus",
    "teu fantasma",
    "o que restou",
    "não te esqueci",
}

SHALLOW_THEME_TERMS = {
    "goodbye",
    "miss you",
    "without you",
    "addio",
    "mi manchi",
    "senza di te",
    "adieu",
    "tu me manques",
    "sans toi",
    "adios",
    "adiós",
    "te extraño",
    "sin ti",
    "auf wiedersehen",
    "ich vermisse dich",
    "ohne dich",
    "adeus",
    "sem você",
}

THEME_QUERY_LANGUAGE_ORDER = ("EN", "IT", "FR", "ES", "DE", "PT", "JA", "KO", "ZH")
EUROPEAN_QUERY_LANGS = {"EN", "IT", "FR", "ES", "DE", "PT"}
ASIAN_QUERY_LANGS = {"JA", "KO", "ZH"}
THEME_QUERY_CLUSTER_ORDER = (
    "afterimage",
    "hour",
    "trenches",
    "war_machine",
    "ceasefire",
    "resistance",
    "bombings",
    "barricades",
    "soldiers",
    "combat",
    "endless_war",
    "struggle",
    "war_shadow",
    "battlefield",
    "battle_horn",
    "sarcasm",
    "mask",
    "room",
    "abandonment",
    "remains",
    "city",
    "body",
    "attachment",
    "return",
    "echo",
    "phone",
    "cold",
    "memory",
    "promise",
    "empty",
    "ceiling",
    "light",
    "awake",
    "bed",
    "call",
)


def _theme_queries_for_text(
    text: str, allowed_langs: Optional[set[str]] = None
) -> list[dict[str, str]]:
    normalized = text.casefold()
    queries: list[dict[str, str]] = []
    for triggers, bank in THEME_QUERY_BANK:
        if any(trigger in normalized for trigger in triggers):
            queries.extend(dict(item) for item in bank)
    # Task 6: limita le query del banco alle sole lingue selezionate (se indicate).
    if allowed_langs:
        allowed_upper = {code.upper() for code in allowed_langs}
        queries = [
            q for q in queries if str(q.get("lang", "")).upper() in allowed_upper
        ]
    cluster_order: list[str] = []
    for query in queries:
        cluster = str(query.get("cluster", "")).lower()
        if cluster and cluster not in cluster_order:
            cluster_order.append(cluster)
    if not cluster_order:
        cluster_order = list(THEME_QUERY_CLUSTER_ORDER)
    else:
        priority = {
            cluster: index for index, cluster in enumerate(THEME_QUERY_CLUSTER_ORDER)
        }
        cluster_order.sort(key=lambda cluster: priority.get(cluster, len(priority)))

    by_cluster_language: dict[tuple[str, str], list[dict[str, str]]] = {}
    for query in queries:
        cluster = str(query.get("cluster", "")).lower()
        language = str(query.get("lang", "")).upper()
        by_cluster_language.setdefault((cluster, language), []).append(query)

    rng = random.SystemRandom()
    languages = list(THEME_QUERY_LANGUAGE_ORDER)
    rng.shuffle(languages)
    rng.shuffle(cluster_order)

    candidates: list[dict[str, str]] = []
    index = 0
    while True:
        added = False
        for language in languages:
            shuffled_clusters = list(cluster_order)
            rng.shuffle(shuffled_clusters)
            for cluster in shuffled_clusters:
                bucket = by_cluster_language.get((cluster, language), [])
                if index < len(bucket):
                    candidates.append(bucket[index])
                    added = True
        if not added:
            break
        index += 1

    european = [
        query
        for query in candidates
        if str(query.get("lang", "")).upper() in EUROPEAN_QUERY_LANGS
    ]
    asian = [
        query
        for query in candidates
        if str(query.get("lang", "")).upper() in ASIAN_QUERY_LANGS
    ]
    rng.shuffle(european)
    rng.shuffle(asian)

    mixed: list[dict[str, str]] = []
    while len(mixed) < 20 and (european or asian):
        pools = [pool for pool in (european, asian) if pool]
        rng.shuffle(pools)
        for pool in pools:
            if pool and len(mixed) < 20:
                mixed.append(pool.pop())
    return mixed


def _query_text(query: dict[str, str]) -> str:
    return " ".join(str(query.get(key, "")) for key in ("q", "q_lyrics")).casefold()


def _is_generic_theme_query(query: dict[str, str]) -> bool:
    text = _query_text(query)
    if not text:
        return False
    if any(term in text for term in GENRE_STYLE_TERMS):
        return True
    if any(term in text for term in SHALLOW_THEME_TERMS):
        return True
    if any(term in text for term in CONCRETE_THEME_TERMS):
        return False
    return any(term in text for term in GENERIC_THEME_TERMS)


def _dedupe_queries(queries: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, str]] = []
    for query in queries:
        key = tuple(
            str(query.get(field, "")).casefold()
            for field in ("q", "q_track", "q_artist", "q_lyrics")
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(query)
    return result


def _interleave_queries_by_language(
    queries: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Mescola l'ordine delle query così le lingue si ALTERNANO in modo casuale,
    invece di restare raggruppate (evita 10 query francesi seguite da 10 spagnole).

    Raggruppa per lingua, mischia ogni gruppo, poi estrae una query alla volta
    scegliendo la lingua con probabilità proporzionale alle query ancora rimaste:
    ne risulta un'alternanza naturale (a volte due della stessa lingua di fila,
    es. una FR, una ES, due FR, una ES) invece di blocchi monolingua.
    """
    if len(queries) <= 2:
        return list(queries)
    groups: dict[str, list[dict[str, str]]] = {}
    for query in queries:
        lang = str(query.get("lang", "")).upper() or "?"
        groups.setdefault(lang, []).append(query)
    if len(groups) <= 1:
        return list(queries)
    rng = random.SystemRandom()
    for bucket in groups.values():
        rng.shuffle(bucket)
    result: list[dict[str, str]] = []
    while any(groups.values()):
        langs = [lang for lang, bucket in groups.items() if bucket]
        weights = [len(groups[lang]) for lang in langs]
        chosen = rng.choices(langs, weights=weights, k=1)[0]
        result.append(groups[chosen].pop())
    return result


class Storyteller:
    """Genera analisi emotive e curatela playlist tramite un LLM 'Thinking'."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.85,
        timeout: Optional[float] = None,
        reasoning_effort: str = "low",
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.temperature = temperature
        self.timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        # Low reasoning effort keeps the gigantic chain-of-thought (and the per
        # request latency) down so /api/chat stays well under the proxy timeout.
        self.reasoning_effort = reasoning_effort
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if not self.api_key:
            raise StorytellerError(
                "Chiave API LLM mancante. Imposta LLM_API_KEY (e LLM_BASE_URL/LLM_MODEL) nel file .env"
            )
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url or None,
                timeout=self.timeout,
            )
        return self._client

    # ------------------------------------------------------------------ #
    # API pubblica
    # ------------------------------------------------------------------ #
    def analyze(
        self,
        *,
        title: str,
        artist: str,
        lyrics: str,
        biography: str = "",
        theme: str = "",
        language: str = "Italiano",
    ) -> EmotionalAnalysis:
        """Genera l'analisi psicologica + micro-racconto in Markdown."""
        theme_line = (
            f"- Tema/filo conduttore richiesto: {theme}\n" if theme.strip() else ""
        )
        user_prompt = ANALYSIS_TEMPLATE.format(
            title=title or "(sconosciuto)",
            artist=artist or "(sconosciuto)",
            theme_line=theme_line,
            biography=biography.strip() or "(nessuna biografia disponibile)",
            lyrics=lyrics.strip() or "(testo non disponibile)",
            language=language,
        )
        content, reasoning = self._chat(
            system=SYSTEM_PROMPT.format(language=language),
            user=user_prompt,
        )
        archetype, keywords = self._extract_vector(content)
        return EmotionalAnalysis(
            narrative=content,
            archetype=archetype,
            keywords=keywords,
            reasoning=reasoning,
            model=self.model,
        )

    def suggest_tracks(
        self,
        *,
        title: str,
        artist: str,
        analysis: str,
        n: int = 8,
        language: str = "Italiano",
    ) -> list[dict[str, str]]:
        """Propone una lista di brani affini (per la curatela della playlist)."""
        return []

    def studio_brief(
        self,
        *,
        title: str,
        tracks: list[dict[str, str]],
        language: str = "Italiano",
    ) -> dict[str, Any]:
        """Genera, in una sola chiamata, UN solo 'discorso' accorpato per ogni
        brano (campo "speech") che intreccia testo Musixmatch e contesto TheAudioDB.

        Origine geografica e mood NON sono generati qui: arrivano dai dati reali
        (TheAudioDB/MusicBrainz per l'origine, generi Musixmatch per il mood).
        Valence/energy NON sono stimati dall'LLM: arrivano dalle audio-features
        di Spotify; se non disponibili restano vuoti e il grafico non si mostra.
        Ritorna un dict con chiave 'narrations' (list). In caso di errore o
        playlist vuota ritorna {}.
        """
        if not tracks:
            return {}
        track_parts: list[str] = []
        for i, t in enumerate(tracks):
            line = f'{i + 1}. "{t.get("title", "")}" — {t.get("artist", "")}'
            bio = (t.get("_bio") or t.get("bio") or "").strip()
            lyrics = (t.get("lyrics") or "").strip()
            if lyrics:
                # Testo piu' ampio cosi' il modello puo' citare versi/immagini concrete.
                lyrics_short = lyrics[:900] + ("…" if len(lyrics) > 900 else "")
                line += f"\n   Musixmatch testo: {lyrics_short}"
            # Feature testuali estratte da Musixmatch (analisi dei testi + generi):
            # rinforzano la regia con genere, mood e temi reali del brano.
            # Il genere proviene ESCLUSIVAMENTE dai generi primari Musixmatch
            # (primary_genres della traccia): si usa la lista completa mx_genres
            # e si ripiega solo sul campo genre (anch'esso Musixmatch), mai sul
            # mood, cosi' l'etichetta "Musixmatch genere" resta sempre veritiera.
            mx_genres = [
                str(g).strip() for g in (t.get("mx_genres") or []) if str(g).strip()
            ]
            genre = (
                ", ".join(mx_genres[:3])
                if mx_genres
                else str(t.get("genre") or "").strip()
            )
            if genre:
                line += f"\n   Musixmatch genere: {genre}"
            mx_moods = [
                str(m).strip() for m in (t.get("mx_moods") or []) if str(m).strip()
            ]
            if mx_moods:
                line += f"\n   Musixmatch mood: {', '.join(mx_moods[:6])}"
            mx_themes = [
                str(x).strip() for x in (t.get("mx_themes") or []) if str(x).strip()
            ]
            if mx_themes:
                line += f"\n   Musixmatch temi: {', '.join(mx_themes[:4])}"
            song_news = (t.get("audio_db_song_news") or "").strip()
            album_news = (t.get("audio_db_album_news") or "").strip()
            artist_description = (t.get("audio_db_artist_description") or bio).strip()
            if song_news:
                song_short = song_news[:420] + ("…" if len(song_news) > 420 else "")
                line += f"\n   Contesto esterno 1 - brano: {song_short}"
            if album_news:
                album_short = album_news[:360] + ("…" if len(album_news) > 360 else "")
                line += f"\n   Contesto esterno 2 - album: {album_short}"
            if artist_description:
                artist_short = artist_description[:360] + (
                    "…" if len(artist_description) > 360 else ""
                )
                line += f"\n   Contesto esterno 3 - artista: {artist_short}"
            audiodb_text = (
                t.get("audio_db_text") or t.get("audiodb_text") or ""
            ).strip()
            if audiodb_text and not (song_news or album_news or artist_description):
                audiodb_short = audiodb_text[:240] + (
                    "…" if len(audiodb_text) > 240 else ""
                )
                line += f"\n   Contesto esterno ordinato: {audiodb_short}"
            fact = (t.get("audio_db_fact") or t.get("audiodb_fact") or "").strip()
            if fact and fact != audiodb_text and not song_news:
                line += f"\n   Nota brano/album: {fact}"
            track_parts.append(line)
        track_lines = "\n\n".join(track_parts)
        user = STUDIO_BRIEF_TEMPLATE.format(
            title=title or "(senza titolo)",
            tracks=track_lines,
            language=language,
            n=len(tracks),
        )
        content, _ = self._chat(
            system=(
                "Sei un autore radiofonico. Rispondi esclusivamente con JSON valido. "
                f"Tutto il testo dei campi generati deve essere scritto esclusivamente in {language}, "
                "anche quando le fonti (testi, biografie, contesto) sono in un'altra lingua."
            ),
            user=user,
        )
        return self._parse_json(content)

    def suggest_listening_themes(
        self,
        *,
        artists: list[str],
        tracks: list[str],
        genres: list[str],
        language: str = "Italiano",
        n: int = 4,
    ) -> list[str]:
        """Deriva temi narrativi brevi dagli ascolti reali dell'utente (task 10).

        Restituisce una lista di stringhe-tema (in {language}); lista vuota in caso
        di errore o input insufficiente. Non inventa: si basa solo sui dati passati.
        """
        if not (artists or tracks or genres):
            return []
        listening = {
            "top_artists": artists[:15],
            "top_tracks": tracks[:15],
            "top_genres": genres[:15],
        }
        lang_rule = f"Scrivi i temi SEMPRE in {language}"
        user = (
            "Questi sono gli ascolti reali dell'utente su Spotify (artisti, brani, generi):\n"
            f"{json.dumps(listening, ensure_ascii=False, indent=2)}\n\n"
            f"Proponi {n} TEMI NARRATIVI brevi (3-7 parole ciascuno) per esplorare nuova musica "
            "coerente con questi gusti: atmosfere, immagini, stati d'animo o contesti, NON nomi di "
            "artisti o brani già ascoltati. Evita generi puri e parole come 'playlist'. "
            f"{lang_rule}.\n"
            'Rispondi SOLO con un array JSON di stringhe, es: ["...", "...", "...", "..."]'
        )
        try:
            content, _ = self._chat(
                system="Sei un curatore musicale. Rispondi esclusivamente con un array JSON di stringhe.",
                user=user,
            )
        except StorytellerError:
            return []
        cleaned = re.sub(r"^```(?:json)?", "", content.strip()).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned)
        except (ValueError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        themes = [str(item).strip() for item in data if str(item).strip()]
        return themes[:n]

    def plan_musixmatch_search(
        self,
        *,
        messages: list[dict[str, str]],
        language: str = "Italiano",
        context: str = "",
        search_languages: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        # Auto rimossa: la risposta segue SEMPRE la lingua della UI, anche se
        # l'utente scrive in un'altra lingua.
        language_rule = f"Rispondi SEMPRE in {language}, anche se l'utente scrive in un'altra lingua."
        # Task 6: lingue in cui cercare i brani (codici EN/IT/FR/...). Default = tutte.
        allowed_langs = {code.upper() for code in (search_languages or []) if code}
        all_langs = list(THEME_QUERY_LANGUAGE_ORDER)
        if allowed_langs:
            search_languages_text = ", ".join(
                code for code in all_langs if code in allowed_langs
            ) or ", ".join(sorted(allowed_langs))
        else:
            search_languages_text = ", ".join(all_langs) + " (tutte)"
        recent = messages[-4:]
        last_user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                last_user = message.get("content", "")
                break
        # Sorgenti attive: il prompt include il blocco "queries" (ricerca per TESTO)
        # solo se musixmatch_use_lyrics, e il blocco "meanings" (ricerca per SIGNIFICATO)
        # solo se musixmatch_use_meaning. Gli stessi flag governano a valle quali sorgenti
        # contribuiscono (search_musixmatch_from_plan): qui rendiamo l'output dell'LLM
        # specializzato e coerente con la/le sola/e sorgente/i attiva/e. Il parsing e la
        # ricerca a valle restano invariati (gestiscono naturalmente le liste vuote).
        want_lyrics = settings.musixmatch_use_lyrics
        want_meaning = settings.musixmatch_use_meaning
        # Se entrambe sono disattivate il router deve comunque classificare e pianificare:
        # includiamo entrambi i blocchi come fallback sicuro (a valle nessuna sorgente
        # contribuira', quindi il piano resta innocuo).
        if not want_lyrics and not want_meaning:
            want_lyrics = want_meaning = True

        sections = [
            MUSIXMATCH_SEARCH_HEADER.format(
                language_rule=language_rule,
                search_languages=search_languages_text,
                messages=json.dumps(recent, ensure_ascii=False, indent=2),
            )
        ]
        schema_fields = [
            '  "music_related": true',
            '  "needs_search": true',
            '  "limit": 10',
            '  "narration_lang": "it"',
        ]
        footer_notes = [
            "Usa limit 1-10 per il numero massimo di tracce finali, non per il numero di elementi generati."
        ]
        empty_when_no_search: list[str] = []
        if want_lyrics:
            sections.append(MUSIXMATCH_SEARCH_LYRICS_BLOCK)
            schema_fields.append(
                '  "queries": [\n'
                '    {"q": "", "q_track": "", "q_artist": "", "q_lyrics": "", "lang": "EN", "reason": ""}\n'
                "  ]"
            )
            footer_notes.append(
                "Per richieste tematiche con needs_search=true restituisci 20 query."
            )
            empty_when_no_search.append("queries=[]")
        if want_meaning:
            # Con i TESTI attivi i nomi propri/eventi storici restano alle q_lyrics e i
            # "meanings" coprono solo l'astratto/le atmosfere (min 1). Con il SIGNIFICATO
            # come sola sorgente i "meanings" devono SEMPRE esserci (min 4): anche gli
            # eventi storici vanno tradotti in atmosfera emotiva, altrimenti la ricerca
            # semantica non avrebbe nulla su cui agganciarsi.
            if want_lyrics:
                meaning_min = "1"
                meaning_proper_noun_rule = (
                    '- NON usare "meanings" per temi incentrati su NOMI PROPRI o eventi storici specifici '
                    "(città, monumenti, battaglie, persone, date): in questi casi lasciali alle q_lyrics e "
                    'imposta "meanings": []. Riserva i "meanings" ai temi astratti, emotivi ed esistenziali e alle atmosfere.'
                )
            else:
                meaning_min = "4"
                meaning_proper_noun_rule = (
                    "- Genera SEMPRE le frasi-significato, anche per temi incentrati su NOMI PROPRI o eventi "
                    "storici specifici: NON inserire il nome proprio nel testo, ma TRADUCILO nell'ATMOSFERA "
                    'emotiva e nell\'esperienza umana dell\'evento (es. "seconda guerra mondiale" -> "the fear '
                    'and grief of soldiers in the trenches", "civili in fuga sotto i bombardamenti"), perché la '
                    "ricerca semantica coglie emozioni e temi, non i nomi."
                )
            sections.append(
                MUSIXMATCH_SEARCH_MEANING_BLOCK.format(
                    meaning_min=meaning_min,
                    meaning_proper_noun_rule=meaning_proper_noun_rule,
                )
            )
            schema_fields.append(
                '  "meanings": [\n    {"meaning": "", "lang": "EN"}\n  ]'
            )
            empty_when_no_search.append("meanings=[]")

        footer_notes.append(
            "Se non serve cercare, needs_search=false e "
            + " e ".join(empty_when_no_search)
            + "."
        )
        schema = "Schema:\n{\n" + ",\n".join(schema_fields) + "\n}"
        sections.append(schema)
        sections.append("\n".join(footer_notes))
        user = "\n\n".join(sections)
        try:
            content, _ = self._chat(
                system="Sei un router di ricerca musicale. Rispondi esclusivamente con JSON valido.",
                user=user,
            )
            data = self._parse_json(content)
        except StorytellerError as exc:
            return self._fallback_musixmatch_plan(
                last_user,
                reason=f"LLM router unavailable for {self.model}: {exc}",
                allowed_langs=allowed_langs or None,
            )
        if not data:
            return self._fallback_musixmatch_plan(
                last_user,
                reason=f"LLM router returned non-JSON output for {self.model}.",
                allowed_langs=allowed_langs or None,
            )

        def as_bool(value: Any, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "yes", "si", "sì", "1"}:
                    return True
                if normalized in {"false", "no", "0"}:
                    return False
            return default

        try:
            limit = int(data.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 10))
        queries: list[dict[str, str]] = []
        raw_queries = data.get("queries") or []
        if isinstance(raw_queries, list):
            for item in raw_queries:
                if not isinstance(item, dict):
                    continue
                query = {
                    "q": str(item.get("q", "")).strip(),
                    "q_track": str(item.get("q_track", "")).strip(),
                    "q_artist": str(item.get("q_artist", "")).strip(),
                    "q_lyrics": str(item.get("q_lyrics", "")).strip(),
                    "lang": str(item.get("lang", "")).strip().upper(),
                    "reason": str(item.get("reason", "")).strip(),
                }
                # Task 6: scarta le query in lingue non consentite (solo se dichiarano
                # una lingua e non sono ricerche per titolo/artista esplicito).
                if (
                    allowed_langs
                    and query["lang"]
                    and query["lang"] not in allowed_langs
                    and not (query["q_track"] or query["q_artist"])
                ):
                    continue
                if any(query[k] for k in ("q", "q_track", "q_artist", "q_lyrics")):
                    queries.append(query)
        has_router_queries = bool(queries)
        needs_search = as_bool(data.get("needs_search"), True)
        if needs_search and not queries and last_user:
            queries.append(
                {
                    "q": last_user,
                    "q_track": "",
                    "q_artist": "",
                    "q_lyrics": "",
                    "reason": "",
                }
            )
        has_explicit_track = any(
            query.get("q_track") or query.get("q_artist") for query in queries
        )
        theme_queries = _theme_queries_for_text(last_user, allowed_langs or None)
        if theme_queries and not has_explicit_track:
            if has_router_queries:
                queries = _dedupe_queries(queries + theme_queries)
            else:
                queries = _dedupe_queries(theme_queries)
            limit = 10
        else:
            queries = _dedupe_queries(queries)
        narration_lang = str(data.get("narration_lang", "")).strip().lower()
        meanings = self._parse_meanings(data.get("meanings"), allowed_langs)
        return {
            "music_related": as_bool(data.get("music_related"), True),
            "needs_search": needs_search,
            "limit": limit,
            "narration_lang": narration_lang,
            "queries": _interleave_queries_by_language(queries)[:20],
            "meanings": meanings,
        }

    @staticmethod
    def _parse_meanings(
        raw: Any, allowed_langs: Optional[set[str]] = None, cap: int = 6
    ) -> list[dict[str, str]]:
        """Normalizza le frasi-significato per la ricerca semantica (analysis.search).

        Accetta sia stringhe sia dict ``{"meaning", "lang"}``; scarta le lingue
        non consentite, deduplica per testo e limita a ``cap`` frasi.
        """
        if not isinstance(raw, list):
            return []
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, dict):
                text = str(item.get("meaning", "")).strip()
                lang = str(item.get("lang", "")).strip().upper()
            elif isinstance(item, str):
                text, lang = item.strip(), ""
            else:
                continue
            if not text:
                continue
            if allowed_langs and lang and lang not in allowed_langs:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"meaning": text, "lang": lang})
            if len(out) >= cap:
                break
        return out

    def _fallback_musixmatch_plan(
        self,
        last_user: str,
        reason: str = "",
        allowed_langs: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        queries = _theme_queries_for_text(last_user, allowed_langs or None)
        if not queries and last_user:
            queries = [
                {
                    "q": last_user,
                    "q_track": "",
                    "q_artist": "",
                    "q_lyrics": "",
                    "reason": "fallback dalla richiesta utente",
                }
            ]
        return {
            "music_related": True,
            "needs_search": bool(queries),
            "limit": 10,
            "narration_lang": "",
            "queries": _interleave_queries_by_language(_dedupe_queries(queries))[:20],
            "meanings": [],
            "_router_fallback": reason or "Used local Musixmatch query fallback.",
        }

    def compose_musixmatch_response(
        self,
        *,
        prompt: str,
        tracks: list[dict[str, Any]],
        language: str = "Italiano",
        context: str = "",
    ) -> tuple[str, str]:
        track_parts: list[str] = []
        for i, t in enumerate(tracks):
            line = f'{i + 1}. "{t.get("title", "")}" — {t.get("artist", "")}'
            if t.get("album"):
                line += f"\n   Album: {t.get('album', '')}"
            if t.get("reason"):
                line += f"\n   Motivo ricerca: {t.get('reason', '')}"
            audiodb_text = (
                t.get("audio_db_text") or t.get("audiodb_text") or ""
            ).strip()
            if audiodb_text:
                audiodb_short = audiodb_text[:260] + (
                    "…" if len(audiodb_text) > 260 else ""
                )
                line += f"\n   TheAudioDB: {audiodb_short}"
            richsync = t.get("richsync") or []
            if isinstance(richsync, list) and richsync:
                line += "\n   Richsync Musixmatch: disponibile"
            lyrics = (t.get("lyrics") or "").strip()
            if lyrics:
                lyrics_short = lyrics[:220] + ("…" if len(lyrics) > 220 else "")
                line += f"\n   Testo Musixmatch: {lyrics_short}"
            fact = (t.get("audio_db_fact") or t.get("audiodb_fact") or "").strip()
            if fact and fact != audiodb_text:
                fact_short = fact[:160] + ("…" if len(fact) > 160 else "")
                line += f"\n   Nota TheAudioDB: {fact_short}"
            track_parts.append(line)
        user = MUSIXMATCH_RESPONSE_TEMPLATE.format(
            prompt=prompt,
            tracks="\n\n".join(track_parts) if track_parts else "(nessun risultato)",
            language=language,
        )
        return self._chat(
            system=(
                "Sei un critico musicale. Usa solo i risultati forniti. "
                "Non aggiungere altri brani, artisti o dati non presenti. "
                "Dai priorita' al testo/contesto TheAudioDB quando presente. "
                "Parafrasa i testi senza copiarli integralmente. "
                f"Scrivi l'intera risposta esclusivamente in {language}, "
                "anche quando le fonti sono in un'altra lingua."
            ),
            user=user,
        )

    def curate(
        self,
        *,
        title: str,
        artist: str,
        lyrics: str,
        biography: str = "",
        theme: str = "",
        language: str = "Italiano",
        n_tracks: int = 8,
    ) -> EmotionalAnalysis:
        """Pipeline completa: analisi + proposta di playlist tematica."""
        analysis = self.analyze(
            title=title,
            artist=artist,
            lyrics=lyrics,
            biography=biography,
            theme=theme,
            language=language,
        )
        try:
            analysis.suggested_tracks = self.suggest_tracks(
                title=title,
                artist=artist,
                analysis=analysis.narrative,
                n=n_tracks,
                language=language,
            )
        except StorytellerError:
            analysis.suggested_tracks = []
        return analysis

    # ------------------------------------------------------------------ #
    # Verifica topico
    # ------------------------------------------------------------------ #
    def is_music_related(self, text: str) -> bool:
        """Ritorna True se il testo e' inerente alla musica (o ai suoi confini naturali:
        emozioni, testi, artisti, generi, cultura, psicologia, letteratura legata a musica).
        Usa una chiamata LLM minimale (pochi token). In caso di errore lascia passare (True).
        """
        system = (
            "You are a strict binary classifier. "
            "You MUST reply with the single word YES or NO and absolutely nothing else. "
            "No punctuation, no explanation, no reasoning."
        )
        user = (
            "Does the following message relate to music, song lyrics, artists, "
            "music emotions, music history, music genres, music psychology, or their "
            "connections to literature, culture and psychology?\n\n"
            f"Message: {text.strip()}\n\n"
            "Answer with only YES or NO."
        )
        try:
            answer, _ = self._complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            normalized = answer.strip().upper()
            if "NO" in normalized:
                return False
            return "YES" in normalized or normalized.startswith("Y")
        except StorytellerError:
            return True

    # ------------------------------------------------------------------ #
    # Interni
    # ------------------------------------------------------------------ #
    def converse(
        self,
        *,
        messages: list[dict[str, str]],
        language: str = "Italiano",
        context: str = "",
    ) -> tuple[str, str]:
        """Conversazione libera con la persona, mantenendo lo storico dei messaggi.

        `messages` e' la cronologia [{role: user|assistant, content: ...}].
        La risposta segue SEMPRE la lingua `language` (quella della UI), anche se
        l'utente scrive in un'altra lingua.
        `context` (testo/biografia opzionali) viene iniettato nel system prompt.
        """
        language_rule = f"Rispondi sempre in {language}, indipendentemente dalla lingua dell'utente."
        system = CHAT_SYSTEM_PROMPT.format(language_rule=language_rule)
        if context.strip():
            system += "\n\n## Contesto fornito dall'utente\n" + context.strip()

        chat_messages = [{"role": "system", "content": system}, *messages]
        return self._complete(chat_messages)

    @staticmethod
    def extract_playlist(content: str) -> tuple[str, list[dict[str, str]]]:
        """Separa il testo conversazionale da un eventuale blocco ```playlist```.

        Ritorna (testo_pulito, lista_brani). Se non c'e' blocco, lista vuota.
        """
        match = re.search(
            r"```playlist\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE
        )
        if not match:
            return content, []
        tracks = Storyteller._parse_tracks(match.group(1))
        clean = (content[: match.start()] + content[match.end() :]).strip()
        return clean, tracks

    def _chat(self, *, system: str, user: str) -> tuple[str, str]:
        """Chiamata chat con un singolo turno system+user (usata dalla pipeline brano)."""
        return self._complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )

    def _complete(self, messages: list[dict[str, str]]) -> tuple[str, str]:
        """Esegue la chiamata chat, con fallback se 'temperature' non e' supportata."""
        # --- Debug logging: what we are about to send to the LLM ----------- #
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        print(
            f"[LLM] → POST model={self.model} timeout={self.timeout}s "
            f"messages={len(messages)} total_chars={total_chars}",
            flush=True,
        )
        for i, m in enumerate(messages):
            content = str(m.get("content", ""))
            preview = content.replace("\n", " ")[:300]
            print(
                f"[LLM]    [{i}] role={m.get('role')} len={len(content)} :: {preview}",
                flush=True,
            )
        started = time.monotonic()
        # ------------------------------------------------------------------- #
        extra_body = (
            {"reasoning": {"effort": self.reasoning_effort}}
            if self.reasoning_effort
            else None
        )

        def _create(*, with_temperature: bool, with_reasoning: bool):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "timeout": self.timeout,
            }
            if with_temperature:
                kwargs["temperature"] = self.temperature
            if with_reasoning and extra_body:
                kwargs["extra_body"] = extra_body
            return self.client.chat.completions.create(**kwargs)

        try:
            response = _create(with_temperature=True, with_reasoning=True)
        except StorytellerError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalizziamo qualsiasi errore SDK
            err = str(exc).lower()
            # Some endpoints reject 'temperature' (reasoning models) and/or the
            # 'reasoning'/extra_body field (OpenAI-compatible targets that don't
            # support reasoning controls). Retry, dropping only the offending
            # parameter(s), so we degrade gracefully instead of hard-failing.
            drop_temperature = "temperature" in err
            drop_reasoning = bool(extra_body) and (
                "reasoning" in err or "extra_body" in err or "extra body" in err
            )
            if drop_temperature or drop_reasoning:
                print(
                    f"[LLM] ⚠ retry (temperature={'off' if drop_temperature else 'on'}, "
                    f"reasoning={'off' if drop_reasoning else 'on'}) "
                    f"dopo {time.monotonic() - started:.1f}s: {exc}",
                    flush=True,
                )
                try:
                    response = _create(
                        with_temperature=not drop_temperature,
                        with_reasoning=not drop_reasoning,
                    )
                except Exception as exc2:  # noqa: BLE001
                    print(
                        f"[LLM] ✗ FAILED dopo {time.monotonic() - started:.1f}s: {exc2}",
                        flush=True,
                    )
                    raise StorytellerError(f"Errore LLM: {exc2}") from exc2
            else:
                print(
                    f"[LLM] ✗ FAILED dopo {time.monotonic() - started:.1f}s: {exc}",
                    flush=True,
                )
                raise StorytellerError(f"Errore LLM: {exc}") from exc

        elapsed = time.monotonic() - started
        if not response.choices:
            print(
                f"[LLM] ✗ risposta vuota (no choices) dopo {elapsed:.1f}s", flush=True
            )
            raise StorytellerError("Risposta LLM vuota.")

        message = response.choices[0].message
        content = (message.content or "").strip()
        # I modelli di reasoning possono esporre la catena di pensiero a parte.
        reasoning = (getattr(message, "reasoning", None) or "").strip()
        print(
            f"[LLM] ← OK in {elapsed:.1f}s content_len={len(content)} "
            f"reasoning_len={len(reasoning)}",
            flush=True,
        )
        if not content:
            raise StorytellerError("Il modello non ha restituito contenuto testuale.")
        return content, reasoning

    @staticmethod
    def _extract_vector(text: str) -> tuple[str, list[str]]:
        """Estrae archetipo e parole chiave dalla sezione 'Vettore emotivo'."""
        archetype = ""
        keywords: list[str] = []

        match = re.search(r"archetipo\s*[:\-]\s*(.+)", text, flags=re.IGNORECASE)
        if match:
            archetype = match.group(1).splitlines()[0].strip(" *_`.")

        # Cerca una riga con parole chiave separate da virgola dopo l'archetipo.
        for line in text.splitlines():
            stripped = line.strip(" *_`-")
            if (
                "," in stripped
                and len(stripped.split(",")) >= 3
                and len(stripped) < 160
            ):
                if not stripped.lower().startswith("archetipo"):
                    keywords = [
                        k.strip(" *_`.") for k in stripped.split(",") if k.strip()
                    ]
                    if len(keywords) >= 3:
                        break
        return archetype, keywords[:8]

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """Estrae un oggetto JSON da una risposta LLM (tollerante ai code-fence)."""
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

        candidate = cleaned
        if not candidate.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = cleaned[start : end + 1]

        try:
            data = json.loads(candidate)
        except (ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _parse_tracks(content: str) -> list[dict[str, str]]:
        """Estrae un array JSON di brani da una risposta LLM (tollerante ai code-fence)."""
        cleaned = content.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

        candidate = cleaned
        if not candidate.startswith("["):
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end != -1 and end > start:
                candidate = cleaned[start : end + 1]

        try:
            data = json.loads(candidate)
        except (ValueError, json.JSONDecodeError):
            return []

        tracks: list[dict[str, str]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("title") and item.get("artist"):
                    tracks.append(
                        {
                            "title": str(item.get("title", "")).strip(),
                            "artist": str(item.get("artist", "")).strip(),
                            "reason": str(item.get("reason", "")).strip(),
                        }
                    )
        return tracks
