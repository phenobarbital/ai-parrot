---
type: Concept
title: project_report_frontmatter()
id: func:parrot.knowledge.graphindex.projection.project_report_frontmatter
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generate OKF YAML frontmatter string for GRAPH_REPORT.md.
---

# project_report_frontmatter

```python
def project_report_frontmatter(analytics: AnalyticsResult, tenant_id: str, timestamp: Optional[str]=None) -> str
```

Generate OKF YAML frontmatter string for GRAPH_REPORT.md.

The output is byte-deterministic when ``timestamp`` is supplied; without
it the current UTC time is embedded, making each call unique.

Args:
    analytics: The analytics result from the graph build.
    tenant_id: Tenant identifier used in the concept-id.
    timestamp: Optional ISO-8601 timestamp string.  When provided, the
        frontmatter is byte-identical for the same inputs.  When omitted,
        the current UTC time is used (non-deterministic across calls).

Returns:
    YAML frontmatter string delimited by ``---\n``.
