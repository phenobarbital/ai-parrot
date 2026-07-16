---
type: Wiki Entity
title: RevisionBrief
id: class:parrot.flows.dev_loop.models.RevisionBrief
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input to a revision-mode run (no new PR; update an existing one).
---

# RevisionBrief

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class RevisionBrief(BaseModel)
```

Input to a revision-mode run (no new PR; update an existing one).

Built by the PR-comment / PR-review webhook handler and passed to
``DevLoopRunner.run_revision(...)``. The revision flow enters at the
Development node with ``cwd=repo_path`` (the existing clone + branch),
re-runs QA, then pushes to the same branch and comments on the same PR.
