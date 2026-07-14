---
type: Concept
title: cleanup_worktree()
id: func:parrot.flows.dev_loop.webhook.cleanup_worktree
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Run ``git worktree remove`` then ``git worktree prune``.
---

# cleanup_worktree

```python
async def cleanup_worktree(branch: str) -> None
```

Run ``git worktree remove`` then ``git worktree prune``.

Best-effort: a missing worktree (already cleaned) is *not* an error.
All subprocess failures are logged and swallowed.
