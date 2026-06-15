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


LLM_MODEL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Gemma", "google/gemma-4-31b-it:free"),
    ("Nemotron 3 Ultra", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("Owl Alpha", "openrouter/owl-alpha"),
    ("Nex N2 Pro", "nex-agi/nex-n2-pro:free"),
    ("GPT OSS 120B", "openai/gpt-oss-120b:free"),
)
DEFAULT_LLM_MODEL = LLM_MODEL_OPTIONS[0][1]


def _env(key: str, default: str = "") -> str:
    """Legge una variabile d'ambiente restituendo sempre una stringa pulita."""
    value = os.getenv(key, default)
    return (value or default).strip()


@dataclass(frozen=True)
class Settings:
    """Snapshot immutabile della configurazione dell'applicazione."""

    # --- Musixmatch ---
    musixmatch_api_key: str = field(
        default_factory=lambda: _env("MUSIXMATCH_API_KEY") or _env("MXM_KEY")
    )

    # --- TheAudioDB ("123" = chiave di test pubblica gratuita v1) ---
    audiodb_api_key: str = field(default_factory=lambda: _env("AUDIODB_API_KEY", "123"))

    # --- Last.fm API (biografie + statistiche ascolto) ---
    # Ottieni la chiave su https://www.last.fm/api/account/create
    lastfm_api_key: str = field(default_factory=lambda: _env("LASTFM_API_KEY"))

    # --- Motore LLM (OpenRouter / OpenAI / DeepSeek) ---
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    )
    llm_model: str = field(
        default_factory=lambda: _env("LLM_MODEL", DEFAULT_LLM_MODEL)
    )

    # --- ElevenLabs TTS ---
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    # Voice ID from your ElevenLabs account (default: George - warm/narrative).
    elevenlabs_voice_id: str = field(
        default_factory=lambda: _env("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    )

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
        return bool(self.audiodb_api_key)

    @property
    def lastfm_ready(self) -> bool:
        return bool(self.lastfm_api_key)

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
    def spotify_pkce_ready(self) -> bool:
        """Per il flusso per-utente (PKCE) basta il Client ID pubblico."""
        return bool(self.spotify_client_id)

    def status(self) -> dict[str, bool]:
        """Mappa servizio -> configurato, da mostrare nella UI."""
        return {
            "Musixmatch": self.musixmatch_ready,
            "TheAudioDB": self.audiodb_ready,
            "Last.fm": self.lastfm_ready,
            "LLM (Thinking)": self.llm_ready,
            "ElevenLabs TTS": self.elevenlabs_ready,
            "Spotify": self.spotify_pkce_ready,
        }


# Istanza singleton condivisa da tutti i moduli.
settings = Settings()
