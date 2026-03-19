# Feature Specification: MS Teams Voice Note Support

**Feature ID**: FEAT-008
**Date**: 2026-02-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The `MSTeamsAgentWrapper` currently only processes text messages from users. When a user sends a voice note (audio attachment) in MS Teams, the wrapper ignores it completely. This creates a poor user experience for users who prefer voice input or are in situations where typing is inconvenient (mobile, accessibility needs, hands-free scenarios).

Users expect modern AI assistants to understand voice messages. MS Teams supports voice notes natively, and our agents should be able to:
1. Detect incoming voice note attachments
2. Transcribe the audio to text using fast speech-to-text
3. Process the transcribed text as the user's question
4. Respond to the agent query normally

### Goals
- Enable `MSTeamsAgentWrapper` to process voice note attachments from MS Teams
- Use fast, efficient speech-to-text (Faster Whisper or OpenAI Whisper API) for transcription
- Seamless integration — transcribed text is processed identically to typed text
- Show user the transcription before processing (transparency)
- Support common audio formats: OGG, MP4, WebM, WAV, M4A
- Minimal latency — transcription should complete in < 3 seconds for typical voice notes

### Non-Goals (explicitly out of scope)
- Real-time streaming transcription (voice notes are sent as complete files)
- Text-to-speech responses (user receives text/card responses)
- Supporting video attachments with audio extraction (future feature)
- Multi-language auto-detection (initial version uses configured language)
- Voice authentication or speaker identification

---

## 2. Architectural Design

### Overview

The solution adds a voice processing pipeline to `MSTeamsAgentWrapper`. When a message contains audio attachments, the wrapper:
1. Downloads the audio file from MS Teams storage
2. Passes it to a `VoiceTranscriber` service for speech-to-text
3. Sends a typing indicator while processing
4. Optionally shows the transcription to the user
5. Processes the transcribed text through the normal agent flow

The `VoiceTranscriber` is a standalone async service that can use either:
- **Faster Whisper** (local, GPU-accelerated, no API costs)
- **OpenAI Whisper API** (cloud, simple, pay-per-use)

### Component Diagram
```
MS Teams User
      │
      ▼ (voice note attachment)
MSTeamsAgentWrapper.on_message_activity()
      │
      ├── Detect audio attachment
      │
      ▼
AttachmentDownloader
      │ (downloads audio from MS Teams CDN)
      │
      ▼
VoiceTranscriber
      │ (speech-to-text)
      ├── FasterWhisperBackend (local GPU)
      └── OpenAIWhisperBackend (cloud API)
      │
      ▼ (transcribed text)
MSTeamsAgentWrapper
      │
      └── Process as normal text message
          (form_orchestrator.process_message)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MSTeamsAgentWrapper` | extends | Add `_handle_voice_attachment()` method |
| `MSTeamsAgentConfig` | extends | Add voice transcription settings |
| `parrot/loaders/basevideo.py` | reuses patterns | WhisperX patterns for transcription |
| `aiohttp` | uses | Download attachments from MS Teams CDN |
| `botbuilder.schema.Attachment` | uses | Parse attachment metadata |

### Data Models
```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum

class TranscriberBackend(str, Enum):
    """Available transcription backends."""
    FASTER_WHISPER = "faster_whisper"
    OPENAI_WHISPER = "openai_whisper"

class VoiceTranscriberConfig(BaseModel):
    """Configuration for voice transcription."""
    enabled: bool = Field(True, description="Enable voice note processing")
    backend: TranscriberBackend = Field(
        TranscriberBackend.FASTER_WHISPER,
        description="Transcription backend to use"
    )
    model_size: str = Field(
        "small",
        description="Whisper model size (tiny, base, small, medium, large-v3)"
    )
    language: Optional[str] = Field(
        None,
        description="Force language (None = auto-detect)"
    )
    show_transcription: bool = Field(
        True,
        description="Show transcription to user before processing"
    )
    max_audio_duration_seconds: int = Field(
        120,
        description="Max audio duration to process (seconds)"
    )
    # OpenAI-specific
    openai_api_key: Optional[str] = Field(
        None,
        description="OpenAI API key (if using openai_whisper backend)"
    )

class TranscriptionResult(BaseModel):
    """Result of voice transcription."""
    text: str = Field(..., description="Transcribed text")
    language: str = Field(..., description="Detected language code")
    duration_seconds: float = Field(..., description="Audio duration")
    confidence: Optional[float] = Field(None, description="Confidence score if available")
    processing_time_ms: int = Field(..., description="Transcription processing time")

class AudioAttachment(BaseModel):
    """Parsed audio attachment from MS Teams."""
    content_url: str = Field(..., description="URL to download audio")
    content_type: str = Field(..., description="MIME type (audio/ogg, etc.)")
    name: Optional[str] = Field(None, description="Original filename")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")
```

### New Public Interfaces
```python
from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path

class AbstractTranscriberBackend(ABC):
    """Abstract base for transcription backends."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file to text.

        Args:
            audio_path: Path to audio file (WAV, OGG, MP4, etc.)
            language: Optional language hint (ISO 639-1 code)

        Returns:
            TranscriptionResult with text and metadata
        """
        ...

    async def close(self) -> None:
        """Release resources."""
        pass


class FasterWhisperBackend(AbstractTranscriberBackend):
    """Local GPU-accelerated transcription using Faster Whisper."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cuda",
        compute_type: str = "float16",
    ):
        ...


class OpenAIWhisperBackend(AbstractTranscriberBackend):
    """Cloud-based transcription using OpenAI Whisper API."""

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
    ):
        ...


class VoiceTranscriber:
    """
    Voice transcription service.

    Manages transcription backend lifecycle and provides
    simple interface for MSTeamsAgentWrapper.
    """

    def __init__(self, config: VoiceTranscriberConfig):
        ...

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe a local audio file."""
        ...

    async def transcribe_url(
        self,
        url: str,
        auth_token: Optional[str] = None,
    ) -> TranscriptionResult:
        """Download and transcribe audio from URL."""
        ...

    async def close(self) -> None:
        """Release transcription resources."""
        ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Data Models
- **Path**: `parrot/integrations/msteams/voice/models.py`
- **Responsibility**: Pydantic models for voice transcription config and results
- **Depends on**: None

### Module 2: Abstract Backend
- **Path**: `parrot/integrations/msteams/voice/backend.py`
- **Responsibility**: `AbstractTranscriberBackend` ABC defining the transcription interface
- **Depends on**: Module 1

### Module 3: Faster Whisper Backend
- **Path**: `parrot/integrations/msteams/voice/faster_whisper_backend.py`
- **Responsibility**: Local GPU transcription using `faster-whisper` library. Handles model loading, audio preprocessing, and transcription with timing.
- **Depends on**: Module 1, Module 2

### Module 4: OpenAI Whisper Backend
- **Path**: `parrot/integrations/msteams/voice/openai_backend.py`
- **Responsibility**: Cloud transcription via OpenAI Whisper API using `aiohttp`. Handles file upload and response parsing.
- **Depends on**: Module 1, Module 2

### Module 5: Voice Transcriber Service
- **Path**: `parrot/integrations/msteams/voice/__init__.py`
- **Responsibility**: `VoiceTranscriber` class that selects backend based on config, handles audio download from URLs, manages temp files, and provides unified interface.
- **Depends on**: Module 1, 2, 3, 4

### Module 6: MSTeamsAgentWrapper Integration
- **Path**: `parrot/integrations/msteams/wrapper.py` (modify existing)
- **Responsibility**: Add voice attachment detection and processing to `on_message_activity()`. Download audio, transcribe, show transcription, process as text.
- **Depends on**: Module 5

### Module 7: Config Extension
- **Path**: `parrot/integrations/msteams/models.py` (modify existing)
- **Responsibility**: Add `voice_config: VoiceTranscriberConfig` field to `MSTeamsAgentConfig`
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_voice_config_defaults` | Module 1 | Validates default config values |
| `test_voice_config_validation` | Module 1 | Validates config constraints (model size, duration) |
| `test_transcription_result_model` | Module 1 | Validates TranscriptionResult serialization |
| `test_backend_abc_interface` | Module 2 | Verifies ABC cannot be instantiated directly |
| `test_faster_whisper_transcribe` | Module 3 | Mocked transcription with faster-whisper |
| `test_faster_whisper_language_hint` | Module 3 | Language hint is passed correctly |
| `test_openai_whisper_transcribe` | Module 4 | Mocked OpenAI API call |
| `test_openai_whisper_error_handling` | Module 4 | Handles API errors gracefully |
| `test_transcriber_backend_selection` | Module 5 | Correct backend instantiated from config |
| `test_transcriber_url_download` | Module 5 | Downloads and transcribes from URL |
| `test_transcriber_temp_file_cleanup` | Module 5 | Temp files are cleaned up after use |
| `test_wrapper_audio_detection` | Module 6 | Detects audio attachments correctly |
| `test_wrapper_ignores_non_audio` | Module 6 | Non-audio attachments are ignored |
| `test_wrapper_transcription_flow` | Module 6 | Full flow from attachment to agent response |

### Integration Tests
| Test | Description |
|---|---|
| `test_faster_whisper_real_audio` | Transcribes real audio file with faster-whisper |
| `test_openai_whisper_real_audio` | Transcribes real audio via OpenAI API (requires key) |
| `test_msteams_voice_e2e` | Mocked MS Teams activity with audio attachment, full pipeline |

### Test Data / Fixtures
```python
import pytest
from pathlib import Path
from parrot.integrations.msteams.voice.models import (
    VoiceTranscriberConfig,
    TranscriberBackend,
)

@pytest.fixture
def voice_config_local():
    """Config for local Faster Whisper."""
    return VoiceTranscriberConfig(
        enabled=True,
        backend=TranscriberBackend.FASTER_WHISPER,
        model_size="tiny",  # Fast for tests
        language="en",
    )

@pytest.fixture
def voice_config_openai():
    """Config for OpenAI Whisper API."""
    return VoiceTranscriberConfig(
        enabled=True,
        backend=TranscriberBackend.OPENAI_WHISPER,
        openai_api_key="test-key",
    )

@pytest.fixture
def sample_audio_file(tmp_path) -> Path:
    """Create a sample audio file for testing."""
    # Generate a simple WAV file with silence (or use a fixture file)
    audio_path = tmp_path / "test_audio.wav"
    # ... generate or copy test audio
    return audio_path

@pytest.fixture
def mock_teams_audio_activity():
    """Mocked MS Teams activity with audio attachment."""
    return {
        "type": "message",
        "attachments": [{
            "contentType": "audio/ogg",
            "contentUrl": "https://teams.microsoft.com/files/audio123.ogg",
            "name": "voice_note.ogg",
        }],
        "text": "",
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `VoiceTranscriberConfig` model validates correctly
- [ ] `FasterWhisperBackend` transcribes audio files with < 3s latency for 10s audio
- [ ] `OpenAIWhisperBackend` transcribes via API with proper error handling
- [ ] `VoiceTranscriber` selects correct backend based on config
- [ ] `VoiceTranscriber` downloads audio from URLs with auth tokens
- [ ] `MSTeamsAgentWrapper` detects audio attachments (OGG, MP4, WebM, WAV, M4A)
- [ ] `MSTeamsAgentWrapper` transcribes audio and processes as text
- [ ] User sees transcription message before agent response (if `show_transcription=True`)
- [ ] Audio duration limit is enforced (rejects audio > max duration)
- [ ] All unit tests pass: `pytest tests/integrations/msteams/test_voice*.py -v`
- [ ] Integration test passes with real audio file
- [ ] Temp files are cleaned up after transcription
- [ ] No blocking I/O — fully async
- [ ] Graceful degradation: if transcription fails, inform user clearly

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `AbstractTranscriberBackend` pattern from `parrot/tools/toolkit.py` (ABC + implementations)
- Async-first: use `aiohttp` for downloads, `asyncio.to_thread` for CPU-bound whisper
- Pydantic models for all structured data
- Comprehensive logging with `self.logger`
- Temp file handling with `tempfile.NamedTemporaryFile` and proper cleanup

### Audio Format Handling
MS Teams voice notes are typically OGG (Opus codec). Faster Whisper natively supports:
- WAV, MP3, FLAC, OGG, M4A, WebM

For best results, consider converting to 16kHz mono WAV before transcription (reuse `ensure_wav_16k_mono` from `basevideo.py`).

### Known Risks / Gotchas
- **GPU memory**: Faster Whisper models use GPU memory. The `small` model uses ~2GB VRAM. Consider lazy loading and unloading after idle period.
- **MS Teams CDN auth**: Downloading attachments may require the bot's access token. The `TurnContext` provides access to tokens.
- **Audio download timeout**: Large voice notes may take time to download. Set reasonable timeout (30s).
- **Rate limiting**: OpenAI Whisper API has rate limits. Implement retry with backoff.
- **Concurrent transcriptions**: If multiple users send voice notes simultaneously, queue or limit concurrent transcriptions to avoid GPU OOM.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `faster-whisper` | `>=1.0.0` | Local GPU-accelerated transcription |
| `pydub` | `>=0.25.0` | Audio format conversion (already in project) |
| `aiohttp` | `>=3.9` | Download attachments (already in project) |
| `openai` | `>=1.0` | OpenAI Whisper API client (optional) |

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Should we support both local (Faster Whisper) and cloud (OpenAI) backends? — **Yes, configurable**
- [ ] Should we auto-detect language or require explicit config? — *Suggest: default to auto-detect with config override*
- [ ] What's the max audio duration we should support? — *Suggest: 2 minutes default, configurable*: one minute default, configurable.
- [ ] Should we show transcription as a separate message or inline with response? — *Suggest: separate message with 🎤 prefix*
- [ ] Should we support multiple audio attachments in one message? — *Suggest: process first audio only, warn if multiple*: process only first and warn if multiple

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-24 | Jesus Lara | Initial draft |
