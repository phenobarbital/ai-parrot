# TASK-2780: Add configuration and ProcessObserver unit tests

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2774, TASK-2775
**Assigned-to**: unassigned

---

## Context

This task implements the deterministic unit-test portion of spec §3 Module 6 and §4 for configuration and observer behavior, without spawning heavy REPL workers.

## Scope

- Add config default/validator coverage for all new fields and invariants.
- Create fake/synthetic process sample helpers covering settled, computing, stalled, booting, and unavailable verdicts.
- Test that CPU progress resets a stalled classification.
- Test `NoSuchProcess`, `AccessDenied`, and non-POSIX degradation without exceptions escaping.
- Test soft-limit one-warning-per-episode behavior and 90% hysteresis re-arm.
- Test hard callback invocation exactly once with measured RSS and configured limit.
- Test `describe()` with and without a last sample.

**NOT in scope**: real subprocess interrupt behavior, handle/pool integration, or memory-bomb E2E tests.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | MODIFY | WorkerConfig model defaults and validators |
| `packages/ai-parrot/tests/repl_worker/test_observer.py` | CREATE | Observer sampling/verdict/RSS unit tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
from pydantic import ValidationError
from parrot.tools.repl_worker.observer import ProcessObserver
from parrot.tools.repl_worker.protocol import MemoryVerdict, ProcessSample, WorkerConfig
```

### Existing Signatures to Use

```python
# test_protocol.py:80
def test_worker_config_new_fields_defaults_and_validation(): ...

# New public API from TASK-2775
class ProcessObserver:
    def mark_busy(self) -> None: ...
    def mark_idle(self) -> None: ...
    def verdict(self) -> Verdict: ...
    def last(self) -> ProcessSample | None: ...
    def cpu_progress(self, window_s: float) -> float: ...
```

### Does NOT Exist

- ~~`test_observer.py`~~ does not exist yet.
- ~~Synthetic observer sample fixtures~~ do not exist.
- Do not require a new third-party mocking dependency; pytest monkeypatch is available.

## Implementation Notes

- Drive time and samples deterministically; do not use multi-second sleeps.
- Parameterize invalid configurations and verdict transitions where it improves failure clarity.
- Assert warning count, not merely warning content, for hysteresis episodes.

## Acceptance Criteria

- [ ] Every config field/default and cross-field error is covered.
- [ ] All five verdict values have deterministic coverage.
- [ ] Observation errors never escape tests and resolve to the documented state.
- [ ] Soft hysteresis and one-shot hard callback are proven.
- [ ] Tests run without spawning a REPL worker.
- [ ] `pytest packages/ai-parrot/tests/repl_worker/test_protocol.py packages/ai-parrot/tests/repl_worker/test_observer.py -v` passes.

## Test Specification

Implement the unit cases named in spec §4: `test_config_validators`, `test_verdict_settled_vs_computing`, `test_verdict_stalled_after_window`, `test_observer_never_raises`, `test_soft_limit_hysteresis`, and `test_hard_limit_invokes_callback`.

## Agent Instructions

Confirm TASK-2774 and TASK-2775 are completed and verify their public API before writing tests. Keep this task deterministic and independent from subprocess timing.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none
