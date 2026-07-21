---
type: Wiki Entity
title: RevisionWebhookHandler
id: class:parrot.flows.dev_loop.webhook.RevisionWebhookHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: React to ``github.pr_comment`` / ``github.pr_review`` events.
---

# RevisionWebhookHandler

Defined in [`parrot.flows.dev_loop.webhook`](../summaries/mod:parrot.flows.dev_loop.webhook.md).

```python
class RevisionWebhookHandler
```

React to ``github.pr_comment`` / ``github.pr_review`` events.

Filters reviewer feedback by ``DEV_LOOP_REVISION_TRIGGER``, drops
bot-authored comments, dedups by ``head_sha`` (mirroring
``GitHubReviewer``), builds a :class:`RevisionBrief`, and calls
``DevLoopRunner.run_revision(...)``. A single handler instance keeps the
seen-``head_sha`` set so a chatty PR cannot spawn a revision storm (R3).

Args:
    runner: A ``DevLoopRunner`` constructed with the revision deps.
    trigger: Override for ``conf.DEV_LOOP_REVISION_TRIGGER`` —
        ``"changes_requested"`` (default), ``"any_comment"`` or
        ``"command"`` (``/revise`` prefix).
    bot_login: GitHub login of the flow-bot; comments authored by it are
        ignored. When ``None``, no author is treated as a bot.
    repo_base_path: Base dir under which the existing clone lives; the
        revision reuses ``<repo_base_path>/<branch>``. Defaults to
        ``conf.WORKTREE_BASE_PATH``.

## Methods

- `async def handle_event(self, event_type: str, payload: Dict[str, Any]) -> Optional[Any]` — Maybe trigger a revision run. Returns the ``FlowResult`` or ``None``.
