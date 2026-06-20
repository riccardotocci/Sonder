---
name: Sonder Spotify token refresh
description: Why the Spotify PKCE token must be auto-refreshed client-side, and what silently breaks when it isn't.
---

# The Spotify PKCE access token must be refreshed on the client

Spotify PKCE access tokens expire after ~1h. When the token is stale, EVERY
Spotify-dependent feature breaks at once, and the failure is silent (no crash):
- `/api/songstats` -> backend `_resolve_isrc` -> Spotify `/v1/search` returns
  `401 access token expired` -> no ISRC -> empty `rows` -> stats look "gone".
- The studio player's client-side `resolveUri()` (in `studio.html`) can't search
  Spotify, so tracks get no `uri` and the embed loads nothing.

**Symptom signature:** in deployment logs, repeated
`HTTP Error for GET to https://api.spotify.com/v1/search ... returned 401 due to
The access token expired`. If you see that, it's token refresh, NOT the
songstats UI or the player code.

**The fix that must stay wired:** `refreshSpotify()` exists in `spotify.js` but is
useless unless something calls it. `App.jsx` must (a) on session restore, refresh
immediately if the stored token is already expired before first use, and (b) run
a self-rescheduling timer that refreshes ~60s before `obtained_at + expires_in`.
Each refresh writes a new `obtained_at`, which re-triggers the effect and
reschedules — keeping the session alive indefinitely.

**Why it's easy to regress:** the token object carries `refresh_token`,
`expires_in`, `obtained_at`; if any of those stop being persisted/propagated, the
expiry math silently defaults and refresh either never fires or fires wrong.

**Cache note:** backend `_resolve_isrc` / `_songstats_track_stats` are
`lru_cache`d keyed by `user_token`, so a refreshed token is a new key and bypasses
any cached 401/None — no manual cache busting needed.
