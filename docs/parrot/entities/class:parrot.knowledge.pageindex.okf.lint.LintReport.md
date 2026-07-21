---
type: Wiki Entity
title: LintReport
id: class:parrot.knowledge.pageindex.okf.lint.LintReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured knowledge base lint report.
---

# LintReport

Defined in [`parrot.knowledge.pageindex.okf.lint`](../summaries/mod:parrot.knowledge.pageindex.okf.lint.md).

```python
class LintReport(BaseModel)
```

Structured knowledge base lint report.

Attributes:
    tree_name: Name of the PageIndex tree that was linted.
    orphans: Findings for concepts with zero inbound edges.
    broken_links: Findings for edges targeting unknown concept_ids.
    missing_concepts: Findings for known concepts with no sidecar body.
    stale_claims: Findings for concepts whose timestamp exceeds the
        configured threshold.
    total_findings: Sum of all findings across all categories.
    total_concepts: Number of concept_ids in the knowledge graph.
