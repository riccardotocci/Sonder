---
name: Sonder Spotify wiring
description: How Spotify PKCE auth and playlist creation work in the React+FastAPI Sonder app, and why Spotify only works in production.
---

# Spotify in Sonder (React + FastAPI)

## Shared PKCE module
Both the original Streamlit `app.py` and the React frontend drive auth through
the **same** `core/spotify_pkce.py` (`AUTH_URL`, `TOKEN_URL`, `build_auth_url`,
`exchange_code`, `refresh_access_token`). The React frontend rebuilds the
authorize URL client-side in `frontend/src/spotify.js` but must keep the exact
same params (incl. `show_dialog=true`) and pull `redirect_uri`/`scopes`/`auth_url`
from `/api/bootstrap`. Token exchange/refresh are proxied through the backend.
**Why:** keep auth behavior 1:1 with the previous version so the published app
keeps working unchanged.

## Auth only works on the PUBLISHED app
`SPOTIFY_REDIRECT_URI` is set to the prod domain (`https://sonder-music.replit.app`)
and that exact URI is registered in the Spotify developer dashboard. In the dev
preview the redirect lands on prod, so the PKCE round-trip cannot complete in dev
— this is expected, not a bug. Do not "fix" it by pointing the redirect at the
dev domain unless that URI is also registered in the Spotify dashboard.

## "Open on Spotify" arrow — link by ISRC, not text search
The studio track-list arrow (`trackSpotifyLink` in `frontend/src/studio.html`)
prefers a direct `/track/<id>` URL from the resolved Spotify URI; if there's no
URI it uses `open.spotify.com/search/isrc:<ISRC>` (the track's `isrc`, exposed
top-level on the payload in `build_studio` from the same `search_track` result),
falling back to a title+artist text search only when ISRC is missing too.
**Why:** Spotify has **no** URL that opens a track directly by ISRC (track URLs
need the Spotify track ID, not the ISRC) — `search/isrc:...` is the canonical way
to land on the *exact* song, vs the fuzzy title+artist search the user disliked.
**Gotcha:** `uri` and `isrc` currently both come from the SAME Spotify search
result, so the isrc branch only fires if a track ever has an ISRC without a URI
(e.g. a future non-Spotify ISRC source). Musixmatch free tier does NOT provide ISRC.

## Playlist creation requires playlist-modify scopes on the PKCE token
The "Create this playlist on Spotify" button (per chat message with tracks) calls
`/api/spotify/create-playlist`, which uses `SpotifyClient(access_token=<pkce token>)`
→ `create_thematic_playlist`. For this to work the browser PKCE token must carry
`playlist-modify-public playlist-modify-private`, so those scopes live in
`core/spotify_pkce.SCOPES`.
**Why:** the original Streamlit app created playlists via a separate interactive
`SpotifyOAuth` flow (needs client secret + a server-side browser) which is not
viable for end users of a deployed multi-user web app. `SpotifyClient.user_client`
was extended to prefer `access_token` (mirroring `search_client`) so the PKCE
token works without a client secret.
**How to apply:** changing the scope means users must re-consent on next login
(the Spotify dialog shows the new permission automatically).
