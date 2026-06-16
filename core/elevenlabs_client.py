"""ElevenLabs Text-to-Speech client.

Generates MP3 audio bytes for narration speeches using the ElevenLabs API.
Falls back gracefully when the API key is not configured.
"""
from __future__ import annotations

import base64
import logging

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

    def _client(self):
        """Build an official ElevenLabs SDK client (lazy import for graceful degradation)."""
        if not settings.elevenlabs_ready:
            raise ElevenLabsError("ELEVENLABS_API_KEY not configured.")
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ElevenLabsError(
                "elevenlabs SDK not installed. Run: pip install elevenlabs"
            ) from exc
        return ElevenLabs(api_key=settings.elevenlabs_api_key)

    @staticmethod
    def _voice_settings():
        try:
            from elevenlabs import VoiceSettings

            return VoiceSettings(stability=0.50, similarity_boost=0.75)
        except Exception:  # pragma: no cover - optional, falls back to API defaults
            return None

    def text_to_speech(
        self,
        text: str,
        voice_id: str | None = None,
        model_id: str | None = None,
        output_format: str | None = None,
    ) -> bytes:
        """Return MP3 audio bytes for *text* using the official ElevenLabs SDK.

        Raises ElevenLabsError on any API or network failure.
        """
        vid = voice_id or settings.elevenlabs_voice_id or self.DEFAULT_VOICE
        mid = model_id or self.DEFAULT_MODEL
        out = output_format or self.DEFAULT_OUTPUT_FORMAT
        client = self._client()

        try:
            logger.warning(
                "ElevenLabs TTS voice=%s model=%s output=%s text_chars=%s",
                vid, mid, out, len(text),
            )
            stream = client.text_to_speech.convert(
                voice_id=vid,
                text=text,
                model_id=mid,
                output_format=out,
                voice_settings=self._voice_settings(),
            )
            audio = b"".join(stream)
        except ElevenLabsError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any SDK/network failure uniformly
            logger.warning("ElevenLabs TTS error: %s", exc)
            raise ElevenLabsError(f"ElevenLabs TTS failed: {exc}") from exc

        if not audio:
            raise ElevenLabsError("ElevenLabs returned empty audio.")
        logger.warning("ElevenLabs TTS ok bytes=%s", len(audio))
        return audio

    def text_to_speech_with_marks(
        self,
        text: str,
        voice_id: str | None = None,
        model_id: str | None = None,
        output_format: str | None = None,
    ) -> tuple[bytes, list[dict]]:
        """Return ``(mp3_bytes, word_marks)`` for *text* in a single API call.

        ``word_marks`` is an ordered list of ``{"w", "s", "e", "c0"}`` dicts where
        ``s``/``e`` are the word start/end in seconds and ``c0`` is the word's
        character offset within *text*. Audio and marks come from the same
        ``convert_with_timestamps`` rendition, so the karaoke captions stay in sync.
        """
        vid = voice_id or settings.elevenlabs_voice_id or self.DEFAULT_VOICE
        mid = model_id or self.DEFAULT_MODEL
        out = output_format or self.DEFAULT_OUTPUT_FORMAT
        client = self._client()

        try:
            logger.warning(
                "ElevenLabs TTS+timestamps voice=%s model=%s text_chars=%s",
                vid, mid, len(text),
            )
            resp = client.text_to_speech.convert_with_timestamps(
                voice_id=vid,
                text=text,
                model_id=mid,
                output_format=out,
                voice_settings=self._voice_settings(),
            )
        except ElevenLabsError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ElevenLabs TTS+timestamps error: %s", exc)
            raise ElevenLabsError(f"ElevenLabs timestamps failed: {exc}") from exc

        audio_b64 = self._extract_attr(resp, "audio_base_64", "audio_base64")
        if not audio_b64:
            raise ElevenLabsError("ElevenLabs returned no audio.")
        try:
            audio = base64.b64decode(audio_b64)
        except Exception as exc:  # noqa: BLE001
            raise ElevenLabsError(f"Invalid ElevenLabs audio payload: {exc}") from exc

        marks = self._marks_from_alignment(getattr(resp, "alignment", None))
        logger.warning(
            "ElevenLabs TTS+timestamps ok bytes=%s words=%s", len(audio), len(marks)
        )
        return audio, marks

    @staticmethod
    def _extract_attr(obj, *names: str) -> str:
        for name in names:
            value = getattr(obj, name, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _marks_from_alignment(alignment) -> list[dict]:
        """Group per-character alignment into per-word timing marks."""
        if alignment is None:
            return []
        characters = list(getattr(alignment, "characters", None) or [])
        starts = list(getattr(alignment, "character_start_times_seconds", None) or [])
        ends = list(getattr(alignment, "character_end_times_seconds", None) or [])
        count = min(len(characters), len(starts), len(ends))
        marks: list[dict] = []
        word: list[str] = []
        word_start = 0.0
        word_end = 0.0
        word_c0 = 0
        for i in range(count):
            char = characters[i] or ""
            if char.strip() == "":  # whitespace -> word boundary
                if word:
                    marks.append({
                        "w": "".join(word),
                        "s": round(word_start, 3),
                        "e": round(word_end, 3),
                        "c0": word_c0,
                    })
                    word = []
                continue
            if not word:
                word_start = float(starts[i])
                word_c0 = i
            word.append(char)
            word_end = float(ends[i])
        if word:
            marks.append({
                "w": "".join(word),
                "s": round(word_start, 3),
                "e": round(word_end, 3),
                "c0": word_c0,
            })
        return marks
