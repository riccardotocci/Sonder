---
name: Sonder Musixmatch search sources (lyrics vs meaning)
description: The two independent candidate sources in search_musixmatch_from_plan and the flags that gate them.
---

# Sonder Musixmatch search sources

`search_musixmatch_from_plan` builds candidates from **two independent sources**:

1. **Lyrics/query source** — the `plan["queries"]` loop using
   `q`/`q_track`/`q_artist`/`q_lyrics` (track.search). Gated by
   `settings.musixmatch_use_lyrics` (env `MUSIXMATCH_USE_LYRICS`, default true).
2. **Meaning source** — semantic `track.lyrics.analysis.search` over
   `plan["meanings"]` phrases. Gated by `settings.musixmatch_use_meaning`
   (env `MUSIXMATCH_USE_MEANING`, **default false**).

Flags can combine or stand alone; both off → empty results (clean).

## Meaning-only returns the same tracks
The meaning endpoint (`track.lyrics.analysis.search`) is too coarse to be a sole
source: for almost any meaning phrase it surfaces the same pool of popular,
well-analyzed tracks, so different questions yield near-identical results. That is
why `musixmatch_use_meaning` defaults to **False** — lyrics-query search provides
the real per-request variety; meaning is only an optional supplement.
**How to apply:** if a user reports "same songs for different prompts," check the
flags first — meaning-only (or lyrics off) is the usual cause.

## Per-query selection is RANDOM, not best-rated
The lyrics-query loop pulls `search_tracks(..., limit=5)` (results are
`s_track_rating desc`) and promotes ONE track per query via
`random.choice(fresh-unseen)` — NOT `fresh[0]`. **Why:** always taking the top
rating returned the same popular songs across repeated searches; random pick adds
per-search variety. **Exception:** when the query has explicit `q_track`/`q_artist`
it keeps `fresh[0]` (best match), because there the user wants that specific song.
The meaning source is intentionally NOT randomized ("tra i rating" applies only to
the rating-sorted track.search path).

## track_rating quality threshold (>= 35)
Both sources drop tracks whose Musixmatch `track_rating` (0-100, in `track.raw`) is
below `MUSIXMATCH_MIN_TRACK_RATING` (35) via `_below_rating_threshold`. **A MISSING
rating is also discarded** (treated as unknown/low-value) — this was a deliberate
user reversal of the earlier "keep unknowns" rule. **Why:** the user decided a track
with no rating is probably obscure and not worth surfacing. **Watch:** the meaning
endpoint (`analysis.search`) often omits `track_rating`, so this can sharply shrink
the meaning pool — if the user later reports too few results, this is the first
suspect. **Exception:** explicit `q_track`/`q_artist` queries skip the threshold
entirely (respect the specifically requested song, even if low-rated/missing).

## "Similar to <artist/song>" must NOT contain the name
The search-planning prompt (`MUSIXMATCH_SEARCH_LYRICS_BLOCK` in `core/storyteller.py`)
splits two intents: a SPECIFIC artist/song request ("metti X di Y") uses
`q_track`/`q_artist`; a SIMILARITY request ("brani simili a Blanco", "come", "in
stile") must NEVER put the artist/song name in ANY field (q/q_track/q_artist/q_lyrics)
— doing so hard-constrains track.search to that artist's own catalogue. Instead the
LLM infers the recurring themes/imagery/mood/style and builds thematic q_lyrics.
**Why:** "Brani simili a Blanco" had produced 20 queries each with `q="Blanco"`,
returning only Blanco. The NOME PROPRIO rule carries an explicit EXCEPTION so it
doesn't re-leak the imitated artist's name.

## True-independence gotcha
The "explicit track" override (`has_explicit_track`) that disables the lyrics-language
filter is read from `plan["queries"]`. It **must also be gated by
`musixmatch_use_lyrics`** — otherwise, in meaning-only mode, an explicit `q_track`/
`q_artist` in the (now-ignored) queries would still switch off the language filter for
the meaning results, breaking source independence.

**Why:** the user asked for lyrics/meaning toggles that work alone or together.
**Boundary:** these flags must NOT change the LLM plan generation nor the
post-candidate check (`select_known_candidates` / language filter) — they only choose
which candidate sources contribute and correctly scope `has_explicit_track`.
