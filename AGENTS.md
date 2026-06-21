# AGENTS.md — Sonder

Sonder turns a song / artist / theme into a multilingual, narrated emotional
storytelling experience. It chains Musixmatch (lyrics) → TheAudioDB / MusicBrainz
(artist data) → an OpenAI-compatible LLM "Thinking" engine → ElevenLabs (AI voice
narration) → Spotify (per-user playback via PKCE) → Songstats (streaming stats).

The app was **migrated from a single Streamlit `app.py` to a React (Vite)
frontend + FastAPI backend** with 1:1 visual/functional parity. The Python service
clients in [core/](core/) are reused unchanged. `app.py` is kept **only as a
reference** for the ported UI/orchestration — it is not the entry point anymore.

See [README.md](README.md) for the product overview and data-flow diagram, and
[replit.md](replit.md) for the canonical architecture/structure notes. API-key
names live in [.env.example](.env.example).

## Architecture

A `/api/chat` request flows through pure functions in
[backend/pipeline.py](backend/pipeline.py) (search them by name to find where to
edit):
`Storyteller.plan_musixmatch_search` (LLM router → themed queries balanced across
languages) → `search_musixmatch_from_plan` (fetch tracks + lyrics in parallel
workers) → `select_known_candidates` (drop tracks under `SONGSTATS_MIN_STREAMS`
by ISRC, backfill from reserve) → `build_studio` (bio + LLM speeches/mood/geo +
ElevenLabs MP3) → studio payload with track data injected into `STUDIO_HTML`.

- **Backend** — FastAPI ([backend/main.py](backend/main.py)) on **port 8000**,
  reuses [core/](core/). Endpoints: `/api/bootstrap`, `/api/chat`, `/api/tts`,
  `/api/spotify/{exchange,refresh,theme-recs,create-playlist}`, `/api/songstats`.
  Orchestration is ported into [backend/pipeline.py](backend/pipeline.py) as
  **pure functions** (no `st.session_state`, no `st.cache_*`); the per-user
  Spotify token is passed in explicitly so process-wide caches stay thread-safe
  inside the FastAPI worker threadpool. In production the backend also serves the
  built frontend (`frontend/dist`) with an SPA fallback.
- **Frontend** — Vite + React on **port 5000** (webview). In dev it proxies
  `/api/*` and `/static/*` to the backend at `localhost:8000`.
- **Studio** — rendered as an `<iframe srcDoc>` containing the ported
  `STUDIO_HTML` (the exact original markup/CSS/JS), with track data injected via
  the same placeholder substitution the original used.
- [core/config.py](core/config.py) exposes the singleton `settings`. `_env()`
  reads `.env` first, then (if present) `st.secrets`. Every service exposes a
  `settings.<name>_ready` boolean and `settings.status()` aggregates them.
- [core/__init__.py](core/__init__.py) exports clients **lazily** — do not add
  import-time work that pulls in heavy clients during boot.

## Run & validate

Two workflows (see [replit.md](replit.md)):

```bash
# Backend API (port 8000)
uvicorn backend.main:app --host 0.0.0.0 --port 8000
# Start application — frontend webview (port 5000)
cd frontend && npm run dev
```

- Python deps: `requirements.txt`. Frontend deps: `frontend/package.json`.
- **No test suite and no linter config exist.** After editing, validate by
  booting **both** workflows and confirming `/api/bootstrap` responds and the
  webview renders. For changes to the embedded studio JS, also run `node --check`
  on the inline `<script>` from [frontend/src/studio.html](frontend/src/studio.html)
  (substitute the `__PLACEHOLDER__` tokens with JSON first).
- Production build/run (autoscale): `cd frontend && npm install && npm run build`,
  then `uvicorn backend.main:app --host 0.0.0.0 --port 5000` (FastAPI serves the
  built React app from `frontend/dist`).
- Secrets live in `.env` (git-ignored) — never commit them; copy from
  [.env.example](.env.example).

## Project conventions (do not break these)

- **Graceful degradation is mandatory.** Gate every external call on
  `settings.<service>_ready` and fall back to a "demo mode" caption telling the
  user which env var to set. The app must boot and run with **zero API keys**.
- **Comments & docstrings are in Italian** (most user-facing UI strings are
  English). Match the surrounding language when editing a file.
- **LLM output is untrusted.** Parse it through the tolerant
  `Storyteller._parse_json` / `_parse_tracks` helpers; free models often omit
  optional JSON fields (e.g. `narration_lang`), so detect/derive missing fields
  server-side instead of relying on them.
- **Pipeline functions must stay pure & thread-safe.** No Streamlit state.
  Capture per-user values (e.g. the Spotify token) in the request handler and
  pass them into workers; never read request-scoped state from a
  `ThreadPoolExecutor` worker. `build_studio` runs concurrently with the response
  writer and is safe **only** because it clones track dicts — keep it from
  mutating its inputs in place.
- **Resolve narration language once** in `run_chat` and thread it to all LLM text
  AND the translated-lyrics fetch, or "Auto"/source-language leakage and
  divergence creep back in.
- **Three language-code formats coexist — never mix them:** TheAudioDB uses
  2-letter UPPER (`IT`), Musixmatch/translations use ISO 639-1 lower (`it`),
  Web Speech/TTS use BCP-47 (`it-IT`). Convert via the
  [backend/constants.py](backend/constants.py) helpers
  (`musixmatch_translation_code`, `_detect_narration_lang`,
  `resolve_narration_lang`) instead of hand-building codes.
- **Each client follows the same shape:** a class + a custom `*Error` exception
  (e.g. `MusixmatchClient` / `MusixmatchError`). Keep that pattern when adding
  clients.

## Known pitfalls (hard-won — verify before "fixing")

- **TTS on hosting:** the browser cannot reach the container's `127.0.0.1`
  loopback TTS server. Set `SONDER_TTS_MODE=embedded` so ElevenLabs MP3s are
  generated server-side (via `/api/tts`) and embedded as base64 on Play. `auto`
  keeps the loopback only for local dev.
- **Embedded studio component** is a single HTML string (`STUDIO_HTML`,
  [frontend/src/studio.html](frontend/src/studio.html) imported via `?raw`)
  rendered in an `<iframe srcDoc>`. Track data is injected through the same
  placeholder substitution (`__TRACKS__`, `__TOKEN__`, …) the original used —
  keep every injected value JSON-serialized.
- **Spotify auth only works on the published app:** PKCE redirect must match the
  registered prod redirect URI; localhost is not accepted (use `127.0.0.1` for
  local dev). Playlist creation needs the `playlist-modify-*` scopes on the PKCE
  token.
- **Spotify PKCE token expires (~1h):** the frontend must auto-refresh (via
  `/api/spotify/refresh`) or both Songstats AND the player silently break
  (Spotify search returns 401).
- **`@dataclass` at import time crashed on some hosts:** keep
  [core/audiodb_client.py](core/audiodb_client.py) model classes as plain classes.
  Other clients use dataclasses safely; this gotcha is specific to import-time
  model definitions.
- **Spotify `popularity` is 0-100, NOT a play count.** Use Songstats stream
  counts (by ISRC) for the `SONGSTATS_MIN_STREAMS` notability threshold.

## External API documentation

All keys are optional; each service degrades to demo mode when unset. Env-var
names are read in [core/config.py](core/config.py).

### Musixmatch — lyrics & track search
- Client: [core/musixmatch_client.py](core/musixmatch_client.py)
- Base URL: `https://api.musixmatch.com/ws/1.1`
- Key endpoints: `track.search`, `track.lyrics.get`,
  `track.lyrics.translation.get`, `track.richsync.get`, `matcher.lyrics.get`,
  `track.get`
- Auth: `apikey` query param — env `MUSIXMATCH_API_KEY` (or `MXM_KEY`)
- Docs: https://developer.musixmatch.com/documentation
- Note: free plan returns partial lyrics (~30%) with a copyright disclaimer.

### TheAudioDB — artist bios & images
- Client: [core/audiodb_client.py](core/audiodb_client.py)
- Base URL: `https://www.theaudiodb.com/api/v1/json/<key>`
- Key endpoints: `search.php`, `searchtrack.php`, `searchalbum.php`
- Auth: API key in the URL path — env `AUDIODB_API_KEY` (public test key `123`)
- Docs: https://www.theaudiodb.com/free_music_api

### MusicBrainz — artist metadata & external IDs
- Client: [core/musicbrainz_client.py](core/musicbrainz_client.py)
- Base URL: `https://musicbrainz.org/ws/2`
- Key endpoints: `artist` (search), `artist/<mbid>?inc=url-rels` (Wikidata /
  Wikipedia / Discogs / AllMusic relations)
- Auth: none, but a descriptive `User-Agent` header is required (set in client)
- Docs: https://musicbrainz.org/doc/MusicBrainz_API

### LLM "Thinking" engine — OpenAI-compatible (OpenRouter / OpenAI)
- Client: [core/storyteller.py](core/storyteller.py) (uses the `openai` SDK)
- Base URL: configurable, default `https://openrouter.ai/api/v1`
- Key endpoint: `POST /chat/completions` (`client.chat.completions.create`)
- Auth: bearer key — env `LLM_API_KEY`; also `LLM_BASE_URL`, `LLM_MODEL`
  (default `openai/gpt-oss-120b:free`), `LLM_TIMEOUT_SECONDS`. Selectable models
  live in `LLM_MODEL_OPTIONS` ([core/config.py](core/config.py)).
- Docs: https://openrouter.ai/docs (or https://platform.openai.com/docs)

### ElevenLabs — AI voice narration (TTS)
- Client: [core/elevenlabs_client.py](core/elevenlabs_client.py) (official
  `elevenlabs` SDK)
- Base URL: `https://api.elevenlabs.io/v1`
- Key calls: `text_to_speech.convert`,
  `text_to_speech.convert_with_timestamps` (for karaoke word marks)
- Auth: API key — env `ELEVENLABS_API_KEY`; also `ELEVENLABS_VOICE_ID`
  (default George `JBFqnCBsd6RMkjVDRZzb`), `SONDER_TTS_MODE` (`auto`/`embedded`)
- Docs: https://elevenlabs.io/docs/api-reference/text-to-speech

### Spotify Web API — search & playlists
- Client: [core/spotify_client.py](core/spotify_client.py) (via `spotipy`)
- Base URL: `https://api.spotify.com/v1` (through spotipy)
- Key calls: `search` (type=track), `current_user`, `user_playlist_create`,
  `playlist_add_items`
- Auth: per-user PKCE token (preferred — only the public Client ID is needed) or
  Client Credentials fallback. Env `SPOTIFY_CLIENT_ID`,
  `SPOTIFY_CLIENT_SECRET` (not needed for PKCE), `SPOTIFY_REDIRECT_URI`
- Docs: https://developer.spotify.com/documentation/web-api

### Spotify Authorization Code + PKCE (per-user login)
- Client: [core/spotify_pkce.py](core/spotify_pkce.py); proxied through
  [backend/main.py](backend/main.py) (`/api/spotify/exchange`, `/api/spotify/refresh`)
- Endpoints: `https://accounts.spotify.com/authorize`,
  `https://accounts.spotify.com/api/token`
- Scopes: `user-read-private user-top-read playlist-modify-public
  playlist-modify-private`
- Auth: PKCE (S256), no client secret — public `SPOTIFY_CLIENT_ID` + the
  registered `SPOTIFY_REDIRECT_URI`
- Docs: https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow

### Songstats — real streaming statistics
- Client: [core/songstats_client.py](core/songstats_client.py)
- Base URL: `https://api.songstats.com/enterprise/v1`
- Auth: `apikey` request header — env `SONGSTATS_API_KEY`
- Docs: https://docs.songstats.com/ (Stoplight docs are JS-rendered; the
  **authoritative contract is the official SDK**:
  https://github.com/Songstats/songstats-node-sdk and its Python twin.)
- **Track identifiers** (any one): `isrc`, `spotify_track_id`,
  `apple_music_track_id`, `songstats_track_id`. We resolve ISRC from Spotify and
  query by `isrc` — the canonical, unambiguous path. First-ever ISRC lookups may
  be sparse: Songstats aggregates cross-platform links in the background and data
  fills in on subsequent requests.
- **Max ~8 concurrent requests.** Songstats fails (rate/limit errors) when more
  than ~8 requests hit it at once. Batches of track lookups MUST be processed in
  sequential chunks of at most 8: each chunk runs concurrently, but the next
  chunk only starts after the current one finishes. See
  `SONGSTATS_MAX_CONCURRENCY` + `_map_in_chunks` in
  [backend/pipeline.py](backend/pipeline.py) (used by `select_known_candidates`).
  Never raise the per-call `ThreadPoolExecutor` worker count above 8 for
  Songstats, and never fire all lookups for >8 tracks in a single unchunked map.
- **Key endpoints:**
  - `tracks/info` — metadata + cross-platform ID **mappings** (Spotify/Apple/ISRC),
    `name`, `artists[]`, `cover_url`.
  - `tracks/stats?isrc=...` — current stats per source (this is the ONLY endpoint
    we call; the provided API key is authorized for this path only). The ISRC is
    resolved from Spotify, so no text-search step is needed.
- **`tracks/stats` response shape:**
  ```json
  {
    "result": "success",
    "track": { "name": "...", "artists": [{"name": "..."}], "cover_url": "...",
               "songstats_track_id": "..." },
    "stats": [
      { "source": "spotify",
        "data": { "streams_total": 0, "streams_daily": 0, "popularity": 0,
                  "playlists_total": 0, "playlists_total_reach": 0,
                  "playlists_editorial_total": 0, "charts_total": 0,
                  "saves_total": 0 } },
      { "source": "youtube", "data": { "views_total": 0, "likes_total": 0 } },
      { "source": "shazam",  "data": { "shazams_total": 0 } }
    ]
  }
  ```
  Track metadata lives under the top-level `track` key (NOT inside `stats`).
  `METRIC_LABELS` / `STREAM_FIELDS` in the client map these `data` field names to
  human labels and to the real-stream notability floor.
