# TASK-4614: Make auto-boot and fan-out failures loud in `bootstrap.py`

**Feature**: FEAT-725 — Re-arm the Observability Auto-Boot (`set_bootstrap_hook`)
**Spec**: `sdd/specs/fixgroup-f3ad5ee39704.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:9296682eda19`

---

## Context

Implements spec §3 Module 2 (AC4, AC5, AC6).

The second defect recorded in `issue:9296682eda19`: navigator-eventbus wraps
the bootstrap hook in `try/except Exception` + `logger.debug()`
(`navigator_eventbus/lifecycle/mixin.py:90-95`). Once TASK-4613 installs the
hook, a *raising* bootstrap can never break construction and never surfaces
above DEBUG. FEAT-710's "startup fails loudly" contract is therefore
unachievable through the hook path alone — **loudness must come from
`bootstrap.py` logging at `error` level itself**. `navigator_eventbus` is an
external distribution and is not changed (spec NG2).

The module docstring is also stale: it still claims the function is *"Called
once (lazily, from `EventEmitterMixin._init_events`)"*, which has been false
since `b1388892f`.

---

## Scope

- Rewrite the stale sentence in `bootstrap.py`'s module docstring to describe
  the injectable-hook path (installed by `parrot.core.events.lifecycle`).
- Raise the swallowed `_do_bootstrap()` failure log from `logger.debug` to
  `logger.error` (same message, same `exc_info=True`).
- Wrap the `setup_event_fanout()` call so a failure is logged at `error` with
  `exc_info=True` **and then re-raised unchanged**.
- Extend `tests/unit/observability/test_bootstrap.py` with the two log-level
  regression tests named in spec §4.

**NOT in scope**:
- `parrot/core/events/lifecycle/__init__.py` and
  `tests/unit/observability/test_bootstrap_hook.py` — those are **TASK-4613**.
  Do not touch either file.
- **Fail-once / error-caching semantics** for a raising `setup_event_fanout()`
  (`issue:bd94e0afa8e6`, spec NG1). `_BOOTSTRAPPED` must still stay `False` on
  that path and the next construction must still retry. Only the logging
  changes.
- The body of `_do_bootstrap()` — backends, recorders, `ObservabilityConfig`
  resolution and the atexit flush are untouched (spec NG3).
- Investigating whether `setup_event_fanout()` performs blocking Redis I/O
  (spec NG4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | MODIFY | Docstring fix; `debug` → `error`; loud fan-out failure |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` | MODIFY | Two log-level regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# in the test module — both already imported there today
# verified: packages/ai-parrot/tests/unit/observability/test_bootstrap.py:8
from parrot.observability import bootstrap as boot
# verified: packages/ai-parrot/tests/unit/observability/test_bootstrap.py:7
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/bootstrap.py:30
logger = logging.getLogger("parrot.observability.bootstrap")

# packages/ai-parrot/src/parrot/observability/bootstrap.py:43
def ensure_observability_bootstrapped() -> None: ...
# packages/ai-parrot/src/parrot/observability/bootstrap.py:70
def _event_fanout_enabled() -> bool: ...
# packages/ai-parrot/src/parrot/observability/bootstrap.py:84
def _do_bootstrap() -> None: ...
# packages/ai-parrot/src/parrot/observability/bootstrap.py:271
def reset_bootstrap_for_tests() -> None: ...   # autouse `_clean` fixture already calls this

# packages/ai-parrot/src/parrot/observability/fanout.py:90
def setup_event_fanout(bus: Any = None) -> None: ...   # called with no argument
```

Existing test patterns in `test_bootstrap.py` / `test_event_fanout.py` that
these tests follow:

```python
# packages/ai-parrot/tests/unit/observability/test_bootstrap.py:11
@pytest.fixture(autouse=True)
def _clean(): ...           # calls boot.reset_bootstrap_for_tests() before and after

# packages/ai-parrot/tests/unit/observability/test_event_fanout.py:116-119
monkeypatch.delenv("PARROT_EVENT_FANOUT_ENABLED", raising=False)
monkeypatch.setattr(bootstrap, "_do_bootstrap", lambda: None)
monkeypatch.setattr(bootstrap, "_BOOTSTRAPPED", False)
```

### Does NOT Exist

- ~~`bootstrap._FANOUT_ERROR`~~ / ~~`bootstrap._fanout_failed`~~ — no cached
  error state exists. Do NOT add one; that is `issue:bd94e0afa8e6` (NG1).
- ~~`logger.critical` anywhere in `bootstrap.py`~~ — use `error`, matching the
  spec; do not escalate further.
- ~~`parrot.observability.fanout.setup_event_fanout_safe`~~ — no such helper.
- ~~a `caplog` fixture configured at package level~~ — none; set the level in
  the test with `caplog.at_level(logging.ERROR, logger="parrot.observability.bootstrap")`.
- ~~`ensure_observability_bootstrapped(force=...)`~~ — the function takes no
  arguments.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/bootstrap.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_bootstrap.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#ensure_observability_bootstrapped",
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#_do_bootstrap",
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#_event_fanout_enabled",
    "sym:packages/ai-parrot/src/parrot/observability/fanout.py#setup_event_fanout"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Keep the `raise`.** The fan-out branch must still propagate, leaving
  `_BOOTSTRAPPED` `False`. Converting it to a swallow, or caching the error,
  is a different ledger issue and would silently re-break FEAT-710's startup
  contract.
- **Expected log volume is the point, not a bug.** With fan-out enabled and
  misconfigured, `_BOOTSTRAPPED` is never set, so the new `logger.error` fires
  on *every* construction (spec R3). Do not add deduplication to soften it and
  do not downgrade the level.
- Lazy in-function imports keep their `# noqa: PLC0415` comments.
- Tests that mutate `boot._BOOTSTRAPPED` rely on the existing autouse `_clean`
  fixture; use `monkeypatch.setattr` so restoration is automatic.

### References in Codebase
- `packages/ai-parrot/tests/unit/observability/test_event_fanout.py:114-122` —
  `test_flag_off_does_not_setup_fanout`, the closest existing pattern for
  driving `ensure_observability_bootstrapped` with a patched `_do_bootstrap`.

---

## Implementation Blueprint

### Steps (in order)
1. Fix the module docstring sentence — *why*: it is the written contract
   future readers trust, and it currently points at a deleted call site (AC6).
2. Change the `except Exception` log from `debug` to `error` — *why*: the hook
   site logs at DEBUG, so an `error` record from here is the only thing an
   operator ever sees (AC4).
3. Wrap `setup_event_fanout()` in `try/except` → `logger.error(..., exc_info=True)`
   → bare `raise` — *why*: makes the misconfiguration visible without changing
   who sees the exception or when the retry happens (AC5).
4. Add the two regression tests — *why*: both changes are log-level-only and
   would otherwise be re-"simplified" away by a future refactor.

### `packages/ai-parrot/src/parrot/observability/bootstrap.py` (MODIFY — docstring)
```python
# occurrences: 1 (verified: grep -c 'Called once (lazily, from' packages/ai-parrot/src/parrot/observability/bootstrap.py)
# REPLACE the sentence beginning `Called once (lazily, from ``EventEmitterMixin._init_events``)`
# (verified: packages/ai-parrot/src/parrot/observability/bootstrap.py:3-4)
Invoked on every ``EventEmitterMixin._init_events()`` — i.e. on each bot/client/tool
construction — through the injectable bootstrap hook that
``parrot.core.events.lifecycle`` installs via
``navigator_eventbus.lifecycle.mixin.set_bootstrap_hook`` (FEAT-725). This
function is idempotent, which that hook contract requires: the first call does
the work, every later call returns on the ``_BOOTSTRAPPED`` check.
```
**Why**: the old wording described the pre-`b1388892f` hard import from a
module that no longer exists, which is exactly how the breakage stayed
invisible for three months. Keep the rest of the docstring (backend list,
FEAT-462 note, idempotency paragraph) unchanged.

### `packages/ai-parrot/src/parrot/observability/bootstrap.py` (MODIFY — fan-out branch)
```python
# occurrences: 1 (verified: grep -c '            setup_event_fanout()' packages/ai-parrot/src/parrot/observability/bootstrap.py)
# REPLACE `            setup_event_fanout()` and the two comment lines above it
# (verified: packages/ai-parrot/src/parrot/observability/bootstrap.py:59-61)
            # Invalid durable fan-out configuration is a startup error. This is
            # deliberately outside the best-effort local-observability guard —
            # but logged at error first (FEAT-725): the EventEmitterMixin hook
            # site swallows a raising hook at DEBUG, so without this the
            # misconfiguration would be completely silent in production.
            try:
                setup_event_fanout()
            except Exception:
                logger.error(
                    "Durable event fan-out setup failed; PARROT_EVENT_FANOUT_ENABLED "
                    "is set but no lifecycle event will reach the bus.",
                    exc_info=True,
                )
                raise
```
**Why**: the bare `raise` keeps today's semantics byte-for-byte —
`_BOOTSTRAPPED` is still not set and the next construction retries — while the
`error` record makes the failure reachable by an operator. Do not replace the
bare `raise` with `raise ... from` or a custom exception type.

### `packages/ai-parrot/src/parrot/observability/bootstrap.py` (MODIFY — guard log level)
```python
# occurrences: 1 (verified: grep -c 'logger.debug("Observability auto-boot failed; continuing.", exc_info=True)' packages/ai-parrot/src/parrot/observability/bootstrap.py)
# REPLACE `            logger.debug("Observability auto-boot failed; continuing.", exc_info=True)`
# (verified: packages/ai-parrot/src/parrot/observability/bootstrap.py:65)
            logger.error("Observability auto-boot failed; continuing.", exc_info=True)
```
**Why**: same message and traceback, visible level. The `except`/`finally`
structure around it does not change — construction must still never break.

### `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` (MODIFY — append tests)
```python
# occurrences: 1 (verified: grep -c '^from parrot.observability import bootstrap as boot' packages/ai-parrot/tests/unit/observability/test_bootstrap.py)
# AFTER — append at end of file; add `import logging` to the existing import block
# (verified: packages/ai-parrot/tests/unit/observability/test_bootstrap.py:8)


def test_bootstrap_failure_logs_at_error(monkeypatch, caplog) -> None:
    """A failing _do_bootstrap() is loud (ERROR) but never breaks construction.

    FEAT-725 AC4: the navigator-eventbus hook site logs at DEBUG, so this
    record is the only signal an operator gets.
    """
    def _boom() -> None:
        raise RuntimeError("bootstrap exploded")

    monkeypatch.setattr(boot, "_do_bootstrap", _boom)
    monkeypatch.setattr(boot, "_BOOTSTRAPPED", False)
    # FILL IN: disable the fan-out branch for this test so only _do_bootstrap
    # raises — bounded by AC4 (see test_event_fanout.py:116 for the env pattern)

    with caplog.at_level(logging.ERROR, logger="parrot.observability.bootstrap"):
        boot.ensure_observability_bootstrapped()  # must NOT raise

    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert boot._BOOTSTRAPPED is True


def test_fanout_setup_failure_logs_error_and_raises(monkeypatch, caplog) -> None:
    """A failing setup_event_fanout() is logged at ERROR and still propagates.

    FEAT-725 AC5 / NG1: the raise and the un-set _BOOTSTRAPPED are deliberate —
    fail-once caching is issue:bd94e0afa8e6, not this task.
    """
    monkeypatch.setattr(boot, "_BOOTSTRAPPED", False)
    # FILL IN: enable the fan-out flag and make `setup_event_fanout` raise.
    # NOTE the lazy import: bootstrap does `from parrot.observability.fanout
    # import setup_event_fanout` INSIDE the function, so patch the attribute on
    # the `parrot.observability.fanout` module, not on `boot` — bounded by AC5

    with caplog.at_level(logging.ERROR, logger="parrot.observability.bootstrap"):
        with pytest.raises(RuntimeError):
            boot.ensure_observability_bootstrapped()

    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert boot._BOOTSTRAPPED is False
```
**Why this shape**: both tests assert the *level*, not just that something was
logged — the defect being guarded is precisely a DEBUG-level record nobody
sees. The second test's `assert boot._BOOTSTRAPPED is False` is the NG1
tripwire: if someone later implements fail-once caching here instead of in
`issue:bd94e0afa8e6`, this test tells them they changed scope.

### FILL IN checklist
- [ ] `test_bootstrap_failure_logs_at_error` — how to keep the fan-out branch
      out of the way (env delete, per `test_event_fanout.py:116`); bounded by AC4
- [ ] `test_fanout_setup_failure_logs_error_and_raises` — enabling the flag and
      patching `parrot.observability.fanout.setup_event_fanout` (NOT `boot`,
      because the import is lazy and in-function); bounded by AC5

---

## Acceptance Criteria

- [ ] A failing `_do_bootstrap()` emits an `ERROR` record from
      `parrot.observability.bootstrap` and `ensure_observability_bootstrapped()`
      still returns normally with `_BOOTSTRAPPED is True` (AC4)
- [ ] A failing `setup_event_fanout()` emits an `ERROR` record **and** still
      raises; `_BOOTSTRAPPED` stays `False` (AC5)
- [ ] The module docstring no longer claims a direct call from
      `EventEmitterMixin._init_events` (AC6)
- [ ] `grep -c 'logger.debug("Observability auto-boot failed' bootstrap.py` is 0
- [ ] No new caching/dedup state was added (NG1 held)
- [ ] No linting errors: `ruff check` on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_event_fanout.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_cleanup.py -q`

---

## Test Specification

See the blueprint block for
`packages/ai-parrot/tests/unit/observability/test_bootstrap.py`. The existing
autouse `_clean` fixture already resets bootstrap module state around every
test — do not add a second reset fixture.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-f3ad5ee39704 --feature-id FEAT-725`)
2. **Read the spec** at `sdd/specs/fixgroup-f3ad5ee39704.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-f3ad5ee39704.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `FILL IN`
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the two files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4614 fixgroup-f3ad5ee39704 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-opus-5-5 (/sdd-fix issue:9296682eda19)
**Date**: 2026-10-22
**Notes**: Three edits to `bootstrap.py` as blueprinted — module docstring
rewritten to describe the hook path (AC6), the swallowed `_do_bootstrap()`
failure raised from `logger.debug` to `logger.error` (AC4), and
`setup_event_fanout()` wrapped so a failure logs at ERROR with `exc_info` and
is then re-raised by a bare `raise` (AC5). Two regression tests appended to
`test_bootstrap.py`, both asserting the log LEVEL (the defect being guarded is
a DEBUG record nobody sees) and `_BOOTSTRAPPED` state.
Validation: the full cached contract — `test_bootstrap_hook.py`,
`test_bootstrap.py`, `test_bootstrap_cleanup.py`, `test_event_fanout.py` —
35 passed. `ruff check` clean on both files.
NG1 held: no caching/dedup state was added; `_BOOTSTRAPPED` still stays False
on the fan-out path and the next construction still retries. The second new
test asserts exactly that, so `issue:bd94e0afa8e6` will have to change it
deliberately.

**Deviations from spec**: one addition. The *function* docstring of
`ensure_observability_bootstrapped()` also claimed "Never raises: any failure
is logged at DEBUG and swallowed" — false on both counts (it was already false
about the fan-out path before this change). Corrected it alongside the module
docstring; same file, same AC6 intent, no behaviour change.
