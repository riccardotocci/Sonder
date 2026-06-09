"""Client per le API Spotify (via spotipy).

- Ricerca tracce: usa il flusso Client Credentials (nessun login utente).
- Creazione playlist: richiede il flusso OAuth (login dell'utente).

Documentazione: https://spotipy.readthedocs.io/
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

from .config import settings

# Permessi necessari per creare/aggiornare playlist sull'account dell'utente.
OAUTH_SCOPE = "playlist-modify-public playlist-modify-private"


class SpotifyError(RuntimeError):
    """Errore generico durante una chiamata a Spotify."""


@dataclass
class SpotifyTrack:
    uri: str
    name: str
    artist: str
    url: str = ""
    preview_url: str = ""
    album_image: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> "SpotifyTrack":
        artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
        images = item.get("album", {}).get("images", [])
        return cls(
            uri=item.get("uri", ""),
            name=item.get("name", ""),
            artist=artists,
            url=item.get("external_urls", {}).get("spotify", ""),
            preview_url=item.get("preview_url") or "",
            album_image=images[0]["url"] if images else "",
            raw=item,
        )


@dataclass
class SpotifyPlaylist:
    id: str
    name: str
    url: str
    track_count: int = 0

    @property
    def embed_url(self) -> str:
        return f"https://open.spotify.com/embed/playlist/{self.id}"


class SpotifyClient:
    """Wrapper su spotipy per ricerca e curatela automatica delle playlist."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        cache_path: str = ".cache-spotify",
    ) -> None:
        self.client_id = client_id if client_id is not None else settings.spotify_client_id
        self.client_secret = (
            client_secret if client_secret is not None else settings.spotify_client_secret
        )
        self.redirect_uri = redirect_uri or settings.spotify_redirect_uri
        self.cache_path = cache_path
        self._public: Optional[spotipy.Spotify] = None
        self._user: Optional[spotipy.Spotify] = None

    # ------------------------------------------------------------------ #
    # Client factory
    # ------------------------------------------------------------------ #
    def _require_credentials(self) -> None:
        if not (self.client_id and self.client_secret):
            raise SpotifyError(
                "Credenziali Spotify mancanti. Imposta SPOTIFY_CLIENT_ID e "
                "SPOTIFY_CLIENT_SECRET nel file .env"
            )

    @property
    def public_client(self) -> spotipy.Spotify:
        """Client per sole letture (ricerca)."""
        self._require_credentials()
        if self._public is None:
            auth = SpotifyClientCredentials(
                client_id=self.client_id, client_secret=self.client_secret
            )
            self._public = spotipy.Spotify(auth_manager=auth)
        return self._public

    @property
    def user_client(self) -> spotipy.Spotify:
        """Client autenticato come utente (necessario per creare playlist)."""
        self._require_credentials()
        if self._user is None:
            auth = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=OAUTH_SCOPE,
                cache_path=self.cache_path,
                open_browser=True,
            )
            self._user = spotipy.Spotify(auth_manager=auth)
        return self._user

    # ------------------------------------------------------------------ #
    # Ricerca
    # ------------------------------------------------------------------ #
    def search_track(self, title: str, artist: Optional[str] = None) -> Optional[SpotifyTrack]:
        """Cerca la traccia piu' pertinente per titolo (+ artista)."""
        query = f'track:{title}'
        if artist:
            query += f' artist:{artist}'
        try:
            results = self.public_client.search(q=query, type="track", limit=1)
        except SpotifyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpotifyError(f"Errore ricerca Spotify: {exc}") from exc

        items = results.get("tracks", {}).get("items", [])
        return SpotifyTrack.from_api(items[0]) if items else None

    def resolve_tracks(self, tracks: list[dict[str, str]]) -> list[SpotifyTrack]:
        """Converte una lista di {title, artist} in tracce Spotify trovate."""
        resolved: list[SpotifyTrack] = []
        for t in tracks:
            found = self.search_track(t.get("title", ""), t.get("artist"))
            if found and found.uri:
                resolved.append(found)
        return resolved

    # ------------------------------------------------------------------ #
    # Curatela
    # ------------------------------------------------------------------ #
    def create_thematic_playlist(
        self,
        name: str,
        description: str,
        tracks: list[dict[str, str]],
        public: bool = False,
    ) -> SpotifyPlaylist:
        """Crea una playlist sull'account utente e vi aggiunge i brani trovati."""
        sp = self.user_client
        try:
            user_id = sp.current_user()["id"]
            playlist = sp.user_playlist_create(
                user=user_id,
                name=name,
                public=public,
                description=(description or "")[:300],
            )
            uris = [t.uri for t in self.resolve_tracks(tracks) if t.uri]
            if uris:
                # Spotify accetta max 100 URI per chiamata.
                for i in range(0, len(uris), 100):
                    sp.playlist_add_items(playlist["id"], uris[i : i + 100])
        except SpotifyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpotifyError(f"Errore creazione playlist Spotify: {exc}") from exc

        return SpotifyPlaylist(
            id=playlist["id"],
            name=playlist.get("name", name),
            url=playlist.get("external_urls", {}).get("spotify", ""),
            track_count=len(uris),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def embed_url(playlist_ref: str) -> str:
        """Ricava l'URL di embed da un id, URI o URL di playlist Spotify."""
        match = re.search(r"playlist[:/]([A-Za-z0-9]+)", playlist_ref)
        playlist_id = match.group(1) if match else playlist_ref
        return f"https://open.spotify.com/embed/playlist/{playlist_id}"
