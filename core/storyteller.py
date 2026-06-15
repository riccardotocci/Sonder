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
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI

from .config import settings


class StorytellerError(RuntimeError):
    """Errore generico durante la generazione LLM."""


@dataclass
class EmotionalAnalysis:
    """Output strutturato del motore narrativo."""

    narrative: str = ""                       # analisi + micro-racconto (Markdown)
    archetype: str = ""                       # es. "L'Ombra redenta"
    keywords: list[str] = field(default_factory=list)
    suggested_tracks: list[dict[str, str]] = field(default_factory=list)
    reasoning: str = ""                       # catena di pensiero (se esposta)
    model: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.narrative.strip()


SYSTEM_PROMPT = """Sei "Empathy for the Devil", un critico musicale, poeta e \
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
2-3 paragrafi che decodificano metafore, slang e tensioni interiori, collegando \
il testo al vissuto dell'artista (se la biografia lo consente).

### Micro-racconto
Un breve racconto in seconda o terza persona (120-200 parole) che traduce il \
"vettore emotivo" del brano in una scena narrativa, in stile nota di copertina."""


CHAT_SYSTEM_PROMPT = """Sei "Empathy for the Devil": critico musicale, poeta e \
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
- Output in Markdown pulito ed elegante.
- Sii evocativo ma fondato; non inventare dati biografici non forniti.
- Niente disclaimer, niente meta-commenti sul fatto che sei un'IA.
- AMBITO: rispondi SOLO a domande inerenti alla musica, ai testi, alle emozioni \
musicali, agli artisti, ai generi, alla storia della musica e alle sue connessioni \
con letteratura, psicologia e cultura. Se l'utente ti chiede qualcosa di \
completamente estraneo alla musica, scrivi PRIMA la riga esatta [NON_MUSICALE] e poi \
il tuo rifiuto in-character breve e senza playlist. Non rispondere mai a domande di \
cucina, sport, politica, tecnologia o qualsiasi altro argomento non musicale."""


MUSIXMATCH_SEARCH_TEMPLATE = """Prepara query Musixmatch concise. Rispondi SOLO JSON.

Lingua: {language_rule}

Messaggi:
{messages}

Regole:
- Se l'utente cita titolo/artista, usa q_track e q_artist.
- Per temi crea 4-8 query incentrate su parole/immagini del tema, NON su emozioni generiche.
- Metti parole da testo in q_lyrics: goodbye, addio, adieu, adios, miss you, mi manchi, tu me manques, te extraño, senza di te, sin ti.
- Usa q solo per genere/lingua/periodo. Non usare q per mood astratti.
- Evita parole inutili: canzoni, brani, playlist, consigliami.
- Evita etichette generiche: sad, emotional, melancholic, heartbreak, loss, broken heart, triste.
- Non inventare titoli o artisti.
- reason: descrizione tematica profonda, 5-8 parole.
- reason NON deve citare genere, mood, emozioni generiche, strumenti o lingua.

Schema:
{{
  "music_related": true,
  "needs_search": true,
    "limit": 10,
  "queries": [
    {{
      "q": "",
      "q_track": "",
      "q_artist": "",
      "q_lyrics": "",
    "reason": ""
    }}
  ]
}}
Usa limit 1-10. Se non serve cercare, needs_search=false e queries=[]."""


MUSIXMATCH_RESPONSE_TEMPLATE = """Richiesta: {prompt}

Risultati:
{tracks}

Scrivi in {language}, Markdown pulito.
Usa solo questi brani. Niente titoli extra.
Per ogni brano: una frase puntuale sul perche' risponde alla richiesta.
Dai priorita' a TheAudioDB; usa Musixmatch solo come supporto.
Parafrasa, non copiare versi lunghi.
Se non ci sono risultati, chiedi una richiesta piu' precisa."""


STUDIO_BRIEF_TEMPLATE = """Crea una regia audio concisa per: "{title}".

Brani (nell'ordine):
{tracks}

Per ogni brano scrivi DUE parti separate in {language}:
- musixmatch_speech: 25-40 parole basate solo su testo/richsync Musixmatch e motivo ricerca.
- audiodb_speech: 25-40 parole basate solo su TheAudioDB/biografia/metadati.
Non mescolare le fonti. Non inventare.

Rispondi SOLO JSON valido:
{{
  "narrations": [
    {{
      "title": "...",
      "artist": "...",
            "musixmatch_speech": "...",
            "audiodb_speech": "...",
            "mood": "...",
            "origin": "...",
      "lat": <latitudine decimale dell'origine>,
      "lng": <longitudine decimale dell'origine>
    }}
  ],
    "summary": "...",
    "moods": ["..."]
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
            {"lang": "EN", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "goodbye", "reason": "congedo detto prima del vuoto"},
            {"lang": "EN", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "miss you", "reason": "assenza che abita il presente"},
            {"lang": "EN", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "without you", "reason": "identità ridotta dal distacco"},
            {"lang": "IT", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "addio", "reason": "soglia chiusa senza ritorno"},
            {"lang": "IT", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "mi manchi", "reason": "nome invocato nello spazio vuoto"},
            {"lang": "IT", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "senza di te", "reason": "vita ridefinita dalla sottrazione"},
            {"lang": "FR", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "adieu", "reason": "separazione trasformata in destino"},
            {"lang": "FR", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "tu me manques", "reason": "il tu resta come mancanza"},
            {"lang": "FR", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "sans toi", "reason": "mondo privato del suo centro"},
            {"lang": "ES", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "adios", "reason": "porta chiusa sul passato condiviso"},
            {"lang": "ES", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "te extraño", "reason": "distanza che continua a chiamare"},
            {"lang": "ES", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "sin ti", "reason": "io incompleto senza il tu"},
            {"lang": "DE", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "auf wiedersehen", "reason": "promessa fragile dentro il congedo"},
            {"lang": "DE", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "ich vermisse dich", "reason": "assenza misurata nel quotidiano"},
            {"lang": "DE", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "ohne dich", "reason": "presenza cancellata dalla frase"},
            {"lang": "PT", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "adeus", "reason": "partenza senza data di ritorno"},
            {"lang": "PT", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "saudade", "reason": "memoria che sostituisce la presenza"},
            {"lang": "PT", "q": "", "q_track": "", "q_artist": "", "q_lyrics": "sem você", "reason": "quotidiano svuotato dal pronome"},
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
}

THEME_QUERY_LANGUAGE_ORDER = ("EN", "IT", "FR", "ES", "DE", "PT")


def _theme_queries_for_text(text: str) -> list[dict[str, str]]:
    normalized = text.casefold()
    queries: list[dict[str, str]] = []
    for triggers, bank in THEME_QUERY_BANK:
        if any(trigger in normalized for trigger in triggers):
            queries.extend(dict(item) for item in bank)
    by_language: dict[str, list[dict[str, str]]] = {lang: [] for lang in THEME_QUERY_LANGUAGE_ORDER}
    for query in queries:
        language = str(query.get("lang", "")).upper()
        by_language.setdefault(language, []).append(query)

    spread: list[dict[str, str]] = []
    index = 0
    while len(spread) < 10:
        added = False
        for language in THEME_QUERY_LANGUAGE_ORDER:
            bucket = by_language.get(language, [])
            if index < len(bucket):
                spread.append(bucket[index])
                added = True
                if len(spread) >= 10:
                    break
        if not added:
            break
        index += 1
    return spread


def _query_text(query: dict[str, str]) -> str:
    return " ".join(str(query.get(key, "")) for key in ("q", "q_lyrics")).casefold()


def _is_generic_theme_query(query: dict[str, str]) -> bool:
    text = _query_text(query)
    if not text:
        return False
    if any(term in text for term in CONCRETE_THEME_TERMS):
        return False
    return any(term in text for term in GENERIC_THEME_TERMS)


def _dedupe_queries(queries: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, str]] = []
    for query in queries:
        key = tuple(str(query.get(field, "")).casefold() for field in ("q", "q_track", "q_artist", "q_lyrics"))
        if key in seen:
            continue
        seen.add(key)
        result.append(query)
    return result


class Storyteller:
    """Genera analisi emotive e curatela playlist tramite un LLM 'Thinking'."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.85,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.temperature = temperature
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if not self.api_key:
            raise StorytellerError(
                "Chiave API LLM mancante. Imposta LLM_API_KEY (e LLM_BASE_URL/LLM_MODEL) nel file .env"
            )
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url or None)
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
        theme_line = f"- Tema/filo conduttore richiesto: {theme}\n" if theme.strip() else ""
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
        """Genera, in una sola chiamata, i 'discorsi' parlati per ogni brano,
        l'origine geografica, i mood e un riassunto della playlist.

        Ritorna un dict con chiavi: 'narrations' (list), 'summary' (str), 'moods' (list).
        In caso di errore o playlist vuota ritorna {}.
        """
        if not tracks:
            return {}
        track_parts: list[str] = []
        for i, t in enumerate(tracks):
            line = f'{i + 1}. "{t.get("title", "")}" — {t.get("artist", "")}'
            bio = (t.get("_bio") or t.get("bio") or "").strip()
            lyrics = (t.get("lyrics") or "").strip()
            if bio:
                bio_short = bio[:180] + ("…" if len(bio) > 180 else "")
                line += f'\n   TheAudioDB bio: {bio_short}'
            if lyrics:
                lyrics_short = lyrics[:180] + ("…" if len(lyrics) > 180 else "")
                line += f'\n   Musixmatch testo: {lyrics_short}'
            audiodb_text = (t.get("audio_db_text") or t.get("audiodb_text") or "").strip()
            if audiodb_text:
                audiodb_short = audiodb_text[:240] + ("…" if len(audiodb_text) > 240 else "")
                line += f'\n   TheAudioDB contesto: {audiodb_short}'
            fact = (t.get("audio_db_fact") or t.get("audiodb_fact") or "").strip()
            if fact and fact != audiodb_text:
                line += f'\n   TheAudioDB nota: {fact}'
            track_parts.append(line)
        track_lines = "\n\n".join(track_parts)
        user = STUDIO_BRIEF_TEMPLATE.format(
            title=title or "(senza titolo)",
            tracks=track_lines,
            language=language,
            n=len(tracks),
        )
        content, _ = self._chat(
            system="Sei un autore radiofonico. Rispondi esclusivamente con JSON valido.",
            user=user,
        )
        return self._parse_json(content)

    def plan_musixmatch_search(
        self,
        *,
        messages: list[dict[str, str]],
        language: str = "Italiano",
        context: str = "",
    ) -> dict[str, Any]:
        if language == "Auto":
            language_rule = (
                "Riconosci automaticamente la lingua dell'ultimo messaggio dell'utente."
            )
        else:
            language_rule = f"Interpreta la richiesta e rispondi in {language} quando richiesto."
        recent = messages[-4:]
        last_user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                last_user = message.get("content", "")
                break
        user = MUSIXMATCH_SEARCH_TEMPLATE.format(
            language_rule=language_rule,
            context=context.strip() or "(nessuno)",
            messages=json.dumps(recent, ensure_ascii=False, indent=2),
        )
        content, _ = self._chat(
            system="Sei un router di ricerca musicale. Rispondi esclusivamente con JSON valido.",
            user=user,
        )
        data = self._parse_json(content)
        if not data:
            return {
                "music_related": True,
                "needs_search": True,
                "limit": 10,
                "queries": [{"q": last_user, "q_track": "", "q_artist": "", "q_lyrics": "", "reason": ""}],
            }
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
                    "reason": str(item.get("reason", "")).strip(),
                }
                if any(query[k] for k in ("q", "q_track", "q_artist", "q_lyrics")):
                    queries.append(query)
        if as_bool(data.get("needs_search"), True) and not queries and last_user:
            queries.append({"q": last_user, "q_track": "", "q_artist": "", "q_lyrics": "", "reason": ""})
        has_explicit_track = any(query.get("q_track") or query.get("q_artist") for query in queries)
        theme_queries = _theme_queries_for_text(last_user)
        if theme_queries and not has_explicit_track:
            concrete_queries = [query for query in queries if not _is_generic_theme_query(query)]
            queries = _dedupe_queries(theme_queries + concrete_queries)
        else:
            queries = _dedupe_queries(queries)
        return {
            "music_related": as_bool(data.get("music_related"), True),
            "needs_search": as_bool(data.get("needs_search"), True),
            "limit": limit,
            "queries": queries[:10],
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
                line += f'\n   Album: {t.get("album", "")}'
            if t.get("reason"):
                line += f'\n   Motivo ricerca: {t.get("reason", "")}'
            audiodb_text = (t.get("audio_db_text") or t.get("audiodb_text") or "").strip()
            if audiodb_text:
                audiodb_short = audiodb_text[:260] + ("…" if len(audiodb_text) > 260 else "")
                line += f'\n   TheAudioDB: {audiodb_short}'
            richsync = t.get("richsync") or []
            if isinstance(richsync, list) and richsync:
                line += "\n   Richsync Musixmatch: disponibile"
            lyrics = (t.get("lyrics") or "").strip()
            if lyrics:
                lyrics_short = lyrics[:220] + ("…" if len(lyrics) > 220 else "")
                line += f'\n   Testo Musixmatch: {lyrics_short}'
            fact = (t.get("audio_db_fact") or t.get("audiodb_fact") or "").strip()
            if fact and fact != audiodb_text:
                fact_short = fact[:160] + ("…" if len(fact) > 160 else "")
                line += f'\n   Nota TheAudioDB: {fact_short}'
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
                "Parafrasa i testi senza copiarli integralmente."
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
        Con `language == "Auto"` il modello riconosce e usa la lingua dell'utente.
        `context` (testo/biografia opzionali) viene iniettato nel system prompt.
        """
        if language == "Auto":
            language_rule = (
                "Riconosci automaticamente la lingua dell'ultimo messaggio dell'utente "
                "e rispondi SEMPRE in quella stessa lingua."
            )
        else:
            language_rule = (
                f"Rispondi sempre in {language}, indipendentemente dalla lingua dell'utente."
            )
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
        clean = (content[: match.start()] + content[match.end():]).strip()
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
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
        except StorytellerError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalizziamo qualsiasi errore SDK
            # Alcuni modelli "reasoning" (o3/o1) non accettano 'temperature'.
            if "temperature" in str(exc).lower():
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                    )
                except Exception as exc2:  # noqa: BLE001
                    raise StorytellerError(f"Errore LLM: {exc2}") from exc2
            else:
                raise StorytellerError(f"Errore LLM: {exc}") from exc

        if not response.choices:
            raise StorytellerError("Risposta LLM vuota.")

        message = response.choices[0].message
        content = (message.content or "").strip()
        # I modelli di reasoning possono esporre la catena di pensiero a parte.
        reasoning = (getattr(message, "reasoning", None) or "").strip()
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
            if "," in stripped and len(stripped.split(",")) >= 3 and len(stripped) < 160:
                if not stripped.lower().startswith("archetipo"):
                    keywords = [k.strip(" *_`.") for k in stripped.split(",") if k.strip()]
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
