---
name: Sonder studio_brief data sourcing
description: Which studio fields come from the LLM vs real data sources, and why
---

The second chat LLM call (`studio_brief`) generates ONLY a single merged per-track
`speech` (one flowing text intertwining Musixmatch lyrics + TheAudioDB context; no split
musixmatch_speech/audiodb_speech, no LLM valence/energy). Everything else on the studio
comes from real data, set during enrichment — NOT from the LLM:

- `mood` = TheAudioDB `strMood` (v2 lookup): track-level mood overrides, artist-level
  mood as fallback; Musixmatch genre is the last resort. (Was Musixmatch genre only.)
- `genre`/`mx_genres` = Musixmatch `primary_genres` ONLY (Track.from_api). The
  narration brief line labeled "Musixmatch genere:" must source strictly from
  `mx_genres` (else the `genre` field, also Musixmatch) — NEVER fall back to `mood`,
  or the label lies (mood can be LLM/AudioDB). Mood is shown on its own separate line.
- `origin` (display label, the `📍` map-pin text) = TheAudioDB `Artist.country` (messy
  full names like "London, England"), MusicBrainz `search_artist().country` (ISO2) fallback.
- `origin_code` (drives coords ONLY) = TheAudioDB `strCountryCode` (clean ISO2 e.g. "GB"),
  or the MB ISO2 country in the fallback. Resolve coords from `origin_code or origin`
  because messy `origin` strings fail `resolve_coordinates`.
- `lat`/`lng` = internal `backend/geo_coords.py` `resolve_coordinates(origin_code or origin)`,
  which accepts ISO2 codes, full country names, and aliases (USA/UK/England→GB, etc.).
  No external service exposes decimal coords for an artist origin, hence the static table.
- TheAudioDB has NO valence/energy even on v2 Premium — those come from ReccoBeats.
- The global playlist summary + mood tags ("Riepilogo atmosfera") were removed. The chat
  reply is now `compose_track_list_reply(tracks)` (a plain numbered list); `build_studio`
  still returns `summary=""`/`moods=[]` for backward-compat keys.

**Why:** the LLM was inventing geography/coordinates/mood instead of using authoritative
sources, causing wrong map pins and unreliable mood labels.

**How to apply:** if adding studio fields, prefer a real data source over the prompt.
`valence`/`energy` (+ full audio features and a derived `mood` label) come from the
ReccoBeats API (https://api.reccobeats.com) — free, no API key. Two-step flow: resolve the
Spotify ISRC → ReccoBeats id (`/v1/track?ids=`), then `/v1/track/{id}/audio-features`. The
ISRC is resolved via Spotify (`_resolve_isrc`), so audio features only populate when a user
is logged into Spotify; otherwise the Energy/Mood chart hides (graceful degradation). The
deprecated Spotify `/audio-features` endpoint and the Cyanite plan were both abandoned.
