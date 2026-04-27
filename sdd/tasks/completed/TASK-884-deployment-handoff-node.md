# TASK-884: `DeploymentHandoffNode` — push, open PR, transition Jira

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-874, TASK-883
**Assigned-to**: unassigned

---

## Context

Implements **Module 8**. Pure AI-Parrot — no Claude Code dispatch. After
QA passes, this node:

1. Pushes the branch (`git push -u origin <branch_name>` via subprocess).
2. Opens a PR — primary path: `gh pr create` subprocess; fallback if
   `gh` is not installed: HTTP via `parrot_tools.gittoolkit.GitToolkit`
   (which already wraps the GitHub REST API with `requests`).
3. Transitions the Jira ticket to "Ready to Deploy" via
   `jira_toolkit.jira_transition_issue(...)`.
4. Posts the PR URL as a Jira comment via `jira_add_comment(...)`.
5. Retries PR creation ONCE on transient errors with backoff before
   falling back to a "Deployment Blocked" status.

Spec acceptance criterion: "DeploymentHandoffNode pushes the branch,
opens a PR, transitions the Jira ticket to 'Ready to Deploy', and posts
the PR URL as a comment signed by `flow-bot`."

Resolved open question (spec §8): "PR creation transport — check if
`gh` exists; otherwise use PyGithub-style HTTP." `parrot_tools.GitToolkit`
already provides the HTTP fallback.

---

## Scope

- Implement `parrot/flows/dev_loop/nodes/deployment_handoff.py`:
  - `class DeploymentHandoffNode(Node)`.
  - `__init__(*, jira_toolkit, git_toolkit=None, gh_cli_path=None)`.
  - `async def execute(self, prompt, ctx) -> Dict[str, Any]`:
    1. Read `research_output` from `ctx`.
    2. `git push -u origin <branch_name>` via `asyncio.subprocess`.
    3. Detect `gh`: `which gh` (or use `gh_cli_path` if injected). If
       found, run `gh pr create --base dev --head <branch_name>
       --title <title> --body <body>` and parse the URL from stdout.
    4. If `gh` is unavailable OR step 3 fails, fall back to
       `git_toolkit.create_pull_request(...)` (the existing HTTP path).
    5. Retry the PR step ONCE with 2s backoff on `RuntimeError` /
       transient HTTP 5xx.
    6. On success: `jira_transition_issue(issue_key, "Ready to Deploy")`,
       then `jira_add_comment(issue_key, body=<PR URL + summary>)`.
    7. On final failure: `jira_transition_issue(issue_key,
       "Deployment Blocked")`, post error comment, return a result dict
       with `status="blocked"` (failure transition routing belongs to
       the flow factory; this node returns a structured outcome rather
       than raising for blocked deploys).
- Title: `f"FEAT-{feat_id_num}: <bug summary first line>"`. Body
  template: spec link + QA evidence summary.

**NOT in scope**:
- The webhook listener for worktree cleanup (TASK-887).
- Flow wiring (TASK-886).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | CREATE | `DeploymentHandoffNode`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_deployment_handoff.py` | CREATE | Unit tests with mocked subprocess + toolkits. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import logging
import shutil
from typing import Any, Dict, Optional

from parrot.bots.flow.node import Node                            # node.py:14
from parrot.flows.dev_loop.models import (
    DevelopmentOutput, QAReport, ResearchOutput,
)
from parrot_tools.jiratoolkit import JiraToolkit                  # jiratoolkit.py:609
from parrot_tools.gittoolkit import GitToolkit                    # gittoolkit.py:184
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
async def jira_transition_issue(self, ...): ...                   # line 1209
async def jira_add_comment(self, ...): ...                        # line 1616
# Verify exact arg names by reading the methods first.

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
class GitToolkit(AbstractToolkit):                                # line 184
    # Has create_pull_request-style tools using requests against the
    # GitHub REST API (line 447: f"https://api.github.com/repos/.../pulls").
    # Use this as the fallback when `gh` CLI is missing.
```

### Does NOT Exist

- ~~`PyGithub`~~ as a project dependency. The user's open-question
  answer mentioned PyGithub conceptually, but the existing toolkit uses
  `requests` directly. Use `GitToolkit` for HTTP fallback.
- ~~`subprocess.run(..., check=True)` (sync)~~ in async code. Use
  `asyncio.subprocess.create_subprocess_exec(...)`.
- ~~`shell=True`~~ — never. Always pass argv as a list.

---

## Implementation Notes

### `gh` detection

```python
def _gh_available(self) -> bool:
    return shutil.which(self._gh_cli_path or "gh") is not None
```

### PR creation via `gh`

```python
async def _create_pr_with_gh(self, branch, title, body, base="dev"):
    proc = await asyncio.create_subprocess_exec(
        self._gh_cli_path or "gh",
        "pr", "create",
        "--base", base, "--head", branch,
        "--title", title, "--body", body,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {err.decode()}")
    return out.decode().strip().splitlines()[-1]   # PR URL on last line
```

### Push + retry-once

```python
async def _push_branch(self, branch: str, cwd: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", cwd, "push", "-u", "origin", branch,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git push failed: {err.decode()}")

async def _create_pr_with_retry(self, ...):
    for attempt in range(2):
        try:
            if self._gh_available():
                return await self._create_pr_with_gh(...)
            return await self._create_pr_via_http(...)
        except RuntimeError as e:
            if attempt == 0:
                self.logger.warning("PR create failed, retrying: %s", e)
                await asyncio.sleep(2)
                continue
            raise
```

### Key Constraints

- All subprocess invocations use argv lists, never `shell=True`.
- Retry exactly ONCE. After the second failure, transition to
  "Deployment Blocked" and return a structured `dict`.
- The Jira `transition_issue` call uses the **bot** identity — the
  toolkit instance passed to this node already has the
  `StaticCredentialResolver` for `flow-bot` injected (orchestrator
  wiring).

### References in Codebase

- `parrot_tools/gittoolkit.py:447+` — existing PR creation HTTP code.

---

## Acceptance Criteria

- [ ] Branch is pushed before PR creation.
- [ ] `gh pr create` is preferred when available; falls back to
  `GitToolkit` otherwise.
- [ ] First PR call raises 5xx-class error; second succeeds; node
  returns success and posts PR URL to Jira
  (`test_deployment_handoff_retries_pr_once`).
- [ ] On final PR failure, Jira is transitioned to "Deployment Blocked"
  and an error comment is posted.
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_deployment_handoff.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode


@pytest.mark.asyncio
async def test_retries_pr_once(monkeypatch):
    jira = MagicMock()
    jira.jira_transition_issue = AsyncMock()
    jira.jira_add_comment = AsyncMock()
    git = MagicMock()
    git.create_pull_request = AsyncMock(
        side_effect=[RuntimeError("502 bad gateway"),
                     {"html_url": "https://github.com/x/y/pull/1"}]
    )
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.deployment_handoff.shutil.which",
        lambda *a, **kw: None,    # force HTTP fallback
    )
    node = DeploymentHandoffNode(jira_toolkit=jira, git_toolkit=git)
    # … pre-populate ctx with research_output, dev_output, qa_report …
    result = await node.execute(prompt="", ctx=ctx)
    assert result["status"] == "ready_to_deploy"
    assert git.create_pull_request.await_count == 2
    assert jira.jira_transition_issue.await_count == 1
```

---

## Agent Instructions

1. Confirm TASK-874, TASK-883 are completed.
2. Read `parrot_tools/gittoolkit.py` lines 184-460 to learn the exact
   public method name for "create PR via HTTP".
3. Read `parrot_tools/jiratoolkit.py` lines 1209-1300 (transition_issue)
   and 1616-1700 (add_comment) for arg signatures.
4. Update index → `"in-progress"`.
5. Implement; tests; lint.
6. Move to completed.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Implemented `DeploymentHandoffNode` with async subprocess
push, `gh pr create` primary path with REST fallback, retry-once with
2 s backoff, Jira `transition` + `add_comment` calls (verified
signatures `jira_transition_issue(issue, transition, ...)` at
`jiratoolkit.py:1209` and `jira_add_comment(issue, body, ...)` at
`jiratoolkit.py:1616`). On final PR failure the node calls Jira's
"Deployment Blocked" transition and returns
`{"status":"blocked", "error": ...}` rather than raising — the flow
factory may route on the dict shape. 5 unit tests cover retry-once,
final blocked path, push failure, and title/body formatting.
**Deviations from spec**: The `parrot_tools.GitToolkit.create_pull_request`
helper expects a `files: List[GitHubFileChange]` payload (it builds the
commit + PR in one shot) which doesn't fit the "PR for an already-pushed
branch" use case. The node implements a thin direct REST fallback via
aiohttp (`_create_pr_via_rest`) using `GITHUB_TOKEN` and a configurable
`target_repo`. Documented inline.
