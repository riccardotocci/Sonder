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
# La chiave e' il nome del campo Songstats (vedi response /tracks/stats -> stats[].data,
# documentato nell'SDK ufficiale https://github.com/Songstats/songstats-node-sdk),
# il valore l'etichetta leggibile. L'ordine qui definisce la priorita' nei grafici.
METRIC_LABELS: dict[str, str] = {
    "streams_total": "Streams",
    "streams_current": "Streams",
    "spotify_streams_total": "Spotify streams",
    "popularity": "Spotify popularity",
    "popularity_current": "Spotify popularity",
    "playlists_total": "Playlists",
    "playlists_total_reach": "Playlist reach",
    "playlist_reach_total": "Playlist reach",
    "playlists_editorial_total": "Editorial playlists",
    "playlists_editorial_total_reach": "Editorial reach",
    "playlists_algotorial_total": "Algorithmic playlists",
    "charts_total": "Chart entries",
    "saves_total": "Saves",
    "favorites_total": "Favorites",
    "followers_total": "Followers",
    "views_total": "Video views",
    "likes_total": "Likes",
    "shazams_total": "Shazams",
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
    def _track_info(payload: dict[str, Any]) -> dict[str, Any]:
        """Estrae il blocco di metadati della traccia dalla risposta /tracks/stats.

        La risposta documentata (SDK ufficiale) incapsula i metadati sotto la chiave
        ``track`` (con campi ``name``, ``artists``, ``cover_url``, ``songstats_track_id``).
        Gli altri nomi sono mantenuti come fallback difensivi per varianti dell'API.
        """
        for key in ("track", "track_info", "info", "data"):
            value = payload.get(key)
            if isinstance(value, dict) and value:
                return value
        return {}

    @staticmethod
    def _artists_text(info: dict[str, Any]) -> str:
        artists = info.get("artists") or []
        if isinstance(artists, list) and artists:
            return ", ".join(
                str(a.get("name", a)) if isinstance(a, dict) else str(a) for a in artists
            )
        return str(info.get("artist_name") or "")

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
    def track_stats_by_isrc(
        self, isrc: str, name: str = "", artist: str = ""
    ) -> Optional[SongstatsStats]:
        """Statistiche di una traccia interrogando Songstats per ISRC.

        Percorso canonico (vedi docs): ``GET /tracks/stats?isrc=...``. L'ISRC e' un
        identificatore univoco e affidabile (ricavato da Spotify), quindi evita la
        fase di ricerca testuale e le sue ambiguita'. ``name``/``artist`` servono solo
        come etichette di fallback se il payload non le riporta.
        """
        isrc = (isrc or "").strip().upper()
        if not isrc:
            return None
        try:
            payload = self._request("tracks/stats", isrc=isrc)
        except SongstatsError as exc:
            logger.warning("Songstats stats by ISRC failed (%s): %s", isrc, exc)
            raise
        info = self._track_info(payload)
        sources = self._extract_sources(payload)
        if not sources:
            return None
        return SongstatsStats(
            songstats_id=str(
                info.get("songstats_track_id") or info.get("id") or ""
            ),
            name=str(info.get("name") or info.get("title") or name),
            subtitle=self._artists_text(info) or artist,
            avatar=str(
                info.get("cover_url")
                or info.get("avatar")
                or info.get("image_url")
                or ""
            ),
            sources=sources,
            raw=payload,
        )

