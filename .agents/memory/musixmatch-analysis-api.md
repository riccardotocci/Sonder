---
name: Musixmatch lyrics analysis API
description: Semantic "meaning" search + per-track lyrics analysis (moods/themes/genres) quirks and the right way to source them.
---

# Musixmatch lyrics analysis

Two endpoints power semantic search and textual mood/theme/genre data:

- `track.lyrics.analysis.search` — **POST**, body `{"data": {"meaning": "<phrase>"}}`.
  Returns up to ~100 `track_list` items, each with both `track` (incl. `primary_genres`)
  AND a rich `analysis` block (`moods.main_moods`, `themes.main_themes[].theme`,
  `meaning`, `rating`). Slow (~5s/call) — parallelize. This is the reliable source.
- `track.lyrics.analysis.get?track_id=<id>` — GET, needs the **real `track_id`**
  (NOT commontrack_id). Frequently returns an **empty** envelope (HTTP 200 with
  envelope `status_code` 404) even for tracks that the search returned with full
  analysis.

**Why:** the `analysis` embedded in `analysis.search` results is far more complete
than what `analysis.get` returns for the same track. Re-fetching per track via
`analysis.get` often yields nothing.

**How to apply:**
- For meaning/semantic search, prefer `analysis.search` and reuse the embedded
  `analysis` directly — do not re-fetch it per track.
- Treat empty analysis as "no moods" and degrade gracefully (return `{}`).
- To avoid double round-trips, mark a track once analysis has been *attempted*
  (e.g. an internal `mx_analysis_done` flag) so later enrichment steps skip it
  instead of re-calling `analysis.get` whenever moods came back empty.
- Musixmatch returns HTTP 200 with an envelope status code; non-200 envelope
  codes raise — catch and return empty for the optional/analysis paths.
- Use `meaning` search as an EXTRA candidate source for deep/abstract themes;
  keep `q_lyrics` queries primary for proper-name / specific historical events.
