---
type: Wiki Entity
title: CodeReviewVerdict
id: class:parrot.flows.dev_loop.models.CodeReviewVerdict
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extended verdict emitted by all code review dispatchers (FEAT-270).
---

# CodeReviewVerdict

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class CodeReviewVerdict(BaseModel)
```

Extended verdict emitted by all code review dispatchers (FEAT-270).

Public replacement for the previous ``_CodeReviewVerdict`` private model
in ``nodes/qa.py``. A verdict with no findings and no modified files is a
pass, matching the old model's backward-compatible defaults.

The ``findings`` validator coerces plain strings (the format the old model
accepted) into ``CodeReviewFinding(message=s, severity="minor")`` so an LLM
that returns the legacy format doesn't fail Pydantic validation.
