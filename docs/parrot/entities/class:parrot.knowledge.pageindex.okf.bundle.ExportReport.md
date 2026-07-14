---
type: Wiki Entity
title: ExportReport
id: class:parrot.knowledge.pageindex.okf.bundle.ExportReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of an OKF bundle export operation.
---

# ExportReport

Defined in [`parrot.knowledge.pageindex.okf.bundle`](../summaries/mod:parrot.knowledge.pageindex.okf.bundle.md).

```python
class ExportReport(BaseModel)
```

Result of an OKF bundle export operation.

Attributes:
    tree_name: Name of the exported PageIndex tree.
    output_dir: Absolute path of the bundle directory.
    files_written: Number of ``.md`` files written (excludes ``index.md``).
    index_generated: Whether a root ``index.md`` was generated.
    uris_rewritten: Total number of ``pageindex://`` URIs rewritten.
