---
type: Concept
title: sweep_finished_worktrees()
id: func:parrot.flows.dev_loop.webhook.sweep_finished_worktrees
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Remove dev-loop worktrees whose PR is merged/closed. Best effort.
---

# sweep_finished_worktrees

```python
async def sweep_finished_worktrees(*, pr_state_fn: Optional[Callable[[str], Awaitable[Optional[str]]]]=None, remove_orphans: bool=False, dry_run: bool=False, cwd: Optional[str]=None) -> Dict[str, Any]
```

Remove dev-loop worktrees whose PR is merged/closed. Best effort.

The webhook-less fallback for worktree cleanup. Lists every live dev-loop
worktree and decides per branch:

* PR **merged** or **closed** → remove the worktree.
* PR **open** → keep (a reviewer revision may still reuse it).
* **No PR** (orphan) → kept by default; removed only when
  ``remove_orphans=True`` (e.g. a run that failed before opening a PR).

Args:
    pr_state_fn: Async ``branch -> state`` resolver returning one of
        ``"merged"``/``"closed"``/``"open"``/``None``. Defaults to the
        ``gh`` CLI (:func:`_gh_pr_state`). Injectable for tests.
    remove_orphans: Also remove worktrees with no PR.
    dry_run: Report what would be removed without touching anything.
    cwd: Working directory for the git/gh subprocesses (defaults to the
        current process dir; pass the repo root when calling out-of-tree).

Returns:
    A report dict ``{"removed": [...], "kept": [{"branch", "reason"}],
    "errors": [...], "dry_run": bool}``.
