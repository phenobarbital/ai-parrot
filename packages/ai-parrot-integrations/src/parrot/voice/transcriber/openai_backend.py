"""
OpenAI Whisper Backend for Voice Transcription.

Cloud-based transcription backend using OpenAI's Whisper API.
This provides an alternative to local GPU transcription for environments
without GPU access or for simpler deployment.

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, Optional

import aiohttp

from .backend import AbstractTranscriberBackend
from .models import TranscriptionResult

# Per-model response_format; models not listed use "json" (gpt-transcribe rejects verbose_json).
_RESPONSE_FORMATS: Dict[str, str] = {"whisper-1": "verbose_json"}

# Whisper verbose_json returns the language NAME; map it to ISO 639-1.
_LANGUAGE_NAMES: Dict[str, str] = {
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "dutch": "nl",
    "russian": "ru",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "arabic": "ar",
    "hindi": "hi",
    "turkish": "tr",
    "polish": "pl",
    "ukrainian": "uk",
    "catalan": "ca",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "finnish": "fi",
    "greek": "el",
    "hebrew": "he",
    "czech": "cs",
    "romanian": "ro",
}


class OpenAIWhisperBackend(AbstractTranscriberBackend):
    """
    Cloud-based transcription using OpenAI Whisper API.

    Requires an OpenAI API key. Supports automatic retry
    with exponential backoff for rate limits.

    Args:
        api_key: OpenAI API key (required).
        model: Whisper model to use. Default: "whisper-1".
        max_retries: Maximum number of retry attempts for rate limits.
            Default: 3.
        timeout_seconds: Request timeout in seconds. Default: 60.

    Example::

        backend = OpenAIWhisperBackend(api_key="sk-...")
        try:
            result = await backend.transcribe(Path("/path/to/audio.ogg"))
            print(f"Transcription: {result.text}")
        finally:
            await backend.close()  # Release HTTP session

    Raises:
        ValueError: If api_key is empty or None.
    """

    API_URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-transcribe",
        max_retries: int = 3,
        timeout_seconds: int = 60,
    ):
        """Initialize the OpenAI Whisper backend."""
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

    async def _get_session(self) -> aiohttp.ClientSession:
        """
        Get or create aiohttp session.

        Creates a new session if none exists or if the existing one is closed.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    def _get_content_type(self, audio_path: Path) -> str:
        """
        Get MIME content type based on file extension.

        Args:
            audio_path: Path to the audio file.

        Returns:
            MIME type string.
        """
        extension = audio_path.suffix.lower()
        content_types = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".m4a": "audio/m4a",
            ".webm": "audio/webm",
            ".flac": "audio/flac",
        }
        return content_types.get(extension, "audio/wav")

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file to text using OpenAI Whisper API.

        Args:
            audio_path: Path to the audio file to transcribe.
                Supported formats: WAV, MP3, OGG, M4A, WebM, FLAC.
            language: Optional language hint (ISO 639-1 code, e.g., "en", "es").
                If None, the language is auto-detected by OpenAI.

        Returns:
            TranscriptionResult containing the transcribed text, detected
            language, audio duration, and processing time.

        Raises:
            FileNotFoundError: If the audio file does not exist.
            RuntimeError: If transcription fails after all retries.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        start_time = time.perf_counter()
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                result = await self._transcribe_attempt(
                    audio_path, language, start_time
                )
                return result
            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    # Rate limited - retry with exponential backoff
                    wait_time = 2 ** attempt
                    self.logger.warning(
                        "Rate limited by OpenAI API, retrying in %ds (attempt %d/%d)",
                        wait_time,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                elif e.status == 401:
                    raise RuntimeError(
                        "OpenAI API authentication failed. Check your API key."
                    ) from e
                else:
                    raise RuntimeError(
                        f"OpenAI API error ({e.status}): {e.message}"
                    ) from e
            except aiohttp.ClientError as e:
                # Network error - retry with backoff
                wait_time = 2 ** attempt
                self.logger.warning(
                    "Request failed: %s, retrying in %ds (attempt %d/%d)",
                    str(e),
                    wait_time,
                    attempt + 1,
                    self.max_retries,
                )
                await asyncio.sleep(wait_time)
                last_error = e

        raise RuntimeError(
            f"Transcription failed after {self.max_retries} attempts: {last_error}"
        )

    async def _transcribe_attempt(
        self,
        audio_path: Path,
        language: Optional[str],
        start_time: float,
    ) -> TranscriptionResult:
        """
        Single transcription attempt.

        Args:
            audio_path: Path to the audio file.
            language: Optional language hint.
            start_time: Start time for processing duration calculation.

        Returns:
            TranscriptionResult on success.

        Raises:
            aiohttp.ClientResponseError: On HTTP errors.
            aiohttp.ClientError: On network errors.
        """
        session = await self._get_session()

        # Read file content first to avoid keeping file open during request
        content_type = self._get_content_type(audio_path)
        file_content = audio_path.read_bytes()

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            "file",
            file_content,
            filename=audio_path.name,
            content_type=content_type,
        )
        data.add_field("model", self.model)
        data.add_field("response_format", _RESPONSE_FORMATS.get(self.model, "json"))

        if language:
            data.add_field("language", language)

        headers = {"Authorization": f"Bearer {self.api_key}"}

        self.logger.debug(
            "Sending transcription request to OpenAI API for: %s",
            audio_path.name,
        )

        async with session.post(
            self.API_URL,
            data=data,
            headers=headers,
        ) as response:
            if response.status == 200:
                result_json = await response.json()
                processing_time_ms = int(
                    (time.perf_counter() - start_time) * 1000
                )

                self.logger.debug(
                    "Transcription completed: %d chars in %dms",
                    len(result_json.get("text", "")),
                    processing_time_ms,
                )

                text, lang, duration = self._parse_result(self.model, result_json, language)
                return TranscriptionResult(
                    text=text,
                    language=lang,
                    duration_seconds=duration,
                    confidence=None,  # OpenAI API doesn't return confidence
                    processing_time_ms=processing_time_ms,
                )
            else:
                error_text = await response.text()
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=response.status,
                    message=error_text,
                )

    async def close(self) -> None:
        """
        Close the aiohttp session.

        This method should be called when the backend is no longer needed
        to properly release HTTP connection resources.
        """
        if self._session is not None and not self._session.closed:
            self.logger.debug("Closing OpenAI Whisper backend HTTP session")
            await self._session.close()
            self._session = None

    @staticmethod
    def _parse_result(model: str, payload: dict, language_hint: Optional[str]) -> tuple[str, str, float]:
        """Return (text, iso_language, duration_seconds).

        Handles whisper ``verbose_json`` (language name, ``duration``) and
        gpt-transcribe ``json`` (``languages[0].code``, ``usage.seconds``).

        Args:
            model: Model name used for the request.
            payload: Decoded JSON response.
            language_hint: Language requested by the caller, if any.

        Returns:
            Tuple of text, ISO 639-1 language code and duration in seconds.
        """
        text = payload.get("text", "") or ""

        raw_lang = None
        languages = payload.get("languages")
        if isinstance(languages, list) and languages and isinstance(languages[0], dict):
            raw_lang = languages[0].get("code")
        if not raw_lang:
            raw_lang = payload.get("language")
        lang = None
        if isinstance(raw_lang, str) and raw_lang.strip():
            norm = raw_lang.strip().lower()
            lang = _LANGUAGE_NAMES.get(norm) or (norm[:2] if len(norm) <= 5 else None)
        if not lang and language_hint:
            lang = language_hint.strip().lower()[:2]
        if not lang:
            lang = "en"

        duration = payload.get("duration")
        if duration is None:
            usage = payload.get("usage")
            if isinstance(usage, dict):
                duration = usage.get("seconds")
        try:
            duration_f = float(duration) if duration is not None else 0.0
        except (TypeError, ValueError):
            duration_f = 0.0
        return text, lang, duration_f
