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
    def _require_key(self) -> str:
        if not self.api_key:
            raise MusixmatchError(
                "Chiave API Musixmatch mancante. Imposta MUSIXMATCH_API_KEY o MXM_KEY nel file .env"
            )
        return self.api_key

    def _request(self, endpoint: str, **params: Any) -> dict[str, Any]:
        params = dict(params)
        params["apikey"] = self._require_key()
        url = f"{API_BASE}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MusixmatchError(f"Errore di rete Musixmatch: {exc}") from exc
        return self._unwrap(response)

    def _post(self, endpoint: str, data: dict[str, Any], **params: Any) -> dict[str, Any]:
        """POST con corpo JSON (es. ``track.lyrics.analysis.search``)."""
        params = dict(params)
        params["apikey"] = self._require_key()
        url = f"{API_BASE}/{endpoint}"
        try:
            response = self.session.post(
                url,
                params=params,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise MusixmatchError(f"Errore di rete Musixmatch: {exc}") from exc
        return self._unwrap(response)

    @staticmethod
    def _unwrap(response: requests.Response) -> dict[str, Any]:
        try:
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

    def search_lyrics_analysis(
        self, meaning: str, *, limit: int = 20
    ) -> list[tuple["Track", dict[str, Any]]]:
        """Ricerca semantica per "significato" dei testi.

        Usa l'endpoint POST ``track.lyrics.analysis.search`` con corpo
        ``{"data": {"meaning": "..."}}``. Ogni traccia restituita porta con se'
        l'analisi dei testi (mood, temi, rating, ...) e i generi primari, quindi
        non serve un secondo round-trip per arricchirla. Ritorna una lista di
        coppie ``(Track, analysis)``; lista vuota se non ci sono risultati.
        """
        meaning = (meaning or "").strip()
        if not meaning:
            return []
        body = self._post(
            "track.lyrics.analysis.search", {"data": {"meaning": meaning}}
        )
        track_list = body.get("track_list", []) or []
        out: list[tuple[Track, dict[str, Any]]] = []
        for item in track_list:
            track_data = item.get("track") if isinstance(item, dict) else None
            if not track_data:
                continue
            analysis = item.get("analysis") if isinstance(item, dict) else {}
            out.append((Track.from_api(track_data), analysis or {}))
            if len(out) >= max(1, limit):
                break
        return out

    def get_lyrics_analysis(self, track_id: int) -> dict[str, Any]:
        """Analisi testuale di una traccia (``track.lyrics.analysis.get``).

        Richiede il ``track_id`` reale (NON il commontrack_id). Ritorna il dict
        ``analysis`` (mood, temi, rating, ...) oppure ``{}`` se l'analisi non e'
        disponibile o l'endpoint non e' accessibile per il piano corrente
        (degrada con grazia: i chiamanti trattano il vuoto come "nessun mood").
        """
        if not track_id:
            return {}
        try:
            body = self._request("track.lyrics.analysis.get", track_id=track_id)
        except MusixmatchError:
            return {}
        analysis = body.get("analysis")
        return analysis if isinstance(analysis, dict) else {}

    @staticmethod
    def analysis_moods(analysis: dict[str, Any]) -> list[str]:
        """Estrae i mood testuali (``moods.main_moods``) da un dict di analisi."""
        moods = ((analysis or {}).get("moods") or {}).get("main_moods") or []
        if not isinstance(moods, list):
            return []
        return [str(m).strip() for m in moods if str(m).strip()]

    @staticmethod
    def analysis_themes(analysis: dict[str, Any]) -> list[str]:
        """Estrae i temi (``themes.main_themes[].theme``) da un dict di analisi."""
        themes = ((analysis or {}).get("themes") or {}).get("main_themes") or []
        if not isinstance(themes, list):
            return []
        out: list[str] = []
        for item in themes:
            if isinstance(item, dict):
                name = str(item.get("theme") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                out.append(name)
        return out

    def get_lyrics(self, track_id: int) -> Lyrics:
        """Recupera il testo a partire dall'ID traccia."""
        body = self._request("track.lyrics.get", track_id=track_id)
        return self._parse_lyrics(body)

    def get_richsync(self, track_id: int) -> RichSync:
        body = self._request("track.richsync.get", track_id=track_id)
        return self._parse_richsync(body)

    def get_lyrics_translation(self, track_id: int, language: str) -> Lyrics:
        """Recupera la traduzione del testo nella lingua richiesta (codice ISO 2 lettere).

        Usa l'endpoint ``track.lyrics.translation.get``. Se la traduzione non e'
        disponibile o l'endpoint non e' accessibile per il piano corrente, viene
        sollevato ``MusixmatchError`` (gestito dai chiamanti con un fallback vuoto).
        """
        language = (language or "").strip().lower()
        if not language:
            return Lyrics(body="")
        body = self._request(
            "track.lyrics.translation.get",
            track_id=track_id,
            selected_language=language,
        )
        return self._parse_translation(body, language)

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

    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_translation(body: dict[str, Any], language: str) -> Lyrics:
        """Estrae il testo tradotto da una risposta ``track.lyrics.translation.get``.

        Il payload puo' presentarsi in piu' forme a seconda del piano/endpoint:
          1. ``translation_list`` con item ``{"translation": {"snippet", "description"}}``
             dove ``description`` contiene la riga tradotta.
          2. ``lyrics.lyrics_translated.lyrics_body``: il testo gia' tradotto riga-per-riga
             (forma canonica restituita dall'endpoint, vedi ``selected_language``).
          3. ``lyrics.lyrics_body`` quando l'originale e' GIA' nella lingua richiesta.
        Si gestiscono tutte in modo difensivo.
        """
        translation_list = body.get("translation_list")
        if isinstance(translation_list, list) and translation_list:
            lines: list[str] = []
            for item in translation_list:
                if not isinstance(item, dict):
                    continue
                translation = item.get("translation") or {}
                line = (
                    translation.get("description")
                    or translation.get("translation")
                    or ""
                )
                if isinstance(line, str) and line.strip():
                    lines.append(line.strip())
            return Lyrics(body="\n".join(lines), language=language)

        lyrics = body.get("lyrics") or {}
        if isinstance(lyrics, dict):
            # 2) Forma canonica: la traduzione e' annidata in ``lyrics_translated``.
            translated = lyrics.get("lyrics_translated")
            if isinstance(translated, dict) and (translated.get("lyrics_body") or "").strip():
                return Lyrics(
                    body=(translated.get("lyrics_body") or "").strip(),
                    language=translated.get("selected_language", language),
                    copyright=(lyrics.get("lyrics_copyright") or "").strip(),
                    is_restricted=bool(lyrics.get("restricted", 0)),
                )
            # 3) Nessuna traduzione: usa l'originale SOLO se gia' nella lingua richiesta
            #    (es. traduzione IT di un brano gia' in italiano), altrimenti vuoto cosi'
            #    da NON spacciare il testo originale per una traduzione.
            original_lang = str(lyrics.get("lyrics_language") or "").strip().lower()
            target_lang = str(language or "").strip().lower()
            if (lyrics.get("lyrics_body") or "").strip() and original_lang and original_lang == target_lang:
                return Lyrics(
                    body=(lyrics.get("lyrics_body") or "").strip(),
                    language=original_lang or language,
                    copyright=(lyrics.get("lyrics_copyright") or "").strip(),
                    is_restricted=bool(lyrics.get("restricted", 0)),
                )
        return Lyrics(body="", language=language)
