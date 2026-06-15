"""Client per le API Musixmatch.

Gestisce ricerca tracce, recupero testi e metadati.
Documentazione: https://developer.musixmatch.com/documentation

Nota: nel piano gratuito i testi sono restituiti parzialmente (~30%) e includono
un disclaimer di copyright. Il client espone comunque l'intero corpo restituito.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from .config import settings

API_BASE = "https://api.musixmatch.com/ws/1.1"


class MusixmatchError(RuntimeError):
    """Errore generico durante una chiamata a Musixmatch."""


@dataclass
class Track:
    """Rappresentazione semplificata di una traccia Musixmatch."""

    track_id: int
    track_name: str
    artist_name: str
    album_name: str = ""
    has_lyrics: bool = False
    has_richsync: bool = False
    explicit: bool = False
    genres: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Track":
        genres: list[str] = []
        try:
            music_genres = data.get("primary_genres", {}).get("music_genre_list", [])
            genres = [
                g["music_genre"]["music_genre_name"]
                for g in music_genres
                if g.get("music_genre")
            ]
        except (AttributeError, KeyError, TypeError):
            genres = []

        return cls(
            track_id=data.get("track_id", 0),
            track_name=data.get("track_name", ""),
            artist_name=data.get("artist_name", ""),
            album_name=data.get("album_name", ""),
            has_lyrics=bool(data.get("has_lyrics", 0)),
            has_richsync=bool(data.get("has_richsync", 0)),
            explicit=bool(data.get("explicit", 0)),
            genres=genres,
            raw=data,
        )

    @property
    def label(self) -> str:
        return f"{self.artist_name} — {self.track_name}"


@dataclass
class Lyrics:
    """Testo restituito da Musixmatch piu' eventuale disclaimer/copyright."""

    body: str
    language: str = ""
    copyright: str = ""
    is_restricted: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.body.strip()


@dataclass
class RichSync:
    body: list[dict[str, Any]] = field(default_factory=list)
    raw_body: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.body

    @property
    def text(self) -> str:
        lines: list[str] = []
        for item in self.body:
            line = item.get("l") or item.get("line") or item.get("text") or ""
            if isinstance(line, list):
                pieces = []
                for token in line:
                    if isinstance(token, dict):
                        pieces.append(str(token.get("c") or token.get("text") or ""))
                    else:
                        pieces.append(str(token))
                line = "".join(pieces).strip() or " ".join(pieces).strip()
            if isinstance(line, str) and line.strip():
                lines.append(line.strip())
        return "\n".join(lines)


class MusixmatchClient:
    """Wrapper minimale e robusto sulle API REST di Musixmatch."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self.api_key = api_key if api_key is not None else settings.musixmatch_api_key
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    # Low-level
    # ------------------------------------------------------------------ #
    def _request(self, endpoint: str, **params: Any) -> dict[str, Any]:
        if not self.api_key:
            raise MusixmatchError(
                "Chiave API Musixmatch mancante. Imposta MUSIXMATCH_API_KEY o MXM_KEY nel file .env"
            )

        params["apikey"] = self.api_key
        url = f"{API_BASE}/{endpoint}"

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MusixmatchError(f"Errore di rete Musixmatch: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise MusixmatchError("Risposta Musixmatch non valida (JSON malformato)") from exc

        message = payload.get("message", {})
        status_code = message.get("header", {}).get("status_code")

        if status_code != 200:
            hint = {
                401: "chiave API non valida o non autorizzata",
                402: "limite di utilizzo del piano superato",
                403: "accesso negato (controlla i permessi del piano)",
                404: "risorsa non trovata",
            }.get(status_code, "errore non specificato")
            raise MusixmatchError(f"Musixmatch status {status_code}: {hint}")

        return message.get("body", {}) or {}

    # ------------------------------------------------------------------ #
    # High-level
    # ------------------------------------------------------------------ #
    def search_tracks(
        self,
        query: Optional[str] = None,
        *,
        track: Optional[str] = None,
        artist: Optional[str] = None,
        lyrics: Optional[str] = None,
        has_lyrics: bool = False,
        limit: int = 10,
    ) -> list[Track]:
        """Cerca tracce per testo libero e/o titolo/artista."""
        params: dict[str, Any] = {
            "page_size": max(1, min(limit, 100)),
            "page": 1,
            "s_track_rating": "desc",
        }
        if query:
            params["q"] = query
        if track:
            params["q_track"] = track
        if artist:
            params["q_artist"] = artist
        if lyrics:
            params["q_lyrics"] = lyrics
        if has_lyrics:
            params["f_has_lyrics"] = 1

        body = self._request("track.search", **params)
        track_list = body.get("track_list", []) or []
        return [Track.from_api(item["track"]) for item in track_list if item.get("track")]

    def get_lyrics(self, track_id: int) -> Lyrics:
        """Recupera il testo a partire dall'ID traccia."""
        body = self._request("track.lyrics.get", track_id=track_id)
        return self._parse_lyrics(body)

    def get_richsync(self, track_id: int) -> RichSync:
        body = self._request("track.richsync.get", track_id=track_id)
        return self._parse_richsync(body)

    def match_lyrics(self, track: str, artist: str) -> Lyrics:
        """Recupera il testo combinando titolo + artista (fuzzy matcher)."""
        body = self._request("matcher.lyrics.get", q_track=track, q_artist=artist)
        return self._parse_lyrics(body)

    def get_track(self, track_id: int) -> Optional[Track]:
        """Recupera i metadati completi di una traccia."""
        body = self._request("track.get", track_id=track_id)
        track_data = body.get("track")
        return Track.from_api(track_data) if track_data else None

    def find_lyrics(self, track: str, artist: str) -> tuple[Optional[Track], Lyrics]:
        """Helper: prova il matcher, poi ripiega sulla ricerca + lyrics per ID."""
        matches = self.search_tracks(track=track, artist=artist, limit=1)
        if matches:
            best = matches[0]
            lyrics = self.get_lyrics(best.track_id) if best.has_lyrics else Lyrics(body="")
            return best, lyrics

        try:
            lyrics = self.match_lyrics(track, artist)
            if not lyrics.is_empty:
                return None, lyrics
        except MusixmatchError:
            pass

        matches = self.search_tracks(track=track, artist=artist, limit=1)
        if not matches:
            return None, Lyrics(body="")
        best = matches[0]
        lyrics = self.get_lyrics(best.track_id) if best.has_lyrics else Lyrics(body="")
        return best, lyrics

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_richsync(body: dict[str, Any]) -> RichSync:
        richsync = body.get("richsync", {}) or {}
        raw_body = (richsync.get("richsync_body") or "").strip()
        parsed: list[dict[str, Any]] = []
        if raw_body:
            try:
                data = json.loads(raw_body)
                if isinstance(data, list):
                    parsed = [item for item in data if isinstance(item, dict)]
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = []
        return RichSync(body=parsed, raw_body=raw_body)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_lyrics(body: dict[str, Any]) -> Lyrics:
        lyrics = body.get("lyrics", {}) or {}
        return Lyrics(
            body=(lyrics.get("lyrics_body") or "").strip(),
            language=lyrics.get("lyrics_language", ""),
            copyright=(lyrics.get("lyrics_copyright") or "").strip(),
            is_restricted=bool(lyrics.get("restricted", 0)),
        )
