---
type: Wiki Entity
title: WikiExportReport
id: class:parrot.knowledge.wiki.export.WikiExportReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of an OKF bundle export.
---

# WikiExportReport

Defined in [`parrot.knowledge.wiki.export`](../summaries/mod:parrot.knowledge.wiki.export.md).

```python
class WikiExportReport(BaseModel)
```

Result of an OKF bundle export.

Attributes:
    wiki_name: Exported wiki.
    output_dir: Bundle root directory.
    files_written: Number of concept files written.
    index_generated: Whether the root ``index.md`` was written.
    categories: Files written per category directory.
