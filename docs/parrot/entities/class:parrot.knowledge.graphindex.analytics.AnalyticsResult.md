---
type: Wiki Entity
title: AnalyticsResult
id: class:parrot.knowledge.graphindex.analytics.AnalyticsResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Results from graph analytics computation.
---

# AnalyticsResult

Defined in [`parrot.knowledge.graphindex.analytics`](../summaries/mod:parrot.knowledge.graphindex.analytics.md).

```python
class AnalyticsResult
```

Results from graph analytics computation.

Args:
    god_nodes: Top-K nodes by centrality.  Each dict contains
        ``node_id``, ``title``, ``kind``, ``betweenness``,
        ``eigenvector``.
    surprising_connections: Cross-domain ``mentions`` edges ranked by
        confidence (descending).  Each dict contains ``source_id``,
        ``target_id``, ``confidence``, ``source_kind``, ``target_kind``.
    suggested_questions: Generated question strings derived from
        templates.
    communities: Optional FEAT-191 Louvain partition result. When
        set, ``generate_report`` renders an additional
        ``## Communities`` section.
    knowledge_gaps: Optional FEAT-215 knowledge gap detection result.
        When set, ``generate_report`` renders an additional
        ``## Knowledge Gaps`` section.
