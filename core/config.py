"""Caricamento centralizzato delle impostazioni e delle chiavi API.

Tutte le credenziali vengono lette dal file ``.env`` (vedi ``.env.example``).
Nessuna chiave e' hard-coded: se mancano, i client lo segnalano in modo esplicito
e l'interfaccia entra in "modalita' demo".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Carica le variabili dal file .env nella root del progetto (se presente).
load_dotenv()


DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"

# Soglia di notorieta' minima (task 4): le tracce con un numero di stream/ascolti
# Songstats inferiore a questo valore vengono escluse dai risultati. Spotify
# "popularity" e' 0-100 e NON e' un conteggio di riproduzioni, quindi usiamo
# Songstats (conteggio reale di stream) come metrica di soglia.
SONGSTATS_MIN_STREAMS = 10_000

# Lingue selezionabili nella barra di ricerca (task 6): etichetta -> codice usato
# nelle query Musixmatch (coerente con il banco query in storyteller.py).
SEARCH_LANGUAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("English", "EN"),
    ("Italiano", "IT"),
    ("Français", "FR"),
    ("Español", "ES"),
    ("Deutsch", "DE"),
    ("Português", "PT"),
    ("日本語", "JA"),
    ("한국어", "KO"),
    ("中文", "ZH"),
    ("हिन्दी", "HI"),
    ("Nederlands", "NL"),
    ("Dansk", "DA"),
    ("Hrvatski", "HR"),
    ("Ελληνικά", "EL"),
    ("Norsk", "NO"),
    ("Русский", "RU"),
    ("Українська", "UK"),
    ("العربية", "AR"),
    ("Svenska", "SV"),
    ("Polski", "PL"),
    ("Türkçe", "TR"),
    ("Čeština", "CS"),
    ("Română", "RO"),
    ("Magyar", "HU"),
    ("עברית", "HE"),
    ("Suomi", "FI"),
    ("Bahasa Indonesia", "ID"),
    ("Tiếng Việt", "VI"),
    ("ไทย", "TH"),
)

LLM_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("GPT OSS 120B", DEFAULT_LLM_MODEL),
    ("Gemma", "google/gemma-4-31b-it:free"),
    ("Nemotron 3 Ultra", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("Nemotron 3 Super", "nvidia/nemotron-3-super-120b-a12b:free"),
    ("Owl Alpha", "openrouter/owl-alpha"),
    ("Nex N2 Pro", "nex-agi/nex-n2-pro:free"),
)


def _env(key: str, default: str = "") -> str:
    """Legge una variabile d'ambiente restituendo sempre una stringa pulita."""
    value = os.getenv(key)
    if value is None or not str(value).strip():
        try:
            import streamlit as _st

            value = _st.secrets.get(key, "")
        except Exception:
            value = ""
    if value is None or not str(value).strip():
        value = default
    return str(value or default).strip()


def _env_float(key: str, default: float) -> float:
    value = _env(key, str(default))
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    """Legge un flag booleano da ambiente; valori vuoti restituiscono il default."""
    raw = _env(key, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    """Snapshot immutabile della configurazione dell'applicazione."""

    # --- Musixmatch ---
    musixmatch_api_key: str = field(
        default_factory=lambda: _env("MUSIXMATCH_API_KEY") or _env("MXM_KEY")
    )
    # Sorgenti di ricerca Musixmatch attivabili in modo indipendente: le query
    # basate sui TESTI (lyrics) e/o la ricerca per SIGNIFICATO (meaning). Possono
    # stare insieme o da sole. Default: solo lyrics attivo; il meaning e' OFF
    # perche' da solo tende a restituire sempre gli stessi brani popolari.
    # Non influenzano il piano dell'LLM ne' il check successivo sui candidati.
    musixmatch_use_lyrics: bool = field(
        default_factory=lambda: _env_bool("MUSIXMATCH_USE_LYRICS", True)
    )
    musixmatch_use_meaning: bool = field(
        default_factory=lambda: _env_bool("MUSIXMATCH_USE_MEANING", False)
    )
    # --- TheAudioDB (v2 Premium: la chiave va nell'header X-API-KEY) ---
    # La chiave di test "123" funziona solo con la vecchia v1 e viene rifiutata
    # dalla v2, quindi non viene piu' usata come default: senza chiave Premium la
    # sezione entra in modalita' demo.
    audiodb_api_key: str = field(default_factory=lambda: _env("AUDIODB_API_KEY"))

    # --- Motore LLM (OpenRouter / OpenAI / DeepSeek) ---
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    )
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", DEFAULT_LLM_MODEL))
    llm_timeout_seconds: float = field(
        default_factory=lambda: _env_float("LLM_TIMEOUT_SECONDS", 20.0)
    )

    # --- ElevenLabs TTS ---
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    # Voice ID from your ElevenLabs account (default: George - warm/narrative).
    elevenlabs_voice_id: str = field(
        default_factory=lambda: _env("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    )
    # auto = local endpoint in dev, embedded audio on hosted Streamlit URLs.
    sonder_tts_mode: str = field(
        default_factory=lambda: _env("SONDER_TTS_MODE", "auto").lower()
    )

    # --- Songstats (statistiche di streaming/popolarita' reali) ---
    # Ottieni la chiave su https://songstats.com/api (header "apikey").
    songstats_api_key: str = field(default_factory=lambda: _env("SONGSTATS_API_KEY"))

    # --- Spotify ---
    # Solo il Client ID e' richiesto (pubblico) per il flusso PKCE per-utente:
    # ogni visitatore accede col proprio account, senza client secret ne' server.
    spotify_client_id: str = field(default_factory=lambda: _env("SPOTIFY_CLIENT_ID"))
    spotify_client_secret: str = field(
        default_factory=lambda: _env("SPOTIFY_CLIENT_SECRET")
    )
    # Per PKCE il redirect deve puntare alla URL dell'app.
    # NB: Spotify non accetta piu' "localhost" nelle Redirect URI: usa 127.0.0.1.
    spotify_redirect_uri: str = field(
        default_factory=lambda: _env("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8501")
    )

    # ------------------------------------------------------------------ #
    # Helper di stato: utili all'interfaccia per segnalare cosa manca.
    # ------------------------------------------------------------------ #
    @property
    def musixmatch_ready(self) -> bool:
        return bool(self.musixmatch_api_key)

    @property
    def audiodb_ready(self) -> bool:
        # La v2 e' Premium: la vecchia chiave di test "123" non e' valida.
        return bool(self.audiodb_api_key) and self.audiodb_api_key != "123"

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def spotify_ready(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_client_secret)

    @property
    def elevenlabs_ready(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def songstats_ready(self) -> bool:
        return bool(self.songstats_api_key)

    @property
    def spotify_pkce_ready(self) -> bool:
        """Per il flusso per-utente (PKCE) basta il Client ID pubblico."""
        return bool(self.spotify_client_id)

    def status(self) -> dict[str, bool]:
        """Mappa servizio -> configurato, da mostrare nella UI."""
        return {
            "Musixmatch": self.musixmatch_ready,
            "TheAudioDB": self.audiodb_ready,
            "LLM (Thinking)": self.llm_ready,
            "ElevenLabs TTS": self.elevenlabs_ready,
            "Spotify": self.spotify_pkce_ready,
            "Songstats": self.songstats_ready,
        }


# Istanza singleton condivisa da tutti i moduli.
settings = Settings()
