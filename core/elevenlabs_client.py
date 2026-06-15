"""ElevenLabs Text-to-Speech client.

Generates MP3 audio bytes for narration speeches using the ElevenLabs API.
Falls back gracefully when the API key is not configured.
"""
from __future__ import annotations

import logging

import requests

from core.config import settings


logger = logging.getLogger("sonder.elevenlabs")


class ElevenLabsError(Exception):
    pass


class ElevenLabsClient:
    """Client for the ElevenLabs v1 Text-to-Speech API."""

    BASE_URL = "https://api.elevenlabs.io/v1"
    DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # George — warm, narrative
    DEFAULT_MODEL = "eleven_multilingual_v2"
    DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

    def text_to_speech(
        self,
        text: str,
        voice_id: str | None = None,
        model_id: str | None = None,
        output_format: str | None = None,
    ) -> bytes:
        """Return MP3 audio bytes for *text*.

        Raises ElevenLabsError on any API or network failure.
        """
        if not settings.elevenlabs_ready:
            raise ElevenLabsError("ELEVENLABS_API_KEY not configured.")

        vid = voice_id or settings.elevenlabs_voice_id or self.DEFAULT_VOICE
        mid = model_id or self.DEFAULT_MODEL
        out = output_format or self.DEFAULT_OUTPUT_FORMAT
        url = f"{self.BASE_URL}/text-to-speech/{vid}"

        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": mid,
            "voice_settings": {
                "stability": 0.50,
                "similarity_boost": 0.75,
            },
        }

        try:
            logger.warning(
                "ElevenLabs POST voice=%s model=%s output=%s text_chars=%s",
                vid,
                mid,
                out,
                len(text),
            )
            r = requests.post(
                url,
                headers=headers,
                params={"output_format": out},
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.warning("ElevenLabs network error: %s", exc)
            raise ElevenLabsError(f"Network error: {exc}") from exc

        if not r.ok:
            logger.warning("ElevenLabs response error status=%s body=%s", r.status_code, r.text[:160])
            raise ElevenLabsError(
                f"ElevenLabs API {r.status_code}: {r.text[:300]}"
            )

        logger.warning("ElevenLabs response ok status=%s bytes=%s", r.status_code, len(r.content))
        return r.content
