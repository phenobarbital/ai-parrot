---
type: Wiki Entity
title: LintFinding
id: class:parrot.knowledge.pageindex.okf.lint.LintFinding
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single lint finding.
---

# LintFinding

Defined in [`parrot.knowledge.pageindex.okf.lint`](../summaries/mod:parrot.knowledge.pageindex.okf.lint.md).

```python
class LintFinding(BaseModel)
```

A single lint finding.

Attributes:
    kind: Category of the finding.  One of ``"orphan"``,
        ``"broken_link"``, ``"missing_concept"``, ``"stale"``.
    concept_id: The concept_id the finding relates to.
    detail: Human-readable description.
    severity: ``"warning"`` (non-critical) or ``"error"`` (data integrity).
