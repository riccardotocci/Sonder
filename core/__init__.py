"""Empathy for the Devil - pacchetto core.

Espone i client principali e l'oggetto di configurazione condiviso.
"""
from __future__ import annotations

from .config import settings
from .musixmatch_client import MusixmatchClient, MusixmatchError
from .audiodb_client import AudioDBClient, AudioDBError
from .musicbrainz_client import MusicBrainzClient, MusicBrainzError, MBArtist
from .lastfm_client import LastFMClient, LastFMError, LastFMArtist
from .storyteller import Storyteller, StorytellerError, EmotionalAnalysis
from .spotify_client import SpotifyClient, SpotifyError

__version__ = "0.1.0"

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
