---
type: Wiki Entity
title: MigrationReport
id: class:parrot.knowledge.pageindex.okf.migrate.MigrationReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Report produced by ``okf_migrate()``.
---

# MigrationReport

Defined in [`parrot.knowledge.pageindex.okf.migrate`](../summaries/mod:parrot.knowledge.pageindex.okf.migrate.md).

```python
class MigrationReport(BaseModel)
```

Report produced by ``okf_migrate()``.

Attributes:
    tree_name: Name of the migrated tree.
    nodes_processed: Total nodes processed.
    types_histogram: Count of each ConceptType assigned.
    links_resolved: Number of markdown links successfully resolved.
    links_broken: Number of markdown links with unknown targets.
    slug_collisions: Number of concept_id collisions resolved with suffixes.
    files_renamed: Number of sidecar files renamed to concept_id keys.
