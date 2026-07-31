---
type: Wiki Entity
title: EvalReportSink
id: class:parrot.eval.sink.EvalReportSink
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract persistence sink for ``EvalReport`` objects.
---

# EvalReportSink

Defined in [`parrot.eval.sink`](../summaries/mod:parrot.eval.sink.md).

```python
class EvalReportSink(ABC)
```

Abstract persistence sink for ``EvalReport`` objects.

``EvalRunner`` calls ``sink.persist(report)`` after a run completes
if a sink is configured.  The sink returns a ``run_id`` string that
is written back into the report.

## Methods

- `async def persist(self, report: Any) -> str` — Persist *report* and return the assigned run identifier.
