---
name: Sonder artist origin (country-level map)
description: How Sonder resolves artist ORIGIN for the map and why it is country/state-level, not city.
---

# Sonder artist origin geocoding

The Studio map works at **country/state level** (it colors the country region), not
city level. Earlier the map placed city pins; that was replaced.

- **Origin label** = readable country **name** (`origin`), always normalized through
  `geo_coords.country_name()` so a bare ISO2 ("GB") never leaks to the UI.
- **`origin_code`** = ISO2, the join key the frontend uses to color country polygons.
  It is backfilled in the final normalization loop via `geo_coords.to_iso2(origin)`
  when only a country name is present — **without it the polygon won't color** even
  though the label shows.
- **Coordinates** = country **centroid** from `geo_coords.resolve_coordinates`
  (ISO2 preferred). No more per-city geocoding.
- **Sources (priority)**: AudioDB (`strCountry`/`strCountryCode`) first; MusicBrainz
  country next (`_mb_artist_origin` still returns a city, but it is ignored now);
  **ISRC prefix last** — `pipeline.isrc_country(isrc)` extracts the first 2 chars of a
  structurally-valid ISRC (12 alnum: 2 alpha country + 3 alnum registrant + 7 digits).
  This is the ISRC *registrant* country, NOT guaranteed = release country, so it's only
  a fallback and fires only when BOTH `origin`/`origin_code` are empty. Apply it through
  `to_iso2()` so non-country ISRC prefixes (`QM`/`ZZ`/`TC`) — which aren't mappable —
  are discarded instead of painting a bogus polygon. `t["isrc"]` comes from the Spotify
  search done during enrichment (no extra API call).

## Map coloring (frontend `StudioSections.jsx::GeographyMap`)
- One color per **distinct country** (`COUNTRY_PALETTE`, keyed by `origin_code`), NOT
  per track index. Map polygons, the centroid markers, and the legend dots all share
  that per-country color — songs from the same country look identical.
- Country polygons come from `frontend/public/world-countries.geojson` (slim Natural
  Earth 110m, ~170KB, lazy-fetched). Each feature has `properties.iso` (ISO_A2_EH,
  France/Norway fixed). Match polygon `iso` to `origin_code`.
- `GeoJSON` is given a `key` derived from the country set so it remounts/re-styles
  when the playlist's countries change (react-leaflet caches layers otherwise).

## Dead since the city→country switch
- `backend/geocode.py::geocode_city` (Open-Meteo) is no longer called.
- `origin_city` field is no longer set or used.

**Why country-level:** the user asked to color the *state of origin* on the map and
group legend songs by country color, replacing the per-track city search.
