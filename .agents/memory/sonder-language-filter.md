---
name: Sonder lyrics-language filter
description: How "reinforce language choice" discards out-of-language tracks, and why the lyrics-language fetch is gated.
---

# Sonder lyrics-language filter

When the user picks search languages, found songs whose detected lyrics language
isn't in the allowed set are discarded in `search_musixmatch_from_plan`.

- Musixmatch `lyrics_language` is ISO 639-1 **lowercase** (`"en"`, `"it"`);
  the user's selected codes are **uppercase** (`"EN"`). Compare via `.upper()`.
- **Unknown-language tracks are kept** (empty `lyrics_language`): you can't prove
  they're out of scope. If hard enforcement is ever wanted, drop unknowns too.
- The filter is **skipped** when the plan has an explicit `q_track`/`q_artist`:
  a directly requested song must be honored even in another language.
- Dropped tracks are **backfilled**: instead of just shrinking the list, the
  search pulls more candidates and rebuilds until it reaches `limit` (10) or the
  pool is exhausted (see backfill section). The Italian note says whether the
  dropped tracks were replaced or couldn't all be replaced.

## Backfill to reach `limit` after language drops
The goal is to ALWAYS reach `limit` (10) when material exists, not stop at the
first survivors. `search_musixmatch_from_plan`:
- picks ONE random fresh track per thematic query but each `search_tracks(limit=5)`
  returns up to 5 — the other rating-qualified matches go into a **`reserve`** list
  (and into `seen`, so no dupes). Explicit `q_track`/`q_artist` queries DON'T feed
  reserve (the user wants that one song, not alternates).
- an `absorb(pool)` helper builds payloads in **batches** and appends to `kept`,
  applying the language filter only when `need_language`, until `len(kept)==limit`.
- after `absorb(selected)`, a **backfill loop** runs `while kept < limit and
  reserve`: shuffle reserve, take a `needed*3` chunk (oversized to absorb filter
  drops), run `select_known_candidates` (Songstats floor) on it, `absorb` the
  survivors. Reserve is sliced away each round → guaranteed termination.
**Why random:** user wanted unused query results added randomly, not the same
popular leftovers every time. **Why reserve (not re-query):** the extra 4 tracks
per query were already fetched and discarded — reusing them is free.
**Note:** this backfill now also helps the non-language path (reaches `limit` from
reserve when the initial candidate pool is short). Each reserve round emits its own
Songstats note — can look repetitive; aggregate later if it gets noisy.

## Why the lyrics-language fetch is gated (`need_language`)
Detecting the language requires `get_lyrics(track_id)`. Previously richsync
tracks skipped that call. The filter forced it for every `has_lyrics` track,
adding a burst of Musixmatch calls — and Musixmatch rate-limits bursts (known
prod issue).

**Rule:** thread a `need_language` flag (`fetch_musixmatch_text` →
`musixmatch_track_payload` → `build_payload`) set to
`bool(allowed and not has_explicit_track)`. Only force the extra `get_lyrics`
when the filter will actually run; otherwise keep the old behavior (skip the call
when richsync already supplied the body).
