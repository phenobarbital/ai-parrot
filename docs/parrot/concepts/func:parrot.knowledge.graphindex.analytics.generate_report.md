---
type: Concept
title: generate_report()
id: func:parrot.knowledge.graphindex.analytics.generate_report
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generate ``GRAPH_REPORT.md`` from analytics results.
---

# generate_report

```python
def generate_report(analytics: AnalyticsResult, output_dir: Path, llm_polish: bool=False, tenant_id: str='default') -> Path
```

Generate ``GRAPH_REPORT.md`` from analytics results.

The report is deterministic: identical inputs produce identical output.
The ``llm_polish`` parameter is accepted but is a no-op in v1.

FEAT-239: The report now starts with OKF-compatible YAML frontmatter
prepended before the Markdown body.

Args:
    analytics: Pre-computed ``AnalyticsResult``.
    output_dir: Directory where ``GRAPH_REPORT.md`` will be written.
    llm_polish: Reserved for v1.5.  Currently ignored.
    tenant_id: Tenant identifier used in the frontmatter resource URI.

Returns:
    Path to the written report file.
