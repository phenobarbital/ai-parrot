# TASK-887: GitHub `pull_request.closed` webhook for worktree cleanup

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-876
**Assigned-to**: unassigned

---

## Context

Implements **Module 11**. Worktree cleanup is external to the flow
(spec G8). Two paths trigger cleanup:

1. A human running `/sdd-done` manually after merge.
2. **This task**: a GitHub webhook listener that runs
   `git worktree remove <path>` automatically on
   `pull_request.closed` events whose head branch matches the dev-loop
   convention `feat-<id>-<slug>`.

The listener is registered on the existing
`AutonomousOrchestrator.WebhookListener` via
`orchestrator.register_webhook(...)` (`orchestrator.py:646`). HMAC
validation is provided by the listener.

---

## Scope

- Implement `parrot/flows/dev_loop/webhook.py`:
  - `def register_pull_request_webhook(orchestrator, *, secret: str) -> None`
    that calls `orchestrator.register_webhook(path="/github/dev-loop",
    target_type="agent", target_id="dev-loop-cleanup", secret=secret,
    transform_fn=_transform_payload)`.
  - `_transform_payload(payload: dict) -> Optional[str]`: returns
    a string command for the listener to act on, OR returns `None` to
    instruct the listener to ignore the event. Pseudo-code: only
    process `action == "closed"` and a head branch matching
    `feat-\d+(-\w+)*`.
  - The actual subprocess execution
    (`git worktree remove <path>` + `git worktree prune`) lives in a
    small helper function (or a target-agent registered by
    `register_webhook`). Pick whichever pattern matches the existing
    `WebhookListener` design — verify by reading
    `parrot/autonomous/webhooks.py` first.
- Skip `dependabot/...`, `renovate/...`, and any branch not matching
  the `feat-` prefix (verified test
  `test_pr_webhook_ignores_non_dev_loop_branches`).

**NOT in scope**:
- Orchestrator changes — registration is purely additive.
- Cleanup of stale data on the orchestrator's side (run history,
  Redis streams). Streams expire via TTL; runs persist for audit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/webhook.py` | CREATE | `register_pull_request_webhook` + payload transform. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Re-export `register_pull_request_webhook`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_webhook.py` | CREATE | Unit tests for transform + cleanup invocation. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import logging
import os
import re
from typing import Any, Dict, Optional

from parrot.autonomous.orchestrator import AutonomousOrchestrator   # orchestrator.py:112
from parrot.conf import WORKTREE_BASE_PATH
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:                                      # line 112
    def register_webhook(
        self, path: str, target_type: Literal["agent", "crew"],
        target_id: str, *, secret: Optional[str] = None,
        transform_fn: Optional[Callable[[Dict], str]] = None,
        execution_mode: Optional[str] = None, **kwargs,
    ): ...                                                         # line 646

# packages/ai-parrot/src/parrot/autonomous/webhooks.py
class WebhookListener:                                             # line 35
    # HMAC SHA-256 validation: see compare_digest at line 285.
    # `transform_fn` is invoked with the parsed JSON body and returns a
    # string the listener forwards to the target agent/crew.
```

### Does NOT Exist

- ~~`AutonomousOrchestrator.add_github_webhook(...)`~~ — there is no
  GitHub-specific helper. Use the generic `register_webhook`.
- ~~`subprocess.run` (sync) inside async code~~ — use
  `asyncio.create_subprocess_exec`.
- ~~`feat-129-...`~~ as a literal regex — use `r"^feat-\d+"`.

---

## Implementation Notes

### Branch matcher

```python
_DEV_LOOP_BRANCH_RE = re.compile(r"^feat-\d+(?:-[\w-]+)?$")

def _is_dev_loop_branch(name: str) -> bool:
    return bool(_DEV_LOOP_BRANCH_RE.match(name))
```

### Payload transform

```python
def _transform_payload(payload: Dict[str, Any]) -> Optional[str]:
    if payload.get("action") != "closed":
        return None
    head_ref = payload.get("pull_request", {}) \
                      .get("head", {}).get("ref", "")
    if not _is_dev_loop_branch(head_ref):
        return None
    return f"cleanup_worktree:{head_ref}"
```

The downstream agent (registered as `target_id="dev-loop-cleanup"`)
parses this command and calls a helper:

```python
async def cleanup_worktree(branch: str) -> None:
    path = os.path.join(WORKTREE_BASE_PATH, branch)
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        logging.getLogger(__name__).warning(
            "git worktree remove %s failed: %s", path, err.decode(),
        )
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "prune",
    )
    await proc.communicate()
```

How exactly the cleanup helper is invoked depends on the
`WebhookListener` design — read `parrot/autonomous/webhooks.py` and
match the pattern used by other registered webhooks (look for
`target_type="agent"` examples).

### Key Constraints

- Cleanup MUST be best-effort: log and swallow failures. A missing
  worktree (already cleaned) is not an error.
- HMAC validation is the listener's job — do NOT re-implement it.

### References in Codebase

- `parrot/autonomous/orchestrator.py:646` — `register_webhook`.
- `parrot/autonomous/webhooks.py:35` — `WebhookListener`.

---

## Acceptance Criteria

- [ ] `register_pull_request_webhook(orchestrator, secret="x")` calls
  `orchestrator.register_webhook(path="/github/dev-loop", ...)`.
- [ ] A `pull_request.closed` payload with `head.ref="feat-130-fix"`
  triggers the cleanup helper (`test_pr_webhook_removes_worktree`).
- [ ] A payload with `head.ref="dependabot/..."` does NOT trigger any
  subprocess call (`test_pr_webhook_ignores_non_dev_loop_branches`).
- [ ] Cleanup helper swallows non-zero exit codes (already-cleaned
  worktree).
- [ ] Tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_webhook.py -v`.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.flows.dev_loop.webhook import (
    register_pull_request_webhook, _transform_payload,
)


def test_transform_returns_none_for_non_closed_action():
    assert _transform_payload({"action": "opened"}) is None


def test_transform_returns_none_for_non_devloop_branch():
    payload = {"action": "closed",
               "pull_request": {"head": {"ref": "dependabot/x"}}}
    assert _transform_payload(payload) is None


def test_transform_returns_cleanup_command_for_devloop_branch():
    payload = {"action": "closed",
               "pull_request": {"head": {"ref": "feat-130-fix"}}}
    assert _transform_payload(payload) == "cleanup_worktree:feat-130-fix"


def test_register_webhook_calls_orchestrator():
    orch = MagicMock()
    register_pull_request_webhook(orch, secret="s3cr3t")
    orch.register_webhook.assert_called_once()
    kwargs = orch.register_webhook.call_args.kwargs
    assert kwargs.get("path") == "/github/dev-loop" or \
           orch.register_webhook.call_args.args[0] == "/github/dev-loop"
    assert kwargs["secret"] == "s3cr3t"


@pytest.mark.asyncio
async def test_cleanup_swallows_missing_worktree():
    from parrot.flows.dev_loop.webhook import cleanup_worktree
    with patch("parrot.flows.dev_loop.webhook.asyncio.create_subprocess_exec"
               ) as mock_exec:
        proc = MagicMock()
        proc.communicate = AsyncMock(return_value=(b"", b"not a worktree"))
        proc.returncode = 1
        mock_exec.return_value = proc
        await cleanup_worktree("feat-130-fix")    # should not raise
```

---

## Agent Instructions

1. Read `parrot/autonomous/webhooks.py` and at least one existing
   `register_webhook` call site to learn the pattern for "registered
   target agent".
2. Confirm TASK-876 is completed (we read `WORKTREE_BASE_PATH` from
   `parrot.conf`).
3. Update index → `"in-progress"`.
4. Implement; tests; lint.
5. Move to completed.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Implemented `register_pull_request_webhook` (calls
`orchestrator.register_webhook(path='/github/dev-loop',
target_type='agent', target_id='dev-loop-cleanup', secret=...,
transform_fn=_transform_payload)`), `_transform_payload` (returns
`"cleanup_worktree:<branch>"` for `pull_request.closed` events with a
matching `feat-<id>(-<slug>)?` head branch; otherwise None), and
`cleanup_worktree(branch)` (runs `git worktree remove` then
`git worktree prune`, best-effort). 18 unit tests cover branch matching
(4 positive + 6 negative cases), transform behaviour (4 cases),
registration kwargs, and cleanup tolerance. The orchestrator-side
agent that consumes `cleanup_worktree:<branch>` strings is left to the
caller; the cleanup helper is exported so the orchestrator can wire
it into a small target-agent.
**Deviations from spec**: None.
