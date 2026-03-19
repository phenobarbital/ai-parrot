# TASK-019: OpenAI Whisper Backend

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-016, TASK-017
**Assigned-to**: claude-session

---

## Context

This task implements the cloud-based transcription backend using OpenAI's Whisper API. This provides an alternative to local GPU transcription for environments without GPU access or for simpler deployment.

Reference: Spec Section 3 "Module 4: OpenAI Whisper Backend"

---

## Scope

- Implement `OpenAIWhisperBackend` class extending `AbstractTranscriberBackend`
- Use `aiohttp` for async HTTP requests to OpenAI API
- Handle file upload (multipart form data)
- Parse API response and convert to `TranscriptionResult`
- Implement retry with exponential backoff for rate limits
- Handle API errors gracefully (auth failures, rate limits, server errors)
- Write unit tests with mocked API responses

**NOT in scope**:
- Faster Whisper backend (TASK-018)
- VoiceTranscriber service integration (TASK-020)
- Real API tests (require OpenAI API key)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/voice/openai_backend.py` | CREATE | OpenAIWhisperBackend implementation |
| `parrot/integrations/msteams/voice/__init__.py` | MODIFY | Export OpenAIWhisperBackend |
| `tests/integrations/msteams/test_openai_whisper_backend.py` | CREATE | Unit tests with mocked API |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
import time
import logging
from pathlib import Path
from typing import Optional
import aiohttp
from .backend import AbstractTranscriberBackend
from .models import TranscriptionResult

class OpenAIWhisperBackend(AbstractTranscriberBackend):
    """
    Cloud-based transcription using OpenAI Whisper API.

    Requires an OpenAI API key. Supports automatic retry
    with exponential backoff for rate limits.
    """

    API_URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        max_retries: int = 3,
        timeout_seconds: int = 60,
    ):
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using OpenAI Whisper API."""
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        start_time = time.perf_counter()

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field(
            'file',
            open(audio_path, 'rb'),
            filename=audio_path.name,
            content_type='audio/wav'
        )
        data.add_field('model', self.model)
        data.add_field('response_format', 'verbose_json')
        if language:
            data.add_field('language', language)

        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(self.max_retries):
            try:
                session = await self._get_session()
                async with session.post(
                    self.API_URL,
                    data=data,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result_json = await response.json()
                        processing_time_ms = int(
                            (time.perf_counter() - start_time) * 1000
                        )
                        return TranscriptionResult(
                            text=result_json.get("text", ""),
                            language=result_json.get("language", "en"),
                            duration_seconds=result_json.get("duration", 0.0),
                            confidence=None,  # OpenAI doesn't return confidence
                            processing_time_ms=processing_time_ms,
                        )
                    elif response.status == 429:
                        # Rate limited - retry with backoff
                        wait_time = 2 ** attempt
                        self.logger.warning(
                            f"Rate limited, retrying in {wait_time}s"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        error_text = await response.text()
                        raise RuntimeError(
                            f"OpenAI API error ({response.status}): {error_text}"
                        )
            except aiohttp.ClientError as e:
                last_error = e
                self.logger.warning(f"Request failed: {e}, retrying...")
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Transcription failed after {self.max_retries} attempts: {last_error}")

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
```

### Key Constraints
- Use `aiohttp` (not `requests`) for async HTTP
- Always close file handles after request
- Implement exponential backoff for rate limits
- Return `verbose_json` format to get duration
- Validate API key is provided in constructor

### References in Codebase
- `parrot/clients/openai.py` — OpenAI API patterns
- `parrot/tools/web/` — aiohttp request patterns

---

## Acceptance Criteria

- [ ] `OpenAIWhisperBackend` extends `AbstractTranscriberBackend`
- [ ] Uses `aiohttp` for async HTTP requests
- [ ] Handles rate limits with retry and backoff
- [ ] Handles API errors gracefully with clear messages
- [ ] `close()` properly closes aiohttp session
- [ ] Raises `ValueError` if API key is missing
- [ ] All tests pass: `pytest tests/integrations/msteams/test_openai_whisper_backend.py -v`
- [ ] Import works: `from parrot.integrations.msteams.voice import OpenAIWhisperBackend`

---

## Test Specification

```python
# tests/integrations/msteams/test_openai_whisper_backend.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import ClientResponseError
from parrot.integrations.msteams.voice.openai_backend import OpenAIWhisperBackend


class TestOpenAIWhisperBackend:
    def test_requires_api_key(self):
        """Raises ValueError if API key is missing."""
        with pytest.raises(ValueError, match="API key is required"):
            OpenAIWhisperBackend(api_key="")

    def test_initialization(self):
        """Backend initializes with API key."""
        backend = OpenAIWhisperBackend(api_key="sk-test123")
        assert backend.api_key == "sk-test123"
        assert backend.model == "whisper-1"

    @pytest.mark.asyncio
    async def test_transcribe_success(self, tmp_path):
        """Successful transcription returns result."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "text": "Hello world",
            "language": "en",
            "duration": 5.0
        })

        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_post.return_value.__aenter__.return_value = mock_response

            backend = OpenAIWhisperBackend(api_key="sk-test")
            backend._session = MagicMock()
            backend._session.post = mock_post

            result = await backend.transcribe(audio_file)

            assert result.text == "Hello world"
            assert result.language == "en"

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        backend = OpenAIWhisperBackend(api_key="sk-test")

        with pytest.raises(FileNotFoundError):
            await backend.transcribe(Path("/nonexistent/audio.wav"))

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Close properly closes aiohttp session."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        backend._session = MagicMock()
        backend._session.closed = False
        backend._session.close = AsyncMock()

        await backend.close()

        backend._session.close.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md`
2. **Check dependencies** — TASK-016 and TASK-017 must be in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-019-openai-whisper-backend.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Implemented OpenAIWhisperBackend with aiohttp for async HTTP requests
- Validates API key in constructor (raises ValueError if missing)
- Uses verbose_json response format to get duration
- Implements retry with exponential backoff for rate limits (429)
- Handles authentication errors (401) with clear message
- Proper content type detection for various audio formats
- Session management with lazy creation and proper cleanup
- Reads file content before request to avoid keeping file handles open
- All 30 unit tests passing with mocked API responses

**Deviations from spec**: none
