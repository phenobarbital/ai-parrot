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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-03
**Notes**: Added a `TestFeat521ConfigFields` class to `test_protocol.py`
covering every new `WorkerConfig` field's default, each validator's
raise/pass boundary (`hard < soft`, `hard == soft` allowed, `hard >
rlimit_as_bytes`, `hard == rlimit_as_bytes` allowed, `interrupt_grace_ms >=
deadline_ms` in both the equal and greater cases, below-deadline allowed),
zero-disables-either/both-thresholds, `ProcessSample`/`MemoryVerdict`
defaults, and confirmed both host-local models are absent from
`_MESSAGE_TYPES`.

Created `test_observer.py` (32 tests) with two complementary strategies: (1)
direct synthetic-ring injection (`obs._ring.append(...)`, `obs._busy_since =
...`) for the five verdict values, `cpu_progress()` window-boundary math,
`last()`/`describe()`, `mark_busy()`/`mark_idle()` transition semantics, and
the soft/hard memory-pressure helpers — fully deterministic, no sleeps,
matching the Implementation Notes; (2) a scripted `psutil.Process` fake
(`_ScriptedProcess`/`_RaisingProcess`) monkeypatched in to drive the REAL
`run()` loop end-to-end for `NoSuchProcess`/`AccessDenied`/non-POSIX
degradation, an unexpected-exception recovery, the soft-limit
one-warning-per-episode hysteresis (asserts `caplog` WARNING record COUNT,
not just content, per the Implementation Notes), and the hard-breach
callback firing exactly once with the measured RSS/limit before `run()`
returns on its own. Included the spec §4 `tight_config` fixture verbatim.

Caught and fixed two of my own test-authoring bugs before finalizing: (1)
`test_cpu_tick_resets_stalled_to_computing`'s synthetic sample timestamps
(0.0s/0.6s against a 500ms window) placed the earlier sample just outside
`cpu_progress()`'s trailing-window boundary, degenerating progress to 0 —
fixed by tightening the tick interval so both samples fall inside the
window; (2) the "unexpected sampling error" fake process gated its
one-shot `RuntimeError` on the shared sample cursor, which never advances
while the fake keeps raising, causing an infinite loop — fixed with an
explicit call counter. Verified stable across 3 repeated full runs (no
flakiness) and confirmed 8/8 pytest-asyncio "marked with asyncio but not
async" warnings disappeared after switching from a module-level
`pytestmark = pytest.mark.asyncio` to relying on this package's
`asyncio_mode = "auto"` (`pyproject.toml`), which needs no marker at all.
`ruff check` and `black --target-version py312` clean; `pytest
test_protocol.py test_observer.py -v` — 79 passed.

**Deviations from spec**: none.
