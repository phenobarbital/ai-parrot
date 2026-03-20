# TASK-020: Voice Transcriber Service

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-016, TASK-017, TASK-018, TASK-019
**Assigned-to**: claude-session

---

## Context

This task implements the main `VoiceTranscriber` service that orchestrates transcription. It selects the appropriate backend based on configuration, handles audio downloads from URLs, manages temp files, and provides the unified interface used by MSTeamsAgentWrapper.

Reference: Spec Section 3 "Module 5: Voice Transcriber Service"

---

## Scope

- Implement `VoiceTranscriber` class with:
  - Constructor accepting `VoiceTranscriberConfig`
  - Backend selection based on config
  - `transcribe_file(path, language)` method
  - `transcribe_url(url, auth_token)` method
  - `close()` to release backend resources
- Download audio from URLs using `aiohttp` with auth token support
- Handle temp file creation and cleanup
- Validate audio duration before processing
- Write comprehensive unit tests

**NOT in scope**:
- MSTeamsAgentWrapper integration (TASK-021)
- Config extension (TASK-022)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/voice/transcriber.py` | CREATE | VoiceTranscriber service |
| `parrot/integrations/msteams/voice/__init__.py` | MODIFY | Export VoiceTranscriber |
| `tests/integrations/msteams/test_voice_transcriber.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional
import aiohttp
from pydub import AudioSegment
from .models import VoiceTranscriberConfig, TranscriptionResult, TranscriberBackend
from .backend import AbstractTranscriberBackend
from .faster_whisper_backend import FasterWhisperBackend
from .openai_backend import OpenAIWhisperBackend

class VoiceTranscriber:
    """
    Voice transcription service.

    Manages transcription backend lifecycle and provides
    unified interface for transcribing audio files and URLs.
    """

    SUPPORTED_FORMATS = {'.ogg', '.mp3', '.wav', '.m4a', '.webm', '.mp4'}

    def __init__(self, config: VoiceTranscriberConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._backend: Optional[AbstractTranscriberBackend] = None

    def _get_backend(self) -> AbstractTranscriberBackend:
        """Get or create the transcription backend."""
        if self._backend is None:
            if self.config.backend == TranscriberBackend.FASTER_WHISPER:
                self._backend = FasterWhisperBackend(
                    model_size=self.config.model_size,
                )
            elif self.config.backend == TranscriberBackend.OPENAI_WHISPER:
                if not self.config.openai_api_key:
                    raise ValueError("OpenAI API key required for openai_whisper backend")
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
            file_path: Path to audio file
            language: Optional language hint

        Returns:
            TranscriptionResult

        Raises:
            ValueError: If audio exceeds max duration
            FileNotFoundError: If file doesn't exist
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        # Check duration
        duration = self._get_audio_duration(file_path)
        if duration > self.config.max_audio_duration_seconds:
            raise ValueError(
                f"Audio duration ({duration:.1f}s) exceeds limit "
                f"({self.config.max_audio_duration_seconds}s)"
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
    ) -> TranscriptionResult:
        """
        Download and transcribe audio from URL.

        Args:
            url: URL to download audio from
            auth_token: Optional auth token for request

        Returns:
            TranscriptionResult
        """
        # Download to temp file
        temp_path = await self._download_audio(url, auth_token)

        try:
            return await self.transcribe_file(temp_path)
        finally:
            # Cleanup temp file
            if temp_path.exists():
                temp_path.unlink()

    async def _download_audio(
        self,
        url: str,
        auth_token: Optional[str] = None,
    ) -> Path:
        """Download audio from URL to temp file."""
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"Failed to download audio: HTTP {response.status}"
                    )

                # Determine extension from content-type
                content_type = response.headers.get("Content-Type", "")
                ext = self._content_type_to_ext(content_type)

                # Write to temp file
                with tempfile.NamedTemporaryFile(
                    suffix=ext, delete=False
                ) as tmp:
                    tmp.write(await response.read())
                    return Path(tmp.name)

    def _content_type_to_ext(self, content_type: str) -> str:
        """Convert content-type to file extension."""
        mapping = {
            "audio/ogg": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/webm": ".webm",
            "video/webm": ".webm",
        }
        for mime, ext in mapping.items():
            if mime in content_type:
                return ext
        return ".wav"  # fallback

    def _get_audio_duration(self, file_path: Path) -> float:
        """Get audio duration in seconds."""
        try:
            audio = AudioSegment.from_file(str(file_path))
            return len(audio) / 1000.0  # ms to seconds
        except Exception:
            return 0.0  # If we can't determine, let backend handle it

    async def close(self) -> None:
        """Release backend resources."""
        if self._backend:
            await self._backend.close()
            self._backend = None
```

### Key Constraints
- Always cleanup temp files (use try/finally)
- Validate duration before transcription
- Lazy create backend on first use
- Support auth token for MS Teams CDN downloads
- Use `pydub` for audio duration (already in project)

### References in Codebase
- `parrot/loaders/basevideo.py` — audio handling patterns
- `parrot/tools/web/` — URL download patterns

---

## Acceptance Criteria

- [ ] `VoiceTranscriber` selects backend based on config
- [ ] `transcribe_file()` validates duration and delegates to backend
- [ ] `transcribe_url()` downloads, transcribes, and cleans up temp file
- [ ] Auth token is passed in download headers
- [ ] Duration limit is enforced (raises ValueError)
- [ ] `close()` releases backend resources
- [ ] All tests pass: `pytest tests/integrations/msteams/test_voice_transcriber.py -v`
- [ ] Import works: `from parrot.integrations.msteams.voice import VoiceTranscriber`

---

## Test Specification

```python
# tests/integrations/msteams/test_voice_transcriber.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.integrations.msteams.voice.transcriber import VoiceTranscriber
from parrot.integrations.msteams.voice.models import (
    VoiceTranscriberConfig,
    TranscriberBackend,
    TranscriptionResult,
)


@pytest.fixture
def config_local():
    return VoiceTranscriberConfig(
        backend=TranscriberBackend.FASTER_WHISPER,
        model_size="tiny",
        max_audio_duration_seconds=60,
    )


@pytest.fixture
def config_openai():
    return VoiceTranscriberConfig(
        backend=TranscriberBackend.OPENAI_WHISPER,
        openai_api_key="sk-test",
    )


class TestVoiceTranscriber:
    def test_creates_faster_whisper_backend(self, config_local):
        """Creates FasterWhisperBackend for local config."""
        transcriber = VoiceTranscriber(config_local)
        backend = transcriber._get_backend()
        assert backend.__class__.__name__ == "FasterWhisperBackend"

    def test_creates_openai_backend(self, config_openai):
        """Creates OpenAIWhisperBackend for cloud config."""
        transcriber = VoiceTranscriber(config_openai)
        backend = transcriber._get_backend()
        assert backend.__class__.__name__ == "OpenAIWhisperBackend"

    def test_openai_requires_api_key(self):
        """Raises if OpenAI backend but no API key."""
        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.OPENAI_WHISPER,
            openai_api_key=None,
        )
        transcriber = VoiceTranscriber(config)
        with pytest.raises(ValueError, match="API key required"):
            transcriber._get_backend()

    @pytest.mark.asyncio
    async def test_transcribe_file_validates_duration(self, config_local, tmp_path):
        """Rejects audio exceeding duration limit."""
        config_local.max_audio_duration_seconds = 5
        transcriber = VoiceTranscriber(config_local)

        audio_file = tmp_path / "long.wav"
        audio_file.write_bytes(b"fake")

        # Mock duration to exceed limit
        with patch.object(transcriber, '_get_audio_duration', return_value=120.0):
            with pytest.raises(ValueError, match="exceeds limit"):
                await transcriber.transcribe_file(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_url_downloads_and_cleans(self, config_local):
        """Downloads audio, transcribes, and cleans up temp file."""
        transcriber = VoiceTranscriber(config_local)

        mock_result = TranscriptionResult(
            text="Hello", language="en",
            duration_seconds=5.0, processing_time_ms=100
        )

        with patch.object(transcriber, '_download_audio') as mock_download, \
             patch.object(transcriber, 'transcribe_file', return_value=mock_result):

            tmp = Path("/tmp/test_audio.ogg")
            mock_download.return_value = tmp

            result = await transcriber.transcribe_url("https://example.com/audio.ogg")

            assert result.text == "Hello"

    @pytest.mark.asyncio
    async def test_close_releases_backend(self, config_local):
        """Close releases backend resources."""
        transcriber = VoiceTranscriber(config_local)

        mock_backend = MagicMock()
        mock_backend.close = AsyncMock()
        transcriber._backend = mock_backend

        await transcriber.close()

        mock_backend.close.assert_called_once()
        assert transcriber._backend is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md`
2. **Check dependencies** — TASK-016, TASK-017, TASK-018, TASK-019 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-020-voice-transcriber-service.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Implemented VoiceTranscriber service orchestrating backend selection and transcription
- Supports both FasterWhisperBackend (local GPU) and OpenAIWhisperBackend (cloud)
- transcribe_file() validates audio duration before processing
- transcribe_url() downloads audio to temp file, transcribes, and ensures cleanup (even on error)
- Auth token support for MS Teams CDN downloads
- Content-type to extension mapping for multiple audio formats
- Uses pydub for audio duration calculation (gracefully handles failures)
- Lazy backend creation to save resources
- All 33 unit tests passing

**Deviations from spec**: none
