---
type: Wiki Entity
title: ImportReport
id: class:parrot.knowledge.pageindex.okf.bundle.ImportReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of an OKF bundle import operation.
---

# ImportReport

Defined in [`parrot.knowledge.pageindex.okf.bundle`](../summaries/mod:parrot.knowledge.pageindex.okf.bundle.md).

```python
class ImportReport(BaseModel)
```

Result of an OKF bundle import operation.

Attributes:
    tree_name: Name of the newly created PageIndex tree.
    input_dir: Absolute path of the source bundle directory.
    nodes_created: Number of PageIndex nodes created.
    edges_created: Number of ``relates_to`` edges created.
    types_mapped: Mapping of raw ``type`` string → ``ConceptType.value``.
    unknown_types: List of raw ``type`` strings that were unmapped (→ OTHER).
