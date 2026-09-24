"""Amazon Polly text-to-speech backend."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from .backend import AbstractTTSBackend
from .models import SynthesisResult

_DEFAULT_VOICE = "Danielle"
_DEFAULT_REGION = "us-east-1"
_MAX_CHARS = 2800
_MIME_TO_POLLY = {
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg_vorbis",
    "audio/pcm": "pcm",
}


def split_text_for_polly(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Split text into sentence-oriented chunks accepted by Amazon Polly.

    Args:
        text: The source text to split.
        max_chars: Maximum number of characters in each chunk.

    Returns:
        Chunks in their original order, each no longer than ``max_chars``.

    Raises:
        ValueError: If ``max_chars`` is not positive.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text.strip()) if sentence.strip()]
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        while len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:max_chars])
            sentence = sentence[max_chars:]

        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)
    return chunks


class AmazonPollyTTSBackend(AbstractTTSBackend):
    """TTS backend over Amazon Polly using aioboto3."""

    def __init__(
        self,
        voice: Optional[str] = None,
        *,
        engine: str = "long-form",
        region: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the backend without making network calls.

        Args:
            voice: Default Amazon Polly voice identifier.
            engine: Polly engine to use for synthesis.
            region: AWS region, falling back to ``AWS_POLLY_REGION``.
            **kwargs: Additional aioboto3 session keyword arguments.
        """
        self._default_voice = voice or _DEFAULT_VOICE
        self._engine = engine
        self._region = region or os.getenv("AWS_POLLY_REGION") or _DEFAULT_REGION
        self._session_kwargs = kwargs
        self._session: Any = None
        self.logger = logging.getLogger(__name__)

    def _get_session(self) -> Any:
        """Lazily create the aioboto3 session required for Polly calls."""
        if self._session is None:
            try:
                import aioboto3
            except ImportError as exc:
                raise ImportError("Amazon Polly support requires ai-parrot-integrations[voice-polly]") from exc
            self._session = aioboto3.Session(**self._session_kwargs)
        return self._session

    @staticmethod
    def _error_code(error: Exception) -> str:
        """Return an AWS error code when one is present on an exception."""
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            details = response.get("Error", {})
            if isinstance(details, dict) and details.get("Code"):
                return str(details["Code"])
        return error.__class__.__name__

    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        mime_format: str = "audio/mpeg",
        language: Optional[str] = None,
    ) -> SynthesisResult:
        """Synthesize text sequentially through Amazon Polly.

        Args:
            text: Text to synthesize.
            voice: Optional Polly voice override.
            mime_format: Requested supported output MIME type.
            language: Optional BCP-47 language code for Polly.

        Returns:
            Concatenated audio output from every Polly chunk.

        Raises:
            ValueError: If text is empty or the MIME type is unsupported.
            ImportError: If the optional Polly dependency is not installed.
            RuntimeError: If Polly rejects or fails a synthesis request.
        """
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        if mime_format not in _MIME_TO_POLLY:
            raise ValueError(f"Unsupported Amazon Polly MIME format: {mime_format}")

        chunks = split_text_for_polly(text)
        request: dict[str, str] = {
            "OutputFormat": _MIME_TO_POLLY[mime_format],
            "VoiceId": voice or self._default_voice,
            "Engine": self._engine,
        }
        if language is not None:
            request["LanguageCode"] = language

        self.logger.debug("AmazonPollyTTSBackend: synthesizing %d chunks in %s", len(chunks), self._region)
        audio_parts: list[bytes] = []
        try:
            session = self._get_session()
            async with session.client("polly", region_name=self._region) as client:
                for chunk in chunks:
                    response = await client.synthesize_speech(Text=chunk, **request)
                    audio_parts.append(await response["AudioStream"].read())
        except ImportError:
            raise
        except Exception as exc:
            code = self._error_code(exc)
            raise RuntimeError(f"Amazon Polly synthesis failed ({code}): {exc}") from exc

        return SynthesisResult(audio=b"".join(audio_parts), mime_format=mime_format)

    async def close(self) -> None:
        """Release the lazily created aioboto3 session reference."""
        self._session = None
