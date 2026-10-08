# TASK-4172: Fix the two stale host-layout assertions in test_namespace_imports.py

**Feature**: FEAT-644 — SchedulerManager base — target-agnostic scheduler (db | redis | code backends) with AgentSchedulerManager as a subclass
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4163
**Assigned-to**: unassigned
**discovered_from**: issue:e523973539f5

---

## Context

Promoted from ledger issue `issue:e523973539f5` (tech_debt/minor, discovered
during FEAT-644) by `/sdd-fix`, which routed it to the open parent FEAT-644:

> `packages/ai-parrot-server/tests/test_namespace_imports.py::TestHostStubFiles::test_handlers_host_only_stubs`
> (unexpected `spatial_filter_handler.py`, `dataset_filter_handler.py` in host
> `handlers/`) and `::TestHostPyprojectUpdates::test_scheduler_extra_removed`
> (host `pyproject.toml` still has a `scheduler` extra) fail on plain dev,
> independent of FEAT-644. Update the assertions or the layout.

Both failures are **stale assertions**, not layout regressions. The FEAT-203
extraction tests predate two deliberate decisions:

1. `packages/ai-parrot/src/parrot/handlers/spatial_filter_handler.py` (FEAT-219)
   and `dataset_filter_handler.py` (FEAT-225) live in core on purpose. Core's own
   tests import them from `parrot.handlers.*`
   (`packages/ai-parrot/tests/handlers/test_spatial_handler_compat.py`,
   `packages/ai-parrot/tests/integration/test_dataset_filter_handler.py`,
   `packages/ai-parrot/tests/integration/test_spatial_transport.py`), so moving
   them to the satellite would break core.
2. `packages/ai-parrot/pyproject.toml:357-367` documents FEAT-453 Decision D1:
   the core `scheduler = ["apscheduler==3.11.2"]` extra is an intentional,
   partial reversal of FEAT-203 ("This is NOT a regression to 'fix back'"),
   pinned to the satellite's exact `apscheduler==3.11.2` to avoid a split-brain
   dependency.

So fix the **tests**, not the layout. This file is also reformatted by FEAT-644
(black + a `scheduler/base.py` parametrize row), so implement against the
feature branch's version, in the FEAT-644 worktree.

---

## Scope

- Allow the two core-resident filter handlers in `test_handlers_host_only_stubs`,
  with a comment naming FEAT-219/FEAT-225 as the reason.
- Replace `test_scheduler_extra_removed` with `test_scheduler_extra_is_inprocess_only`:
  it asserts the host `scheduler` extra (if present) depends only on
  `apscheduler` and pins the same version as the satellite's
  `apscheduler==...` dependency (FEAT-453 D1), and never pulls `ai-parrot-server`.

**NOT in scope**: moving any handler file; editing either `pyproject.toml`;
`conftest.py` (the `host_pyproject_text` fixture is reused as-is); any other
test in this file; FEAT-644 scheduler code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_namespace_imports.py` | MODIFY | Update two stale host-layout assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pathlib  # verified: test_namespace_imports.py already imports it at module top
import pytest   # verified: test_namespace_imports.py already imports it at module top
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/tests/conftest.py:224 (session fixture)
def host_pyproject_text() -> str:  # text of packages/ai-parrot/pyproject.toml

# packages/ai-parrot-server/tests/test_namespace_imports.py (FEAT-644 branch line numbers)
class TestHostStubFiles:                                   # line 52
    def test_handlers_host_only_stubs(self): ...           # line 55
        unexpected = py_files - {"__init__.py", "vault_utils.py", "credentials_utils.py"}  # line 66
class TestHostPyprojectUpdates:                            # line 79
    def test_scheduler_extra_removed(self, host_pyproject_text): ...  # lines 82-96
```

Facts the assertions encode (verified 2026-10-09):
- `packages/ai-parrot/pyproject.toml:367` → `scheduler = ["apscheduler==3.11.2"]`
- `packages/ai-parrot-server/pyproject.toml:43` → `    "apscheduler==3.11.2",`
- `packages/ai-parrot/src/parrot/handlers/` top-level `.py`: `__init__.py`,
  `credentials_utils.py`, `vault_utils.py`, `spatial_filter_handler.py`,
  `dataset_filter_handler.py`

### Does NOT Exist
- ~~a `satellite_pyproject_text` fixture~~ — not in `conftest.py`; read
  `pathlib.Path(__file__).parent.parent / "pyproject.toml"` inline.
- ~~`tomllib` usage in this file~~ — the file uses regex over the raw text; keep it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/test_namespace_imports.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/tests/test_namespace_imports.py#TestHostStubFiles.test_handlers_host_only_stubs",
    "sym:packages/ai-parrot-server/tests/test_namespace_imports.py#TestHostPyprojectUpdates.test_scheduler_extra_removed"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the regex-over-text style of the surrounding tests; no new imports
  beyond `re` (already imported locally inside the old test).
- black, line length 120.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the allowed-set line in `test_handlers_host_only_stubs` — *why*: the
   two filter handlers are core-resident by design and core tests import them.
2. Replace `test_scheduler_extra_removed` wholesale with
   `test_scheduler_extra_is_inprocess_only` — *why*: FEAT-453 D1 re-added the
   extra on purpose; what must stay true is that it is apscheduler-only and
   pinned identically to the satellite.
3. Run the Validation Commands.

### `packages/ai-parrot-server/tests/test_namespace_imports.py` (MODIFY) — handlers
```python
# occurrences: 1 (verified: grep -c 'unexpected = py_files - {"__init__.py", "vault_utils.py", "credentials_utils.py"}')
# REPLACE the line `unexpected = py_files - {...}` (verified: FEAT-644 branch line 66) and its comment above with:
        # No other .py files should remain at the top level, except the
        # dataset/spatial filter handlers, which are core-resident by design
        # (FEAT-219 / FEAT-225) — core tests import them from parrot.handlers.
        allowed = {
            "__init__.py",
            "vault_utils.py",
            "credentials_utils.py",
            "spatial_filter_handler.py",
            "dataset_filter_handler.py",
        }
        unexpected = py_files - allowed
```

### `packages/ai-parrot-server/tests/test_namespace_imports.py` (MODIFY) — scheduler extra
```python
# occurrences: 1 (verified: grep -c 'def test_scheduler_extra_removed')
# REPLACE the whole method `test_scheduler_extra_removed` (FEAT-644 branch lines 82-96) with:
    def test_scheduler_extra_is_inprocess_only(self, host_pyproject_text):
        """Host scheduler extra exists only for the in-process scheduler (FEAT-453 D1).

        FEAT-203 moved scheduling to ai-parrot-server[scheduler]; FEAT-453
        deliberately re-added a core extra so an agent can run
        InProcessScheduler without the server distribution. It must stay
        apscheduler-only and pinned to the satellite's exact version.
        """
        import re

        match = re.search(r"^scheduler\s*=\s*\[(.*?)\]", host_pyproject_text, re.MULTILINE | re.DOTALL)
        if match is None:
            return  # extra removed entirely: also consistent with FEAT-203
        deps = re.findall(r'"([^"]+)"', match.group(1))
        # FILL IN: assert every dep starts with "apscheduler" and none mentions "ai-parrot-server"
        satellite = (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        sat_pin = re.search(r'"(apscheduler==[^"]+)"', satellite)
        # FILL IN: assert sat_pin is not None and sat_pin.group(1) in deps — bounded by the
        #          split-brain rule in packages/ai-parrot/pyproject.toml:357-366
```
**Why**: the old test asserted the opposite of a documented decision. The new
one guards what that decision actually promises (apscheduler-only, same pin).

### FILL IN checklist
- [ ] `test_scheduler_extra_is_inprocess_only` — the two assertions, with messages naming FEAT-453 D1.

---

## Acceptance Criteria

- [ ] `test_handlers_host_only_stubs` and `test_scheduler_extra_is_inprocess_only` pass.
- [ ] No other test in the file changes outcome.
- [ ] `ruff check packages/ai-parrot-server/tests/test_namespace_imports.py` is clean.
- [ ] No file other than the test file is modified.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_namespace_imports.py -q`

---

## Test Specification

The task *is* the test change; see the blueprint.

---

## Agent Instructions

1. Work in the FEAT-644 worktree `.claude/worktrees/feat-FEAT-644-scheduler-manager-base`.
2. Update this task to `"in-progress"` in `sdd/tasks/index/scheduler-manager-base.json`.
3. Implement from the blueprint, run the Validation Commands, commit only the test file.
4. Close with `scripts/sdd/close_task.sh TASK-4172 scheduler-manager-base verified`.
5. Fill in the Completion Note and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
