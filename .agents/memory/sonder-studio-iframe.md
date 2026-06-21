---
name: Sonder studio iframe parity
description: How the migrated React frontend renders the Sonder "studio" with parity to the Streamlit original.
---

The studio is rendered as an `<iframe srcDoc>` containing the **exact** ported
`STUDIO_HTML` (extracted from `app.py` and saved as `frontend/src/studio.html`,
imported via `?raw`). Track data is injected by substituting the same
placeholders the original used (`__TRACKS__`, `__TTSLANG__`, `__PLAYLIST__`,
`__TOKEN__`, `__TTS_ENDPOINT__`, `__TTS_TOKEN__`, `__TTS_MODE__`,
`__STUDIO_ID__`, `__AUTOPLAY__`), with `__TRACKS__` JSON having `</` escaped to
`<\/` to avoid breaking the `<script>` tag.

**Why:** the studio is large, self-contained vanilla JS; re-implementing it in
React would risk drift. Keeping the markup verbatim guarantees 1:1 parity.

**How to apply:** the injected track payload must include the same field subset
as the original (title/artist/speech/musixmatch_speech/audiodb_speech/mood/
origin/reason/image/uri/audio_b64/speech_marks/lyrics/translated_lyrics/
translation_lang/richsync/track_id/album). Migration-only differences:
`TTS_ENDPOINT` points at `/api/tts` (on-demand narration), `TTS_MODE="local"`,
and `STUDIO_ID`/`AUTOPLAY` are empty (no server-side session reload model).

**Lyrics rendering tiers (`showLyrics`):** synced word/line highlight is shown
ONLY when `TOKEN && richsync.length && richsyncTimingOk(richsync)` — synced text
without a Spotify player is pointless. Every other case (no token, missing or
unreliable richsync) falls back to the full bilingual plain text: prefer
`t.lyrics`, else richsync-derived lines, with `translated_lyrics` matched
line-by-line by index, and only a "no lyrics" message when neither exists.
**Why:** users want original+translation visible even without playback; richsync
(Musixmatch paid) is often absent. Untimed `.lyr-line` divs are safe — `syncLyrics`
no-ops on them (falls back via `hasTimedLines`).

**Spotify-required empty states:** ReccoBeats (energy/mood, audio-features table)
and Songstats are keyed by ISRC resolved via Spotify, so they're empty without a
token. Their placeholders use the shared `addSpotifyForInfo` key ("Add Spotify to
get all the information"); StudioSections always renders the Energy/Mood heading
and shows that prompt (no token) or `energyMoodEmpty` (token present, still no data).

**i18n inside the iframe:** the studio gets its strings via a `__I18N__`
placeholder (a per-language `studio` dict injected as `const I18N=__I18N__;`),
not via React context — context does not cross the iframe boundary. Localizing
the studio means BOTH the static chrome (handled by an `applyI18n()` IIFE) AND
every runtime `setStatus(...)`/`setPMsg(...)` call. The runtime status/error
strings are easy to miss because they live deep in the vanilla JS; any future
i18n pass over the studio must grep for `setStatus(`/`setPMsg(` literals, not
just the visible HTML. Each new studio string must be added to all 9 language
blocks in `frontend/src/i18n.jsx`.
