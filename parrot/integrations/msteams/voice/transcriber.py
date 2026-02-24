"""
Voice Transcriber Service.

Main service that orchestrates voice transcription. Selects the appropriate
backend based on configuration, handles audio downloads from URLs,
manages temp files, and provides the unified interface used by
MSTeamsAgentWrapper.

Part of FEAT-008: MS Teams Voice Note Support.
"""
import logging
import tempfile
from pathlib import Path
from typing import Optional

import aiohttp

from .backend import AbstractTranscriberBackend
from .faster_whisper_backend import FasterWhisperBackend
from .models import (
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriberConfig,
)
from .openai_backend import OpenAIWhisperBackend


class VoiceTranscriber:
    """
    Voice transcription service.

    Manages transcription backend lifecycle and provides
    a unified interface for transcribing audio files and URLs.

    The backend is lazily created on first use. Use `close()` to
    release backend resources when done.

    Args:
        config: Configuration for the transcriber, including backend
            selection, model size, language, and duration limits.

    Example::

        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.FASTER_WHISPER,
            model_size="small",
            max_audio_duration_seconds=60,
        )
        transcriber = VoiceTranscriber(config)
        try:
            result = await transcriber.transcribe_url(
                url="https://teams.microsoft.com/files/voice.ogg",
                auth_token="Bearer xyz"
            )
            print(f"Transcription: {result.text}")
        finally:
            await transcriber.close()
    """

    SUPPORTED_FORMATS = {".ogg", ".mp3", ".wav", ".m4a", ".webm", ".mp4", ".flac"}

    def __init__(self, config: VoiceTranscriberConfig):
        """Initialize the voice transcriber service."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._backend: Optional[AbstractTranscriberBackend] = None

    def _get_backend(self) -> AbstractTranscriberBackend:
        """
        Get or create the transcription backend.

        Lazily creates the backend on first call based on configuration.

        Returns:
            The transcription backend instance.

        Raises:
            ValueError: If OpenAI backend selected but no API key provided,
                or if an unknown backend type is specified.
        """
        if self._backend is None:
            if self.config.backend == TranscriberBackend.FASTER_WHISPER:
                self.logger.info(
                    "Creating FasterWhisperBackend with model_size=%s",
                    self.config.model_size,
                )
                self._backend = FasterWhisperBackend(
                    model_size=self.config.model_size,
                )
            elif self.config.backend == TranscriberBackend.OPENAI_WHISPER:
                if not self.config.openai_api_key:
                    raise ValueError(
                        "OpenAI API key required for openai_whisper backend"
                    )
                self.logger.info("Creating OpenAIWhisperBackend")
                self._backend = OpenAIWhisperBackend(
                    api_key=self.config.openai_api_key,
                )
            else:
                raise ValueError(f"Unknown backend: {self.config.backend}")

        return self._backend

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe a local audio file.

        Args:
            file_path: Path to the audio file to transcribe.
            language: Optional language hint (ISO 639-1 code).
                If None, uses config language or auto-detection.

        Returns:
            TranscriptionResult containing transcribed text and metadata.

        Raises:
            FileNotFoundError: If the audio file doesn't exist.
            ValueError: If audio duration exceeds the configured limit.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        # Check duration before transcribing
        duration = self._get_audio_duration(file_path)
        if duration > self.config.max_audio_duration_seconds:
            raise ValueError(
                f"Audio duration ({duration:.1f}s) exceeds limit "
                f"({self.config.max_audio_duration_seconds}s)"
            )

        self.logger.debug(
            "Transcribing file: %s (duration: %.1fs)",
            file_path.name,
            duration,
        )

        backend = self._get_backend()
        return await backend.transcribe(
            file_path,
            language=language or self.config.language,
        )

    async def transcribe_url(
        self,
        url: str,
        auth_token: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Download and transcribe audio from URL.

        Downloads the audio to a temporary file, transcribes it,
        and cleans up the temp file afterwards.

        Args:
            url: URL to download the audio from.
            auth_token: Optional authorization token for the download request.
                Passed as Bearer token in Authorization header.
            language: Optional language hint for transcription.

        Returns:
            TranscriptionResult containing transcribed text and metadata.

        Raises:
            RuntimeError: If the download fails.
            ValueError: If the audio duration exceeds the configured limit.
        """
        self.logger.debug("Downloading audio from URL: %s", url[:100])

        # Download to temp file
        temp_path = await self._download_audio(url, auth_token)

        try:
            return await self.transcribe_file(temp_path, language=language)
        finally:
            # Always cleanup temp file
            if temp_path.exists():
                temp_path.unlink()
                self.logger.debug("Cleaned up temp file: %s", temp_path)

    async def _download_audio(
        self,
        url: str,
        auth_token: Optional[str] = None,
    ) -> Path:
        """
        Download audio from URL to a temporary file.

        Args:
            url: URL to download from.
            auth_token: Optional Bearer token for authorization.

        Returns:
            Path to the downloaded temp file.

        Raises:
            RuntimeError: If the download fails (non-200 status).
        """
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"Failed to download audio: HTTP {response.status}"
                    )

                # Determine extension from content-type
                content_type = response.headers.get("Content-Type", "")
                ext = self._content_type_to_ext(content_type)

                # Write to temp file
                content = await response.read()
                with tempfile.NamedTemporaryFile(
                    suffix=ext, delete=False
                ) as tmp:
                    tmp.write(content)
                    temp_path = Path(tmp.name)

                self.logger.debug(
                    "Downloaded audio to temp file: %s (%d bytes)",
                    temp_path,
                    len(content),
                )
                return temp_path

    def _content_type_to_ext(self, content_type: str) -> str:
        """
        Convert Content-Type header to file extension.

        Args:
            content_type: HTTP Content-Type header value.

        Returns:
            File extension including the dot (e.g., ".ogg").
        """
        mapping = {
            "audio/ogg": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/m4a": ".m4a",
            "audio/webm": ".webm",
            "video/webm": ".webm",
            "audio/flac": ".flac",
        }
        for mime, ext in mapping.items():
            if mime in content_type.lower():
                return ext
        return ".wav"  # fallback

    def _get_audio_duration(self, file_path: Path) -> float:
        """
        Get audio duration in seconds using pydub.

        Args:
            file_path: Path to the audio file.

        Returns:
            Duration in seconds, or 0.0 if duration cannot be determined.
        """
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(file_path))
            return len(audio) / 1000.0  # milliseconds to seconds
        except Exception as e:
            self.logger.warning(
                "Could not determine audio duration for %s: %s",
                file_path,
                e,
            )
            # If we can't determine duration, let the backend handle it
            return 0.0

    async def close(self) -> None:
        """
        Release backend resources.

        Should be called when the transcriber is no longer needed
        to free up GPU memory (for local backend) or HTTP sessions
        (for cloud backend).
        """
        if self._backend is not None:
            self.logger.debug("Closing transcriber backend")
            await self._backend.close()
            self._backend = None
