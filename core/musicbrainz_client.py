"""Client per le API MusicBrainz.

Recupera metadati artista, ID Wikidata per biografie, e relazioni.
Documentazione: https://musicbrainz.org/doc/Development/XML_Web_Service/Version_2

MusicBrainz richiede uno User-Agent identificativo. E' gratuito e open.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import requests

API_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "EmpathyForTheDevil/0.1.0 (hackathon@example.com)"


class MusicBrainzError(RuntimeError):
    """Errore generico durante una chiamata a MusicBrainz."""


@dataclass
class MBArtist:
    """Profilo artista normalizzato da MusicBrainz."""

    id: str = ""  # MBID
    name: str = ""
    sort_name: str = ""
    type: str = ""  # Person, Group, Orchestra, etc.
    country: str = ""
    disambiguation: str = ""
    # Relazioni utili
    wikidata_id: Optional[str] = None  # Per biografie tramite Wikidata
    wikipedia_url: Optional[str] = None
    official_website: Optional[str] = None
    discogs_id: Optional[str] = None
    allmusic_id: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "MBArtist":
        """Crea oggetto MBArtist dalla risposta API."""
        relations = data.get("relations", [])
        
        wikidata_id = None
        wikipedia_url = None
        official_website = None
        discogs_id = None
        allmusic_id = None
        
        for rel in relations:
            rel_type = rel.get("type")
            target = rel.get("target", "")
            if rel_type == "wikidata":
                # Estrae Q-ID dall'URL Wikidata
                wikidata_id = target.split("/")[-1] if target else None
            elif rel_type == "wikipedia":
                wikipedia_url = target
            elif rel_type == "official website":
                official_website = target
            elif rel_type == "discogs":
                discogs_id = target.split("/")[-1] if target else None
            elif rel_type == "allmusic":
                allmusic_id = target.split("/")[-1] if target else None
        
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            sort_name=data.get("sort-name", ""),
            type=data.get("type", ""),
            country=data.get("country", ""),
            disambiguation=data.get("disambiguation", ""),
            wikidata_id=wikidata_id,
            wikipedia_url=wikipedia_url,
            official_website=official_website,
            discogs_id=discogs_id,
            allmusic_id=allmusic_id,
            raw=data,
        )


class MusicBrainzClient:
    """Wrapper sulle API REST di MusicBrainz (JSON)."""

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Esegue richiesta GET all'endpoint MusicBrainz."""
        url = f"{API_BASE}/{endpoint}"
        query_params = params.copy() if params else {}
        query_params["fmt"] = "json"
        
        try:
            response = self.session.get(url, params=query_params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MusicBrainzError(f"Errore di rete MusicBrainz: {exc}") from exc

        try:
            return response.json() or {}
        except ValueError as exc:
            raise MusicBrainzError("Risposta MusicBrainz non valida (JSON malformato)") from exc

    def search_artist(self, name: str, limit: int = 5) -> list[MBArtist]:
        """Cerca artisti per nome. Restituisce lista di risultati."""
        if not name or not name.strip():
            return []
        
        data = self._request("artist", params={
            "query": name.strip(),
            "limit": limit,
        })
        
        artists = data.get("artists", [])
        return [MBArtist.from_api(a) for a in artists]

    def get_artist(self, mbid: str, include_relations: bool = True) -> Optional[MBArtist]:
        """Recupera artista per MBID (MusicBrainz ID)."""
        if not mbid or not mbid.strip():
            return None
        
        params = {}
        if include_relations:
            params["inc"] = "url-rels"  # Include relazioni URL (Wikidata, Wikipedia, etc.)
        
        data = self._request(f"artist/{mbid.strip()}", params=params)
        artist_data = data.get("artist") or data  # API restituisce diretto o wrapped
        
        if not artist_data:
            return None
        return MBArtist.from_api(artist_data)

    def get_artist_by_name(self, name: str) -> Optional[MBArtist]:
        """Cerca artista per nome e restituisce il primo risultato con relazioni."""
        results = self.search_artist(name, limit=1)
        if not results:
            return None
        
        # Ricarica con relazioni complete
        return self.get_artist(results[0].id, include_relations=True)

    def get_biography_hint(self, artist: MBArtist | str | None) -> dict[str, Any]:
        """Restituisce indirizzi per biografia (Wikipedia, Wikidata, etc.).
        
        Utile per recuperare testo biografico da altre fonti.
        """
        if isinstance(artist, str):
            artist = self.get_artist_by_name(artist)
        if not artist:
            return {}
        
        hints = {}
        if artist.wikipedia_url:
            hints["wikipedia"] = artist.wikipedia_url
        if artist.wikidata_id:
            hints["wikidata"] = f"https://www.wikidata.org/wiki/{artist.wikidata_id}"
        if artist.discogs_id:
            hints["discogs"] = f"https://www.discogs.com/artist/{artist.discogs_id}"
        if artist.allmusic_id:
            hints["allmusic"] = f"https://www.allmusic.com/artist/{artist.allmusic_id}"
        
        return hints
