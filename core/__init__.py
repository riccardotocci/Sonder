"""Empathy for the Devil - pacchetto core.

Gli export pubblici sono caricati in modo lazy: quando Streamlit importa
``core.config`` non deve inizializzare anche client non usati nel bootstrap.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.1.0"

_EXPORTS: dict[str, tuple[str, str]] = {
    "settings": (".config", "settings"),
    "MusixmatchClient": (".musixmatch_client", "MusixmatchClient"),
    "MusixmatchError": (".musixmatch_client", "MusixmatchError"),
    "AudioDBClient": (".audiodb_client", "AudioDBClient"),
    "AudioDBError": (".audiodb_client", "AudioDBError"),
    "MusicBrainzClient": (".musicbrainz_client", "MusicBrainzClient"),
    "MusicBrainzError": (".musicbrainz_client", "MusicBrainzError"),
    "MBArtist": (".musicbrainz_client", "MBArtist"),
    "LastFMClient": (".lastfm_client", "LastFMClient"),
    "LastFMError": (".lastfm_client", "LastFMError"),
    "LastFMArtist": (".lastfm_client", "LastFMArtist"),
    "Storyteller": (".storyteller", "Storyteller"),
    "StorytellerError": (".storyteller", "StorytellerError"),
    "EmotionalAnalysis": (".storyteller", "EmotionalAnalysis"),
    "SpotifyClient": (".spotify_client", "SpotifyClient"),
    "SpotifyError": (".spotify_client", "SpotifyError"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    "settings",
    "MusixmatchClient",
    "MusixmatchError",
    "AudioDBClient",
    "AudioDBError",
    "MusicBrainzClient",
    "MusicBrainzError",
    "MBArtist",
    "LastFMClient",
    "LastFMError",
    "LastFMArtist",
    "Storyteller",
    "StorytellerError",
    "EmotionalAnalysis",
    "SpotifyClient",
    "SpotifyError",
    "__version__",
]
