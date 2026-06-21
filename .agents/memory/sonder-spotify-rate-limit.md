---
name: Sonder Spotify rate-limit handling
description: How a Spotify 429 surfaces in the studio iframe and how logout/messaging is wired to the parent.
---

# Spotify rate-limit (429) flow

There are TWO rate-limit paths and they need SEPARATE detection:

1. **Web API 429** — from Spotify Web API calls in the studio iframe (`api()` →
   search/resolveUri). Directly readable; `api()` keys off `r.status === 429`.
2. **Embed-player rate limit** — the "Your application has reached a rate/request
   limit." text comes from the **cross-origin Spotify embed iframe**. It is NOT a 429
   on any of our calls. Critically, when a track's `t.uri` is already resolved/cached,
   `resolveUri` early-returns and NO Web API call fires, so path 1 never triggers even
   though the embed is rate-limited. TWO detectors cover this:
   - **Message-text detector (immediate):** the embed `postMessage`s a payload
     containing that phrase to the studio-iframe window. The studio `message` listener
     intercepts it **before** the `ev.source !== window.parent` parent-only guard
     (the embed is a child frame, source ≠ parent) and calls `handleSpotifyRateLimit()`.
     MUST gate on `ev.origin` matching `*.spotify.com` (regex), else a forged
     `postMessage` from any frame could force a spurious logout (DoS). Stringify
     `ev.data` (string as-is else `JSON.stringify`, wrapped in try/catch for cyclics).
   - **Playback-start watchdog (fallback):** after `embedController.play()`, start a
     ~9s timer; if the player never reports real playback (`embedPlayed` stays false →
     no `playback_update` with position>0 / unpaused), call `handleSpotifyRateLimit()`.
     Clear the timer when playback truly starts (`onState`) and in `stopAudio()`.

**Wiring:** `studio.html` detects 429 in `api()`, shows `I18N.spotifyUnavailable`,
and `postMessage({type:'sonder-spotify-rate-limit'})` to the parent (one-shot guard
`spotifyRateLimited`). `Studio.jsx` (source-pinned to its own iframe) forwards via
`onSpotifyUnavailable` → `App.jsx` clears the PKCE token + shows the banner.
Reconnection is intentionally **manual** from the sidebar (no auto-retry / no
auto re-login) — this was the user's explicit choice.

**Why no loop:** clearing the token re-renders `Studio` (token is a `srcDoc` useMemo
dep) so the iframe reloads with empty TOKEN; `resolveUri` early-returns on `!TOKEN`,
so no further Web API call → no repeated 429.
