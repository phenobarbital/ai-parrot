---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [observability, lifecycle, eventbus, bootstrap, fanout]
---

# Feature Specification: Re-arm the Observability Auto-Boot (`set_bootstrap_hook`)

**Feature ID**: FEAT-725
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

> Ledger group `fixgroup:f3ad5ee39704` — resolves `issue:9296682eda19`
> (major, bug, discovered from `spec:FEAT-710`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`ensure_observability_bootstrapped()` has **no production caller anywhere in
the repository**. A repo-wide grep finds it only in
`parrot/observability/__init__.py` (re-export) and in the unit tests.

Cause, verified: commit `b1388892f` (*parrot-eventbus-migration, TASK-1828,
2026-07-20*) deleted `packages/ai-parrot/src/parrot/core/events/lifecycle/mixin.py`,
whose `_init_events()` ended with:

```python
try:
    from parrot.observability.bootstrap import ensure_observability_bootstrapped
    ensure_observability_bootstrapped()
except Exception:
    logger.debug("observability bootstrap skipped", exc_info=True)
```

navigator-eventbus replaced that hard import with an **injectable hook** —
`navigator_eventbus/lifecycle/mixin.py:29 set_bootstrap_hook()`, invoked from
`_init_events()` at `mixin.py:91-94`. ai-parrot **never calls
`set_bootstrap_hook`**, so the module-global `_bootstrap_hook` stays `None`
and the call site is a no-op.

Impact — since 2026-07-20 the entire env-driven auto-boot is inert:

- `OBSERVABILITY_ENABLED=true` registers no `UsageRecordingSubscriber`, so no
  logging/prometheus cost recording happens.
- FEAT-710's `PARROT_EVENT_FANOUT_ENABLED=true` never reaches
  `setup_event_fanout()`, so no lifecycle event is published to the durable bus.
- Neither takes effect unless an application calls the bootstrap by hand.
- `bootstrap.py`'s module docstring still claims it is *"Called once (lazily,
  from `EventEmitterMixin._init_events`)"* — false since the migration.

**Second defect on the same path.** `navigator_eventbus` `mixin.py:91-94`
wraps the hook in `try/except Exception` + `logger.debug()`. Once the hook is
installed, a *raising* bootstrap can never break construction and never
surfaces above DEBUG. FEAT-710's "startup fails loudly" contract (spec §7
Patterns, Q2) is therefore unachievable through the hook path alone —
loudness must come from `bootstrap.py` logging at `error`/`critical` itself.
`navigator_eventbus` is an external distribution; this feature does not
change it.

### Goals

- G1 — Install the bootstrap hook from ai-parrot so that
  `ensure_observability_bootstrapped()` runs again on the first
  `EventEmitterMixin._init_events()`, restoring the pre-`b1388892f` behaviour
  for every bot, client and tool.
- G2 — Make a swallowed auto-boot failure, and a failing durable fan-out
  setup, visible at `error` level from `bootstrap.py` itself, so the hook
  site's DEBUG-level guard cannot hide them.
- G3 — Correct `bootstrap.py`'s stale docstring to describe the hook path.
- G4 — Unit coverage that fails if the hook is ever uninstalled again
  (regression guard for the exact 2026-07-20 silent breakage).

### Non-Goals (explicitly out of scope)

- NG1 — The **fail-once / fail-loud caching semantics** for a raising
  `setup_event_fanout()` (`issue:bd94e0afa8e6`, minor, tech_debt). This
  feature unblocks it; it does not implement it. `setup_event_fanout()` keeps
  raising out of `ensure_observability_bootstrapped()` exactly as today — it
  only becomes *loud* first.
- NG2 — Any change to `navigator_eventbus` (external package): the DEBUG-level
  guard at its `mixin.py:91-94` stays as-is.
- NG3 — Changing what the auto-boot does once it runs (backends, recorders,
  `ObservabilityConfig` resolution, atexit flush) — the body of
  `_do_bootstrap()` is untouched.
- NG4 — Verifying whether `setup_event_fanout()` performs blocking Redis I/O
  in the sync bootstrap (left to `issue:bd94e0afa8e6`).

---

## 2. Architectural Design

### Overview

ai-parrot installs a **module-level, lazily-importing hook function** at
import time of `parrot/core/events/lifecycle/__init__.py` — the single
ai-parrot module that re-exports `EventEmitterMixin` and through which all
three mixin consumers (`AbstractBot`, `AbstractClient`, `AbstractTool`)
import it. Installing there reproduces exactly the coverage the deleted
`mixin.py` had, with no import cycle: the hook body defers
`from parrot.observability.bootstrap import ...` to first call, so importing
the lifecycle package never drags in `parrot.observability` (whose `__init__`
imports subscribers that themselves import `parrot.core.events.lifecycle`).

```
parrot.core.events.lifecycle.__init__        (import time)
        │  set_bootstrap_hook(_observability_bootstrap_hook)
        ▼
navigator_eventbus.lifecycle.mixin._bootstrap_hook
        │  called from EventEmitterMixin._init_events() (every construction)
        ▼
_observability_bootstrap_hook()              (lazy import)
        ▼
parrot.observability.bootstrap.ensure_observability_bootstrapped()
        │  idempotent via _BOOTSTRAPPED / _LOCK
        ├─ _event_fanout_enabled() → setup_event_fanout()   (raises; now logged at error first)
        └─ _do_bootstrap()                                  (guarded; now logged at error)
```

### Integration Points

| Module | Change |
|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` | Import `set_bootstrap_hook`, define `_observability_bootstrap_hook()`, call `set_bootstrap_hook(...)` at import time |
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | Docstring correction; `logger.debug` → `logger.error` for the swallowed `_do_bootstrap()` failure; log the fan-out setup failure at `error` before re-raising |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py` | **New** — regression guard that the hook is installed and wired |

### Data Models

None — no new or modified Pydantic models.

### New Public Interfaces

None. `_observability_bootstrap_hook` is private (underscore-prefixed) and is
deliberately **not** added to `parrot.core.events.lifecycle.__all__`.

---

## 3. Module Breakdown

### Module 1: Hook installation (`parrot.core.events.lifecycle`)

Add alongside the existing `from navigator_eventbus.lifecycle.mixin import
EventEmitterMixin`:

```python
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook


def _observability_bootstrap_hook() -> None:
    """Run ai-parrot's env-driven observability auto-boot.

    Installed process-wide via ``set_bootstrap_hook`` so that
    ``EventEmitterMixin._init_events()`` boots observability on the first
    bot/client/tool construction, as it did before FEAT-313 extracted the
    mixin (the deleted ``mixin.py`` hard-imported the bootstrap here).

    The import is deferred to call time: ``parrot.observability`` imports
    subscribers that import this very module, so a module-level import would
    be circular. ``ensure_observability_bootstrapped`` is itself idempotent,
    which the hook contract requires (it runs on *every* ``_init_events()``).
    """
    from parrot.observability.bootstrap import ensure_observability_bootstrapped  # noqa: PLC0415

    ensure_observability_bootstrapped()


# FEAT-725: re-arm the auto-boot that b1388892f (TASK-1828) silently dropped.
set_bootstrap_hook(_observability_bootstrap_hook)
```

Placement: after the `navigator_eventbus` imports and before the local
`parrot.core.events.lifecycle.*` imports is acceptable, but the simplest
diff keeps the import on the existing line and appends the function +
`set_bootstrap_hook(...)` call at the **end of the module, after `__all__`**,
so no existing import order changes.

### Module 2: Loud failures (`parrot.observability.bootstrap`)

1. Module docstring, first paragraph: replace

   > Called once (lazily, from ``EventEmitterMixin._init_events``) the first time any
   > bot/client/tool is constructed.

   with wording that names the hook path and FEAT-725 — the mixin now calls an
   *injectable* hook that ai-parrot installs from
   `parrot.core.events.lifecycle`.

2. In `ensure_observability_bootstrapped()`, the `except Exception` branch:
   `logger.debug("Observability auto-boot failed; continuing.", exc_info=True)`
   becomes `logger.error(...)` — same message and `exc_info`, higher level.
   Reason: the hook site in `navigator_eventbus` logs at DEBUG, so an
   `error`-level record from here is the only thing an operator sees.

3. Wrap the fan-out branch so the failure is loud before it propagates:

   ```python
   if _event_fanout_enabled():
       from parrot.observability.fanout import setup_event_fanout  # noqa: PLC0415

       # Invalid durable fan-out configuration is a startup error. Deliberately
       # outside the best-effort local-observability guard — but logged at
       # error first (FEAT-725): the EventEmitterMixin hook site swallows a
       # raising hook at DEBUG, so without this the misconfiguration is silent.
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

   The `raise` preserves today's semantics exactly (`_BOOTSTRAPPED` stays
   `False`, the next construction retries). Converting that to fail-once is
   `issue:bd94e0afa8e6`, out of scope here (NG1).

### Module 3: Regression test (`tests/unit/observability/test_bootstrap_hook.py`)

New module. Must not depend on import ordering within the session: import
`navigator_eventbus.lifecycle.mixin` and `parrot.core.events.lifecycle`
explicitly, then assert against the module global.

---

## 4. Test Specification

### Unit Tests

`packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py`:

| Test | Asserts |
|---|---|
| `test_bootstrap_hook_is_installed` | After importing `parrot.core.events.lifecycle`, `navigator_eventbus.lifecycle.mixin._bootstrap_hook` is not `None` and is `lifecycle._observability_bootstrap_hook` |
| `test_hook_calls_ensure_observability_bootstrapped` | Monkeypatch `parrot.observability.bootstrap.ensure_observability_bootstrapped` with a counter; call the hook; counter == 1 |
| `test_init_events_triggers_bootstrap` | A throwaway `class _X(EventEmitterMixin)` calling `_init_events()` invokes the patched bootstrap at least once — the end-to-end wiring, the exact thing that regressed |
| `test_hook_import_is_deferred` | `parrot.core.events.lifecycle` can be imported with `parrot.observability` absent from `sys.modules` (guards the circular-import deferral) |

`packages/ai-parrot/tests/unit/observability/test_bootstrap.py` (extend):

| Test | Asserts |
|---|---|
| `test_bootstrap_failure_logs_at_error` | With `OBSERVABILITY_ENABLED=true` and `_do_bootstrap` monkeypatched to raise, `caplog` at `ERROR` contains the auto-boot failure record, and the call still returns normally (`_BOOTSTRAPPED` is `True`) |
| `test_fanout_setup_failure_logs_error_and_raises` | With fan-out enabled and `setup_event_fanout` monkeypatched to raise, `pytest.raises` still fires **and** an `ERROR` record was emitted first; `_BOOTSTRAPPED` stays `False` |

### Integration Tests

None. The `test_init_events_triggers_bootstrap` case above covers the
mixin→hook→bootstrap chain in-process; no external service is involved.

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py
- packages/ai-parrot/tests/unit/observability/test_bootstrap.py
- packages/ai-parrot/tests/unit/observability/test_bootstrap_cleanup.py
- packages/ai-parrot/tests/unit/observability/test_event_fanout.py
markers: none

> Lint is not part of the cached contract; each task runs it on its own files:
> `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py
> packages/ai-parrot/src/parrot/observability/bootstrap.py
> packages/ai-parrot/tests/unit/observability/`
>
> `test_bootstrap_cleanup.py` and `test_event_fanout.py` are listed although
> neither task edits them: they drive `ensure_observability_bootstrapped()`
> directly and are the nearest thing to a blast-radius check for the hook now
> firing on every construction.

### Test Data / Fixtures

Existing `tests/unit/observability/` fixtures. Tests that mutate
`bootstrap._BOOTSTRAPPED` must restore it (the existing module already does
this — follow its pattern), and any test that calls `set_bootstrap_hook` must
restore the previous hook in a `finally`/fixture teardown so it does not leak
into other test modules.

---

## 5. Acceptance Criteria

- **AC1** — `grep -rn "set_bootstrap_hook" packages/*/src` returns at least one
  ai-parrot call site; importing `parrot.core.events.lifecycle` leaves
  `navigator_eventbus.lifecycle.mixin._bootstrap_hook` non-`None`.
- **AC2** — Constructing any `EventEmitterMixin` subclass (bot, client or
  tool) calls `ensure_observability_bootstrapped()` exactly as before
  `b1388892f`; with `OBSERVABILITY_ENABLED=true` a `UsageRecordingSubscriber`
  is registered on the global registry without any application code.
- **AC3** — With `PARROT_EVENT_FANOUT_ENABLED=true` and a valid config,
  `setup_event_fanout()` runs on first construction.
- **AC4** — A failing `_do_bootstrap()` emits an `ERROR` record from
  `parrot.observability.bootstrap` and still does not break construction.
- **AC5** — A failing `setup_event_fanout()` emits an `ERROR` record **and**
  still raises out of `ensure_observability_bootstrapped()` (unchanged
  semantics; NG1).
- **AC6** — `bootstrap.py`'s module docstring no longer claims it is called
  from `EventEmitterMixin._init_events` directly; it describes the hook.
- **AC7** — Importing `parrot.core.events.lifecycle` does not import
  `parrot.observability` (no circular import, no startup cost regression).
- **AC8** — The validation contract in §4 exits 0.

---

## 6. Codebase Contract

### Verified Imports

```python
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook   # VERIFIED
from parrot.observability.bootstrap import ensure_observability_bootstrapped           # VERIFIED
from parrot.observability.fanout import setup_event_fanout                             # VERIFIED (lazy, in-function)
#   fanout.py:90  def setup_event_fanout(bus: Any = None) -> None  — called with no argument
```

### Existing Signatures

```python
# .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/mixin.py:29
def set_bootstrap_hook(hook: Optional[Callable[[], None]]) -> None: ...
# module global at mixin.py:26
_bootstrap_hook: Optional[Callable[[], None]] = None
# invoked at mixin.py:93, inside the try/except Exception + logger.debug at mixin.py:90-95

# packages/ai-parrot/src/parrot/observability/bootstrap.py:43
def ensure_observability_bootstrapped() -> None: ...
```

### Integration Points

- `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:24` —
  `from navigator_eventbus.lifecycle.mixin import EventEmitterMixin`
- `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` —
  `__all__` ends at the `"WebhookSubscriber"` entry
- `packages/ai-parrot/src/parrot/observability/bootstrap.py:55-66` — the
  fan-out branch (`setup_event_fanout()` at :61) and the `except Exception`
  guard (`logger.debug` at :65) inside `ensure_observability_bootstrapped()`

### Does NOT Exist (Anti-Hallucination)

- ❌ `parrot/core/events/lifecycle/mixin.py` — deleted by `b1388892f`. Do not
  recreate it; ai-parrot no longer owns the mixin.
- ❌ Any existing `set_bootstrap_hook` call in `packages/` — this feature adds
  the first one.
- ❌ `parrot.observability.bootstrap.install_hook` / `_HOOK_INSTALLED` — no
  such symbol; do not invent a second installation API.
- ❌ A `conftest.py` fixture that already resets `_bootstrap_hook` — none
  exists; the new test module owns its teardown.

### Edit Sites (Blueprint Anchors)

| File | Anchor | Edit |
|---|---|---|
| `parrot/core/events/lifecycle/__init__.py` | `from navigator_eventbus.lifecycle.mixin import EventEmitterMixin` | add `, set_bootstrap_hook` |
| `parrot/core/events/lifecycle/__init__.py` | end of file (after the closing `]` of `__all__`) | append `_observability_bootstrap_hook` + `set_bootstrap_hook(...)` |
| `parrot/observability/bootstrap.py` | `"""ensure_observability_bootstrapped — env-driven, idempotent auto-boot.` | rewrite the "Called once (lazily, …)" sentence |
| `parrot/observability/bootstrap.py` | `            setup_event_fanout()` | wrap in try/except → `logger.error(..., exc_info=True)` → `raise` |
| `parrot/observability/bootstrap.py` | `logger.debug("Observability auto-boot failed; continuing.", exc_info=True)` | → `logger.error(...)` |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Lazy, in-function imports with `# noqa: PLC0415`, matching the existing
  style throughout `bootstrap.py`.
- `self.logger` is not available at module scope here; `bootstrap.py` already
  owns `logger = logging.getLogger("parrot.observability.bootstrap")`.
- Google-style docstrings and full type hints (`-> None`) on the new hook.

### Known Risks / Gotchas

- **R1 — Import cycle.** `parrot/observability/__init__.py` imports
  `provider`/`subscribers`, which import `parrot.core.events.lifecycle`. The
  hook body **must** keep its import deferred to call time. A module-level
  `from parrot.observability...` in the lifecycle package will deadlock the
  import graph. AC7 guards this.
- **R2 — The hook runs on every `_init_events()`**, not just the first:
  idempotency is the hook's responsibility. `ensure_observability_bootstrapped`
  already short-circuits on `_BOOTSTRAPPED` as its first statement — do not
  add call-once logic at the installation site.
- **R3 — Error-log volume.** With fan-out enabled and misconfigured,
  `_BOOTSTRAPPED` is never set, so the new `logger.error` fires on *every*
  construction. This is the intended loudness for now and is the precise
  motivation for `issue:bd94e0afa8e6` (fail once, cache the error). Do not
  pre-empt that fix here; do not downgrade the level to avoid the noise.
- **R4 — Previously dormant code now runs.** Any environment that already
  sets `OBSERVABILITY_ENABLED` / `PARROT_EVENT_FANOUT_ENABLED` has been
  silently inert since 2026-07-20 and will start doing real work after this
  lands. That is the fix, but it is a behavioural change worth calling out in
  the PR body.
- **R5 — Test leakage.** A test that installs its own hook must restore the
  previous value; otherwise unrelated modules in the same session construct
  bots against a stubbed bootstrap.

### External Dependencies

- `navigator-eventbus` (already a dependency) — `set_bootstrap_hook` has
  existed since FEAT-313/TASK-1822. No version bump required; no change to
  that package is in scope.

---

## 8. Open Questions

None. The installation point, the deferral and the loudness level were all
settled against the verified pre-`b1388892f` behaviour; the fail-once
question is explicitly deferred to `issue:bd94e0afa8e6` (NG1).

---

## 9. Design Research Cross-Check

- `mem-40b90db332de` (wiki memory, *"Observability auto-boot is dead since the
  eventbus migration"*) — agrees on cause, blast radius and the DEBUG-guard
  consequence.
- `ledger::issue:bd94e0afa8e6` — records that its own premise is unreachable
  until this feature lands, and names the chosen follow-up semantics.
- `sdd/tasks/completed/TASK-1822-mixin-bootstrap-hook.md` — the task that
  introduced the injectable hook; confirms the hook was *designed* to be
  installed by ai-parrot and that nobody ever did it.

---

## Revision History

| Rev | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial spec — ledger group `fixgroup:f3ad5ee39704` / `issue:9296682eda19` |
