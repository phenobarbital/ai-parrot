# TASK-4615: Fail *once* on a bad fan-out configuration

**Feature**: FEAT-725 — Re-arm the Observability Auto-Boot (`set_bootstrap_hook`)
**Spec**: `sdd/specs/fixgroup-f3ad5ee39704.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4614
**Assigned-to**: unassigned
**Discovered-from**: `issue:bd94e0afa8e6`

---

## Context

Lifts spec NG1 — the deliberate non-goal TASK-4614 left behind.

TASK-4613 installed the bootstrap hook, so `ensure_observability_bootstrapped()`
now runs on **every** `EventEmitterMixin._init_events()`. TASK-4614 made a
failing `setup_event_fanout()` loud (ERROR + re-raise) but kept it *outside*
the `_BOOTSTRAPPED` latch: the flag stays `False`, so every subsequent bot /
client / tool construction re-enters the lock, re-runs `setup_event_fanout()`
and re-raises. With the hook now installed that is a per-construction cost on
the hot path, and `_do_bootstrap()` never runs at all — a bad
`PARROT_EVENT_FANOUT_*` value silently disables *local* observability too.

`issue:bd94e0afa8e6` asked to decide between "fail once at process startup" and
"degrade with a warning". **Decision: fail loudly, once.** A durable fan-out
misconfiguration stays a startup error (the caller keeps seeing it raise — it
is never downgraded to a warning), but the *setup attempt* happens exactly once
and local observability is no longer collateral damage.

Verified while triaging the issue's second, unanswered question — *"whether
setup does blocking Redis I/O in the sync bootstrap"*: it does **not**.
`setup_event_fanout()` constructs `EventBus(...)`, whose `__init__` only builds
a `BusCore` and leaves `_started = False`; the connection is established lazily
on first publish. `_validate_bus()`, `attach_bus()` and `registry.subscribe()`
are all in-process. The only filesystem touch is outbox-path resolution. Spec
NG4 can therefore be closed as answered.

---

## Scope

- Add module state `_FANOUT_ERROR` (the cached exception) and `_FANOUT_ERROR_TB`
  (its original traceback) to `bootstrap.py`.
- In `ensure_observability_bootstrapped()`:
  - Catch a failing `setup_event_fanout()` instead of letting it propagate out
    of the lock. Keep TASK-4614's ERROR log — it must still fire exactly once.
  - Continue to `_do_bootstrap()` on that path, set `_BOOTSTRAPPED = True`, then
    re-raise the cached exception.
  - On every later call, re-raise the cached exception from the fast path
    *without* re-running `setup_event_fanout()` or `_do_bootstrap()`, and
    without logging again.
  - Re-raise via `.with_traceback(_FANOUT_ERROR_TB)` so repeatedly raising the
    same exception object cannot grow its traceback chain unboundedly on the
    construction hot path.
- Clear both new globals in `reset_bootstrap_for_tests()`.
- Update the module and function docstrings to state the fail-once contract.
- Rewrite `test_fanout_setup_failure_logs_error_and_raises` — it currently
  asserts the superseded `_BOOTSTRAPPED is False` and names this task's issue
  as the reason — and add the fail-once regression tests.

**NOT in scope**:
- Downgrading the fan-out failure to a warning / silent degradation. The
  caller still sees it raise; only the retry is removed.
- `parrot/observability/fanout.py` — `setup_event_fanout()` itself is
  unchanged.
- `parrot/core/events/lifecycle/__init__.py` (TASK-4613) and
  `tests/unit/observability/test_bootstrap_hook.py`.
- The body of `_do_bootstrap()` (spec NG3).

---

## Files to Create / Modify

**Modify**:
- `packages/ai-parrot/src/parrot/observability/bootstrap.py`
- `packages/ai-parrot/tests/unit/observability/test_bootstrap.py`

---

## Codebase Contract

### Verified Imports
- `from parrot.observability import bootstrap as boot` — used throughout
  `tests/unit/observability/test_bootstrap.py`.
- `from parrot.observability import fanout` — the test patches
  `fanout.setup_event_fanout`, because `bootstrap.py` imports it lazily
  *inside* the function.

### Existing Signatures
- `bootstrap.ensure_observability_bootstrapped() -> None`
- `bootstrap.reset_bootstrap_for_tests() -> None`
- `bootstrap._event_fanout_enabled() -> bool`
- `fanout.setup_event_fanout(bus: Any = None) -> None`
- Module globals present today: `_BOOTSTRAPPED`, `_LOCK`, `_SUBSCRIBER`,
  `_SUBSCRIPTION_IDS`, `_SHUTDOWN_TASKS`, `_ATEXIT_REGISTERED`.

### Does NOT Exist
- `_FANOUT_ERROR` / `_FANOUT_ERROR_TB` — created by this task.
- Any caller of `ensure_observability_bootstrapped()` that depends on the
  retry-on-every-construction behaviour.

---

## Acceptance Criteria

- AC1: With `PARROT_EVENT_FANOUT_ENABLED=true` and a raising
  `setup_event_fanout()`, the first `ensure_observability_bootstrapped()` logs
  ERROR `"Durable event fan-out setup failed"` and raises the original
  exception.
- AC2: After that first call, `_BOOTSTRAPPED is True`.
- AC3: `_do_bootstrap()` still ran on the failing-fan-out path — local
  observability is unaffected by a durable-bus misconfiguration.
- AC4: A second call raises the **same** exception object and does **not**
  call `setup_event_fanout()` again, does not re-enter `_do_bootstrap()`, and
  logs nothing further.
- AC5: Repeated calls do not grow `exc.__traceback__` without bound.
- AC6: `reset_bootstrap_for_tests()` clears the cached error, so a later
  successful bootstrap behaves normally.
- AC7: With fan-out disabled or succeeding, behaviour is byte-for-byte what
  TASK-4614 left: no raise, `_BOOTSTRAPPED is True`.

---

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src python -m pytest \
  packages/ai-parrot/tests/unit/observability/test_bootstrap.py \
  packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py \
  packages/ai-parrot/tests/unit/observability/test_bootstrap_cleanup.py \
  packages/ai-parrot/tests/unit/observability/test_event_fanout.py -q
ruff check packages/ai-parrot/src/parrot/observability/bootstrap.py \
  packages/ai-parrot/tests/unit/observability/test_bootstrap.py
```

---

## Test Specification

- `test_fanout_setup_failure_logs_error_and_raises` — rewritten for AC1–AC3.
- `test_fanout_failure_is_cached_and_not_retried` — AC4/AC5: patch
  `setup_event_fanout` with a call-counting raiser, call the bootstrap twice,
  assert one call, identical exception identity, and a bounded traceback.
- `test_reset_clears_cached_fanout_error` — AC6.

---

## Completion Note

_To be filled on completion._
