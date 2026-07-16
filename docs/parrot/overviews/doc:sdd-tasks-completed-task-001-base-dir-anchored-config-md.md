---
type: Wiki Overview
title: 'TASK-001: BASE_DIR-anchored WORKTREE / repo base paths'
id: doc:sdd-tasks-completed-task-001-base-dir-anchored-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec. Today `WORKTREE_BASE_PATH` is the relative
---

# TASK-001: BASE_DIR-anchored WORKTREE / repo base paths

**Feature**: FEAT-253 — Complete FEAT-250 Repo Wiring
**Spec**: `sdd/specs/complete-feat-250-dev-loop-repo-wiring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. Today `WORKTREE_BASE_PATH` is the relative
string `".claude/worktrees"` (`conf.py:846`), and both `_provision_repos` and the
dispatcher cwd-safety guard call `os.path.abspath(...)` on it — so the resolved
location depends on the process's launch directory. Anchoring at `navconfig.BASE_DIR`
makes worktrees/clones land deterministically at `BASE_DIR/.claude/worktrees[...]`
regardless of where the server is started. This is the prerequisite for the
BASE_DIR local fallback (TASK-003).

---

## Scope

- Resolve `WORKTREE_BASE_PATH` against `BASE_DIR` (already imported at `conf.py:5`):
  - default fallback becomes `str(BASE_DIR / ".claude/worktrees")`;
  - if a configured value is **relative**, join it onto `BASE_DIR`; if it is
    already **absolute**, honor it verbatim (R1 backward-compat).
- Update `DEV_LOOP_REPO_BASE_PATH` so its default is anchored under the resolved
  `WORKTREE_BASE_PATH` (i.e. `BASE_DIR/.claude/worktrees/repos`); same relative→
  join / absolute→verbatim rule.
- Keep the emitted leaf names identical (`.claude/worktrees`, `.../repos`) so
  existing worktrees and tests don't move when launched from the repo root.
- Add unit tests for the anchoring behavior.

**NOT in scope**: the `DEV_LOOP_REPOS`→`RepoSpec` parser (TASK-002), any change to
`research.py` / `server.py`, relaxing the dispatcher guard.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Anchor `WORKTREE_BASE_PATH` + `DEV_LOOP_REPO_BASE_PATH` at `BASE_DIR`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_conf_paths_anchored.py` | CREATE | Unit tests for path anchoring. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import config, BASE_DIR   # conf.py:5  — BASE_DIR is a pathlib.PosixPath
                                          #   == /home/jesuslara/proyectos/navigator/ai-parrot
from parrot import conf                   # test side
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py
from navconfig import config, BASE_DIR                                     # :5
WORKTREE_BASE_PATH: str = config.get("WORKTREE_BASE_PATH",
                                     fallback=".claude/worktrees")          # :846  (RELATIVE today)
DEV_LOOP_REPOS: list[str] = config.getlist("DEV_LOOP_REPOS", fallback=[]) or []  # :870
DEV_LOOP_REPO_BASE_PATH: str = config.get(
    "DEV_LOOP_REPO_BASE_PATH", fallback=f"{WORKTREE_BASE_PATH}/repos")      # :873

# BASE_DIR is already used elsewhere in conf.py as an anchor, e.g.:
PROJECT_ROOT = BASE_DIR                                                     # :34
STATIC_DIR = config.get('STATIC_DIR', fallback=BASE_DIR.joinpath('static'))  # :43
```

### Does NOT Exist
- ~~`conf.WORKTREE_BASE_PATH` being absolute today~~ — it is relative; this task
  makes it absolute (anchored).
- ~~A helper like `conf.resolve_under_base_dir()`~~ — not present; either inline
  the join logic or add a small private helper local to `conf.py`.

---

## Implementation Notes

### Pattern to Follow
`conf.py` already anchors many dirs with `BASE_DIR.joinpath(...)` (e.g.
`STATIC_DIR` at `:43`, `OUTPUT_DIR` at `:49-52`). Mirror that idiom. Suggested
logic (relative→join, absolute→verbatim):

```python
import os
_wt = config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))
WORKTREE_BASE_PATH: str = _wt if os.path.isabs(_wt) else str(BASE_DIR / _wt)

_repos = config.get("DEV_LOOP_REPO_BASE_PATH",
                    fallback=str(BASE_DIR / ".claude/worktrees" / "repos"))
DEV_LOOP_REPO_BASE_PATH: str = _repos if os.path.isabs(_repos) else str(BASE_DIR / _repos)
```

### Key Constraints
- Emit `str(...)` values (these conf attrs are typed `str`).
- Do NOT import `dev_loop` from `conf.py`.
- Preserve `DEV_LOOP_REPOS` as-is (TASK-002 parses it elsewhere).

---

## Acceptance Criteria

- [ ] `conf.WORKTREE_BASE_PATH` is absolute and under `str(BASE_DIR)`.
- [ ] `conf.DEV_LOOP_REPO_BASE_PATH` is absolute, under `WORKTREE_BASE_PATH`, ends in `repos`.
- [ ] An explicitly-set absolute `WORKTREE_BASE_PATH` env is honored verbatim.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_conf_paths_anchored.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/conf.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_conf_paths_anchored.py
import os
from navconfig import BASE_DIR
from parrot import conf


def test_worktree_base_path_anchored_at_base_dir():
    assert os.path.isabs(conf.WORKTREE_BASE_PATH)
    assert conf.WORKTREE_BASE_PATH.startswith(str(BASE_DIR))


def test_repo_base_path_under_worktree_base():
    assert os.path.isabs(conf.DEV_LOOP_REPO_BASE_PATH)
    base = os.path.abspath(conf.WORKTREE_BASE_PATH)
    assert os.path.commonpath([base, conf.DEV_LOOP_REPO_BASE_PATH]) == base
    assert conf.DEV_LOOP_REPO_BASE_PATH.rstrip("/").endswith("repos")
```

---

## Agent Instructions

1. Read the spec for full context (§2, §3 Module 1, §7 R1).
2. Verify the Codebase Contract lines before editing.
3. Update index → `in-progress`.
4. Implement, run tests + ruff.
5. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
