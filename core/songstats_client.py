"""Client per le API Songstats (statistiche di streaming/popolarita' reali).

Songstats espone metriche aggregate cross-DSP (Spotify, YouTube, TikTok, ...):
conteggi di stream, follower, playlist, ecc. A differenza della "popularity"
0-100 di Spotify, qui i numeri sono conteggi reali, quindi utili sia per i
grafici a fondo pagina (task 8) sia come soglia di notorieta' (task 4).

Documentazione: https://docs.songstats.com/ (header di autenticazione: ``apikey``).

Il client e' difensivo: qualsiasi errore di rete/parsing si traduce in un valore
vuoto (``None``/``[]``), cosi' l'app resta utilizzabile in "modalita' demo" quando
la chiave manca o l'endpoint cambia forma.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from .config import settings

logger = logging.getLogger("sonder.songstats")

API_BASE = "https://api.songstats.com/enterprise/v1"

# Metriche "interessanti" e il loro ordine di visualizzazione nei grafici.
# La chiave e' il nome del campo Songstats, il valore l'etichetta leggibile.
METRIC_LABELS: dict[str, str] = {
    "streams_total": "Streams",
    "streams_current": "Streams",
    "spotify_streams_total": "Spotify streams",
    "popularity_current": "Spotify popularity",
    "followers_total": "Followers",
    "playlists_total": "Playlists",
    "playlist_reach_total": "Playlist reach",
    "views_total": "Video views",
    "shazams_total": "Shazams",
    "favorites_total": "Favorites",
}

# Campi che rappresentano un conteggio di riproduzioni reali (per la soglia task 4).
STREAM_FIELDS: tuple[str, ...] = (
    "streams_total",
    "streams_current",
    "spotify_streams_total",
)


class SongstatsError(RuntimeError):
    """Errore generico durante una chiamata a Songstats."""


@dataclass
class SongstatsStats:
    """Statistiche normalizzate per una traccia o un artista."""

    songstats_id: str = ""
    name: str = ""
    subtitle: str = ""  # artista (per le tracce) o genere principale (per gli artisti)
    avatar: str = ""
    sources: dict[str, dict[str, float]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.sources

    @property
    def total_streams(self) -> int:
        """Miglior stima del numero di stream reali, cercando tra tutte le fonti."""
        best = 0
        for metrics in self.sources.values():
            for field_name in STREAM_FIELDS:
                value = metrics.get(field_name)
                if isinstance(value, (int, float)) and value > best:
                    best = int(value)
        return best

    def headline_metrics(self) -> list[tuple[str, float]]:
        """Lista ordinata (etichetta, valore) delle metriche principali per i grafici."""
        seen: dict[str, float] = {}
        for source, metrics in self.sources.items():
            for field_name, label in METRIC_LABELS.items():
                value = metrics.get(field_name)
                if isinstance(value, (int, float)) and value > 0:
                    key = f"{label}" if len(self.sources) == 1 else f"{label} · {source}"
                    seen[key] = float(value)
        return sorted(seen.items(), key=lambda kv: kv[1], reverse=True)


class SongstatsClient:
    """Wrapper minimale e robusto sulle API Songstats."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self.api_key = api_key if api_key is not None else settings.songstats_api_key
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def _request(self, endpoint: str, **params: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SongstatsError("SONGSTATS_API_KEY non configurata.")
        url = f"{API_BASE}/{endpoint.lstrip('/')}"
        headers = {"apikey": self.api_key, "Accept": "application/json"}
        try:
            response = self.session.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise SongstatsError(f"Errore di rete Songstats: {exc}") from exc
        if response.status_code == 401:
            raise SongstatsError("Songstats: chiave API non valida o non autorizzata.")
        if not response.ok:
            raise SongstatsError(
                f"Songstats status {response.status_code}: {response.text[:160]}"
            )
        try:
            return response.json() or {}
        except ValueError as exc:
            raise SongstatsError("Risposta Songstats non valida (JSON malformato).") from exc

    # ------------------------------------------------------------------ #
    # Parsing helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _first_result(payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("results", "tracks", "artists", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list) and value:
                return value[0] if isinstance(value[0], dict) else {}
            if isinstance(value, dict) and value:
                return value
        return {}

    @staticmethod
    def _extract_sources(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
        """Estrae la mappa fonte -> {metrica: valore} dalla risposta /stats."""
        sources: dict[str, dict[str, float]] = {}
        stats = payload.get("stats")
        if isinstance(stats, dict):
            stats = stats.get("stats", stats) if "stats" in stats else stats
        if isinstance(stats, list):
            for entry in stats:
                if not isinstance(entry, dict):
                    continue
                source = str(entry.get("source") or entry.get("platform") or "songstats")
                data = entry.get("data") if isinstance(entry.get("data"), dict) else entry
                metrics = {
                    k: float(v)
                    for k, v in data.items()
                    if isinstance(v, (int, float))
                }
                if metrics:
                    sources[source] = metrics
        return sources

    # ------------------------------------------------------------------ #
    # High-level
    # ------------------------------------------------------------------ #
    def track_stats(self, title: str, artist: str = "") -> Optional[SongstatsStats]:
        """Cerca la traccia per titolo (+ artista) e ne restituisce le statistiche."""
        query = " ".join(p for p in (title, artist) if p).strip()
        if not query:
            return None
        try:
            search = self._request("tracks/search", q=query, limit=1)
        except SongstatsError as exc:
            logger.warning("Songstats track search failed: %s", exc)
            raise
        result = self._first_result(search)
        track_id = str(
            result.get("songstats_track_id")
            or result.get("songstats_id")
            or result.get("id")
            or ""
        )
        if not track_id:
            return None
        artists = result.get("artists") or []
        artist_name = ""
        if isinstance(artists, list) and artists:
            artist_name = ", ".join(
                str(a.get("name", a)) if isinstance(a, dict) else str(a) for a in artists
            )
        try:
            stats_payload = self._request("tracks/stats", songstats_track_id=track_id)
        except SongstatsError as exc:
            logger.warning("Songstats track stats failed: %s", exc)
            raise
        return SongstatsStats(
            songstats_id=track_id,
            name=str(result.get("title") or title),
            subtitle=artist_name or artist,
            avatar=str(result.get("avatar") or result.get("image_url") or ""),
            sources=self._extract_sources(stats_payload),
            raw=stats_payload,
        )

    def artist_stats(self, name: str) -> Optional[SongstatsStats]:
        """Cerca l'artista per nome e ne restituisce le statistiche aggregate."""
        if not name or not name.strip():
            return None
        try:
            search = self._request("artists/search", q=name.strip(), limit=1)
        except SongstatsError as exc:
            logger.warning("Songstats artist search failed: %s", exc)
            raise
        result = self._first_result(search)
        artist_id = str(
            result.get("songstats_artist_id")
            or result.get("songstats_id")
            or result.get("id")
            or ""
        )
        if not artist_id:
            return None
        try:
            stats_payload = self._request("artists/stats", songstats_artist_id=artist_id)
        except SongstatsError as exc:
            logger.warning("Songstats artist stats failed: %s", exc)
            raise
        genres = result.get("genres") or []
        subtitle = ", ".join(str(g) for g in genres[:3]) if isinstance(genres, list) else ""
        return SongstatsStats(
            songstats_id=artist_id,
            name=str(result.get("name") or name),
            subtitle=subtitle,
            avatar=str(result.get("avatar") or result.get("image_url") or ""),
            sources=self._extract_sources(stats_payload),
            raw=stats_payload,
        )
