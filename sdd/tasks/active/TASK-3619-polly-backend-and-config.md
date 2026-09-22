# TASK-3619: Amazon Polly backend, configuration, and dependency extra

**Feature**: FEAT-591 — speech_report pluggable TTS backends (fast-path)
**Spec**: `sdd/specs/speech-report-models.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implement spec §3 M1 so the integration TTS layer can select Amazon Polly without introducing a core-package dependency.

## Scope

- Add async, chunked Amazon Polly synthesis using `aioboto3`.
- Extend `TTSConfig`, `VoiceSynthesizer`, package exports, and voice extras.
- Add focused unit and integration tests.

**NOT in scope**: process-wide cache (TASK-3620), agent routing (TASK-3622), or Telegram conversion (TASK-3621).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/polly_backend.py` | CREATE | Async Polly backend and splitter |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` | MODIFY | Polly config fields |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` | MODIFY | Polly backend branch |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py` | MODIFY | Public export |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | `voice-polly` extra/bundle |
| `packages/ai-parrot-integrations/tests/voice/tts/test_polly_backend.py` | CREATE | Backend tests |
| `packages/ai-parrot-integrations/tests/voice/tts/test_synthesizer.py` | MODIFY | Polly selection test |
| `packages/ai-parrot-integrations/tests/voice/tts/test_tts_integration.py` | MODIFY | Mocked Polly integration |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .backend import AbstractTTSBackend  # verified: packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:15
from .models import SynthesisResult, TTSConfig  # verified: synthesizer.py:16
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py:17
class AbstractTTSBackend(ABC):
    async def synthesize(self, text: str, *, voice: Optional[str] = None, mime_format: str = "audio/ogg", language: Optional[str] = None) -> SynthesisResult: ...
    async def close(self) -> None: ...
# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:47
class VoiceSynthesizer:
    def _get_backend(self) -> AbstractTTSBackend: ...
```

### Does NOT Exist
- `parrot.voice.tts.polly_backend`, `TTSConfig.polly_engine`, and `TTSConfig.polly_region` do not exist.
- Sync `boto3` is not an allowed Polly client.

## Complexity Contract
```json
{"schema_version":1,"targets":[{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/polly_backend.py","action":"CREATE"},{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/models.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/pyproject.toml","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/tests/voice/tts/test_polly_backend.py","action":"CREATE"},{"path":"packages/ai-parrot-integrations/tests/voice/tts/test_synthesizer.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/tests/voice/tts/test_tts_integration.py","action":"MODIFY"}],"contract_symbols":["sym:packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py#AbstractTTSBackend","sym:packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py#VoiceSynthesizer"]}
```

## Implementation Blueprint

### Steps (in order)
1. Create `polly_backend.py` with `_DEFAULT_VOICE="Danielle"`, `_DEFAULT_REGION="us-east-1"`, `_MAX_CHARS=2800`, and the MIME map — *why*: these are fixed by spec §2.
2. Implement sentence-boundary splitting with hard splits and sequential `aioboto3` reads — *why*: preserves order and avoids Polly’s limit.
3. Add config fields, the lazy synthesizer branch, export, and dependency extra — *why*: exposes Polly through the existing TTS surface.
4. Test defaults, failures, chunk boundaries, concatenation, and selector wiring.

### `packages/ai-parrot-integrations/src/parrot/voice/tts/polly_backend.py` (CREATE)
```python
class AmazonPollyTTSBackend(AbstractTTSBackend):
    """TTS backend over Amazon Polly using aioboto3."""
    async def synthesize(self, text: str, *, voice: Optional[str] = None, mime_format: str = "audio/mpeg", language: Optional[str] = None) -> SynthesisResult:
        # FILL IN: validate MIME/text, lazy-import aioboto3, sequentially concatenate chunks; bounded by AC8/AC13/AC14.
        pass
```

### MODIFY anchors
```text
models.py: `backend: Literal["google", "elevenlabs", "openai", "supertonic"] = Field(` (occurrences: 1): add `polly`, `polly_engine`, `polly_region`.
synthesizer.py: `elif backend_name in ("elevenlabs", "openai"):` (occurrences: 1): insert lazy Polly branch immediately before it.
__init__.py: `__all__ = [` (occurrences: 1): export AmazonPollyTTSBackend.
pyproject.toml: `voice-supertonic = [` (occurrences: 1): add voice-polly and include it in voice bundle.
```

### FILL IN checklist
- [ ] Wrap botocore failures in `RuntimeError` retaining the AWS error code.
- [ ] Keep all network I/O async and construction free of network calls.

## Acceptance Criteria

- [ ] AC8, AC13, AC14, and AC15 of FEAT-591 pass.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/voice/tts/test_polly_backend.py -v`
- `pytest packages/ai-parrot-integrations/tests/voice/tts/test_synthesizer.py -v`
- `pytest packages/ai-parrot-integrations/tests/voice/tts/test_tts_integration.py -v`
