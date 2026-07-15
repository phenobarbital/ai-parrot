---
type: Wiki Entity
title: AbstractCodeReviewDispatcher
id: class:parrot.flows.dev_loop.code_review.AbstractCodeReviewDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ABC for all code review dispatchers.
---

# AbstractCodeReviewDispatcher

Defined in [`parrot.flows.dev_loop.code_review`](../summaries/mod:parrot.flows.dev_loop.code_review.md).

```python
class AbstractCodeReviewDispatcher(ABC)
```

ABC for all code review dispatchers.

Wraps an underlying development dispatcher (Claude/Codex/Gemini) and
adds review-specific behavior: building the review prompt/profile,
enforcing the ``CodeReviewVerdict`` output contract (see
``parrot.flows.dev_loop.models``), and allowing the reviewer to fix +
commit issues it finds.

Concrete subclasses only need to implement ``build_review_profile()``
and set ``agent_name``; the ``review()`` dispatch + degrade loop is
handled by the ABC.

## Methods

- `async def review(self, *, brief: BaseModel, run_id: str, node_id: str, cwd: str) -> CodeReviewVerdict` — Run code review, optionally fix issues, return a verdict.
- `def build_review_profile(self) -> BaseModel` — Return the dispatcher-specific review profile.
