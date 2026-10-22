# TASK-4613: Install the observability bootstrap hook from `parrot.core.events.lifecycle`

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

Implements spec §3 Module 1 and Module 3 (AC1, AC2, AC3, AC7).

`ensure_observability_bootstrapped()` has had **no production caller** since
commit `b1388892f` (TASK-1828, 2026-07-20) deleted
`parrot/core/events/lifecycle/mixin.py`, whose `_init_events()` hard-imported
and called it. navigator-eventbus replaced that with an **injectable hook**
(`navigator_eventbus/lifecycle/mixin.py:29 set_bootstrap_hook`, invoked at
`:93`) — and ai-parrot never installs it, so `_bootstrap_hook` stays `None`
and the whole env-driven auto-boot is inert.

This task re-arms it: ai-parrot installs a lazily-importing hook at import
time of `parrot/core/events/lifecycle/__init__.py` — the single ai-parrot
module that re-exports `EventEmitterMixin`, and through which all three
consumers (`AbstractBot`, `AbstractClient`, `AbstractTool`) import it. That
reproduces the pre-`b1388892f` coverage exactly.

---

## Scope

- Import `set_bootstrap_hook` alongside the existing `EventEmitterMixin`
  import in `parrot/core/events/lifecycle/__init__.py`.
- Define a private, module-level `_observability_bootstrap_hook()` whose body
  **defers** `from parrot.observability.bootstrap import ...` to call time.
- Call `set_bootstrap_hook(_observability_bootstrap_hook)` at module import
  time, after `__all__`.
- Write a new unit module `tests/unit/observability/test_bootstrap_hook.py`
  covering installation, delegation, end-to-end `_init_events()` wiring, and
  the import-deferral guard.

**NOT in scope**:
- Any change to `parrot/observability/bootstrap.py` — docstring, log levels
  and the fan-out `try/except` all belong to **TASK-4614**. Do not touch that
  file, and do not edit `tests/unit/observability/test_bootstrap.py`.
- Any change to `navigator_eventbus` (external distribution; spec NG2).
- Adding `_observability_bootstrap_hook` to `__all__` — it is private by
  design.
- Call-once logic at the installation site (spec R2 — the hook runs on every
  `_init_events()` and `ensure_observability_bootstrapped` already
  short-circuits internally).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` | MODIFY | Import `set_bootstrap_hook`; define and install `_observability_bootstrap_hook` |
| `packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py` | CREATE | Regression guard for the hook wiring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/mixin.py:29
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook

# verified: packages/ai-parrot/src/parrot/observability/bootstrap.py:43 (lazy, in-function)
from parrot.observability.bootstrap import ensure_observability_bootstrapped
```

### Existing Signatures to Use

```python
# .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/mixin.py:26
_bootstrap_hook: Optional[Callable[[], None]] = None            # module global

# .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/mixin.py:29
def set_bootstrap_hook(hook: Optional[Callable[[], None]]) -> None: ...

# .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/mixin.py:93
#   _bootstrap_hook() is invoked inside a try/except Exception + logger.debug
#   guard spanning :90-95, from EventEmitterMixin._init_events()

# .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/mixin.py
class EventEmitterMixin:
    def _init_events(self, *, event_bus: Optional[object] = None,
                     forward_to_global: bool = True) -> None: ...

# packages/ai-parrot/src/parrot/observability/bootstrap.py:43
def ensure_observability_bootstrapped() -> None: ...
# packages/ai-parrot/src/parrot/observability/bootstrap.py:271
def reset_bootstrap_for_tests() -> None: ...
```

### Does NOT Exist

- ~~`parrot/core/events/lifecycle/mixin.py`~~ — deleted by `b1388892f`. Do NOT
  recreate it; ai-parrot no longer owns the mixin.
- ~~any existing `set_bootstrap_hook(...)` call under `packages/`~~ — this task
  adds the first one in the repository.
- ~~`parrot.observability.bootstrap.install_hook`~~ / ~~`_HOOK_INSTALLED`~~ —
  no such symbols; do not invent a second installation API.
- ~~`navigator_eventbus.lifecycle.mixin.get_bootstrap_hook`~~ — there is no
  getter; read the module global `_bootstrap_hook` directly in tests.
- ~~a conftest fixture that already resets `_bootstrap_hook`~~ — none exists;
  this test module owns its own teardown.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#ensure_observability_bootstrapped",
    "sym:packages/ai-parrot/src/parrot/observability/bootstrap.py#reset_bootstrap_for_tests"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The deferred import is load-bearing, not a style choice.**
  `parrot/observability/__init__.py` imports `provider` and `subscribers`,
  which import `parrot.core.events.lifecycle`. A module-level
  `from parrot.observability...` in the lifecycle package is circular.
  Keep the import inside the function body with `# noqa: PLC0415`.
- Google-style docstring and a full `-> None` annotation on the hook.
- Do not reorder or remove any existing import in the module.

### References in Codebase
- `git show b1388892f^:packages/ai-parrot/src/parrot/core/events/lifecycle/mixin.py`
  — the original call site this restores (lines 64-74 of that revision).
- `packages/ai-parrot/tests/unit/observability/test_bootstrap.py` — the
  `_clean` autouse fixture pattern (`boot.reset_bootstrap_for_tests()`).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the existing `navigator_eventbus.lifecycle.mixin` import with
   `set_bootstrap_hook` — *why*: it is the only supported installation API,
   and reusing the existing line keeps the import block's order untouched.
2. Append the hook function and the `set_bootstrap_hook(...)` call at the end
   of the module, after `__all__` — *why*: appending cannot disturb the
   re-export order other modules depend on, and the call must run at import
   time so the hook is armed before any mixin subclass is constructed.
3. Write `test_bootstrap_hook.py` with a fixture that saves and restores
   `mixin._bootstrap_hook` — *why*: a leaked stub hook would make unrelated
   test modules construct bots against a fake bootstrap (spec R5).
4. Run the Validation Commands — *why*: AC7 (no circular import) only shows up
   when the module is imported in a fresh interpreter.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` (MODIFY — import line)
```python
# occurrences: 1 (verified: grep -c 'from navigator_eventbus.lifecycle.mixin import EventEmitterMixin' packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py)
# REPLACE `from navigator_eventbus.lifecycle.mixin import EventEmitterMixin` (verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:24)
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook
```
**Why**: `set_bootstrap_hook` lives in the same module as the mixin that calls
it; one import line keeps the diff minimal. Do not move this line — the
`navigator_eventbus` imports must stay above the local
`parrot.core.events.lifecycle.*` imports.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` (MODIFY — append)
```python
# occurrences: 1 (verified: grep -c '    "WebhookSubscriber",' packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py)
# AFTER — append at end of file, below the closing `]` of `__all__` (verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:106)


def _observability_bootstrap_hook() -> None:
    """Run ai-parrot's env-driven observability auto-boot.

    Installed process-wide via :func:`set_bootstrap_hook` so that
    ``EventEmitterMixin._init_events()`` boots observability on the first
    bot/client/tool construction, as it did before FEAT-313 extracted the
    mixin to ``navigator_eventbus`` (the deleted ``mixin.py`` hard-imported
    the bootstrap at that point).

    The import is deferred to call time on purpose: ``parrot.observability``
    imports subscribers that import this very module, so a module-level
    import would be circular. ``ensure_observability_bootstrapped`` is itself
    idempotent, which the hook contract requires — the hook runs on *every*
    ``_init_events()`` call, not just the first.
    """
    from parrot.observability.bootstrap import ensure_observability_bootstrapped  # noqa: PLC0415

    ensure_observability_bootstrapped()


# FEAT-725: re-arm the auto-boot that b1388892f (TASK-1828) silently dropped
# when it deleted ai-parrot's own EventEmitterMixin.
set_bootstrap_hook(_observability_bootstrap_hook)
```
**Why this shape**: the hook is the whole fix — installing it is what makes
`OBSERVABILITY_ENABLED` and `PARROT_EVENT_FANOUT_ENABLED` do anything again
(AC1–AC3). The name stays underscore-prefixed and out of `__all__` because it
is an internal wiring detail, not public API. Do not add a guard such as
`if _bootstrap_hook is None` around the call: ai-parrot owns this hook slot,
and re-installing on re-import is harmless and idempotent.

### `packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py` (CREATE)
```python
"""Regression guard for the observability bootstrap hook (FEAT-725).

Commit ``b1388892f`` (TASK-1828) silently disarmed ai-parrot's env-driven
observability auto-boot by deleting the mixin that called it, and nothing
noticed for three months. These tests fail if the hook is ever uninstalled
again.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from navigator_eventbus.lifecycle import mixin as nav_mixin

from parrot.core.events import lifecycle


@pytest.fixture(autouse=True)
def _restore_hook():
    """Save and restore the process-wide hook around each test.

    A leaked stub would make every later-constructed bot/client/tool in this
    session boot against a fake, so restoration is mandatory, not tidiness.
    """
    previous = nav_mixin._bootstrap_hook
    yield
    nav_mixin.set_bootstrap_hook(previous)


def test_bootstrap_hook_is_installed() -> None:
    """Importing parrot.core.events.lifecycle arms the navigator-eventbus hook."""
    assert nav_mixin._bootstrap_hook is not None
    assert nav_mixin._bootstrap_hook is lifecycle._observability_bootstrap_hook


def test_hook_calls_ensure_observability_bootstrapped(monkeypatch) -> None:
    """The hook delegates to the bootstrap, once per invocation."""
    calls: list[int] = []
    # FILL IN: monkeypatch `ensure_observability_bootstrapped` on the
    # `parrot.observability.bootstrap` MODULE object (the hook imports it by
    # attribute lookup at call time) — bounded by AC2
    lifecycle._observability_bootstrap_hook()
    assert len(calls) == 1


def test_init_events_triggers_bootstrap(monkeypatch) -> None:
    """EventEmitterMixin._init_events() reaches the bootstrap end to end.

    This is the exact chain that regressed; assert the wiring, not a mock of it.
    """
    # FILL IN: patch the bootstrap as above, define a throwaway
    # `class _Host(EventEmitterMixin)`, call `_Host()._init_events()`, and
    # assert the bootstrap ran at least once — bounded by AC2
    raise NotImplementedError


def test_hook_import_is_deferred() -> None:
    """parrot.core.events.lifecycle imports without dragging in parrot.observability.

    Guards the circular-import deferral (AC7) in a FRESH interpreter — an
    in-process check is worthless because the test session has already
    imported both packages.
    """
    code = (
        "import sys; import parrot.core.events.lifecycle; "
        "sys.exit(1 if 'parrot.observability' in sys.modules else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
```
**Why this shape**: `test_bootstrap_hook_is_installed` is the minimal tripwire
for the original defect; `test_init_events_triggers_bootstrap` proves the
chain rather than the installation alone; `test_hook_import_is_deferred` must
use a subprocess because `sys.modules` is already polluted inside the suite.
Do not import `parrot.observability` at module scope in this file — that would
defeat the deferral test's premise for any runner that shares the module.

### FILL IN checklist
- [ ] `test_hook_calls_ensure_observability_bootstrapped` — how to patch the
      bootstrap so the hook's call-time attribute lookup sees it; bounded by AC2
- [ ] `test_init_events_triggers_bootstrap` — the throwaway mixin subclass and
      its assertion; bounded by AC2

---

## Acceptance Criteria

- [ ] `grep -rn "set_bootstrap_hook" packages/ai-parrot/src` returns the new
      call site (AC1)
- [ ] After `import parrot.core.events.lifecycle`,
      `navigator_eventbus.lifecycle.mixin._bootstrap_hook` is
      `lifecycle._observability_bootstrap_hook` (AC1)
- [ ] Constructing an `EventEmitterMixin` subclass calls
      `ensure_observability_bootstrapped()` (AC2)
- [ ] Importing `parrot.core.events.lifecycle` does not import
      `parrot.observability` (AC7)
- [ ] `_observability_bootstrap_hook` is NOT in `__all__`
- [ ] No linting errors: `ruff check` on both files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_bootstrap.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_event_fanout.py -q`

---

## Test Specification

See the blueprint block for
`packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py` — it is
the scaffold. Run it with
`PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/unit/observability/test_bootstrap_hook.py -q`
from the worktree root.

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
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4613 fixgroup-f3ad5ee39704 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-opus-5-5 (/sdd-fix issue:9296682eda19)
**Date**: 2026-10-22
**Notes**: Installed `set_bootstrap_hook(_observability_bootstrap_hook)` at the
end of `parrot/core/events/lifecycle/__init__.py`, with the
`parrot.observability.bootstrap` import deferred to call time. Verified live in
a fresh interpreter: `navigator_eventbus.lifecycle.mixin._bootstrap_hook is
lifecycle._observability_bootstrap_hook` is True and `parrot.observability` is
NOT in `sys.modules` after importing the lifecycle package (AC1, AC7).
New `tests/unit/observability/test_bootstrap_hook.py`: 4 tests, all passing —
installation, delegation, end-to-end `_init_events()` wiring, and a subprocess
import-deferral guard. `ruff check` clean on both files.
Validation: `test_bootstrap_hook.py` 4 passed; `test_bootstrap.py` +
`test_event_fanout.py` 21 passed.

**Deviations from spec**: none. Both blueprint `FILL IN` markers were resolved
as the blueprint predicted — the hook's lazy `from ... import` resolves the
attribute at call time, so `monkeypatch.setattr` on the
`parrot.observability.bootstrap` module object is what it sees.
