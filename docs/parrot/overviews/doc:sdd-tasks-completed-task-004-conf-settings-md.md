---
type: Wiki Overview
title: 'TASK-004: conf settings for repos, revision trigger, code-review model'
id: doc:sdd-tasks-completed-task-004-conf-settings-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 11. Adds the navconfig settings the new dev-loop behaviours
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-004: conf settings for repos, revision trigger, code-review model

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Module 11. Adds the navconfig settings the new dev-loop behaviours
read. Mirrors the existing dev-loop settings block (`conf.py:833-864`).

---

## Scope

- Add to `parrot/conf.py`:
  - `DEV_LOOP_REPOS` — JSON/list of repo specs, default `[]` (raw; parsed into
    `RepoSpec` by the flow config, not here).
  - `DEV_LOOP_REPO_BASE_PATH` — default `".claude/worktrees/repos"` (kept under
    `WORKTREE_BASE_PATH`).
  - `DEV_LOOP_REVISION_TRIGGER` — default `"changes_requested"`; also accepts
    `"any_comment"`, `"command"`.
  - `DEV_LOOP_CODEREVIEW_MODEL` — default `"claude-sonnet-4-6"`.
- Unit test for defaults.

**NOT in scope**: consuming the settings (TASKs 006/008/012).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add 4 settings near the dev-loop block |
| `packages/ai-parrot/tests/flows/dev_loop/test_settings_feat250.py` | CREATE | Defaults test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py  (existing dev-loop block — match the style)
CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES: int = config.getint("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", fallback=3)  # :833
FLOW_MAX_CONCURRENT_RUNS: int = config.getint("FLOW_MAX_CONCURRENT_RUNS", fallback=5)                            # :836
WORKTREE_BASE_PATH: str = config.get("WORKTREE_BASE_PATH", fallback=".claude/worktrees")                         # :846
FLOW_STREAM_TTL_SECONDS: int = config.getint("FLOW_STREAM_TTL_SECONDS", fallback=604800)                         # :850
ACCEPTANCE_CRITERION_ALLOWLIST: list[str] = config.getlist("ACCEPTANCE_CRITERION_ALLOWLIST", ...)                # :855
DEV_LOOP_PLAN_LLM: str = config.get("DEV_LOOP_PLAN_LLM", fallback="")                                            # :863
```

### Does NOT Exist
- ~~`DEV_LOOP_REPOS`, `DEV_LOOP_REPO_BASE_PATH`, `DEV_LOOP_REVISION_TRIGGER`, `DEV_LOOP_CODEREVIEW_MODEL`~~ — added here.

---

## Implementation Notes

### Key Constraints
- Use the same `config.get*` accessor style as the surrounding block.
- For `DEV_LOOP_REPOS` use `config.get(...)` returning a string the flow parses,
  or `config.getlist(...)` if the repos are simple slugs — keep it a raw value;
  do NOT import `RepoSpec` into `conf.py`.
- `DEV_LOOP_REPO_BASE_PATH` default must be under `WORKTREE_BASE_PATH` (R4).

### References in Codebase
- `packages/ai-parrot/src/parrot/conf.py:833-864` — the dev-loop settings block.

---

## Acceptance Criteria

- [ ] The 4 settings resolve to documented defaults with no env override.
- [ ] No `RepoSpec`/dev_loop import added to `conf.py`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_settings_feat250.py -v` passes.

---

## Test Specification
```python
def test_dev_loop_feat250_defaults(monkeypatch):
    import importlib, parrot.conf as conf
    importlib.reload(conf)
    assert conf.DEV_LOOP_REVISION_TRIGGER == "changes_requested"
    assert conf.DEV_LOOP_CODEREVIEW_MODEL == "claude-sonnet-4-6"
    assert conf.DEV_LOOP_REPO_BASE_PATH.startswith(conf.WORKTREE_BASE_PATH.split('/')[0]) or conf.DEV_LOOP_REPO_BASE_PATH
```

---

## Agent Instructions
Standard SDD lifecycle.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`parrot/conf.py`, after `DEV_LOOP_PLAN_LLM`)
- `DEV_LOOP_REPOS: list[str]` — `config.getlist(..., fallback=[])` (raw; parsed
  to `RepoSpec` by the flow, NOT here — no dev_loop import added).
- `DEV_LOOP_REPO_BASE_PATH: str` — default `f"{WORKTREE_BASE_PATH}/repos"`
  (stays under `WORKTREE_BASE_PATH`, R4).
- `DEV_LOOP_REVISION_TRIGGER: str` — default `"changes_requested"`.
- `DEV_LOOP_CODEREVIEW_MODEL: str` — default `"claude-sonnet-4-6"`.

**Verification**
- `pytest test_settings_feat250.py` → 2 passed (defaults + base-path-under-
  worktree-base).
- `ruff check`: the only reported error is a **pre-existing** `E402` at
  `conf.py:450` (a deliberate mid-file `from .models.google import GoogleModel`)
  that I did not touch; my diff is isolated to lines 866+ and the new test file
  is clean.
