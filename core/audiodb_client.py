"""Client per le API TheAudioDB.

Recupera biografie multilingua e immagini degli artisti.
Documentazione: https://www.theaudiodb.com/api_guide.php

La chiave di test gratuita e' "2" (endpoint pubblico, rate-limited).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

import requests

from .config import settings

API_BASE = "https://www.theaudiodb.com/api/v1/json"

# Mappa lingua -> campo biografia restituito da TheAudioDB.
BIOGRAPHY_FIELDS: dict[str, str] = {
    "IT": "strBiographyIT",
    "EN": "strBiographyEN",
    "FR": "strBiographyFR",
    "DE": "strBiographyDE",
    "ES": "strBiographyES",
    "PT": "strBiographyPT",
    "NL": "strBiographyNL",
    "RU": "strBiographyRU",
    "JP": "strBiographyJP",
}


class AudioDBError(RuntimeError):
    """Errore generico durante una chiamata a TheAudioDB."""


@dataclass
class Artist:
    """Profilo artista normalizzato."""

    id: str = ""
    name: str = ""
    genre: str = ""
    style: str = ""
    country: str = ""
    formed_year: str = ""
    website: str = ""
    thumb_url: str = ""
    fanart_url: str = ""
    logo_url: str = ""
    biographies: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Artist":
        biographies = {
            lang: (data.get(api_field) or "").strip()
            for lang, api_field in BIOGRAPHY_FIELDS.items()
            if (data.get(api_field) or "").strip()
        }
        return cls(
            id=data.get("idArtist", "") or "",
            name=data.get("strArtist", "") or "",
            genre=data.get("strGenre", "") or "",
            style=data.get("strStyle", "") or "",
            country=data.get("strCountry", "") or "",
            formed_year=data.get("intFormedYear", "") or "",
            website=data.get("strWebsite", "") or "",
            thumb_url=data.get("strArtistThumb", "") or "",
            fanart_url=data.get("strArtistFanart", "") or "",
            logo_url=data.get("strArtistLogo", "") or "",
            biographies=biographies,
            raw=data,
        )

    def biography(self, language: str = "EN") -> str:
        """Restituisce la biografia nella lingua richiesta, con fallback EN -> qualsiasi."""
        lang = language.upper()
        if lang in self.biographies:
            return self.biographies[lang]
        if "EN" in self.biographies:
            return self.biographies["EN"]
        return next(iter(self.biographies.values()), "")

    @property
    def image_url(self) -> str:
        return self.thumb_url or self.fanart_url or self.logo_url


class AudioDBClient:
    """Wrapper minimale sulle API REST di TheAudioDB."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self.api_key = (api_key if api_key is not None else settings.audiodb_api_key) or "2"
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, endpoint: str, **params: Any) -> dict[str, Any]:
        url = f"{API_BASE}/{self.api_key}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AudioDBError(f"Errore di rete TheAudioDB: {exc}") from exc

        try:
            return response.json() or {}
        except ValueError as exc:
            raise AudioDBError("Risposta TheAudioDB non valida (JSON malformato)") from exc

    def get_artist(self, name: str) -> Optional[Artist]:
        """Cerca un artista per nome e restituisce il primo risultato."""
        if not name or not name.strip():
            return None
        data = self._request("search.php", s=name.strip())
        artists = data.get("artists")
        if not artists:
            return None
        return Artist.from_api(artists[0])

    def get_biography(self, artist: Union[str, Artist, None], language: str = "EN") -> str:
        """Restituisce la biografia (accetta nome o oggetto Artist)."""
        if isinstance(artist, str):
            artist = self.get_artist(artist)
        if not artist:
            return ""
        return artist.biography(language)

    def get_artist_image(self, artist: Union[str, Artist, None]) -> str:
        """Restituisce l'URL dell'immagine principale dell'artista."""
        if isinstance(artist, str):
            artist = self.get_artist(artist)
        if not artist:
            return ""
        return artist.image_url
