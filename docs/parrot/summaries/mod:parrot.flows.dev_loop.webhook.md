---
type: Wiki Summary
title: parrot.flows.dev_loop.webhook
id: mod:parrot.flows.dev_loop.webhook
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GitHub ``pull_request.closed`` webhook for worktree cleanup.
relates_to:
- concept: class:parrot.flows.dev_loop.webhook.RevisionWebhookHandler
  rel: defines
- concept: func:parrot.flows.dev_loop.webhook.cleanup_worktree
  rel: defines
- concept: func:parrot.flows.dev_loop.webhook.register_pull_request_webhook
  rel: defines
- concept: func:parrot.flows.dev_loop.webhook.sweep_finished_worktrees
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
---

# `parrot.flows.dev_loop.webhook`

GitHub ``pull_request.closed`` webhook for worktree cleanup.

Implements **Module 11** of the dev-loop spec. Worktree cleanup is
external to the flow itself (spec G8). Two paths trigger it:

1. A human running ``/sdd-done`` manually after a merge.
2. **This module**: a webhook listener registered on the existing
   :class:`parrot.autonomous.AutonomousOrchestrator.WebhookListener`
   via ``orchestrator.register_webhook(...)``. The listener handles
   HMAC validation — this module only adds the GitHub-specific
   transform and cleanup helper.

## Classes

- **`RevisionWebhookHandler`** — React to ``github.pr_comment`` / ``github.pr_review`` events.

## Functions

- `async def cleanup_worktree(branch: str) -> None` — Run ``git worktree remove`` then ``git worktree prune``.
- `async def sweep_finished_worktrees(*, pr_state_fn: Optional[Callable[[str], Awaitable[Optional[str]]]]=None, remove_orphans: bool=False, dry_run: bool=False, cwd: Optional[str]=None) -> Dict[str, Any]` — Remove dev-loop worktrees whose PR is merged/closed. Best effort.
- `def register_pull_request_webhook(orchestrator: Any, *, secret: str, path: str='/github/dev-loop', target_id: str='dev-loop-cleanup') -> None` — Register the GitHub ``pull_request.closed`` webhook handler.
