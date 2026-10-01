# TASK-3903: Add `_stub_if_absent()` choke point so conftest stubs never shadow real modules

**Feature**: FEAT-617 — Unpoison `packages/ai-parrot/tests` collection (merge-gate unblock)
**Spec**: `sdd/specs/manager-test-bot-cleanup-lifecycle-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`issue:c3c59277ef77` (critical) reports that sdd-coder merge-tier validation cannot
reach a clean outcome for any feature touching widely-reached core files, because
`packages/ai-parrot/tests/` fails collection wholesale — **18 collection errors** on
`dev` @ `883fe4480`.

**14 of those 18 are self-inflicted.** `tests/conftest.py` installs 37 lightweight
`types.ModuleType` stubs via `sys.modules.setdefault()` at *conftest import time*.
`setdefault` asks "is this name already in `sys.modules`?" — a question about import
*order*, not availability. Any name not yet imported gets the stub, and the real
module's symbols vanish for the rest of the pytest process.

The tell is `(unknown location)` in the ImportError: a `types.ModuleType` stub has no
`__file__`. Verified examples, all of which import fine standalone:
`aiohttp.FormData`, `aiohttp.web.Application`, `parrot._imports.load_satellite_attr`,
`parrot.registry.agent_registry`, `parrot.tools.filemanager.FileManagerTool`,
`parrot.handlers.crew.execution_history_handler`.

FEAT-268/TASK-1689 already fixed this exact class of bug once — for
`_install_parrot_stubs()`, by converting it into the opt-in `fake_parrot_bots`
fixture (`conftest.py:465`, note at `conftest.py:722-727`). The two remaining
installers were never converted. **This task finishes that job.**

`discovered_from: issue:c3c59277ef77`

## Scope

Add a single helper, `_stub_if_absent(name, module)`, and route **every**
`sys.modules.setdefault(...)` call inside `_install_navconfig_stub()` and
`_install_navigator_stubs()` through it. The helper installs the stub only when the
real module genuinely cannot be resolved, so a healthy module always wins.

**NOT in scope**:
- The 4 genuinely-stale test files (TASK-3904, TASK-3905) — different root cause.
- The regression guard test (TASK-3906) — depends on this task.
- `pytest-timeout` (TASK-3907).
- Deleting the stubs outright (spec §8 Q3 — deliberately left open).
- Any change under `src/` (spec AC9 — this is a test-infrastructure fix).
- `fake_parrot_bots` (`conftest.py:465`) — already correct, leave untouched.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/tests/conftest.py` | MODIFY | add `_stub_if_absent`; route all 37 setdefault sites |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import importlib.util   # stdlib — NOT yet imported by conftest.py; must be added
import sys              # verified: conftest.py:7
import types            # verified: conftest.py:11
```
`conftest.py` imports (verified `conftest.py:1-15`): `logging, os, sys, dataclasses,
io.BytesIO, pathlib.Path, types, typing, pandas as pd, pytest`. **`importlib.util` is
not among them** — add it.

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/conftest.py
def _install_navconfig_stub() -> None:      # line 89
def _install_navigator_stubs() -> None:     # line 173
_install_navconfig_stub()                   # line 720  (unconditional module-scope call)
_install_navigator_stubs()                  # line 721  (unconditional module-scope call)

@pytest.fixture
def fake_parrot_bots(monkeypatch):           # line 465 — FEAT-268 precedent, DO NOT TOUCH
```
`grep -c 'sys\.modules\.setdefault(' packages/ai-parrot/tests/conftest.py` → **37**
(verified at `883fe4480`).

### Does NOT Exist
- ~~`_stub_if_absent`~~ — this task creates it
- ~~`importlib` / `importlib.util` in conftest.py~~ — not currently imported
- ~~`_install_parrot_stubs()`~~ — removed by FEAT-268; do NOT resurrect
- ~~`pytest_timeout`~~ — not installed (TASK-3907 adds it)
- ~~a `conftest.py` fixture that undoes the stubs~~ — the stubs are module-scope, not fixture-scope

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/tests/conftest.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/conftest.py#_install_navconfig_stub",
    "sym:packages/ai-parrot/tests/conftest.py#_install_navigator_stubs"
  ]
}
```

## Implementation Notes

### Pattern to Follow
FEAT-268's `fake_parrot_bots` (`conftest.py:465`) is the house precedent for scoping
stubs. This task applies the same lesson along a different axis: **availability**
rather than opt-in. Keep the docstring style and the explanatory `# NOTE (FEAT-...)`
comment convention already used at `conftest.py:722-727`.

### Key Constraints
- The fallback behaviour for genuinely-absent optional dependencies must be
  **byte-identical** to today. `navigator`, `asyncdb`, `querysource` and `navconfig`
  are not guaranteed installed; if they are missing, their stubs must still land.
- Never overwrite a name already present in `sys.modules` (preserves `setdefault`'s
  original contract for the already-imported case).
- No `src/` changes (spec AC9).

### References in Codebase
- `conftest.py:722-727` — FEAT-268's note explaining the previous instance of this bug
- `packages/ai-parrot/tests/unit/conftest.py` — a separate, smaller stub installer (out of scope)

## Implementation Blueprint

### Steps (in order)
1. Add `import importlib.util` to the stdlib import block — because `find_spec()` is
   the availability check the whole fix turns on, and it is not currently imported.
2. Define `_stub_if_absent()` immediately **above** `_install_navconfig_stub()`
   (`conftest.py:89`) — because both installers call it, so it must be defined before
   either runs at module scope (lines 720-721).
3. Mechanically replace all **37** `sys.modules.setdefault(X, Y)` occurrences inside
   the two installers with `_stub_if_absent(X, Y)`. The argument order is identical,
   so this is a literal substitution — do **not** reorder or restructure the
   surrounding stub-construction code.
4. Verify `grep -c 'sys\.modules\.setdefault(' packages/ai-parrot/tests/conftest.py`
   returns `0` (spec AC2).
5. Run the full-tree collection and confirm the error count drops from 18 to **≤ 4**
   (the 4 Bucket-B stale tests owned by TASK-3904/3905 will remain).

### `packages/ai-parrot/tests/conftest.py` (MODIFY — import block)
```python
# occurrences: 1 (verified: grep -c 'import types' packages/ai-parrot/tests/conftest.py)
# AFTER — insert below `import types` (verified: packages/ai-parrot/tests/conftest.py:11)
import importlib.util
```
**Why**: `find_spec()` must be importable before `_stub_if_absent` runs at module
scope. Placed with the other stdlib imports to match the file's existing grouping.

### `packages/ai-parrot/tests/conftest.py` (MODIFY — new helper)
```python
# occurrences: 1 (verified: grep -c 'def _install_navconfig_stub() -> None:' packages/ai-parrot/tests/conftest.py)
# BEFORE — insert above `def _install_navconfig_stub() -> None:` (verified: packages/ai-parrot/tests/conftest.py:89)

def _stub_if_absent(name: str, module: types.ModuleType) -> bool:
    """Register ``module`` under ``name`` only if the real module is unavailable.

    FEAT-617 / issue:c3c59277ef77. The previous ``sys.modules.setdefault(name, stub)``
    asked "is this name already imported?" — a question about import *order*, not
    availability — so a stub pre-empted any real module that simply had not been
    imported yet, and its symbols vanished for the rest of the pytest process. The
    tell was ``(unknown location)`` in the resulting ImportError: a ``ModuleType``
    stub has no ``__file__``. That poisoned 14 of 18 collection errors in this tree.

    The stub's legitimate purpose — keeping tests importable when an optional
    third-party dependency (navigator, asyncdb, querysource, navconfig) is genuinely
    missing — is preserved exactly: if the real module cannot be resolved, the stub
    still lands.

    Args:
        name: Fully-qualified module name, e.g. ``"parrot.tools.filemanager"``.
        module: The lightweight stand-in to install if the real module is absent.

    Returns:
        True if the stub was installed, False if the real module won (or the name
        was already present in ``sys.modules``).
    """
    if name in sys.modules:
        # Preserve setdefault's original contract for the already-imported case.
        return False
    # FILL IN: resolve availability — call importlib.util.find_spec(name) and treat a
    # non-None spec as "real module exists, do not stub" (return False).
    # find_spec() imports the PARENT package, so it can raise rather than return None:
    # catch (ImportError, AttributeError, ValueError) and treat ANY failure as absent,
    # so the fallback for genuinely-missing optional deps stays identical to today.
    # Bounded by: spec R1, AC3.
    sys.modules[name] = module
    return True
```
**Why this shape**: the early `name in sys.modules` return keeps the original
`setdefault` semantics for names already imported, so the change is strictly additive
— the only new behaviour is deferring to a resolvable real module. Returning `bool`
is what TASK-3906's guard asserts on. The broad `except` is deliberate: a `find_spec`
failure must degrade to *install the stub*, never to crash conftest import, or every
test in the tree dies instead of 18 collecting badly.

### `packages/ai-parrot/tests/conftest.py` (MODIFY — 37 call sites)
```python
# occurrences: 37 (verified: grep -c 'sys\.modules\.setdefault(' packages/ai-parrot/tests/conftest.py)
# Mechanical substitution across both installers, e.g. at conftest.py:264:
#   BEFORE: sys.modules.setdefault("parrot.tools.filemanager", _parrot_tools_fm)
#   AFTER:  _stub_if_absent("parrot.tools.filemanager", _parrot_tools_fm)
```
**Why**: 37 occurrences means no single anchor is unique — apply this as a
whole-file substitution of the literal `sys.modules.setdefault(` → `_stub_if_absent(`
**restricted to the bodies of `_install_navconfig_stub` (line 89) and
`_install_navigator_stubs` (line 173)**. Confirm no `sys.modules.setdefault(` survives
anywhere in the file afterwards (AC2); if one appears outside those two functions,
stop and report it rather than converting it blindly.

### FILL IN checklist
- [ ] `_stub_if_absent` body: the `find_spec` availability check and its `except` clause
- [ ] Confirm all 37 call sites converted (`grep -c` → 0)
- [ ] Confirm no `sys.modules.setdefault(` exists outside the two installers

## Acceptance Criteria

- [ ] **AC-1** `grep -c 'sys\.modules\.setdefault(' packages/ai-parrot/tests/conftest.py` → `0` (spec AC2)
- [ ] **AC-2** `_stub_if_absent` returns `False` and leaves `sys.modules` untouched for a resolvable module
- [ ] **AC-3** `_stub_if_absent` returns `True` and installs the stub for a genuinely absent module
- [ ] **AC-4** `_stub_if_absent` never overwrites a name already in `sys.modules`
- [ ] **AC-5** Full-tree collection errors drop from **18** to **≤ 4** (remaining 4 owned by TASK-3904/3905)
- [ ] **AC-6** The 6 symbols in spec AC3 resolve to a real `__file__` **during a full-tree collection**
- [ ] **AC-7** Collected test count does not regress below **22873** (spec AC5)
- [ ] **AC-8** `ruff check` clean on `conftest.py`
- [ ] **AC-9** No file under `src/` is modified (spec AC9)

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/test_combined_callback.py packages/ai-parrot/tests/test_botmanager_flags.py packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py -q`
- `pytest packages/ai-parrot/tests/interfaces/obsidian/test_rest_backend.py packages/ai-parrot/tests/unit/forms/test_shim.py -q`

Full-tree evidence for AC-5/AC-7 (not a validation command — a directory target is
forbidden by FEAT-563; run it by hand and paste the counts into the Completion Note):
```bash
python -m pytest --collect-only -q packages/ai-parrot/tests/ 2>&1 | tail -5
```

## Test Specification

Unit coverage for `_stub_if_absent` itself is **TASK-3906's** deliverable
(`test_conftest_stub_isolation.py`), to keep this task's diff to the one file.
This task's own evidence is the 14 previously-erroring files that must now collect:

```
packages/ai-parrot/tests/interfaces/obsidian/test_rest_backend.py
packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py
packages/ai-parrot/tests/test_botmanager_flags.py
packages/ai-parrot/tests/test_lazy_imports.py
packages/ai-parrot/tests/test_notification.py
packages/ai-parrot/tests/test_scheduler_report_decorators.py
packages/ai-parrot/tests/test_schedules.py
packages/ai-parrot/tests/test_stdio_concurrency.py
packages/ai-parrot/tests/unit/forms/test_shim.py
packages/ai-parrot/tests/unit/handlers/test_artifact_html_serving.py
packages/ai-parrot/tests/unit/scripts/test_recompute_contextual_embeddings.py
packages/ai-parrot/tests/unit/test_combined_callback.py
packages/ai-parrot/tests/interfaces/test_file_shim.py
packages/ai-parrot/tests/manager/test_bot_cleanup_lifecycle.py
```

## Agent Instructions

1. This is a **test-infrastructure** task. Do not touch `src/`.
2. Expect **R2 (unmasking)**: letting real modules win may surface new *failures* in
   tests that silently relied on a stub's narrow surface. That is the fix working.
   Record any such test in the Completion Note; repair it only if it is one of the
   14 files above, otherwise report it rather than widening scope.
3. `parrot.tools.filemanager`'s stub carries only `FileManagerFactory` (`conftest.py:264`).
   Once the real module wins, check consumers of `FileManagerFactory` still pass.
4. Run tests with `PYTHONPATH=packages/ai-parrot/src`.
5. This task is **exclusive**: it rewrites a `conftest.py` every other task's tests load.

## Completion Note

<!-- filled in on completion -->
**Completed by**:
**Date**:
