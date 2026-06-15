"""Client per le API TheAudioDB.

Recupera biografie multilingua e immagini degli artisti.
Documentazione: https://www.theaudiodb.com/free_music_api

La chiave di test gratuita v1 e' "123" (endpoint pubblico, rate-limited).
"""
from __future__ import annotations

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
DESCRIPTION_FIELDS: dict[str, str] = {
    "IT": "strDescriptionIT",
    "EN": "strDescriptionEN",
    "FR": "strDescriptionFR",
    "DE": "strDescriptionDE",
    "ES": "strDescriptionES",
    "PT": "strDescriptionPT",
    "NL": "strDescriptionNL",
    "RU": "strDescriptionRU",
    "JP": "strDescriptionJP",
}
TRACK_LYRICS_FIELDS: tuple[str, ...] = (
    "strTrackLyrics",
    "strLyrics",
    "strLyric",
    "strTrackLyric",
)


class AudioDBError(RuntimeError):
    """Errore generico durante una chiamata a TheAudioDB."""


class Artist:
    """Profilo artista normalizzato."""

    def __init__(
        self,
        *,
        id: str = "",
        name: str = "",
        genre: str = "",
        style: str = "",
        country: str = "",
        formed_year: str = "",
        website: str = "",
        thumb_url: str = "",
        fanart_url: str = "",
        logo_url: str = "",
        biographies: Optional[dict[str, str]] = None,
        raw: Optional[dict[str, Any]] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.genre = genre
        self.style = style
        self.country = country
        self.formed_year = formed_year
        self.website = website
        self.thumb_url = thumb_url
        self.fanart_url = fanart_url
        self.logo_url = logo_url
        self.biographies = biographies or {}
        self.raw = raw or {}

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
        self.api_key = (api_key if api_key is not None else settings.audiodb_api_key) or "123"
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

    def search_track(self, artist: str, title: str) -> Optional[dict[str, Any]]:
        """Cerca metadati TheAudioDB per una traccia."""
        if not artist.strip() or not title.strip():
            return None
        data = self._request("searchtrack.php", s=artist.strip(), t=title.strip())
        tracks = data.get("track")
        if not tracks:
            return None
        first = tracks[0]
        return first if isinstance(first, dict) else None

    def search_album(self, artist: str, album: str) -> Optional[dict[str, Any]]:
        """Cerca metadati TheAudioDB per un album."""
        if not artist.strip() or not album.strip():
            return None
        data = self._request("searchalbum.php", s=artist.strip(), a=album.strip())
        albums = data.get("album")
        if not albums:
            return None
        first = albums[0]
        return first if isinstance(first, dict) else None

    @staticmethod
    def _localized_description(data: dict[str, Any], language: str = "EN") -> str:
        lang = language.upper()
        field = DESCRIPTION_FIELDS.get(lang, "strDescriptionEN")
        text = (data.get(field) or "").strip()
        if text:
            return text
        text = (data.get("strDescriptionEN") or "").strip()
        if text:
            return text
        for api_field in DESCRIPTION_FIELDS.values():
            text = (data.get(api_field) or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _first_present(data: dict[str, Any], fields: tuple[str, ...]) -> str:
        for field_name in fields:
            text = (data.get(field_name) or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _shorten(text: str, limit: int = 360) -> str:
        text = " ".join((text or "").split())
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
        return cut + "..."

    def get_music_fact(
        self,
        *,
        artist: str,
        title: str = "",
        album: str = "",
        language: str = "EN",
    ) -> str:
        """Restituisce una curiosita' fondata su dati TheAudioDB.

        Priorita': descrizione brano -> dettagli album -> dati artista. La stringa
        e' gia' corta e pronta da passare al prompt LLM come contesto fattuale.
        """
        if not artist.strip():
            return ""

        track = self.search_track(artist, title) if title.strip() else None
        if track:
            description = self._localized_description(track, language)
            if description:
                return self._shorten(description)
            pieces = []
            if track.get("strAlbum"):
                pieces.append(f"album: {track['strAlbum']}")
            if track.get("strGenre"):
                pieces.append(f"genre: {track['strGenre']}")
            if track.get("strMood"):
                pieces.append(f"mood: {track['strMood']}")
            if pieces:
                return self._shorten(f"TheAudioDB associa il brano a " + ", ".join(pieces) + ".")

        album_data = self.search_album(artist, album) if album.strip() else None
        if album_data:
            description = self._localized_description(album_data, language)
            if description:
                return self._shorten(description)
            pieces = []
            if album_data.get("intYearReleased"):
                pieces.append(f"pubblicato nel {album_data['intYearReleased']}")
            if album_data.get("strGenre"):
                pieces.append(f"genere {album_data['strGenre']}")
            if album_data.get("strLabel"):
                pieces.append(f"etichetta {album_data['strLabel']}")
            if pieces:
                album_name = album_data.get("strAlbum") or album
                return self._shorten(f"TheAudioDB registra l'album {album_name} come " + ", ".join(pieces) + ".")

        artist_data = self.get_artist(artist)
        if artist_data:
            pieces = []
            if artist_data.formed_year:
                pieces.append(f"attivo/formato dal {artist_data.formed_year}")
            if artist_data.country:
                pieces.append(f"origine {artist_data.country}")
            if artist_data.genre:
                pieces.append(f"genere {artist_data.genre}")
            if artist_data.style:
                pieces.append(f"stile {artist_data.style}")
            if pieces:
                return self._shorten(f"TheAudioDB descrive {artist_data.name or artist} come " + ", ".join(pieces) + ".")

        return ""

    def get_ordered_context(
        self,
        *,
        artist: str,
        title: str = "",
        album: str = "",
        language: str = "EN",
        limit: int = 900,
    ) -> dict[str, str]:
        """Restituisce contesto ordinato: brano -> album -> artista."""
        result = {
            "song_news": "",
            "album_news": "",
            "artist_description": "",
            "combined": "",
        }
        if not artist.strip():
            return result

        track = self.search_track(artist, title) if title.strip() else None
        if track:
            song_parts = []
            description = self._localized_description(track, language)
            if description:
                song_parts.append(description)
            details = []
            if track.get("strTheme"):
                details.append(f"tema {track['strTheme']}")
            if track.get("strMood"):
                details.append(f"mood {track['strMood']}")
            if track.get("strAlbum"):
                details.append(f"album {track['strAlbum']}")
            if track.get("strGenre"):
                details.append(f"genere {track['strGenre']}")
            if track.get("strMusicVid"):
                details.append("video musicale registrato")
            if details:
                song_parts.append("Dettagli brano: " + ", ".join(details) + ".")
            result["song_news"] = self._shorten(" ".join(song_parts), limit)

        album_data = self.search_album(artist, album) if album.strip() else None
        if album_data:
            album_parts = []
            description = self._localized_description(album_data, language)
            if description:
                album_parts.append(description)
            details = []
            album_name = album_data.get("strAlbum") or album
            if album_name:
                details.append(f"album {album_name}")
            if album_data.get("intYearReleased"):
                details.append(f"pubblicato nel {album_data['intYearReleased']}")
            if album_data.get("strLabel"):
                details.append(f"etichetta {album_data['strLabel']}")
            if album_data.get("strGenre"):
                details.append(f"genere {album_data['strGenre']}")
            if details:
                album_parts.append("Dettagli album: " + ", ".join(details) + ".")
            result["album_news"] = self._shorten(" ".join(album_parts), limit)

        artist_data = self.get_artist(artist)
        if artist_data:
            artist_parts = []
            biography = artist_data.biography(language)
            if biography:
                artist_parts.append(biography)
            details = []
            if artist_data.formed_year:
                details.append(f"attivo/formato dal {artist_data.formed_year}")
            if artist_data.country:
                details.append(f"origine {artist_data.country}")
            if artist_data.genre:
                details.append(f"genere {artist_data.genre}")
            if artist_data.style:
                details.append(f"stile {artist_data.style}")
            if details:
                artist_parts.append("Dettagli artista: " + ", ".join(details) + ".")
            result["artist_description"] = self._shorten(" ".join(artist_parts), limit)

        combined_parts = [
            text for text in (
                result["song_news"],
                result["album_news"],
                result["artist_description"],
            )
            if text
        ]
        result["combined"] = self._shorten(" ".join(combined_parts), limit)
        return result

    def get_track_text(
        self,
        *,
        artist: str,
        title: str,
        album: str = "",
        language: str = "EN",
        limit: int = 900,
    ) -> str:
        """Restituisce testo/contesto brano da TheAudioDB, se disponibile.

        TheAudioDB non garantisce testi completi per ogni traccia: quando un campo
        lyric non e' presente, usiamo la descrizione localizzata del brano come
        contesto testuale verificato.
        """
        track = self.search_track(artist, title) if artist.strip() and title.strip() else None
        if track:
            lyrics = self._first_present(track, TRACK_LYRICS_FIELDS)
            if lyrics:
                return self._shorten(lyrics, limit)

            description = self._localized_description(track, language)
            if description:
                return self._shorten(description, limit)

            pieces = []
            if track.get("strMood"):
                pieces.append(f"mood: {track['strMood']}")
            if track.get("strGenre"):
                pieces.append(f"genre: {track['strGenre']}")
            if track.get("strAlbum"):
                pieces.append(f"album: {track['strAlbum']}")
            if pieces:
                return self._shorten("TheAudioDB associa il brano a " + ", ".join(pieces) + ".", limit)

        album_data = self.search_album(artist, album) if artist.strip() and album.strip() else None
        if album_data:
            description = self._localized_description(album_data, language)
            if description:
                return self._shorten(description, limit)

        artist_data = self.get_artist(artist) if artist.strip() else None
        if artist_data:
            description = artist_data.biography(language)
            if description:
                return self._shorten(description, limit)

        return ""
