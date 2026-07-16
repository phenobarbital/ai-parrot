---
type: Wiki Entity
title: RepoSpec
id: class:parrot.flows.dev_loop.models.RepoSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A git repository the dev-loop run operates on.
---

# RepoSpec

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class RepoSpec(BaseModel)
```

A git repository the dev-loop run operates on.

Declared on the flow config (``DEV_LOOP_REPOS``); the repo-provisioning
step clones/pulls each spec under ``DEV_LOOP_REPO_BASE_PATH`` before the
Development node runs.

## Methods

- `def alias_is_safe_dirname(cls, v: str) -> str` — Reject alias values that could escape the clone base directory.
