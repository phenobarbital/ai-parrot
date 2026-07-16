---
type: Wiki Entity
title: CodexCodeReviewDispatcher
id: class:parrot.flows.dev_loop.code_review.CodexCodeReviewDispatcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps :class:`CodexCodeDispatcher` with a write-enabled sandbox profile.
relates_to:
- concept: class:parrot.flows.dev_loop.code_review.AbstractCodeReviewDispatcher
  rel: extends
---

# CodexCodeReviewDispatcher

Defined in [`parrot.flows.dev_loop.code_review`](../summaries/mod:parrot.flows.dev_loop.code_review.md).

```python
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher)
```

Wraps :class:`CodexCodeDispatcher` with a write-enabled sandbox profile.

Uses ``sandbox="workspace-write"`` and ``approval_policy="on-request"`` so
the reviewer can fix issues it finds and commit the fixes to the
worktree branch, mirroring the Claude reviewer's write-enabled behavior.

## Methods

- `def build_review_profile(self) -> CodexCodeReviewProfile`
