---
type: Wiki Entity
title: DryRunCheck
id: class:parrot.knowledge.ontology.schema_overlay.models.DryRunCheck
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a single validation step within a dry-run.
---

# DryRunCheck

Defined in [`parrot.knowledge.ontology.schema_overlay.models`](../summaries/mod:parrot.knowledge.ontology.schema_overlay.models.md).

```python
class DryRunCheck(BaseModel)
```

Result of a single validation step within a dry-run.

N3 fix: replaces the untyped ``dict[str, Any]`` used in ``DryRunReport.checks``
with a structured Pydantic model, enabling proper serialisation and validation.

Attributes:
    check_name: Human-readable name of the validation step.
    passed: True if this step succeeded.
    details: Optional explanation (error message or pass note).
