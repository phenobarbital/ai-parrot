---
type: Wiki Overview
title: 'TASK-007: DeploymentHandoff opens a DRAFT PR (and surfaces PR number)'
id: doc:sdd-tasks-completed-task-007-draft-pr-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 7 (G5). The PR must be a DRAFT so the revision loop (TASK-012)
---

# TASK-007: DeploymentHandoff opens a DRAFT PR (and surfaces PR number)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Module 7 (G5). The PR must be a DRAFT so the revision loop (TASK-012)
can react to reviewer comments before the human marks-ready. The node must also
surface the PR **number** (needed to comment on the same PR later).

---

## Scope

- `_create_pr_with_gh`: add `--draft` to the `gh pr create` argv.
- `_create_pr_via_rest`: send `"draft": true` in the JSON body.
- Parse and return the PR **number** (in addition to the URL) from both paths;
  include it in the node's returned dict
  (`{"status": "ready_to_deploy", "pr_url": ..., "pr_number": ...}`).
- Unit tests for both paths.

**NOT in scope**: the revision loop or webhook (TASK-011/012); GitToolkit
clone/pull (TASK-002).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | MODIFY | `--draft` / `draft:true` + return PR number |
| `packages/ai-parrot/tests/flows/dev_loop/test_deployment_handoff_draft.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py
class DeploymentHandoffNode(DevLoopNode):
    def __init__(self, jira_toolkit, git_toolkit=None, gh_cli_path=None,
                 target_repo=None, base_branch="dev", name="deployment_handoff")   # :57
    async def execute(self, ctx, deps, **kwargs) -> Dict[str, Any]                  # :82
    def _gh_available(self) -> bool                                                 # :205 (shutil.which)
    async def _create_pr(self, branch, title, body) -> str                         # :207
    async def _create_pr_with_gh(self, branch, title, body) -> str                 # :212 (no --draft today)
    async def _create_pr_via_rest(self, branch, title, body) -> str                # :240 (no draft today)
    async def _push_branch(self, branch, cwd) -> None                              # :182
```

### Does NOT Exist
- ~~`--draft` in `gh pr create` / `draft:true` in REST body~~ — added here.
- ~~a returned PR number today~~ — only the URL is returned; add `pr_number`.

---

## Implementation Notes

### Key Constraints
- `gh pr create --draft --base <base> --head <branch> --title ... --body ...`;
  the URL is still the last stdout line — derive the number from the URL tail or
  `gh pr view --json number`.
- REST: `POST /repos/{owner}/{repo}/pulls` with `"draft": true`; response JSON
  has `number` and `html_url`.
- Keep the existing retry-once-with-backoff behaviour.

### References in Codebase
- `deployment_handoff.py:212-274` — the two PR-creation paths to modify.

---

## Acceptance Criteria

- [ ] `gh pr create` argv contains `--draft`.
- [ ] REST body contains `"draft": true`.
- [ ] Node returns `pr_number` alongside `pr_url`.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_deployment_handoff_draft.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` clean.

---

## Test Specification
```python
async def test_create_pr_with_gh_is_draft(monkeypatch):
    """The gh argv includes --draft."""
async def test_create_pr_via_rest_is_draft(monkeypatch):
    """The REST JSON body includes draft=True; pr_number parsed from response."""
```

---

## Agent Instructions
Standard SDD lifecycle.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`nodes/deployment_handoff.py`)
- `_create_pr_with_gh`: added `--draft` to the `gh pr create` argv.
- `_create_pr_via_rest`: added `"draft": True` to the REST JSON body.
- Added static `_parse_pr_number(pr_url)` (`…/pull/<n>` → int).
- `execute` now computes `pr_number = self._parse_pr_number(pr_url)` and returns
  `{"status": "ready_to_deploy", "pr_url": ..., "pr_number": ...}`.

**Design decision (non-breaking)**: the spec sketch suggested returning a tuple
from `_create_pr*`, but the existing `test_deployment_handoff.py` patches
`_create_pr_via_rest` to return a **string**. To avoid breaking it, the PR
methods keep returning the URL string and `execute` derives the number by
parsing the URL — the REST `html_url` also ends in `/pull/<n>`, so a single
helper covers both paths. This keeps the AC ("return PR number") satisfied with
zero breakage.

**Verification**
- `pytest test_deployment_handoff_draft.py` → 3 passed (gh `--draft`, REST
  `draft:true` + number parse, non-URL parse).
- Backward compat: existing `test_deployment_handoff.py` → 5 passed (8 total).
- `ruff check` clean on both files.
