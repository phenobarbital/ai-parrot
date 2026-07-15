---
type: Wiki Entity
title: ProjectionReport
id: class:parrot.knowledge.pageindex.okf.projection.ProjectionReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Report returned by project_sidecars().
---

# ProjectionReport

Defined in [`parrot.knowledge.pageindex.okf.projection`](../summaries/mod:parrot.knowledge.pageindex.okf.projection.md).

```python
class ProjectionReport(BaseModel)
```

Report returned by project_sidecars().

Attributes:
    tree_name: Name of the tree that was projected.
    nodes_projected: Number of nodes written.
    files_written: Concept_id-keyed filenames written.
    old_files_removed: Legacy node_id-keyed filenames removed.
