"""Local on-demand TTS endpoint for the Streamlit studio component."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from core.config import settings
from core.elevenlabs_client import ElevenLabsClient, ElevenLabsError


class TTSServerError(RuntimeError):
    """Raised when the local TTS endpoint cannot be started."""


@dataclass
class TTSServerInfo:
    endpoint: str
    token: str


@dataclass
class _TTSServerState:
    host: str = "127.0.0.1"
    port: int = 0
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    cache: dict[str, bytes] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_STATE = _TTSServerState()
_MAX_TEXT_CHARS = 3500
_MAX_BODY_BYTES = 64_000


def _audio_cache_key(text: str) -> str:
    voice_id = settings.elevenlabs_voice_id or ElevenLabsClient.DEFAULT_VOICE
    payload = {
        "voice_id": voice_id,
        "model_id": ElevenLabsClient.DEFAULT_MODEL,
        "output_format": ElevenLabsClient.DEFAULT_OUTPUT_FORMAT,
        "text": text,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    _set_cors_headers(handler)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _set_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin") or "*"
    handler.send_header("Access-Control-Allow-Origin", origin)
    handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sonder-TTS-Token")


class _TTSRequestHandler(BaseHTTPRequestHandler):
    server_version = "SonderTTS/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        _set_cors_headers(self)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/tts":
            _json_response(self, 404, {"error": "not_found"})
            return
        if self.headers.get("X-Sonder-TTS-Token") != _STATE.token:
            _json_response(self, 403, {"error": "forbidden"})
            return
        if not settings.elevenlabs_ready:
            _json_response(self, 503, {"error": "elevenlabs_not_configured"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > _MAX_BODY_BYTES:
            _json_response(self, 413, {"error": "invalid_body_size"})
            return

        try:
            data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _json_response(self, 400, {"error": "invalid_json"})
            return

        text = str(data.get("text", "")).strip()
        if not text:
            _json_response(self, 400, {"error": "missing_text"})
            return
        text = text[:_MAX_TEXT_CHARS]
        cache_key = _audio_cache_key(text)

        with _STATE.lock:
            audio = _STATE.cache.get(cache_key)
        cache_hit = audio is not None

        if audio is None:
            try:
                audio = ElevenLabsClient().text_to_speech(text)
            except ElevenLabsError as exc:
                _json_response(self, 502, {"error": str(exc)})
                return
            with _STATE.lock:
                _STATE.cache[cache_key] = audio

        self.send_response(200)
        _set_cors_headers(self)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.send_header("X-Sonder-TTS-Cache", "hit" if cache_hit else "miss")
        self.end_headers()
        self.wfile.write(audio)


def ensure_tts_server() -> TTSServerInfo:
    """Start the local TTS endpoint once and return browser connection details."""
    if not settings.elevenlabs_ready:
        raise TTSServerError("ELEVENLABS_API_KEY not configured.")

    with _STATE.lock:
        if _STATE.server and _STATE.thread and _STATE.thread.is_alive():
            return TTSServerInfo(
                endpoint=f"http://{_STATE.host}:{_STATE.port}/tts",
                token=_STATE.token,
            )

        host = os.getenv("SONDER_TTS_HOST", "127.0.0.1").strip() or "127.0.0.1"
        try:
            base_port = int(os.getenv("SONDER_TTS_PORT", "8765"))
        except ValueError:
            base_port = 8765

        last_error: OSError | None = None
        for port in range(base_port, base_port + 25):
            try:
                server = ThreadingHTTPServer((host, port), _TTSRequestHandler)
                break
            except OSError as exc:
                last_error = exc
        else:
            raise TTSServerError(f"Could not start local TTS server: {last_error}")

        thread = threading.Thread(target=server.serve_forever, name="sonder-tts", daemon=True)
        thread.start()
        _STATE.host = host
        _STATE.port = port
        _STATE.server = server
        _STATE.thread = thread

        return TTSServerInfo(endpoint=f"http://{host}:{port}/tts", token=_STATE.token)