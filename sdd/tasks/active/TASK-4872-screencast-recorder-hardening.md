# TASK-4872: Screencast recorder hardening and test gaps

**Feature**: FEAT-765 — Screencast recorder hardening (FEAT-762 review follow-up)
**Spec**: `sdd/specs/fixgroup-6c8fa649cccb.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:c3e0c9065cce`

---

## Context

Deferred FEAT-762 review findings (ledger `issue:c3e0c9065cce`): real encoder
untested in the unit suite, `stop_screencast` not single-flight, no
cancellation test for `AnomalyRecorder.__aexit__`, integration test polls the
private `_session`, missing Google-style docstrings, stale `uv.lock`.

## Scope

- Make `stop_screencast` single-flight via a `ScreencastSession.finished` event.
- Map cancellation in `AnomalyRecorder.__aexit__` to a typed `recorder.error`, then re-raise.
- Add `AnomalyRecorder.recording` and `AnomalyRecorder.wait_started(timeout)`.
- Google-style Args/Returns/Raises on `start_screencast` / `stop_screencast`.
- Unit tests listed in spec §4; integration test switched to the public API.
- `uv lock` (no sync) to record the `screencast` extra.

**NOT in scope**: capture/encoding parameters, worker-process design, cancellation inside `start_screencast`.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/screencast.py` | MODIFY |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast.py` | MODIFY |
| `packages/ai-parrot-server/tests/integration/e2e/test_screencast_integration.py` | MODIFY |
| `uv.lock` | MODIFY |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.e2e import screencast                      # packages/ai-parrot-server/src/parrot/e2e/screencast.py
from parrot.e2e.errors import E2EScreencastError
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/e2e/screencast.py
def _encode_webm(frames: list[tuple[int, bytes]], out_path: str) -> int
def _validate_webm(path: str) -> int
async def _run_in_worker(function: Callable[..., int], *args: Any) -> int
class ScreencastSession  # dataclass: page, cdp, out_dir, max_frames, frames, ack_tasks, overflow, result, error, stopped
async def start_screencast(page, out_dir: Path, *, max_frames: int = 600) -> ScreencastSession
async def stop_screencast(session: ScreencastSession) -> Path
class AnomalyRecorder  # _session, _start_task, _start(), __aexit__
```

### Does NOT Exist
- `AnomalyRecorder.recording`, `AnomalyRecorder.wait_started`, `ScreencastSession.finished` (added by this task).

## Acceptance Criteria

- [ ] Two concurrent `stop_screencast` calls encode once and return the same path; a failure is re-raised to both.
- [ ] Cancelling `__aexit__` mid-stop re-raises `CancelledError` and leaves a typed `recorder.error`.
- [ ] Integration test no longer reads `recorder._session` or polls with sleeps for start.
- [ ] Real in-process encode/decode unit test passes when `av`/`PIL` are installed.
- [ ] `uv.lock` lists `av`/`pillow` under the `screencast` extra of `ai-parrot-server`.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_screencast.py -q`

## Agent Instructions

Implement in the FEAT-765 worktree only; commit code, then close with `scripts/sdd/close_task.sh`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
