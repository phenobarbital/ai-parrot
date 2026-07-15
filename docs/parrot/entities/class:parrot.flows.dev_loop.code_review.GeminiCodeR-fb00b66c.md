---
type: Wiki Entity
title: GeminiCodeReviewDispatcher
id: class:parrot.flows.dev_loop.code_review.GeminiCodeReviewDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps :class:`GeminiCodeDispatcher` with sandbox disabled + auto-edit.
relates_to:
- concept: class:parrot.flows.dev_loop.code_review.AbstractCodeReviewDispatcher
  rel: extends
---

# GeminiCodeReviewDispatcher

Defined in [`parrot.flows.dev_loop.code_review`](../summaries/mod:parrot.flows.dev_loop.code_review.md).

```python
class GeminiCodeReviewDispatcher(AbstractCodeReviewDispatcher)
```

Wraps :class:`GeminiCodeDispatcher` with sandbox disabled + auto-edit.

Uses ``sandbox=False`` and ``approval_mode="auto_edit"`` so the reviewer
can fix issues it finds and commit the fixes to the worktree branch,
mirroring the Claude and Codex reviewers' write-enabled behavior.

## Methods

- `def build_review_profile(self) -> GeminiCodeReviewProfile`
