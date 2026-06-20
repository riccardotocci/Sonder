"""City-level geocoding via Open-Meteo (free, no API key) with caching.

TheAudioDB only gives a country and MusicBrainz adds the artist's city (via the
``begin-area``). To place a pin at city precision we still need decimal
coordinates for that city: Open-Meteo's geocoding API is free, requires no key
and returns lat/lng for a place name. Results are cached in-process so repeated
cities (and repeated builds) don't re-hit the network.

``geocode_city`` returns ``None`` when the place is unknown, so callers can fall
back to the static country centroid table in ``geo_coords``.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import requests

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_TIMEOUT = 8


@lru_cache(maxsize=512)
def geocode_city(name: str, country_code: str = "") -> Optional[tuple[float, float]]:
    """Risolve il nome di una città in ``(lat, lng)`` via Open-Meteo.

    Quando ``country_code`` (ISO alpha-2) è presente viene usato per disambiguare
    gli omonimi (es. Paris FR vs Paris US). Restituisce ``None`` se non trovata.
    """
    place = (name or "").strip()
    if not place:
        return None
    try:
        resp = requests.get(
            _GEOCODE_URL,
            params={"name": place, "count": 5, "language": "en", "format": "json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
    except (requests.RequestException, ValueError):
        return None
    if not results:
        return None

    cc = (country_code or "").strip().upper()
    if cc:
        for r in results:
            if str(r.get("country_code", "")).upper() == cc:
                coords = _coords(r)
                if coords:
                    return coords
    # Nessun match sul paese: usa il primo risultato (il più rilevante).
    return _coords(results[0])


def _coords(result: dict) -> Optional[tuple[float, float]]:
    try:
        return float(result["latitude"]), float(result["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
