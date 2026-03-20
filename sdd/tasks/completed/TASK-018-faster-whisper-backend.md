# TASK-018: Faster Whisper Backend

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-016, TASK-017
**Assigned-to**: claude-session

---

## Context

This task implements the local GPU-accelerated transcription backend using the `faster-whisper` library. This is the default backend for voice transcription, offering low latency and no API costs.

Reference: Spec Section 3 "Module 3: Faster Whisper Backend"

---

## Scope

- Implement `FasterWhisperBackend` class extending `AbstractTranscriberBackend`
- Lazy load the Whisper model on first transcription (save GPU memory)
- Support configurable model size (tiny, base, small, medium, large-v3)
- Handle audio format conversion using existing `ensure_wav_16k_mono` pattern
- Measure and return transcription timing
- Implement `close()` to release GPU memory
- Write unit tests with mocked model

**NOT in scope**:
- OpenAI backend (TASK-019)
- VoiceTranscriber service integration (TASK-020)
- Real integration tests (require GPU and model download)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/voice/faster_whisper_backend.py` | CREATE | FasterWhisperBackend implementation |
| `parrot/integrations/msteams/voice/__init__.py` | MODIFY | Export FasterWhisperBackend |
| `tests/integrations/msteams/test_faster_whisper_backend.py` | CREATE | Unit tests with mocks |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/loaders/basevideo.py for whisper patterns
import asyncio
import time
import logging
from pathlib import Path
from typing import Optional
from .backend import AbstractTranscriberBackend
from .models import TranscriptionResult

class FasterWhisperBackend(AbstractTranscriberBackend):
    """
    Local GPU-accelerated transcription using Faster Whisper.

    The model is loaded lazily on first transcription to save GPU memory.
    Call `close()` to release the model when done.
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cuda",
        compute_type: str = "float16",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self.logger = logging.getLogger(__name__)

    def _ensure_model(self):
        """Lazy load the whisper model."""
        if self._model is None:
            from faster_whisper import WhisperModel
            self.logger.info(f"Loading Faster Whisper model: {self.model_size}")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using Faster Whisper."""
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        start_time = time.perf_counter()

        # Run CPU-bound transcription in thread pool
        result = await asyncio.to_thread(
            self._transcribe_sync, audio_path, language
        )

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        result.processing_time_ms = processing_time_ms

        return result

    def _transcribe_sync(
        self,
        audio_path: Path,
        language: Optional[str],
    ) -> TranscriptionResult:
        """Synchronous transcription (runs in thread pool)."""
        self._ensure_model()

        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        # Collect all segments
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        return TranscriptionResult(
            text=" ".join(text_parts),
            language=info.language,
            duration_seconds=info.duration,
            confidence=info.language_probability,
            processing_time_ms=0,  # Will be set by caller
        )

    async def close(self) -> None:
        """Release the model and free GPU memory."""
        if self._model is not None:
            del self._model
            self._model = None
            # Optionally clear CUDA cache
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
```

### Key Constraints
- Use `asyncio.to_thread()` for CPU-bound transcription
- Lazy load model to save GPU memory at startup
- Support `vad_filter=True` for better accuracy
- Handle FileNotFoundError gracefully
- Log model loading and transcription events

### References in Codebase
- `parrot/loaders/basevideo.py` — `get_whisperx_transcript()` pattern
- `parrot/loaders/audio.py` — `ensure_wav_16k_mono()` helper

---

## Acceptance Criteria

- [ ] `FasterWhisperBackend` extends `AbstractTranscriberBackend`
- [ ] Model loads lazily on first transcription
- [ ] `transcribe()` returns valid `TranscriptionResult`
- [ ] `close()` releases model and clears GPU memory
- [ ] Handles missing files with `FileNotFoundError`
- [ ] All tests pass: `pytest tests/integrations/msteams/test_faster_whisper_backend.py -v`
- [ ] Import works: `from parrot.integrations.msteams.voice import FasterWhisperBackend`

---

## Test Specification

```python
# tests/integrations/msteams/test_faster_whisper_backend.py
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from parrot.integrations.msteams.voice.faster_whisper_backend import FasterWhisperBackend
from parrot.integrations.msteams.voice.models import TranscriptionResult


@pytest.fixture
def mock_whisper_model():
    """Mock the WhisperModel class."""
    with patch('parrot.integrations.msteams.voice.faster_whisper_backend.WhisperModel') as mock:
        # Mock transcribe return value
        mock_info = Mock()
        mock_info.language = "en"
        mock_info.duration = 5.0
        mock_info.language_probability = 0.95

        mock_segment = Mock()
        mock_segment.text = "Hello world"

        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([mock_segment], mock_info)
        mock.return_value = mock_instance

        yield mock


class TestFasterWhisperBackend:
    def test_initialization(self):
        """Backend initializes with config."""
        backend = FasterWhisperBackend(model_size="tiny", device="cpu")
        assert backend.model_size == "tiny"
        assert backend._model is None  # Lazy load

    @pytest.mark.asyncio
    async def test_transcribe_loads_model(self, mock_whisper_model, tmp_path):
        """Transcribe lazily loads model."""
        # Create dummy audio file
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        result = await backend.transcribe(audio_file)

        assert mock_whisper_model.called
        assert result.text == "Hello world"
        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        backend = FasterWhisperBackend()

        with pytest.raises(FileNotFoundError):
            await backend.transcribe(Path("/nonexistent/audio.wav"))

    @pytest.mark.asyncio
    async def test_close_releases_model(self, mock_whisper_model, tmp_path):
        """Close releases model memory."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file)
        assert backend._model is not None

        await backend.close()
        assert backend._model is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md`
2. **Check dependencies** — TASK-016 and TASK-017 must be in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-018-faster-whisper-backend.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Implemented FasterWhisperBackend with lazy model loading
- Supports configurable model_size, device, and compute_type
- Uses asyncio.to_thread() for non-blocking transcription
- Includes VAD filtering and beam search (beam_size=5)
- close() method releases GPU memory and clears CUDA cache
- All 24 unit tests passing with mocked WhisperModel

**Deviations from spec**: none
