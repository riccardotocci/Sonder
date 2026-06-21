# Sonder

> **Musical curation, literary analysis, and multilingual emotional storytelling platform** — Musicathon 2026.

Unlike traditional algorithms (Spotify/Apple Music) that rely primarily on acoustic metadata (BPM, genre), **Sonder** decodes the *deep poetic meaning* of lyrics alongside audio features, connecting tracks across different eras, genres, and languages under the same narrative thread (the shadow, redemption, human conflict).

---

## ✨ Features

- **Text Extraction & Analysis** — Retrieves original lyrics and identifies metaphors, slang, and complex psychological themes (powered by Musixmatch).
- **Multilingual Storytelling** — Generates short essays, micro-stories, and liner notes connecting tracks to emotional archetypes via advanced reasoning LLMs.
- **Audio Intelligence** — Integrates high-level semantic audio features and emotional profiling (powered by ReccoBeats).
- **Streaming Analytics** — Evaluates real-time track impact, popularity, and cross-platform streaming statistics (powered by Songstats).
- **Geographic Awareness** — Derives track and artist origins automatically to enrich the cultural context.
- **Dynamic Playlist Curation** — Automatically generates Spotify playlists driven by the "emotional vector" extracted from textual and audio analysis.
- **Immersive UX** — A minimal, dark Vite+React web interface, fully equipped for podcast-style audio narration (powered by ElevenLabs).

---

## 🧱 Tech Stack

| Layer | Technology |
|---|---|
| **Frontend / UI** | React, Vite |
| **Backend / API** | FastAPI (Python 3.10+) |
| **Catalog & Lyrics** | Musixmatch API |
| **Biographies & Media**| TheAudioDB API |
| **Reasoning Engine** | OpenAI-compatible LLMs (Gemma, Nemotron, Owl Alpha, GPT OSS 120B) |
| **Audio Features** | ReccoBeats API |
| **Streaming Stats** | Songstats API |
| **Voice Narration** | ElevenLabs TTS (Server-side generated MP3s) |
| **Music Automation** | Spotify API (Spotipy + PKCE) |

---

## 🔁 Data Flow

```text
[ Input: Song / Artist / Theme ]
            │
            ▼
[ Musixmatch ] ─► raw lyrics + track metadata
            │
            ▼
[ TheAudioDB ] ─► multilingual biography + artist photo
            │
            ▼
[ Songstats  ] ─► multi-platform streaming stats & track IDs
            │
            ▼
[ ReccoBeats ] ─► semantic audio features & mood profiling
            │
            ▼
[ LLM Thinking ] ─► decodes metaphors/slang, merges with bio & audio data,
                    generates psychological analysis + narrative script
            │
            ▼
[ ElevenLabs ] ─► TTS MP3 generation for narration mode
            │
            ▼
[ Spotify ] ─► generates/updates thematic playlist
            │
            ▼
[ React UI ] ─► displays story + lyrics + artist visuals + metrics + embedded player
```

---

## 📁 Project Structure

```
Sonder/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── pipeline.py          # Pure functions for business logic orchestration
│   ├── geocode.py           # Country extraction routing
│   └── geo_coords.py        # Geodesic translation layer
├── core/
│   ├── __init__.py          # Service clients initialization
│   ├── config.py            # Environment configuration
│   ├── storyteller.py       # LLM prompts & reasoning
│   ├── musixmatch_client.py # Musixmatch integration
│   ├── reccobeats_client.py # ReccoBeats audio intel
│   ├── songstats_client.py  # Songstats analytics
│   ├── spotify_client.py    # Spotify integration
│   ├── spotify_pkce.py      # Spotify Auth
│   ├── audiodb_client.py    # TheAudioDB integration
│   └── elevenlabs_client.py # ElevenLabs TTS
├── frontend/
│   ├── src/                 # React source code components
│   ├── vite.config.js       # Vite bundler configuration
│   └── package.json         # Frontend dependencies
├── app.py                   # Legacy Streamlit reference (deprecated)
├── requirements.txt         # Python dependencies
└── .env.example             # Environment variables template
```

*(Note: The app migrated from a monolithic Streamlit structure to a modern React + FastAPI architecture for enhanced scalability and interactive audio experiences. `app.py` is kept as a reference only.)*

---

## 🚀 Quick Start

### 1. Backend (FastAPI)
```bash
# Optional but recommended: create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure keys
cp .env.example .env      # open .env and add your API keys

# Start API server (port 8000)
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 2. Frontend (React / Vite)
```bash
cd frontend

# Install dependencies
npm install

# Start development server (port 5000)
npm run dev
```

> **Note:** The app features **graceful degradation** and can boot in "demo mode" even without API keys. Missing keys will trigger corresponding placeholder banners on the UI.

---

## 🔑 Required API Keys

| Variable | Source | Requirement |
|---|---|---|
| `MUSIXMATCH_API_KEY` | [Musixmatch Developer](https://developer.musixmatch.com/) | Required for Lyrics |
| `SPOTIFY_CLIENT_ID` | [Spotify Dashboard](https://developer.spotify.com/dashboard) | Required for Playlists & PKCE Auth |
| `LLM_API_KEY` | [OpenRouter](https://openrouter.ai/) / [OpenAI](https://platform.openai.com/) | Required for Analytics & Storytelling |
| `ELEVENLABS_API_KEY` / `_VOICE_ID` | [ElevenLabs](https://elevenlabs.io/) | Optional (Voice Narration) |
| `AUDIODB_API_KEY` | [TheAudioDB](https://www.theaudiodb.com/) | Optional (Bios & Images) |
| `RECCOBEATS_API_KEY` | [ReccoBeats](https://dashboard.reccobeats.com) | Optional (Audio analysis) |
| `SONGSTATS_API_KEY` | [Songstats](https://songstats.com/) | Optional (Stream stats) |

See `AGENTS.md` and `.env.example` for deeper configuration insight!
