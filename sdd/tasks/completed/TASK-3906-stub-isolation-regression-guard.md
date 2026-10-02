# TASK-3906: Regression guard — conftest stubs must never shadow real modules

**Feature**: FEAT-617 — Unpoison `packages/ai-parrot/tests` collection (merge-gate unblock)
**Spec**: `sdd/specs/manager-test-bot-cleanup-lifecycle-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3903
**Assigned-to**: unassigned

---

## Context

TASK-3903 replaces 37 `sys.modules.setdefault()` calls with `_stub_if_absent()` so a
test stub can never pre-empt a healthy module. Nothing currently stops that from
silently regressing: the failure mode is invisible (tests still "run"), it only shows
up as collection errors in an unrelated file much later, and it has now happened
**twice** — FEAT-268 fixed one instance (`_install_parrot_stubs`), and
`issue:c3c59277ef77` is the second.

This task adds the guard that makes a third occurrence fail loudly and immediately.

`discovered_from: issue:c3c59277ef77`

## Scope

A new test module asserting (a) `_stub_if_absent`'s contract directly, and (b) that
after conftest import, every first-party name the installers may stub still resolves to
a module with a real `__file__` — the `(unknown location)` tell from the original issue.

**NOT in scope**:
- Any change to `conftest.py` (TASK-3903 owns that file exclusively).
- The stale-test repairs (TASK-3904, TASK-3905) or `pytest-timeout` (TASK-3907).
- Guarding `packages/ai-parrot/tests/unit/conftest.py`'s separate, smaller stub
  installer — out of scope for this feature.
- Any change under `src/` (spec AC9).

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/tests/test_conftest_stub_isolation.py` | CREATE | regression guard |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import importlib.util   # stdlib
import sys              # stdlib
import types            # stdlib
import pytest           # verified: used throughout packages/ai-parrot/tests/
```
`_stub_if_absent` is defined in `packages/ai-parrot/tests/conftest.py` (created by
TASK-3903). A `conftest.py` is **not** importable as a normal module by name — import
it explicitly, e.g. via `importlib.util.spec_from_file_location` against
`Path(__file__).parent / "conftest.py"`, or via the `pytest` plugin manager.

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/conftest.py  (as delivered by TASK-3903)
def _stub_if_absent(name: str, module: types.ModuleType) -> bool:
    """Returns True if the stub was installed, False if the real module won."""

def _install_navconfig_stub() -> None:      # line 89
def _install_navigator_stubs() -> None:     # line 173
_install_navconfig_stub()                   # line 720 — runs at conftest import
_install_navigator_stubs()                  # line 721 — runs at conftest import
```

The six symbols named in `issue:c3c59277ef77`, all verified importable standalone on
`dev` @ `883fe4480`:
```python
aiohttp.FormData
aiohttp.web.Application
parrot._imports.load_satellite_attr
parrot.registry.agent_registry
parrot.tools.filemanager.FileManagerTool
parrot.handlers.crew.execution_history_handler   # ships from ai-parrot-server
```

### Does NOT Exist
- ~~`import conftest`~~ — a conftest is not importable by plain module name
- ~~`_stub_if_absent` before TASK-3903 lands~~ — this task is blocked on it
- ~~`parrot.tools.cryptoquant`~~ — genuinely absent; a valid "really missing" case for the stub path
- ~~a public API that lists the stubbed names~~ — the test enumerates them explicitly

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/tests/test_conftest_stub_isolation.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/conftest.py#_stub_if_absent"
  ]
}
```

## Implementation Notes

### Pattern to Follow
Assert on `__file__`: a `types.ModuleType` stub has no `__file__`, a real module does.
That is precisely the `(unknown location)` signal in the original ImportErrors, so it is
the most faithful possible guard.

### Key Constraints
- The guard must be **meaningful**: AC-5 requires demonstrating it FAILS if
  `_stub_if_absent` is reverted to `sys.modules.setdefault` (spec AC6).
- Do not import `conftest.py` by name — load it by path.
- The test runs inside the same pytest process whose conftest already executed at
  import, so `sys.modules` already reflects the installers' effect. Assert on that
  live state; do not re-run the installers.
- No `src/` changes (spec AC9).

### References in Codebase
- `conftest.py:722-727` — FEAT-268's note on the first occurrence of this bug
- `sdd/tasks/completed/TASK-1689-scope-conftest-parrot-bots-stub-leak.md` — the prior fix

## Implementation Blueprint

### Steps (in order)
1. Enumerate the first-party names the installers stub which are nevertheless genuinely
   importable — these are the ones that must NOT be shadowed.
2. Write `test_real_modules_are_not_shadowed`: for each name, assert the live
   `sys.modules` entry (if present) has a real `__file__`. This is the guard that
   catches a regression in the live pytest process.
3. Write direct unit tests for `_stub_if_absent`'s three branches, loading `conftest.py`
   by path.
4. Demonstrate AC-5 by temporarily reverting one `_stub_if_absent` call in `conftest.py`
   to `sys.modules.setdefault`, confirming the guard fails, then restoring it. Record
   the observed failure output in the Completion Note. **Do not commit the revert.**

### `packages/ai-parrot/tests/test_conftest_stub_isolation.py` (CREATE)
```python
"""Regression guard: conftest stubs must never shadow a real module.

FEAT-617 / issue:c3c59277ef77. ``tests/conftest.py`` installs ~37 lightweight
``types.ModuleType`` stubs so the tree stays importable when optional third-party
packages (navigator, asyncdb, querysource, navconfig) are missing. The original
``sys.modules.setdefault(name, stub)`` asked "is this name already imported?" rather
than "is the real module available?", so a stub pre-empted any module that simply had
not been imported yet — poisoning 14 of 18 collection errors in this tree.

The tell was ``(unknown location)`` in the resulting ImportError: a ``ModuleType``
stub has no ``__file__``. These tests assert that tell can never reappear.

This bug has now occurred twice (FEAT-268 fixed the first instance). Do not delete
this module.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

CONFTEST_PATH = Path(__file__).parent / "conftest.py"

# First-party names the installers may stub which ARE genuinely importable.
# Each was verified to import standalone on dev@883fe4480 while simultaneously
# failing inside a full-tree collection — the exact signature of the bug.
REAL_MODULES_THAT_MUST_NOT_BE_STUBBED = (
    "aiohttp",
    "aiohttp.web",
    "parrot._imports",
    "parrot.registry",
    "parrot.tools.filemanager",
)


def _load_conftest() -> types.ModuleType:
    """Load tests/conftest.py by path — a conftest is not importable by name."""
    spec = importlib.util.spec_from_file_location("_feat617_conftest", CONFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", REAL_MODULES_THAT_MUST_NOT_BE_STUBBED)
def test_real_modules_are_not_shadowed(name: str) -> None:
    """A genuinely importable module must never be replaced by a stub.

    Asserts the live sys.modules entry has a real __file__. A types.ModuleType
    stub has none — that absence is the '(unknown location)' tell from
    issue:c3c59277ef77.
    """
    # FILL IN: import the module (importlib.import_module), then assert the resulting
    # sys.modules[name] has a non-None __file__ pointing at a real path on disk.
    # Bounded by AC-1 and spec AC3: this must hold DURING a full-tree collection,
    # not only standalone.


def test_stub_if_absent_does_not_replace_resolvable_module() -> None:
    """A resolvable module wins: returns False and leaves sys.modules untouched."""
    # FILL IN: pick a stdlib name guaranteed resolvable but NOT yet in sys.modules
    # (remove it first if needed, e.g. a rarely-imported stdlib module), call
    # _stub_if_absent(name, types.ModuleType(name)), assert it returned False and that
    # sys.modules does not hold the stub. Bounded by AC-2.


def test_stub_if_absent_installs_for_missing_module() -> None:
    """A genuinely absent module gets the stub: returns True and installs it."""
    # FILL IN: use a name that cannot resolve (e.g. "parrot.tools.cryptoquant", verified
    # absent, or a random unresolvable name). Assert True and that sys.modules holds the
    # stub. Clean up with sys.modules.pop(name, None) in a finally block so the entry
    # does not leak into other tests — the very failure mode this file guards against.
    # Bounded by AC-3.


def test_stub_if_absent_respects_existing_sys_modules_entry() -> None:
    """A name already in sys.modules is never overwritten."""
    # FILL IN: insert a sentinel ModuleType under a unique name, call _stub_if_absent
    # with a DIFFERENT module, assert it returned False and the sentinel is still the
    # sys.modules entry. Clean up in a finally block. Bounded by AC-4.
```
**Why this shape**: `test_real_modules_are_not_shadowed` is the guard that actually
catches a regression, because it runs in the live pytest process where the installers
already executed — it is parametrized so a failure names the exact poisoned module. The
three `_stub_if_absent` unit tests pin the helper's contract branch by branch. Every
test that mutates `sys.modules` must clean up in a `finally`, otherwise this guard
becomes the next source of cross-test pollution.

### FILL IN checklist
- [ ] `test_real_modules_are_not_shadowed` body (the import + `__file__` assertion)
- [ ] `test_stub_if_absent_does_not_replace_resolvable_module` body
- [ ] `test_stub_if_absent_installs_for_missing_module` body + `finally` cleanup
- [ ] `test_stub_if_absent_respects_existing_sys_modules_entry` body + `finally` cleanup
- [ ] AC-5 demonstration: temporary revert, observed failure, restore (do NOT commit the revert)

## Acceptance Criteria

- [ ] **AC-1** `test_real_modules_are_not_shadowed` passes for all 5 parametrized names
- [ ] **AC-2** `_stub_if_absent` returns `False` and does not install for a resolvable module
- [ ] **AC-3** `_stub_if_absent` returns `True` and installs for a genuinely absent module
- [ ] **AC-4** `_stub_if_absent` never overwrites an existing `sys.modules` entry
- [ ] **AC-5** The guard **fails** when `_stub_if_absent` is reverted to `sys.modules.setdefault`; failure output recorded in the Completion Note (spec AC6)
- [ ] **AC-6** No test leaks a `sys.modules` entry (every mutation cleaned up in `finally`)
- [ ] **AC-7** `ruff check` clean on the new file
- [ ] **AC-8** No file under `src/` is modified (spec AC9)

## Validation Commands
- `pytest packages/ai-parrot/tests/test_conftest_stub_isolation.py -q`
- `pytest packages/ai-parrot/tests/test_conftest_stub_isolation.py -v -rA`

## Test Specification

| Test | Asserts |
|---|---|
| `test_real_modules_are_not_shadowed[aiohttp]` | live `sys.modules["aiohttp"].__file__` is a real path |
| `test_real_modules_are_not_shadowed[aiohttp.web]` | same — this is the `Application` AttributeError's source |
| `test_real_modules_are_not_shadowed[parrot._imports]` | same — `load_satellite_attr`'s source |
| `test_real_modules_are_not_shadowed[parrot.registry]` | same — `agent_registry`'s source |
| `test_real_modules_are_not_shadowed[parrot.tools.filemanager]` | same — `FileManagerTool`'s source |
| `test_stub_if_absent_does_not_replace_resolvable_module` | returns `False`, `sys.modules` untouched |
| `test_stub_if_absent_installs_for_missing_module` | returns `True`, stub installed, cleaned up |
| `test_stub_if_absent_respects_existing_sys_modules_entry` | returns `False`, sentinel preserved |

## Agent Instructions

1. Test-only change. Do not touch `src/`, and do **not** edit `conftest.py` — TASK-3903
   owns it exclusively; concurrent edits would conflict.
2. **AC-5 is not optional.** A guard that cannot fail is not a guard. Perform the
   temporary revert, capture the failure output, restore the file, and confirm
   `git status` is clean for `conftest.py` before committing.
3. Every `sys.modules` mutation needs `finally` cleanup — this module must not become
   the next polluter.
4. Run with `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note

**Completed by**: Claude Opus 5 (/sdd-fix issue:c3c59277ef77)
**Date**: 2026-10-01
**Verification**: verified — 9 passed.

Guards both halves of the fix. Beyond the specified tests, added
`test_conftest_has_no_executable_setdefault_calls`, which pins the pattern itself
while ignoring prose and commented-out references (the literal grep count is 3 and
always will be).

**AC-5 demonstrated.** Reverting ONE `_stub_if_absent` call back to
`sys.modules.setdefault` fails exactly two tests:
`test_real_modules_are_not_shadowed[parrot.tools.filemanager]` and
`test_conftest_has_no_executable_setdefault_calls`. The conftest was restored
immediately and the revert was never committed (`git status` clean before commit).

For the restore-hook half, pairing one polluter with this guard was inconclusive —
that pair errors identically with and without the hook, so it is independently
broken. The load-bearing evidence is instead the full-tree delta: **13 collection
errors with the hook disabled vs 3 with it enabled.**

All `sys.modules` mutations clean up in `finally`, so this module cannot become the
next polluter. AC-1..AC-8 ✅.
