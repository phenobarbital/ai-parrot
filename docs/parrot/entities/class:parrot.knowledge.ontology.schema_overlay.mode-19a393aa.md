---
type: Wiki Entity
title: DryRunReport
id: class:parrot.knowledge.ontology.schema_overlay.models.DryRunReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a schema overlay dry-run validation.
---

# DryRunReport

Defined in [`parrot.knowledge.ontology.schema_overlay.models`](../summaries/mod:parrot.knowledge.ontology.schema_overlay.models.md).

```python
class DryRunReport(BaseModel)
```

Result of a schema overlay dry-run validation.

The dry-run runs a sandboxed merge of the candidate overlay with the
tenant's current YAML chain, validates AQL for traversal patterns, and
checks for framework-override attempts.

Attributes:
    ok: True if all checks passed, False if any check failed.
    checks: Per-check results with check_name, passed, and details.
    error: Top-level error message if the entire dry-run failed.
    duration_ms: Wall-clock duration of the dry-run in milliseconds.
