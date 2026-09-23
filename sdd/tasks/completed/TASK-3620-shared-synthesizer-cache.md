# TASK-3620: Process-wide synthesizer cache and Supertonic first-load lock

**Feature**: FEAT-591 — speech_report pluggable TTS backends (fast-path)
**Spec**: `sdd/specs/speech-report-models.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3619
**Assigned-to**: unassigned

---

## Context

Implement spec §3 M2 after TASK-3619, which owns the prior `synthesizer.py` edit.

## Scope

- Add process-wide config-keyed synthesizer reuse and best-effort close.
- Guard Supertonic model first load with a thread lock.
- Export helpers and add concurrency tests.

**NOT in scope**: Polly backend/config construction or agent routing.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` | MODIFY | Cache helpers |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py` | MODIFY | Lock lazy load |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py` | MODIFY | Helper exports |
| `packages/ai-parrot-integrations/tests/voice/tts/test_shared_synthesizer.py` | CREATE | Cache/lock tests |
| `packages/ai-parrot-integrations/tests/voice/tts/test_supertonic_backend.py` | MODIFY | Thread-load test |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models import SynthesisResult, TTSConfig  # verified: synthesizer.py:16
from .backend import AbstractTTSBackend  # verified: synthesizer.py:15
```

### Existing Signatures to Use
```python
# synthesizer.py:47
class VoiceSynthesizer:
    def __init__(self, config: Optional[TTSConfig] = None) -> None: ...
    async def close(self) -> None: ...
# supertonic_backend.py:134
class SupertonicTTSBackend(AbstractTTSBackend):
    def _ensure_session(self) -> None: ...
```

### Does NOT Exist
- `get_shared_synthesizer` and `close_shared_synthesizers` do not exist.
- `SupertonicTTSBackend` has no session lock.

## Complexity Contract
```json
{"schema_version":1,"targets":[{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py","action":"MODIFY"},{"path":"packages/ai-parrot-integrations/tests/voice/tts/test_shared_synthesizer.py","action":"CREATE"},{"path":"packages/ai-parrot-integrations/tests/voice/tts/test_supertonic_backend.py","action":"MODIFY"}],"contract_symbols":["sym:packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py#VoiceSynthesizer","sym:packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py#SupertonicTTSBackend"]}
```

## Implementation Blueprint

### Steps (in order)
1. Append `_SHARED` and a lazily created `asyncio.Lock` after `VoiceSynthesizer` — *why*: cache key is `config.model_dump_json()` and must be safe for concurrent first callers.
2. Implement best-effort close that clears the cache even when individual closes fail — *why*: shutdown cannot prevent cleanup.
3. Add `threading.Lock` in Supertonic initialization and wrap only `_ensure_session()` in `_synthesize_sync` — *why*: loading happens in worker threads.
4. Export helpers and test identity, concurrent construction, failed close, and concurrent session load.

### MODIFY anchors
```text
synthesizer.py: append after `class VoiceSynthesizer` (verified class begins line 22); TASK-3619 must land first because it also modifies this file.
supertonic_backend.py: `self._ensure_session()` (occurrences: 1): replace with a lock-protected call.
__init__.py: `__all__ = [` (occurrences: 1): export both cache functions.
```

### FILL IN checklist
- [ ] Do not close a shared synthesizer from speech_report; AC9 owns that integration check.
- [ ] Preserve Supertonic synthesis behavior after session creation.

## Acceptance Criteria

- [ ] AC9 and AC10 of FEAT-591 pass.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/voice/tts/test_shared_synthesizer.py -v`
- `pytest packages/ai-parrot-integrations/tests/voice/tts/test_supertonic_backend.py -v`

### Completion Note

Implemented via `parrot-sdd-coder` (execution `4bfb2cf6-9bb3-4ebf-87f0-09ee5cb10a02`,
seat `gpt-5.6-terra`/codex, attempt_uid `85c75f5d41bf41218c846f82f0311286`, 1 attempt,
no retries), merged at commit `d5bfe4037` (+lint autofix `ecdf6994f`).

Verified before closing:
- File fidelity: merge commit touches exactly the 5 contract files (synthesizer.py,
  supertonic_backend.py, __init__.py, test_shared_synthesizer.py, test_supertonic_backend.py),
  no unlisted files.
- Task's own Validation Commands (`PYTHONPATH=packages/ai-parrot-integrations/src`):
  12/12 tests pass clean.
- `coder_run_validation(tier="merge")` could not settle: the full
  `packages/ai-parrot-integrations/tests` sweep hung deterministically at the exact
  same point as TASK-3619/TASK-3621's attempts (1200s budget, byte-identical frozen
  tail), confirming the pre-existing, unrelated environment issue filed as
  `issue:312c1988479b` [critical] — not a regression from this task's diff.

No confirmed defect found in the delivered code; no feedback recorded.
