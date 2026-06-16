# AGENTS.md — Sonder

Sonder (codename "Sonder") is a **Streamlit** app that turns a song/artist/theme
into multilingual emotional storytelling: it chains Musixmatch → TheAudioDB/Last.fm → an
OpenAI-compatible LLM → ElevenLabs narration → Spotify playback. See [README.md](README.md) for the
product overview, data-flow diagram, and the full API-key table.

Development site: https://sonder.streamlit.app

## Run & validate

```bash
source .venv/bin/activate          # local venv (Python 3.10+)
pip install -r requirements.txt
streamlit run app.py               # the only entry point
```

- **No test suite and no linter config exist.** After editing, validate the app boots headlessly:
  ```bash
  python -c "from streamlit.testing.v1 import AppTest; at=AppTest.from_file('app.py',default_timeout=60).run(); print('exception:', at.exception)"
  ```
  The validation passes when `len(at.exception) == 0` (the list must contain no exceptions). For changes to the embedded studio JS, also run `node --check` on the
  inline `<script>` (substitute the `__PLACEHOLDER__` tokens with JSON first).
- Secrets live in `.env` (git-ignored). Never commit them; copy from [.env.example](.env.example).
  On Streamlit Cloud the same keys go in **App settings → Secrets**.

## Architecture

A request flows through these functions (search them by name to find where to edit):
`Storyteller.plan_musixmatch_search` (LLM router → ~20 themed queries balanced across languages)
→ `search_musixmatch_from_plan` (fetch tracks + lyrics in parallel workers)
→ `select_known_candidates` (drop tracks under `SONGSTATS_MIN_STREAMS` by ISRC, backfill from reserve)
→ `build_studio` (bio + LLM speeches/mood/geo + ElevenLabs MP3) → `render_studio_component`
(inject JSON into `STUDIO_HTML`).

- [app.py](app.py) is the orchestrator and **all UI** (~3300 lines): chat loop, `build_studio`,
  the `STUDIO_HTML` component, Spotify PKCE, rendering. It is large by design — search within it
  rather than splitting it.
- [core/](core/) holds one client per external API. Each follows the same shape:
  a class + a custom `*Error` exception (e.g. `MusixmatchClient`/`MusixmatchError`).
- [core/config.py](core/config.py) exposes the singleton `settings`. `_env()` reads `.env` first,
  then `st.secrets`. Every service has a `settings.<name>_ready` boolean.
- [core/__init__.py](core/__init__.py) exports clients **lazily** — do not add import-time work that
  pulls in heavy clients during boot.

## Project conventions (do not break these)

- **Graceful degradation is mandatory.** Gate every external call on `settings.<service>_ready` and
  fall back to a "demo mode" caption telling the user which key to set. The app must boot and run
  with zero API keys.
- **Comments & docstrings are in Italian** (user-facing UI strings are mostly English). Match the
  surrounding language when editing a file.
- **LLM output is untrusted.** Parse it through the tolerant `Storyteller._parse_json` /
  `_parse_tracks` helpers; free models often omit optional JSON fields (e.g. `narration_lang`), so
  detect/derive missing fields server-side instead of relying on them.
- **Streamlit state persistence:** use `@st.cache_resource` for stores that must survive reruns and
  the Spotify OAuth full-page redirect (`_pkce_store`, `_persistent_token_store`); use
  `@st.cache_data` for pure cached computations (audio, logos).
- **Never read `st.session_state` from a `ThreadPoolExecutor` worker** (no ScriptRunContext there).
  Capture values like `spotify_token()` in the main thread and pass them in as arguments.
- **Three language-code formats coexist — never mix them:** TheAudioDB uses 2-letter UPPER (`IT`),
  Musixmatch/translations use ISO 639-1 lower (`it`), Web Speech/TTS use BCP-47 (`it-IT`). Convert
  via the [app.py](app.py) helpers (`musixmatch_translation_code`, `_normalize_mxm_lang`,
  `_detect_narration_lang`) instead of hand-building codes.

## Known pitfalls (hard-won — verify before "fixing")

- **TTS on hosting:** the browser cannot reach the container's `127.0.0.1` loopback TTS server on
  Streamlit Cloud. Set `SONDER_TTS_MODE=embedded` so ElevenLabs MP3s are generated server-side and
  embedded as base64 on Play. `auto` keeps the loopback only for local dev.
- **Embedded studio component** is a single HTML string (`STUDIO_HTML`) rendered via
  `components.html`, with `__TRACKS__`, `__TOKEN__`, etc. injected through `str.replace` using
  `json.dumps`. Keep every injected value JSON-serialized.
- **Lyrics/narration auto-scroll inside the iframe:** never use `el.scrollIntoView()` — it drags the
  whole page. Center only the scroll box manually via `box.scrollTo({ top: ... })`.
- **Use a real label + `label_visibility="collapsed"`** for inputs; `st.text_input("", ...)` emits a
  Streamlit warning.
- **Import-time model classes:** keep [core/audiodb_client.py](core/audiodb_client.py) model classes
  as plain classes — `@dataclass` there crashed at import on Streamlit Cloud / Python 3.14. Other
  clients still use dataclasses safely; this gotcha is specific to import-time model definitions.
- **Optional client methods** are called via `getattr(client, "method", None)` + a `callable()` guard
  so newer/older client versions interoperate; keep that pattern when adding methods.

## External API documentation

| Service | Client | Reference |
|---------|--------|-----------|
| Musixmatch | [core/musixmatch_client.py](core/musixmatch_client.py) | [Overview & endpoints](https://docs.musixmatch.com/overview) |
| ElevenLabs TTS | [core/elevenlabs_client.py](core/elevenlabs_client.py) | [API quickstart](https://elevenlabs.io/docs/eleven-api/quickstart) |
| Songstats | [core/songstats_client.py](core/songstats_client.py) | [Python SDK (GitHub)](https://github.com/Songstats/songstats-python-sdk/tree/main) |
| Spotify | [core/spotify_client.py](core/spotify_client.py), [core/spotify_pkce.py](core/spotify_pkce.py) | [Web API reference](https://developer.spotify.com/documentation/web-api) |
