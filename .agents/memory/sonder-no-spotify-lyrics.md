---
name: Sonder no-Spotify lyrics fetch
description: Why the backend prefers plain track.lyrics.get over richsync when there's no user Spotify token.
---

# Sonder no-Spotify lyrics fetch

The studio iframe renders **synced** (richsync, word/line-timed) lyrics ONLY when
the user's Spotify `TOKEN` is present (studio.html: `if (TOKEN && richsync.length
&& richsyncTimingOk(...))`). Without a user PKCE token it always falls back to the
**static** view: original (`t.lyrics`) + translation (`t.translated_lyrics`),
deriving lines from richsync only if `t.lyrics` is empty.

**Decision:** the backend fetch threads `prefer_plain_lyrics = not user_token`
through `fetch_musixmatch_text` / `musixmatch_track_payload`. When set (no Spotify)
it **skips the richsync fetch** (only if `has_lyrics`, so a plain fallback exists)
and fetches the clean `track.lyrics.get` body for `t.lyrics`. Richsync text is
word-segmented/messier; the plain endpoint gives cleaner full lyrics for the static
view, and it's net-neutral on Musixmatch calls (skip richsync, add one plain call).

**Why:** synced timing is wasted with no player; the static original+translation
deserves the cleanest text.
**How to apply:** keep the frontend `TOKEN`-gated synced condition and the backend
`prefer_plain_lyrics` flag in sync — if the studio ever renders synced lyrics
without a user token, revisit this. The `need_language` filter path and the
translation fetch (gated by `translation_lang`) are unaffected.
