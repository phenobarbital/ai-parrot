---
type: Wiki Entity
title: ClaudeCodeReviewDispatcher
id: class:parrot.flows.dev_loop.code_review.ClaudeCodeReviewDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps :class:`ClaudeCodeDispatcher` with a write-enabled review profile.
relates_to:
- concept: class:parrot.flows.dev_loop.code_review.AbstractCodeReviewDispatcher
  rel: extends
---

# ClaudeCodeReviewDispatcher

Defined in [`parrot.flows.dev_loop.code_review`](../summaries/mod:parrot.flows.dev_loop.code_review.md).

```python
class ClaudeCodeReviewDispatcher(AbstractCodeReviewDispatcher)
```

Wraps :class:`ClaudeCodeDispatcher` with a write-enabled review profile.

Delegates to the ``sdd-codereview`` subagent (via the shared
``ClaudeCodeDispatcher``) with ``permission_mode="default"`` and the full
read/write tool set, allowing the reviewer to fix issues it finds and
commit the fixes to the worktree branch.

## Methods

- `def build_review_profile(self) -> ClaudeCodeReviewProfile`
