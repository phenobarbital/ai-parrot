---
type: Wiki Entity
title: CodexCodeReviewProfile
id: class:parrot.flows.dev_loop.models.CodexCodeReviewProfile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Review profile for the Codex code review dispatcher (FEAT-270).
relates_to:
- concept: class:parrot.flows.dev_loop.models.CodexCodeDispatchProfile
  rel: extends
---

# CodexCodeReviewProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class CodexCodeReviewProfile(CodexCodeDispatchProfile)
```

Review profile for the Codex code review dispatcher (FEAT-270).

Inherits ``CodexCodeDispatchProfile`` so it carries the ``ignore_user_config``
and ``ignore_rules`` fields that ``CodexCodeDispatcher._build_command()`` accesses.
Overrides defaults for the write-enabled review use case.
