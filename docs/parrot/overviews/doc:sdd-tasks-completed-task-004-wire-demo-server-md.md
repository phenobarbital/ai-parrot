---
type: Wiki Overview
title: 'TASK-004: Wire GitToolkit + repos into the demo server'
id: doc:sdd-tasks-completed-task-004-wire-demo-server-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4**. The demo (`examples/dev_loop/server.py:389`) calls
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-004: Wire GitToolkit + repos into the demo server

**Feature**: FEAT-253 — Complete FEAT-250 Repo Wiring
**Spec**: `sdd/specs/complete-feat-250-dev-loop-repo-wiring.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-002, TASK-003
**Assigned-to**: unassigned

---

## Context

Implements **Module 4**. The demo (`examples/dev_loop/server.py:389`) calls
`build_dev_loop_flow(...)` with no `git_toolkit=` / `repos=`, so repo provisioning
never runs. This task wires a `GitToolkit` and the parsed `DEV_LOOP_REPOS` into the
flow so the demo can target `git@github.com:phenobarbital/ai-parrot.git` when
configured, and falls back to the local checkout (`BASE_DIR`) when not.

---

## Scope

- In `_on_startup` (`server.py:380`), build a `GitToolkit` from env
  (`GITHUB_TOKEN`/`gh` auth) and compute
  `repos = parse_repo_specs(conf.DEV_LOOP_REPOS)`.
- Pass `git_toolkit=<git_toolkit>` and `repos=repos` into
  `build_dev_loop_flow(...)`.
- Add a `_build_git_toolkit()` helper next to `_build_jira_toolkit()` /
  `_build_log_toolkits()` for symmetry.
- Update the module docstring to document `DEV_LOOP_REPOS` with the
  `git@github.com:phenobarbital/ai-parrot.git` example and the local fallback.
- No behavioral change when `DEV_LOOP_REPOS` is unset (empty `repos` → local).
- Add a unit test that asserts the wiring.

**NOT in scope**: the parser itself (TASK-002); provisioning logic (TASK-003);
conf anchoring (TASK-001).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server.py` | MODIFY | `_build_git_toolkit()` + pass `git_toolkit=`/`repos=`; docstring. |
| `packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py` | CREATE | Unit test (monkeypatch `build_dev_loop_flow`, assert kwargs). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot import conf                                  # DEV_LOOP_REPOS
from parrot.flows.dev_loop import build_dev_loop_flow, parse_repo_specs  # flow.py:164, NEW re-export
from parrot_tools.gittoolkit import GitToolkit           # gittoolkit.py:968
```

### Existing Signatures to Use
```python
# examples/dev_loop/server.py
async def _on_startup(app: web.Application) -> None:                      # :380
    app["flow"] = build_dev_loop_flow(
        dispatcher=dispatcher, jira_toolkit=_build_jira_toolkit(),
        log_toolkits=_build_log_toolkits(), redis_url=redis_url,
        name="dev-loop-demo")                                            # :389  (add git_toolkit=, repos=)
def _build_jira_toolkit() -> JiraToolkit: ...                            # :72  (pattern to mirror)

# packages/ai-parrot/src/parrot/flows/dev_loop/flow.py
def build_dev_loop_flow(*, dispatcher, jira_toolkit, log_toolkits, redis_url,
                        name="dev-loop", publish_flow_events=True,
                        lifecycle_events=True,
                        git_toolkit=None, repos=None) -> AgentsFlow      # :164  (already accepts git_toolkit + repos)

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):
    def __init__(self, default_repository=None, default_branch="main",
                 github_token=None, auth_type="pat", app_id=None,
                 installation_id=None, private_key=None, private_key_path=None,
                 repositories=None, **kwargs): ...                        # :977
```

### Does NOT Exist
- ~~`build_dev_loop_flow` ignoring `git_toolkit`/`repos`~~ — it already forwards
  them via `factories.py` (`:84-85`); only the server omits them today.
- ~~`GitToolkit.from_env()`~~ — no such classmethod; construct with explicit
  kwargs (read `GITHUB_TOKEN`/`conf` as the other `_build_*` helpers do).

---

## Implementation Notes

### Pattern to Follow
Mirror `_build_jira_toolkit()` (`server.py:72`). Example:
```python
def _build_git_toolkit() -> GitToolkit:
    return GitToolkit(
        github_token=conf.config.get("GITHUB_TOKEN", fallback=None),
        default_branch=conf.config.get("GIT_DEFAULT_BRANCH", fallback="main"),
    )
# in _on_startup:
repos = parse_repo_specs(conf.DEV_LOOP_REPOS)
app["flow"] = build_dev_loop_flow(
    ..., git_toolkit=_build_git_toolkit(), repos=repos)
```

### Key Constraints
- Empty `DEV_LOOP_REPOS` → `repos == []` → local fallback (still pass the
  git_toolkit; it's harmless and enables future declared runs).
- Don't log tokens.

---

## Acceptance Criteria

- [ ] `_on_startup` passes `git_toolkit=` and `repos=parse_repo_specs(conf.DEV_LOOP_REPOS)` to `build_dev_loop_flow`.
- [ ] With `DEV_LOOP_REPOS` set, `repos` is non-empty; unset → empty, server still boots.
- [ ] Module docstring documents `DEV_LOOP_REPOS` incl. `git@github.com:phenobarbital/ai-parrot.git`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py -v`
- [ ] No lint errors: `ruff check examples/dev_loop/server.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py
# Import the server module, monkeypatch build_dev_loop_flow to capture kwargs,
# drive _on_startup with a fake aiohttp app dict, and assert:
#   - "git_toolkit" in captured kwargs and is not None
#   - captured["repos"] reflects parse_repo_specs(conf.DEV_LOOP_REPOS)
# Two cases: DEV_LOOP_REPOS set (non-empty) and unset (empty).
```

---

## Agent Instructions

1. Read the spec (§3 Module 4, §7 R4 for SSH-key note).
2. Confirm TASK-002 + TASK-003 are in `sdd/tasks/completed/`.
3. Verify the Codebase Contract (`server.py:72,380,389`, `flow.py:164`).
4. Update index → `in-progress`.
5. Implement, run tests + ruff.
6. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
