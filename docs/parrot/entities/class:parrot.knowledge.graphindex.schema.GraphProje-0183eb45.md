---
type: Wiki Entity
title: GraphProjectionReport
id: class:parrot.knowledge.graphindex.schema.GraphProjectionReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Summary of a completed GraphIndex OKF projection run (FEAT-239).
---

# GraphProjectionReport

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class GraphProjectionReport(BaseModel)
```

Summary of a completed GraphIndex OKF projection run (FEAT-239).

Produced by ``project_graph_sidecars()`` and stored on ``BuildResult``.

Attributes:
    output_dir: Base directory where sidecars were written.
    nodes_projected: Count of nodes successfully projected.
    files_written: Absolute file paths of every sidecar written.
    report_frontmatter_added: ``True`` when ``GRAPH_REPORT.md`` was
        generated with OKF frontmatter during the same build run.
