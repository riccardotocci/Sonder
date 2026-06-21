---
name: Songstats API contract
description: How to read tracks from the Songstats Enterprise API and where the authoritative schema lives.
---

# Songstats Enterprise API contract

The Stoplight docs at docs.songstats.com are JS-rendered, so webFetch returns
nothing useful. **The authoritative contract is the official SDK source**:
https://github.com/Songstats/songstats-node-sdk (and its Python twin). Read the
SDK `src/resources/*.js` for routes and identifiers.

**Why:** the original Python client guessed the response shape and read track
metadata from the wrong keys.

**How to apply (track reads):**
- Identifiers (any one): `isrc`, `spotify_track_id`, `apple_music_track_id`,
  `songstats_track_id`. We resolve ISRC from Spotify and query `tracks/stats?isrc=`.
- `tracks/stats` response: track metadata is under the **top-level `track`** key
  (`name`, `artists[]`, `cover_url`), NOT inside `stats`. The per-source metrics
  live in `stats: [{source, data:{...}}]`.
- Real `data` field names: `streams_total`, `streams_daily`, `popularity`,
  `playlists_total`, `playlists_total_reach`, `playlists_editorial_total`,
  `charts_total`, `saves_total`, `views_total`, `likes_total`, `shazams_total`.
  These are what `METRIC_LABELS`/`STREAM_FIELDS` must key on.
- First-ever ISRC lookups can be empty: Songstats aggregates cross-platform links
  in the background, data fills in on later requests. Keep the client defensive
  (empty → None, never crash).

**Concurrency cap (~8):** Songstats fails with rate/limit errors above ~8
simultaneous requests. Batch track lookups in sequential chunks of ≤8
(`SONGSTATS_MAX_CONCURRENCY` + `_map_in_chunks` in backend/pipeline.py, used by
`select_known_candidates`); each chunk runs concurrently, next waits for it.
Never raise per-call ThreadPoolExecutor workers above 8 for Songstats.
