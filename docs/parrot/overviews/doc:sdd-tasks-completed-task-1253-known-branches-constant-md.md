---
type: Wiki Overview
title: 'TASK-1253: Add `KNOWN_BRANCHES` constant to `sdd_meta`'
id: doc:sdd-tasks-completed-task-1253-known-branches-constant-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 1** of FEAT-187. It adds a small additive
---

# TASK-1253: Add `KNOWN_BRANCHES` constant to `sdd_meta`

**Feature**: FEAT-187 — Git Parrot Flow — Staging Branch and Sync Automation
**Spec**: `sdd/specs/git-parrot-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements **Module 1** of FEAT-187. It adds a small additive
constant to `scripts/sdd/sdd_meta.py` that downstream SDD commands use
to warn (not refuse) when a spec's `base_branch` falls outside the
canonical set `{main, staging, dev}`. The constant is the anchor for
Modules 3 and 4, which reference it from command-side validation.

The change is intentionally additive: no behavioural change to
`FlowMeta` or `parse()`. The schema-level validator that hotfixes must
target `main` stays as-is. The new `KNOWN_BRANCHES` is a public
module-level export.

---

## Scope

- Add `KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})`
  at module scope in `scripts/sdd/sdd_meta.py`.
- Add a one-line docstring above the constant explaining its purpose
  (canonical long-lived branches; used by commands for soft validation,
  not by `FlowMeta` itself).
- Extend `tests/sdd_scripts/test_sdd_meta.py` with two tests covering
  the membership and immutability of the constant.

**NOT in scope**:
- Any change to `FlowMeta`, `parse()`, or `emit()`.
- Any consumer-side use of `KNOWN_BRANCHES` — that lives in TASK-1255
  (`/sdd-done`) and TASK-1256 (other SDD commands).
- Adding `staging` to the `_hotfix_implies_main` validator. The hotfix
  rule stays unchanged: hotfix MUST be `main`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/sdd_meta.py` | MODIFY | Add `KNOWN_BRANCHES` module-level constant + docstring |
| `tests/sdd_scripts/test_sdd_meta.py` | MODIFY | Add two tests for the new constant |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/sdd/sdd_meta.py — current imports (verified 2026-05-19)
from __future__ import annotations
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator
```

No new imports needed. `frozenset` is a builtin.

### Existing Signatures to Use
```python
# scripts/sdd/sdd_meta.py:21-30 (verified 2026-05-19)
class FlowMeta(BaseModel):
    """SDD flow metadata derived from a doc's YAML frontmatter."""
    type: Literal["feature", "hotfix"]
    base_branch: str

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":
        if self.type == "hotfix" and self.base_branch != "main":
            raise ValueError(...)
        return self
```

The module is ~85 lines total. Add `KNOWN_BRANCHES` between the
imports block and the `FlowMeta` class.

### Does NOT Exist
- ~~`tests/scripts/test_sdd_meta.py`~~ — the spec says this path; the
  ACTUAL path is `tests/sdd_scripts/test_sdd_meta.py`. The spec was
  written from the migration script's expected path, not the
  realised path. Use the real one.
- ~~A schema-level `Literal` for `base_branch`~~ — `base_branch` is a
  free-form `str` and stays that way. Do NOT change it to
  `Literal["main", "staging", "dev"]`.
- ~~`SDDFlowMeta.KNOWN_BRANCHES`~~ — the constant is module-level, not
  a class attribute of `FlowMeta`.

---

## Implementation Notes

### Pattern to Follow

Add the constant as a module-level export right before the `FlowMeta`
class declaration:

```python
# scripts/sdd/sdd_meta.py — proposed insertion

#: Canonical long-lived branches in the Git Parrot Flow (FEAT-187).
#: Commands use this for a soft warning when ``base_branch`` falls
#: outside the set; ``FlowMeta`` itself accepts any string so
#: sub-feature branches keep working (see CLAUDE.md).
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})


class FlowMeta(BaseModel):
    ...
```

Then in `tests/sdd_scripts/test_sdd_meta.py`, add two tests at the
bottom of the existing test file (do not introduce a new file):

```python
def test_known_branches_contains_main_staging_dev():
    from scripts.sdd.sdd_meta import KNOWN_BRANCHES
    assert KNOWN_BRANCHES == frozenset({"main", "staging", "dev"})


def test_known_branches_is_frozenset():
    from scripts.sdd.sdd_meta import KNOWN_BRANCHES
    assert isinstance(KNOWN_BRANCHES, frozenset)
```

### Key Constraints
- The constant MUST be a `frozenset`, not a `set` or `list`. Mutability
  on shared module-level state is a foot-gun.
- The docstring MUST cite FEAT-187 so future readers can trace
  provenance.
- Do NOT export from `scripts/sdd/__init__.py` unless the existing
  `__init__.py` already re-exports `FlowMeta` (check first; if it
  doesn't, leave it alone).

### References in Codebase
- `scripts/sdd/sdd_meta.py:1-85` — current state of the module
- `tests/sdd_scripts/test_sdd_meta.py` — existing test file to extend

---

## Acceptance Criteria

- [ ] `KNOWN_BRANCHES` is defined as `frozenset({"main", "staging", "dev"})` at module scope in `scripts/sdd/sdd_meta.py`.
- [ ] A docstring above the constant cites FEAT-187 and its purpose.
- [ ] `from scripts.sdd.sdd_meta import KNOWN_BRANCHES` works.
- [ ] Two new tests pass: `pytest tests/sdd_scripts/test_sdd_meta.py -v` (membership + immutability).
- [ ] No existing tests in `tests/sdd_scripts/` regress.
- [ ] `ruff check scripts/sdd/sdd_meta.py` is clean.
- [ ] No change to `FlowMeta`, `parse()`, or `emit()`.

---

## Test Specification

```python
# tests/sdd_scripts/test_sdd_meta.py — append at end

def test_known_branches_contains_main_staging_dev():
    """KNOWN_BRANCHES exposes exactly the three canonical Git Parrot Flow branches."""
    from scripts.sdd.sdd_meta import KNOWN_BRANCHES
    assert KNOWN_BRANCHES == frozenset({"main", "staging", "dev"})


def test_known_branches_is_frozenset():
    """KNOWN_BRANCHES must be immutable to prevent accidental mutation by consumers."""
    from scripts.sdd.sdd_meta import KNOWN_BRANCHES
    assert isinstance(KNOWN_BRANCHES, frozenset)
```

---

## Agent Instructions

1. Read `scripts/sdd/sdd_meta.py` to confirm current state.
2. Insert `KNOWN_BRANCHES` between the imports block and `class FlowMeta`.
3. Read `tests/sdd_scripts/test_sdd_meta.py` and append the two tests at the end.
4. Activate venv and run `pytest tests/sdd_scripts/test_sdd_meta.py -v`.
5. Run `ruff check scripts/sdd/sdd_meta.py`.
6. Move this task to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

Implemented by sdd-worker (FEAT-187). Added `KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})` between the imports block and `class FlowMeta` in `scripts/sdd/sdd_meta.py`. Extended `tests/sdd_scripts/test_sdd_meta.py` with `test_known_branches_contains_main_staging_dev` and `test_known_branches_is_frozenset`. All 7 tests pass, ruff clean. No change to `FlowMeta`, `parse()`, or `emit()`.
