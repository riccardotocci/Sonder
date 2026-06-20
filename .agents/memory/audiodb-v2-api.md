---
name: TheAudioDB v2 (Premium) API
description: How Sonder's AudioDB client talks to the v2 Premium API and what data it exposes
---

Sonder's `core/audiodb_client.py` targets the v2 **Premium** API.

- Base: `https://www.theaudiodb.com/api/v2/json`. Auth is the `X-API-KEY` **header**
  (the key is NOT in the URL). The free test key `123` is rejected (400) — v2 is
  Premium-only, so `config.audiodb_ready` is False when the key is empty or `123`.
- Endpoints are path-based: `/search/{artist|album|track}/{term}` and
  `/lookup/{artist|album|track}/{id}` plus MBID lookups `/lookup/{kind}_mb/{mbid}`.
- **Combined search forms return 0** (e.g. `/search/track/{artist}/{title}`): search by a
  single term (title or album) and filter rows by `strArtist`. Search by artist name only.
- Search responses are **lean** (wrapper key `search`) — NO multilingual text, mood, theme,
  or lyrics. Rich data lives ONLY in **lookup** responses (wrapper key `lookup`), so the
  client does search→take id→lookup, with a per-instance cache to dedupe calls.
- Text fields: EN is the **base** field (`strBiography`, `strDescription`); other languages
  use a suffix (`strBiographyIT`, `strDescriptionFR`, …). Missing-language → fall back to the
  base EN field. v2 lacks some langs (e.g. KR/AR bios) → EN fallback.
- New/useful fields: `strCountryCode` (clean ISO2, vs messy `strCountry`), `strMood`,
  `strTheme`, and embedded MusicBrainz IDs (so we can do MBID lookups / link to MB).

**Gotcha:** path segments must be encoded with `quote(term, safe="")`. Default `quote`
keeps `/` unescaped, which breaks terms with slashes on a path API (e.g. artist "AC/DC").

**Rate limit:** Premium is ~100 req/min and the cache is per-`AudioDBClient` instance while
a new client is created per track — bursts of concurrent builds can still approach the cap.
If it becomes a problem, add a process-level shared TTL cache or throttle.

**Error policy:** raise `AudioDBError` on 400/401/403/429 (auth/quota — surface loudly);
return empty `{}`/`None` on 404 and 5xx (treat as "no data", degrade gracefully).

**MusicBrainz fallback in `get_artist`:** when the AudioDB name search returns 0 rows,
we resolve the MBID via MusicBrainz (`search_artist`, limit=1) and re-look-up AudioDB by
MBID (`/lookup/artist_mb/{mbid}`, NOT the user's `/lookup/artist/mbid/{mbid}` form which
returns empty). **Why caution:** MusicBrainz search is fuzzy and returns a top match for
almost ANY string (even nonsense), so this fallback can attach a *wrong* artist when
AudioDB legitimately has no data. It's safe in the real pipeline because the artist name
comes from canonical Musixmatch track data, not free user text.
