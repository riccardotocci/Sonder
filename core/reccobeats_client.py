"""Client per ReccoBeats: audio features (danceability, energy, valence, ...).

ReccoBeats (https://api.reccobeats.com) e' gratuito e SENZA autenticazione, e
sostituisce le audio features di Spotify (deprecate). L'endpoint delle features
richiede l'ID interno ReccoBeats, quindi serve un flusso a due passi:
  1. /track?ids=<spotify_id|isrc>  -> ID ReccoBeats
  2. /track/<id>/audio-features    -> features

Difensivo: ogni errore -> None, cosi' l'app resta in "modalita' demo".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

logger = logging.getLogger("sonder.reccobeats")
API_BASE = "https://api.reccobeats.com/v1"


def _to_float(value: Any, default: float = 0.0) -> float:
    """Converte in float in modo difensivo (payload esterno -> mai eccezioni)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = -1) -> int:
    """Converte in int in modo difensivo (payload esterno -> mai eccezioni)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ReccoBeatsError(RuntimeError):
    """Errore generico durante una chiamata a ReccoBeats."""


@dataclass
class AudioFeatures:
    """Audio features normalizzate per una traccia."""

    recco_id: str = ""
    isrc: str = ""
    acousticness: float = 0.0
    danceability: float = 0.0
    energy: float = 0.0
    instrumentalness: float = 0.0
    liveness: float = 0.0
    loudness: float = 0.0
    speechiness: float = 0.0
    tempo: float = 0.0
    valence: float = 0.0
    key: int = -1
    mode: int = -1
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.raw

    @property
    def mood(self) -> str:
        """Etichetta di mood derivata da valence/energy (per lo Storyteller)."""
        v, e = self.valence, self.energy
        if v >= 0.5 and e >= 0.5:
            return "euforico"
        if v >= 0.5 and e < 0.5:
            return "sereno"
        if v < 0.5 and e >= 0.5:
            return "teso"
        return "malinconico"


class ReccoBeatsClient:
    """Wrapper minimale e robusto sulle API ReccoBeats."""

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    @property
    def ready(self) -> bool:
        # Nessuna API key richiesta: sempre disponibile.
        return True

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{API_BASE}/{path.lstrip('/')}"
        try:
            r = self.session.get(
                url, params=params, headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ReccoBeatsError(f"Errore di rete ReccoBeats: {exc}") from exc
        if not r.ok:
            raise ReccoBeatsError(f"ReccoBeats status {r.status_code}: {r.text[:160]}")
        try:
            return r.json() or {}
        except ValueError as exc:
            raise ReccoBeatsError("Risposta ReccoBeats non valida (JSON malformato).") from exc

    def resolve_id(self, spotify_or_isrc: str) -> Optional[str]:
        """Risolve un ID Spotify o ISRC nell'ID interno ReccoBeats."""
        ident = (spotify_or_isrc or "").strip()
        if not ident:
            return None
        payload = self._get("track", ids=ident)
        content = payload.get("content") or []
        if isinstance(content, list) and content and isinstance(content[0], dict):
            return str(content[0].get("id") or "") or None
        return None

    def audio_features_by_recco_id(self, recco_id: str) -> Optional[AudioFeatures]:
        recco_id = (recco_id or "").strip()
        if not recco_id:
            return None
        data = self._get(f"track/{recco_id}/audio-features")
        if not isinstance(data, dict) or not data:
            return None
        return AudioFeatures(
            recco_id=str(data.get("id") or recco_id),
            isrc=str(data.get("isrc") or ""),
            acousticness=_to_float(data.get("acousticness")),
            danceability=_to_float(data.get("danceability")),
            energy=_to_float(data.get("energy")),
            instrumentalness=_to_float(data.get("instrumentalness")),
            liveness=_to_float(data.get("liveness")),
            loudness=_to_float(data.get("loudness")),
            speechiness=_to_float(data.get("speechiness")),
            tempo=_to_float(data.get("tempo")),
            valence=_to_float(data.get("valence")),
            key=_to_int(data.get("key")),
            mode=_to_int(data.get("mode")),
            raw=data,
        )

    def audio_features(
        self, spotify_id: str = "", isrc: str = ""
    ) -> Optional[AudioFeatures]:
        """Orchestratore: risolve l'id (preferendo l'ISRC) e ne ricava le features."""
        ident = (isrc or spotify_id or "").strip()
        if not ident:
            return None
        try:
            recco_id = self.resolve_id(ident)
            if not recco_id:
                return None
            return self.audio_features_by_recco_id(recco_id)
        except ReccoBeatsError as exc:
            logger.warning("ReccoBeats audio_features failed (%s): %s", ident, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - dati esterni: degrada in silenzio
            logger.warning("ReccoBeats audio_features unexpected error (%s): %s", ident, exc)
            return None
