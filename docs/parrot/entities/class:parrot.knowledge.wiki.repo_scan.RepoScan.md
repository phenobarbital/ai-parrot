---
type: Wiki Entity
title: RepoScan
id: class:parrot.knowledge.wiki.repo_scan.RepoScan
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Full result of scanning a repository.
---

# RepoScan

Defined in [`parrot.knowledge.wiki.repo_scan`](../summaries/mod:parrot.knowledge.wiki.repo_scan.md).

```python
class RepoScan(BaseModel)
```

Full result of scanning a repository.

Attributes:
    root: Absolute repository root that was scanned.
    files: One :class:`FileSlice` per scanned file, sorted by path.
    dir_records: Directory overview pages (``dir:`` concept ids).
    dir_edges: ``contains`` edges (dir → child dir/file pages).
    import_edges: ``references`` edges between ``file:`` pages.
    skipped: Relative paths skipped (too large / binary / unreadable).
