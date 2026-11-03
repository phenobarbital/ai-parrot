# TASK-5112: Move `bounded-source` into core (`parrot.tools.optimizations`)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12, amendment C35)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4077 (done; created the bounded-source template)
**Assigned-to**: unassigned

---

## Context

The first end-to-end SDD run in a foreign repo (sandbox project, FEAT-1 `stats-module`) showed that the shipped
`sdd-worker` agent uses MCP tools from two servers: `parrot-sdd-coder` (core — `parrot.flows.dev_loop.sdd_coder`)
and `parrot-bounded-source` (`mcp__parrot-bounded-source__source_inspect_batch`). The second one is
`parrot_tools.tool_optimizations.reader.BoundedSourceToolkit`, shipped by the optional **ai-parrot-tools**
distribution, so a repo that installs only `ai-parrot` cannot register it. Decision (Jesus Lara, 2026-11-03):
move it to core so the SDD install (TASK-5113) can always register it.

Spec rev 0.12 amendment C35 is the normative text. It is a deliberate exception to "concrete toolkits live in
ai-parrot-tools": the SDD flow ships in core and must not depend on an optional distribution.

---

## Scope

- Create core package `packages/ai-parrot/src/parrot/tools/optimizations/` and **move** (git mv + edit, not copy)
  these modules from `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/`:
  `base.py`, `models.py`, `policy.py`, `inspection_models.py`, `inspection.py`, `reader.py`.
  Rewrite their absolute imports (`parrot_tools.tool_optimizations.X` → `parrot.tools.optimizations.X`); keep the
  relative ones. The new package `__init__.py` re-exports the same public names those modules export today
  through the lazy `_EXPORTS` map in `parrot_tools/tool_optimizations/__init__.py` (PEP 562 `__getattr__`, stays
  stdlib-light on import).
- Leave a one-module alias at each old path so the module object is shared (monkeypatching and `isinstance`
  keep working across both spellings):
  ```python
  """Moved to :mod:`parrot.tools.optimizations.reader` (FEAT-633 C35); kept as an alias."""
  import sys
  from parrot.tools.optimizations import reader as _moved
  sys.modules[__name__] = _moved
  ```
  `parrot_tools/tool_optimizations/__init__.py`'s `_EXPORTS` keeps resolving every name (the alias modules make the
  existing `import_module(f".{module_name}", __name__)` return the core module).
- Make `WorktreeLock` (in `policy.py`) portable: no module-level `import fcntl`. Use `fcntl.flock` on POSIX and
  `msvcrt.locking` on Windows, both imported inside the lock code path; same advisory, non-blocking-with-retry
  semantics and the same `LockTimeoutError`.
- Point `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml` at
  `parrot.tools.optimizations.reader.BoundedSourceToolkit` and drop its `parrot:requires_dist` /
  `parrot:requires_pip` lines.
- Update the `bounded_source` entry of the toolkit registry in `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
  to the core class path (the old path still resolves through the alias, but the registry should name the real one).
- Write `packages/ai-parrot/tests/tools/test_optimizations_core.py`.

**NOT in scope**:
- `writer.py`, `patches.py`, `git.py`, `hooks.py`, `installation.py`, `contracts.py` stay in ai-parrot-tools (they
  keep importing `models`/`policy`/`base` through the aliases or, preferably, the new core path — either works).
- The `targeted-writer` and `local_git` toolkits, and the Read/Bash optimizer hooks (`installation.install_guards`).
- Registering the toolkit from `parrot sdd install` (TASK-5113).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/optimizations/__init__.py` | CREATE | Lazy public re-exports (PEP 562) |
| `packages/ai-parrot/src/parrot/tools/optimizations/base.py` | CREATE | Moved from parrot_tools |
| `packages/ai-parrot/src/parrot/tools/optimizations/models.py` | CREATE | Moved |
| `packages/ai-parrot/src/parrot/tools/optimizations/policy.py` | CREATE | Moved; portable `WorktreeLock` |
| `packages/ai-parrot/src/parrot/tools/optimizations/inspection_models.py` | CREATE | Moved |
| `packages/ai-parrot/src/parrot/tools/optimizations/inspection.py` | CREATE | Moved; imports rewritten |
| `packages/ai-parrot/src/parrot/tools/optimizations/reader.py` | CREATE | Moved (`BoundedSourceToolkit`) |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py` | MODIFY | `sys.modules` alias |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py` | MODIFY | alias |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py` | MODIFY | alias |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection_models.py` | MODIFY | alias |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py` | MODIFY | alias |
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py` | MODIFY | alias |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | registry path → core |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml` | MODIFY | core class, no requires_dist |
| `packages/ai-parrot/tests/tools/test_optimizations_core.py` | CREATE | core import, alias identity, portable lock, template |

---

## Codebase Contract (Anti-Hallucination)

Verified on `origin/feat-FEAT-633-parrot-installer` at `577ebd9056` (2026-11-03).

### Verified Imports
```python
from parrot.tools.decorators import tool_schema                                   # used by reader.py:31
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError   # reader.py:32, policy.py:29
from parrot.tools.abstract import ToolResult                                       # base.py:23
from parrot.tools.toolkit import AbstractToolkit                                   # base.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/  (sizes: reader 717, inspection 712, models 488,
#                                                                 policy 390, base 231, inspection_models 206 lines)
reader.py:      class BoundedSourceToolkit(OptimizationToolkitBase)        # exported, __all__ line 57
                imports .base, .inspection, .inspection_models, .models, .policy (lines 35-39)
inspection.py:  absolute imports of parrot_tools.tool_optimizations.{inspection_models,models,policy} (lines 26-39);
                TYPE_CHECKING import of ...reader.BoundedSourceToolkit (line 42)
policy.py:      import fcntl  (line 21) — module level; WorktreeLock (line 329) uses fcntl.flock at 370 and 387
base.py:        class OptimizationToolkitBase(AbstractToolkit); imports .models, .policy
__init__.py:    __all__ (line 18) + _EXPORTS name->submodule map + PEP 562 __getattr__ (lines 79-102)

# packages/ai-parrot/src/parrot/tools/__init__.py
_CORE_SUBMODULES = frozenset({*.py stems} | {dirs with __init__.py})   # line 45 — a new optimizations/ dir is core
                                                                       # automatically; the redirect finder skips it

# packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml
#   lines 3-4: "# parrot:requires_dist: parrot_tools" / "# parrot:requires_pip: ai-parrot-tools"
#   line 6:    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit

# packages/ai-parrot-tools/src/parrot_tools/__init__.py:130
#   "bounded_source": "parrot_tools.tool_optimizations.reader.BoundedSourceToolkit",
```

### Does NOT Exist
- ~~`parrot.tools.optimizations`~~ — created by this task
- ~~a Windows lock in `policy.py`~~ — `WorktreeLock` is fcntl-only today; `import fcntl` fails at import on Windows
- ~~any core module importing `parrot_tools`~~ — after the move, nothing under `packages/ai-parrot/src` may import `parrot_tools` for these modules

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/base.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/inspection_models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/inspection.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/optimizations/reader.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_optimizations_core.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/reader.py#BoundedSourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/policy.py#WorktreeLock",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py#OptimizationToolkitBase",
    "sym:packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/inspection.py#InspectionRunner"
  ]
}
```

---

## Implementation Notes

- Use `git mv` for each module, then put the alias file back at the old path, so `git log --follow` keeps history.
- The alias must be the whole old module (no other code). Do not `from ... import *` — that would create a second
  module object and break `monkeypatch.setattr("parrot_tools.tool_optimizations.policy.X", ...)` in existing tests.
- `ai-parrot-tools` already depends on `ai-parrot`, so the aliases add no new dependency.
- Windows lock: `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` on a 1-byte region, retried like the flock loop; unlock
  with `LK_UNLCK`. Test the POSIX path for real and the import path with `fcntl` removed (`monkeypatch.setitem(sys.modules, "fcntl", None)` + reload).

---

## Acceptance Criteria

- [ ] `from parrot.tools.optimizations.reader import BoundedSourceToolkit` works with ai-parrot-tools NOT importable
      (test hides `parrot_tools` via `sys.modules`).
- [ ] `parrot_tools.tool_optimizations.reader is parrot.tools.optimizations.reader` (same for the other five).
- [ ] `parrot.tools.optimizations.policy` imports with `fcntl` unavailable; `WorktreeLock` still serializes two
      processes on POSIX (existing `test_policy.py` lock tests pass).
- [ ] The packaged `bounded-source` template names the core class and has no `requires_dist`;
      `parrot toolkits list` no longer shows `parrot_tools (missing)` for it.
- [ ] The existing ai-parrot-tools suites `test_reader.py`, `test_inspection.py`, `test_policy.py`, `test_writer.py`,
      `test_hooks.py` pass unchanged.
- [ ] `ruff check` clean on every touched file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_optimizations_core.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_reader.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_inspection.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_policy.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_writer.py -q`
- `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_hooks.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_optimizations_core.py
import importlib
import sys

import pytest


MOVED = ("base", "models", "policy", "inspection_models", "inspection", "reader")


def test_core_import_without_parrot_tools(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "parrot_tools", None)
    reader = importlib.import_module("parrot.tools.optimizations.reader")
    assert hasattr(reader, "BoundedSourceToolkit")


@pytest.mark.parametrize("name", MOVED)
def test_legacy_path_is_the_same_module(name: str) -> None:
    pytest.importorskip("parrot_tools")
    legacy = importlib.import_module(f"parrot_tools.tool_optimizations.{name}")
    assert legacy is importlib.import_module(f"parrot.tools.optimizations.{name}")


def test_policy_imports_without_fcntl(monkeypatch) -> None: ...
def test_bounded_source_template_points_at_core() -> None: ...
```

---

## Agent Instructions

1. **Work in the feature worktree** — branch `feat-FEAT-633-parrot-installer` (never on `dev`)
2. **Read the spec** amendment C35 (§3 M6, "Rev 0.12 amendments C34–C35")
3. **Verify the Codebase Contract** before moving anything
4. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`, commit only that file
5. **Implement**, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
6. **Commit the code** — stage only the files listed above (the `git mv` renames included)
7. **Close the task** with `parrot sdd task close TASK-5112 parrot-installer verified`
8. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
