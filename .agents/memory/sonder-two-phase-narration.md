---
name: Sonder two-phase chat pipeline
description: How the Studio loads immediately while narration text is generated asynchronously, and why the iframe must not reload.
---

# Two-phase chat pipeline (Studio loads first, narration later)

The slow part of a chat request is the `studio_brief` LLM call that writes each
track's narration "speech". To make the Studio appear immediately:

- **Phase 1** — `/api/chat` runs `run_chat(with_narration=False)`. `build_studio`
  skips speech generation (speeches stay `""`) but still does all service
  enrichment (Musixmatch/AudioDB/MusicBrainz/coords). Studio renders right away.
- **Phase 2** — `/api/narrate` calls `pipeline.generate_narration_speeches(...)`
  (the extracted slow studio_brief call + `_fallback_speech`). Frontend fires it
  non-blocking after rendering the Studio.

## Critical constraint: the Studio iframe must NOT reload on narration arrival
The Studio is an `<iframe srcDoc>`. Reloading it would interrupt any in-progress
Spotify playback. So:
- `Studio.jsx` builds `srcDoc` from **phase-1 data only**; `narrationPending` /
  `narrationSpeeches` are deliberately excluded from the memo deps (eslint-disable).
- Speeches are delivered into the live iframe via `postMessage`
  `{type:'sonder-narration', speeches}` — on speeches change AND on iframe
  `onLoad` (covers the race where speeches arrive before the iframe exists; cache
  in a ref). The iframe listener updates `TRACKS[i].speech` in place, flips
  `narrationPending=false`, re-enables the narration toggle, and re-renders only
  the speech block (not `showCenter`, to avoid disturbing the player).

## While pending
Loading bar in the speech area (reuses `I18N.generatingNarration`); narration
(TTS) toggle disabled; song selection + Spotify launch stay enabled.

**Why:** narration text is the only slow piece; everything else is ready in
phase 1, so blocking the whole Studio on it wasted ~75s of perceived load time.

**Gotchas:**
- `_bio` is popped from phase-1 track dicts, so phase-2 `_fallback_speech` loses
  that one fallback source (acceptable, fallback only fires when LLM fails).
- Add a client-side watchdog (App.jsx, ~180s) that clears `narrationPending` so a
  hung `/api/narrate` never leaves the loading bar spinning forever; a late
  response still populates the text afterwards.
- Async narrate promise must guard on a `chatGen` ref so a stale request from a
  previous prompt / New chat can't overwrite the current studio's speeches.

## Narration delivery race (text returned but not shown)
A single `postMessage` push is NOT enough: when the LLM is fast (~3s) the push can
fire before the iframe's `message` listener is registered, and `onLoad` alone
doesn't cover React StrictMode remounts — so the narration silently never renders.
Fix = **readiness handshake**: the iframe posts `{type:'sonder-studio-ready'}` to
`window.parent` right after registering its listener; the parent listens for that
and (re)calls `pushNarration()`, which re-sends whatever `speechesRef` holds. This
makes delivery deterministic across all orderings. Guard both `message` handlers
by `ev.source` (parent ↔ our iframe.contentWindow) so Spotify-embed postMessages
can't collide. `pushNarration` early-returns on null speeches so the handshake
never wrongly clears the loading bar.

**Why:** editing `studio.html` (imported `?raw`) also has flaky HMR — after such
edits restart the `Start application` workflow so the new iframe markup is served.
