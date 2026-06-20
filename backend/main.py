"""Sonder FastAPI backend.

Replaces the Streamlit ``app.py`` server. Reuses the Python ``core/`` clients and
the orchestration pipeline (``backend/pipeline.py``). Serves the built React
frontend (``frontend/dist``) in production; in development the Vite dev server
proxies ``/api/*`` here.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import settings
from core.config import SEARCH_LANGUAGE_OPTIONS, LLM_MODEL_OPTIONS, DEFAULT_LLM_MODEL
from core import spotify_pkce

from . import pipeline
from .constants import (
    LANGUAGES,
    TTS_LANG,
    GREETINGS,
    EXAMPLE_PROMPTS,
    PALETTE,
)

app = FastAPI(title="Sonder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
FRONTEND_DIST = ROOT / "frontend" / "dist"


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = []
    prompt: str
    search_languages: list[str] = []
    llm_model: str = ""
    spotify_token: str = ""
    # UI language key (LANGUAGES dict key, e.g. "Italiano"). It forces the
    # narration AND the Musixmatch translations into that language, even when the
    # user writes in a different language. Auto mode no longer exists; unknown
    # values fall back to English.
    language: str = "English"


class NarrateRequest(BaseModel):
    # Fase 2: i brani arrivano gia' arricchiti dalla fase 1 (/api/chat). Qui si
    # genera solo il testo narrato (la chiamata LLM lenta studio_brief).
    prompt: str = ""
    tracks: list[dict[str, Any]] = []
    language: str = "English"
    llm_model: str = ""


class TTSRequest(BaseModel):
    text: str


class SpotifyExchangeRequest(BaseModel):
    code: str
    redirect_uri: str
    code_verifier: str


class SpotifyRefreshRequest(BaseModel):
    refresh_token: str


class ThemeRecsRequest(BaseModel):
    spotify_token: str
    language: str = "English"
    llm_model: str = ""


class SongstatsRequest(BaseModel):
    tracks: list[dict[str, Any]] = []
    spotify_token: str = ""


class AudioFeaturesRequest(BaseModel):
    tracks: list[dict[str, Any]] = []
    spotify_token: str = ""


class CreatePlaylistRequest(BaseModel):
    tracks: list[dict[str, Any]] = []
    name: str = "Conversation"
    spotify_token: str = ""


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def _llm_model_values() -> list[str]:
    values = [value for _, value in LLM_MODEL_OPTIONS]
    if settings.llm_model and settings.llm_model not in values:
        values.insert(0, settings.llm_model)
    return values


@app.get("/api/bootstrap")
def bootstrap(lang: str = "English") -> dict:
    """Status flags + UI constants + greeting, surfaced to the React frontend.

    ``lang`` is the LANGUAGES/GREETINGS key (e.g. "Italiano", "日本語"); it
    localizes the greeting and example prompts. Unknown values fall back to
    English.
    """
    greeting = GREETINGS.get(lang, GREETINGS["English"])
    prompts = EXAMPLE_PROMPTS.get(lang, EXAMPLE_PROMPTS["English"])
    status = {
        "Musixmatch": settings.musixmatch_ready,
        "TheAudioDB": settings.audiodb_ready,
        "ElevenLabs TTS": settings.elevenlabs_ready,
        "Spotify": settings.spotify_pkce_ready,
        "Songstats": settings.songstats_ready,
    }
    llm_models = [
        {"value": value, "label": label} for label, value in LLM_MODEL_OPTIONS
    ]
    if settings.llm_model and settings.llm_model not in [m["value"] for m in llm_models]:
        llm_models.insert(0, {"value": settings.llm_model, "label": "Configured in .env"})

    return {
        "status": status,
        "greeting": greeting,
        "example_prompts": [
            {"icon": icon, "text": text} for icon, text in prompts[:3]
        ],
        "llm_models": llm_models,
        "selected_llm_model": settings.llm_model or DEFAULT_LLM_MODEL,
        "search_languages": [
            {"label": label, "code": code} for label, code in SEARCH_LANGUAGE_OPTIONS
        ],
        "palette": PALETTE,
        "tts_lang": TTS_LANG,
        "spotify": {
            "client_id": settings.spotify_client_id,
            "redirect_uri": settings.spotify_redirect_uri,
            "pkce_ready": settings.spotify_pkce_ready,
            "scopes": spotify_pkce.SCOPES,
            "auth_url": spotify_pkce.AUTH_URL,
        },
        "narration_note": "🌍 Narration & translations follow the selected interface language.",
    }


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    # Auto mode removed: any unknown/legacy language falls back to English (never
    # the song's language), and a concrete UI language always wins.
    lang_name, lang_code = LANGUAGES.get(req.language, LANGUAGES["English"])
    # Fase 1: tracce + dati dei servizi, SENZA la narrazione (chiamata LLM lenta),
    # cosi' lo Studio si carica subito. Il testo narrato arriva con /api/narrate.
    result = pipeline.run_chat(
        messages=req.messages,
        prompt=req.prompt,
        lang_name=lang_name,
        lang_code=lang_code,
        search_languages=req.search_languages or None,
        llm_model=req.llm_model,
        user_token=req.spotify_token,
        with_narration=False,
    )
    user_message = {"role": "user", "content": req.prompt}
    return {
        "user_message": user_message,
        "assistant_message": result["assistant"],
        "studio": result["studio"],
        "tts_lang": TTS_LANG.get(lang_name, ""),
    }


@app.post("/api/narrate")
def narrate(req: NarrateRequest) -> dict:
    # Fase 2: genera i testi narrati per i brani gia' arricchiti dalla fase 1.
    lang_name, _ = LANGUAGES.get(req.language, LANGUAGES["English"])
    speeches = pipeline.generate_narration_speeches(
        req.prompt, req.tracks, lang_name, llm_model=req.llm_model
    )
    return {"speeches": speeches}


# --------------------------------------------------------------------------- #
# TTS (ElevenLabs narration, on-demand)
# --------------------------------------------------------------------------- #
@app.post("/api/tts")
def tts(req: TTSRequest) -> dict:
    return pipeline.generate_tts(req.text)


# --------------------------------------------------------------------------- #
# Spotify PKCE proxy
# --------------------------------------------------------------------------- #
@app.post("/api/spotify/exchange")
def spotify_exchange(req: SpotifyExchangeRequest) -> JSONResponse:
    try:
        data = spotify_pkce.exchange_code(
            client_id=settings.spotify_client_id,
            redirect_uri=req.redirect_uri,
            code=req.code,
            verifier=req.code_verifier,
        )
    except spotify_pkce.SpotifyPKCEError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(content=data)


@app.post("/api/spotify/refresh")
def spotify_refresh(req: SpotifyRefreshRequest) -> JSONResponse:
    try:
        data = spotify_pkce.refresh_access_token(
            client_id=settings.spotify_client_id,
            refresh_token=req.refresh_token,
        )
    except spotify_pkce.SpotifyPKCEError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(content=data)


@app.post("/api/spotify/theme-recs")
def spotify_theme_recs(req: ThemeRecsRequest) -> dict:
    return pipeline.get_spotify_theme_recs(
        lang_name=req.language or "English",
        user_token=req.spotify_token,
        llm_model=req.llm_model,
    )


@app.post("/api/spotify/create-playlist")
def spotify_create_playlist(req: CreatePlaylistRequest) -> dict:
    return pipeline.create_spotify_playlist(
        tracks=req.tracks,
        name=req.name or "Conversation",
        user_token=req.spotify_token,
    )


# --------------------------------------------------------------------------- #
# Songstats (streaming stats per resolved track)
# --------------------------------------------------------------------------- #
@app.post("/api/songstats")
def songstats(req: SongstatsRequest) -> dict:
    if not settings.songstats_ready:
        return {"available": False, "reason": "no_key", "rows": []}
    user_token = req.spotify_token
    if not (user_token or settings.spotify_ready):
        return {"available": False, "reason": "no_spotify", "rows": []}

    tracks = req.tracks or []
    if not tracks:
        return {"available": True, "rows": []}

    def get_stats(t: dict) -> Optional[dict]:
        return t.get("songstats") or pipeline._songstats_track_stats(
            t.get("title", ""), t.get("artist", ""), user_token
        )

    with ThreadPoolExecutor(max_workers=min(8, len(tracks))) as executor:
        stats_list = list(executor.map(get_stats, tracks))

    rows = []
    for t, stats in zip(tracks, stats_list):
        if not stats:
            continue
        rows.append(
            {
                "label": f'{t.get("title", "")} — {t.get("artist", "")}',
                "total_streams": int(stats.get("total_streams", 0) or 0),
                "headline": stats.get("headline") or [],
            }
        )
    return {"available": True, "rows": rows}


# --------------------------------------------------------------------------- #
# ReccoBeats (audio features per resolved track) — gratuito, senza key, ma
# richiede l'ISRC risolto da Spotify.
# --------------------------------------------------------------------------- #
@app.post("/api/audio-features")
def audio_features(req: AudioFeaturesRequest) -> dict:
    user_token = req.spotify_token
    # ReccoBeats non richiede key, ma l'ISRC arriva da Spotify: senza auth Spotify
    # non possiamo risolvere le tracce.
    if not (user_token or settings.spotify_ready):
        return {"available": False, "reason": "no_spotify", "rows": []}

    tracks = req.tracks or []
    if not tracks:
        return {"available": True, "rows": []}

    def get_features(t: dict) -> Optional[dict]:
        try:
            return t.get("audio_features") or pipeline._reccobeats_features(
                t.get("title", ""), t.get("artist", ""), user_token
            )
        except Exception:  # noqa: BLE001 - degrada in silenzio per singola traccia
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(tracks))) as executor:
        features_list = list(executor.map(get_features, tracks))

    rows = []
    for t, feats in zip(tracks, features_list):
        if not feats:
            continue
        rows.append(
            {
                "label": f'{t.get("title", "")} — {t.get("artist", "")}',
                "valence": feats.get("valence"),
                "energy": feats.get("energy"),
                "mood": feats.get("mood"),
                "features": feats,
            }
        )
    return {"available": True, "rows": rows}


# --------------------------------------------------------------------------- #
# Static assets + SPA fallback
# --------------------------------------------------------------------------- #
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if FRONTEND_DIST.exists():
    app.mount(
        "/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets"
    )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIST / "index.html"))

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
