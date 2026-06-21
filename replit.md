# Sonder

## Overview
Sonder turns songs into multilingual narrative
experiences. It orchestrates several music/AI services:
Musixmatch (lyrics) → TheAudioDB / MusicBrainz (artist data) →
an LLM "Thinking" engine (OpenRouter/OpenAI-compatible) → Spotify (playback via
per-user PKCE) → ElevenLabs (AI voice narration) → Songstats (streaming stats).

The app was migrated from a single Streamlit `app.py` to a **React (Vite)
frontend + FastAPI backend** with 1:1 visual/functional parity. The Python
service clients in `core/` are reused unchanged. The original `app.py` is kept
as a reference for the ported UI/orchestration.

The app runs without any API keys: each section gracefully enters "demo mode"
and indicates which environment variable to set.

## Architecture
- **Backend** — FastAPI on port 8000 (`backend/`), reuses `core/` clients.
  Orchestration logic from `app.py` is ported into `backend/pipeline.py`.
  In production it also serves the built frontend (`frontend/dist`) with an SPA
  fallback; in development the Vite dev server serves the UI.
- **Frontend** — Vite + React on port 5000 (webview). Proxies `/api/*` and
  `/static/*` to the backend at `localhost:8000` during development.
- **Studio** — rendered as an `<iframe srcDoc>` containing the ported
  `STUDIO_HTML` (the exact original markup/CSS/JS), with track data injected via
  the same placeholder substitution the original used.
- **Spotify** — PKCE auth runs in the browser; the token exchange/refresh is
  proxied through the backend.
- **TTS** — ElevenLabs narration audio is generated on-demand via `/api/tts`.

## Project Structure
- `backend/` — FastAPI app:
  - `main.py` — FastAPI app, endpoints (`/api/bootstrap`, `/api/chat`,
    `/api/tts`, `/api/spotify/{exchange,refresh,theme-recs}`, `/api/songstats`),
    static mounts + SPA fallback.
  - `pipeline.py` — orchestration helpers ported from `app.py` (chat handling,
    studio building, search pipeline, songstats) as pure functions.
  - `constants.py` — UI constants (languages, greetings, example prompts, etc.).
- `frontend/` — Vite React app:
  - `src/App.jsx` — top-level state (messages/studio/token/settings).
  - `src/api.js`, `src/spotify.js` — backend calls + browser PKCE flow.
  - `src/index.css` — ported `CUSTOM_CSS` theme.
  - `src/studio.html` — exact ported `STUDIO_HTML`, imported via `?raw`.
  - `src/components/` — `Sidebar`, `ChatLanding`, `Messages`, `Studio`,
    `StudioSections`, `Songstats`.
- `core/` — service clients and the storytelling engine (reused unchanged).
- `static/` — logos and static assets.
- `app.py` — original Streamlit app, kept for reference.

## Development
- Languages: Python 3.12, Node.js 20
- Backend deps: `requirements.txt`; Frontend deps: `frontend/package.json`
- Workflows:
  - `Backend API` — `uvicorn backend.main:app --host 0.0.0.0 --port 8000`
  - `Start application` — `cd frontend && npm run dev` (webview, port 5000)

## Configuration / Secrets
All API keys are optional and read from environment variables (see `.env.example`):
- `MUSIXMATCH_API_KEY`
- `MUSIXMATCH_USE_LYRICS` (default `true`), `MUSIXMATCH_USE_MEANING` (default
  `false`) — flag indipendenti per attivare/disattivare le due sorgenti di ricerca
  Musixmatch: query sui TESTI (lyrics) e ricerca per SIGNIFICATO
  (`track.lyrics.analysis.search`). Il meaning è OFF di default perché da solo
  tende a restituire sempre gli stessi brani popolari. Possono stare insieme o da
  sole; non toccano il piano dell'LLM né il check sui candidati.
- `AUDIODB_API_KEY` — TheAudioDB **v2 (Premium)** key, sent as the `X-API-KEY`
  header. The old free test key "123" is rejected by v2; without a Premium key the
  AudioDB section enters demo mode.
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `SONDER_TTS_MODE`
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`
- `SONGSTATS_API_KEY`

## Deployment
- Target: vm (Reserved VM) — required because a single `/api/chat` request runs a
  multi-step LLM pipeline (~75s end-to-end); Autoscale truncates such long requests.
- Build: `cd frontend && npm install && npm run build`
- Run: `uvicorn backend.main:app --host 0.0.0.0 --port 5000`
  (FastAPI serves the built React app from `frontend/dist`.)
- LLM model: use a reliable paid model (`openai/gpt-oss-120b`); OpenRouter `:free`
  variants frequently never return and leave chat hanging in production.

## User preferences
(none recorded yet)
