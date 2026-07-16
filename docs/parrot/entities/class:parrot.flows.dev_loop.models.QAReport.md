---
type: Wiki Entity
title: QAReport
id: class:parrot.flows.dev_loop.models.QAReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured output from the ``sdd-qa`` dispatch.
---

# QAReport

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class QAReport(BaseModel)
```

Structured output from the ``sdd-qa`` dispatch.

The QA node returns this payload regardless of pass/fail; the *flow*
decides routing based on ``passed``.
