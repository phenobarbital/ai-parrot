---
type: Wiki Entity
title: BuildResult
id: class:parrot.knowledge.graphindex.schema.BuildResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Outcome of a full ``GraphIndexBuilder.build()`` run.
---

# BuildResult

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class BuildResult(BaseModel)
```

Outcome of a full ``GraphIndexBuilder.build()`` run.

Args:
    tenant_id: Tenant that was indexed.
    node_count: Total number of nodes persisted.
    edge_count: Total number of edges persisted.
    inferred_edge_count: Subset of edges with ``provenance=INFERRED``.
    report_path: Path to the generated ``GRAPH_REPORT.md`` file, if any.
    errors: List of non-fatal error messages encountered during the run.
    projection_report: Summary of the OKF projection stage (FEAT-239).
        ``None`` when the builder has no ``output_dir`` or projection
        was skipped.
    graph_html_path: Path to the interactive ``graph.html`` map, if the
        HTML export stage ran. ``None`` when export was disabled or no
        ``output_dir`` was configured.
    graph_json_path: Path to the serialized ``graph.json`` written
        alongside ``graph.html``. ``None`` when export was skipped.
