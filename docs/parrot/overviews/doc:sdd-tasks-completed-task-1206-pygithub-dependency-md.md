---
type: Wiki Overview
title: 'TASK-1206: Add PyGithub dependency to ai-parrot-tools'
id: doc:sdd-tasks-completed-task-1206-pygithub-dependency-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: only (`gittoolkit.py:275`). The feature adds an explicit `auth_type="github_app"`
---

# TASK-1206: Add PyGithub dependency to ai-parrot-tools

**Feature**: FEAT-179 — GitHub App Authentication for GitToolkit
**Spec**: `sdd/specs/github-app-auth-gittoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`GitToolkit` currently authenticates to GitHub with a Personal Access Token
only (`gittoolkit.py:275`). The feature adds an explicit `auth_type="github_app"`
mode that mints installation tokens via PyGithub's `Auth.AppAuth` +
`GithubIntegration.get_access_token`. Before any implementation work in
TASK-1207/1208/1209 can run, PyGithub must be on the dependency manifest
and installed into the active venv. This task is intentionally isolated
so a single `uv pip install` confirms the new dependency resolves cleanly.

See spec §3 Module 4 and §7 External Dependencies.

---

## Scope

- Add `PyGithub>=2.1` to the `dependencies` array in
  `packages/ai-parrot-tools/pyproject.toml`.
- Run `uv pip install -e packages/ai-parrot-tools` (with venv active) and
  confirm PyGithub plus its transitive deps (`cryptography`, `pyjwt`)
  install without conflicts.
- Confirm `from github import Auth, GithubIntegration` works in a Python
  REPL after install.

**NOT in scope**:
- Any code change to `gittoolkit.py` (that is TASK-1207/1208).
- Importing PyGithub anywhere yet.
- Pinning PyGithub to a tighter version.
- Adding `pyjwt` or `cryptography` as direct dependencies (they come in
  transitively via PyGithub and must NOT be declared explicitly).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | Add `"PyGithub>=2.1"` to the `dependencies` list. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# After this task, the following import must work:
from github import Auth, GithubIntegration   # provided by PyGithub>=2.1
```

### Existing Signatures to Use
```toml
# packages/ai-parrot-tools/pyproject.toml — current dependencies block
dependencies = [
    "ai-parrot>=0.24.51",
]
```

Add to that list. Do not introduce a new dependency group.

### Does NOT Exist
- ~~`pyjwt` as a direct dependency of `ai-parrot-tools`~~ — comes in
  transitively via PyGithub; do not declare it explicitly.
- ~~`cryptography` as a direct dependency~~ — same as above.
- ~~A `[tool.uv.dependencies]` table~~ — this project uses PEP 621
  standard `[project] dependencies = [...]`.

---

## Implementation Notes

### Pattern to Follow
Match the formatting of the existing `dependencies = ["ai-parrot>=0.24.51"]`
entry. One dependency per line, double-quoted.

### Key Constraints
- Must use `uv` (per project rules in `CLAUDE.md`).
- ALWAYS `source .venv/bin/activate` first.
- Do NOT modify `packages/ai-parrot/pyproject.toml` — PyGithub is a tools
  package concern; the core `ai-parrot` package does not need it.

### References in Codebase
- `packages/ai-parrot-tools/pyproject.toml` — the file to modify.
- `packages/ai-parrot/pyproject.toml` — DO NOT TOUCH.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/pyproject.toml` contains `"PyGithub>=2.1"` in
      the `dependencies` array.
- [ ] `source .venv/bin/activate && uv pip install -e packages/ai-parrot-tools`
      completes with no resolver errors.
- [ ] `source .venv/bin/activate && python -c "from github import Auth, GithubIntegration"`
      exits 0.
- [ ] No other files are modified.

---

## Test Specification

This task is a build-system change with no Python code. Validation is
manual via the acceptance-criteria commands above. No new pytest tests.

---

## Agent Instructions

1. Read the spec at `sdd/specs/github-app-auth-gittoolkit.spec.md` (§3 Module 4, §7).
2. Activate the venv: `source .venv/bin/activate`.
3. Edit `packages/ai-parrot-tools/pyproject.toml` and append
   `"PyGithub>=2.1",` to the `dependencies` list.
4. Run `uv pip install -e packages/ai-parrot-tools`.
5. Verify the smoke import: `python -c "from github import Auth, GithubIntegration"`.
6. Update the per-spec index status to `done`.
7. Move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
