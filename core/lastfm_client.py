"""Client per le API Last.fm.

Recupera biografie artista, tag, similar artists, e statistiche di ascolto.
Documentazione: https://www.last.fm/api

Richiede una API key gratuita (registrazione su https://www.last.fm/api/account/create).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from .config import settings

API_BASE = "https://ws.audioscrobbler.com/2.0/"


class LastFMError(RuntimeError):
    """Errore generico durante una chiamata a Last.fm."""


@dataclass
class LastFMArtist:
    """Profilo artista normalizzato da Last.fm."""

    name: str = ""
    mbid: str = ""  # MusicBrainz ID
    listeners: int = 0
    playcount: int = 0
    bio_summary: str = ""  # Breve biografia
    bio_content: str = ""  # Biografia completa
    bio_published: str = ""  # Data pubblicazione bio
    tags: list[str] = field(default_factory=list)
    similar: list[dict[str, Any]] = field(default_factory=list)
    image_urls: dict[str, str] = field(default_factory=dict)  # small, medium, large, extralarge, mega
    url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "LastFMArtist":
        """Crea oggetto LastFMArtist dalla risposta artist.getInfo."""
        artist_data = data.get("artist", {})
        
        # Statistiche
        stats = artist_data.get("stats", {})
        listeners = stats.get("listeners", "0")
        playcount = stats.get("playcount", "0")
        
        # Biografia
        bio = artist_data.get("bio", {})
        bio_content = bio.get("content", "")
        bio_summary = bio.get("summary", "")
        bio_published = bio.get("published", "")
        
        # Pulizia bio (rimuove link Last.fm in fondo)
        if bio_content and "<a href" in bio_content:
            bio_content = bio_content.split("<a href")[0].strip()
        if bio_summary and "<a href" in bio_summary:
            bio_summary = bio_summary.split("<a href")[0].strip()
        
        # Tag
        tags_data = artist_data.get("tags", {}).get("tag", [])
        if isinstance(tags_data, dict):  # Caso singolo tag
            tags_data = [tags_data]
        tags = [t.get("name", "") for t in tags_data if t.get("name")]
        
        # Artisti simili
        similar_data = artist_data.get("similar", {}).get("artist", [])
        if isinstance(similar_data, dict):  # Caso singolo
            similar_data = [similar_data]
        similar = [{"name": s.get("name", ""), "url": s.get("url", "")} for s in similar_data]
        
        # Immagini
        images = artist_data.get("image", [])
        image_urls = {}
        for img in images:
            size = img.get("size", "")
            url = img.get("#text", "")
            if size and url:
                image_urls[size] = url
        
        return cls(
            name=artist_data.get("name", ""),
            mbid=artist_data.get("mbid", ""),
            listeners=int(listeners) if listeners else 0,
            playcount=int(playcount) if playcount else 0,
            bio_summary=bio_summary,
            bio_content=bio_content,
            bio_published=bio_published,
            tags=tags,
            similar=similar,
            image_urls=image_urls,
            url=artist_data.get("url", ""),
            raw=artist_data,
        )

    @property
    def biography(self) -> str:
        """Restituisce la biografia completa (o summary se vuota)."""
        return self.bio_content or self.bio_summary
    
    @property
    def image_url(self) -> str:
        """Restituisce l'URL immagine migliore disponibile."""
        for size in ["mega", "extralarge", "large", "medium", "small"]:
            if size in self.image_urls:
                return self.image_urls[size]
        return ""


class LastFMClient:
    """Wrapper sulle API REST di Last.fm."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self.api_key = api_key if api_key is not None else settings.lastfm_api_key
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, method: str, **params: Any) -> dict[str, Any]:
        """Esegue richiesta GET al metodo Last.fm."""
        if not self.api_key:
            raise LastFMError("API key Last.fm non configurata. Ottienila su https://www.last.fm/api/account/create")
        
        url = API_BASE
        query_params = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            **params,
        }
        
        try:
            response = self.session.get(url, params=query_params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LastFMError(f"Errore di rete Last.fm: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LastFMError("Risposta Last.fm non valida (JSON malformato)") from exc
        
        # Last.fm restituisce errori nel JSON
        if "error" in data:
            error_msg = data.get("message", f"Errore {data['error']}")
            raise LastFMError(f"Errore API Last.fm: {error_msg}")
        
        return data

    def get_artist(self, name: Optional[str] = None, mbid: Optional[str] = None, lang: str = "EN") -> Optional[LastFMArtist]:
        """Recupera info artista per nome o MBID.
        
        Args:
            name: Nome artista
            mbid: MusicBrainz ID (preferibile per risultati precisi)
            lang: Lingua biografia (auto, en, de, es, fr, it, ja, pl, pt, ru, sv, tr, zh)
        """
        if not name and not mbid:
            return None
        
        params: dict[str, Any] = {}
        if mbid:
            params["mbid"] = mbid
        elif name:
            params["artist"] = name.strip()
        
        if lang and lang.lower() != "auto":
            params["lang"] = lang.lower()
        
        data = self._request("artist.getInfo", **params)
        return LastFMArtist.from_api(data)

    def get_biography(self, name: Optional[str] = None, mbid: Optional[str] = None, lang: str = "EN") -> str:
        """Restituisce solo la biografia (accetta nome o MBID)."""
        artist = self.get_artist(name=name, mbid=mbid, lang=lang)
        if not artist:
            return ""
        return artist.biography

    def get_artist_image(self, name: Optional[str] = None, mbid: Optional[str] = None) -> str:
        """Restituisce l'URL dell'immagine principale."""
        artist = self.get_artist(name=name, mbid=mbid)
        if not artist:
            return ""
        return artist.image_url

    def search_artist(self, name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Cerca artisti per nome. Restituisce lista risultati grezzi."""
        if not name or not name.strip():
            return []
        
        data = self._request("artist.search", artist=name.strip(), limit=limit)
        results = data.get("results", {}).get("artistmatches", {}).get("artist", [])
        if isinstance(results, dict):  # Caso singolo
            results = [results]
        return results
