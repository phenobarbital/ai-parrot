---
type: Wiki Entity
title: WikiLintReport
id: class:parrot.knowledge.wiki.models.WikiLintReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extended lint report combining OKF checks with wiki-specific checks.
---

# WikiLintReport

Defined in [`parrot.knowledge.wiki.models`](../summaries/mod:parrot.knowledge.wiki.models.md).

```python
class WikiLintReport(BaseModel)
```

Extended lint report combining OKF checks with wiki-specific checks.

Attributes:
    okf_report: Raw dictionary returned by OKFToolkit.lint_knowledge_base().
    orphan_sources: Source IDs present in the manifest but with no
        corresponding wiki pages.
    stale_sources: Source IDs whose file hash or mtime has changed since
        the last ingest.
    uncovered_sources: Source IDs that were never ingested at all.
    cross_ref_issues: List of dicts describing broken cross-references
        between wiki pages.
    total_issues: Aggregate count of all issues across all checks.

## Methods

- `def compute_total_issues(self) -> WikiLintReport` — Recompute total_issues from the individual issue lists.
