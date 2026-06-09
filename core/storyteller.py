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
psicologico. Ma puoi parlare liberamente di qualsiasi cosa l'utente desideri.

Tool musicali (usali SOLO quando sono pertinenti alla conversazione):
- Se l'utente porta un brano/un testo, puoi analizzarne il significato poetico e psicologico.
- Se ha senso proporre una playlist o dei brani affini, elencali e AGGIUNGI in fondo \
un blocco di codice etichettato `playlist` con un array JSON valido nel formato:
```playlist
[{{"title": "...", "artist": "...", "reason": "<max 12 parole>"}}]
```
Non inserire il blocco `playlist` se non stai effettivamente consigliando brani.

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


STUDIO_BRIEF_TEMPLATE = """Stai preparando un'esperienza audio-narrata ("radio d'autore") \
per questa playlist, nata dalla richiesta dell'utente: "{title}".

Per ogni brano sono forniti (quando disponibili) la biografia dell'artista e un estratto del testo.
Usali per rendere ogni narrazione specifica, profonda e ancorata a dettagli reali.

Brani (nell'ordine):
{tracks}

Per OGNI brano scrivi un "discorso" parlato: NON un testo da leggere a video, ma parole \
pensate per essere DETTE ad alta voce da una voce narrante (50-90 parole, in {language}). \
Sii evocativo: cita immagini concrete dal testo o dalla storia dell'artista, spiega il mood \
e perché il brano si lega agli altri nella playlist. Niente elenchi, solo prosa fluida adatta \
alla sintesi vocale.

Rispondi SOLO con un oggetto JSON valido (nessun testo prima o dopo) in questo formato:
{{
  "narrations": [
    {{
      "title": "...",
      "artist": "...",
      "speech": "<discorso parlato in {language}>",
      "mood": "<1-3 parole in {language}>",
      "origin": "<città, paese d'origine dell'artista>",
      "lat": <latitudine decimale dell'origine>,
      "lng": <longitudine decimale dell'origine>
    }}
  ],
  "summary": "<paragrafo in {language} che riassume mood e filo conduttore della playlist>",
  "moods": ["<mood1>", "<mood2>", "..."]
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
        user_prompt = PLAYLIST_TEMPLATE.format(
            analysis=analysis.strip(),
            n=n,
            title=title,
            artist=artist,
            language=language,
        )
        content, _ = self._chat(
            system="Sei un curatore musicale. Rispondi esclusivamente con JSON valido.",
            user=user_prompt,
        )
        return self._parse_tracks(content)

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
                bio_short = bio[:400] + ("…" if len(bio) > 400 else "")
                line += f'\n   Biografia: {bio_short}'
            if lyrics:
                lyrics_short = lyrics[:500] + ("…" if len(lyrics) > 500 else "")
                line += f'\n   Testo (estratto): {lyrics_short}'
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
