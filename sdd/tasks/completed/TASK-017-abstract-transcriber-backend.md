# TASK-017: Abstract Transcriber Backend

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-016
**Assigned-to**: claude-session

---

## Context

This task defines the abstract base class for transcription backends. Both FasterWhisperBackend and OpenAIWhisperBackend will implement this interface, allowing the VoiceTranscriber service to work with either backend interchangeably.

Reference: Spec Section 2 "New Public Interfaces" and Section 3 "Module 2"

---

## Scope

- Implement `AbstractTranscriberBackend` ABC with:
  - `async def transcribe(audio_path, language) -> TranscriptionResult`
  - `async def close() -> None` (default implementation)
- Define clear interface contract in docstrings
- Write tests verifying ABC cannot be instantiated

**NOT in scope**:
- Concrete backend implementations (TASK-018, TASK-019)
- VoiceTranscriber service (TASK-020)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/voice/backend.py` | CREATE | Abstract base class |
| `parrot/integrations/msteams/voice/__init__.py` | MODIFY | Export AbstractTranscriberBackend |
| `tests/integrations/msteams/test_voice_backend.py` | CREATE | ABC tests |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/tools/toolkit.py AbstractToolkit pattern
from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path
from .models import TranscriptionResult

class AbstractTranscriberBackend(ABC):
    """
    Abstract base for transcription backends.

    Implementations must provide the `transcribe` method.
    The `close` method has a default no-op implementation.
    """

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
            language: Optional language hint (ISO 639-1 code, e.g., "en", "es")

        Returns:
            TranscriptionResult with transcribed text and metadata

        Raises:
            FileNotFoundError: If audio_path does not exist
            ValueError: If audio format is unsupported
            RuntimeError: If transcription fails
        """
        ...

    async def close(self) -> None:
        """
        Release resources (models, connections, etc.).

        Default implementation does nothing.
        Subclasses should override if they hold resources.
        """
        pass
```

### Key Constraints
- Must use `ABC` and `@abstractmethod` from `abc` module
- Path parameter should be `pathlib.Path` type
- Method must be async (even if some backends are sync internally)
- Docstrings must document expected exceptions

### References in Codebase
- `parrot/tools/toolkit.py` — AbstractToolkit ABC pattern
- `parrot/clients/abstract_client.py` — AbstractClient pattern

---

## Acceptance Criteria

- [ ] `AbstractTranscriberBackend` is a proper ABC
- [ ] Cannot instantiate ABC directly (raises TypeError)
- [ ] `transcribe` is abstract, `close` has default implementation
- [ ] Clear docstrings with Args, Returns, Raises
- [ ] All tests pass: `pytest tests/integrations/msteams/test_voice_backend.py -v`
- [ ] Import works: `from parrot.integrations.msteams.voice import AbstractTranscriberBackend`

---

## Test Specification

```python
# tests/integrations/msteams/test_voice_backend.py
import pytest
from pathlib import Path
from parrot.integrations.msteams.voice.backend import AbstractTranscriberBackend
from parrot.integrations.msteams.voice.models import TranscriptionResult


class TestAbstractTranscriberBackend:
    def test_cannot_instantiate_abc(self):
        """ABC cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AbstractTranscriberBackend()

    def test_concrete_implementation_works(self):
        """Concrete subclass can be instantiated."""
        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="test",
                    language="en",
                    duration_seconds=1.0,
                    processing_time_ms=100
                )

        backend = MockBackend()
        assert backend is not None

    @pytest.mark.asyncio
    async def test_close_default_implementation(self):
        """Default close() does nothing and doesn't raise."""
        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="test", language="en",
                    duration_seconds=1.0, processing_time_ms=100
                )

        backend = MockBackend()
        await backend.close()  # Should not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md`
2. **Check dependencies** — TASK-016 must be in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the ABC following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-017-abstract-transcriber-backend.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**: Implemented `AbstractTranscriberBackend` ABC with:
- Abstract `transcribe(audio_path, language)` method with full docstring
- Default `close()` method that can be overridden
- Comprehensive docstrings documenting Args, Returns, and Raises
- Updated `__init__.py` to export the ABC
- 11 unit tests covering instantiation, abstract method enforcement, and imports

All tests pass.

**Deviations from spec**: none
