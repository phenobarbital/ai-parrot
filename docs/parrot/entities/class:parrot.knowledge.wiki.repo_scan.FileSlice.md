---
type: Wiki Entity
title: FileSlice
id: class:parrot.knowledge.wiki.repo_scan.FileSlice
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Everything scanned from a single source file.
---

# FileSlice

Defined in [`parrot.knowledge.wiki.repo_scan`](../summaries/mod:parrot.knowledge.wiki.repo_scan.md).

```python
class FileSlice(BaseModel)
```

Everything scanned from a single source file.

Attributes:
    rel_path: POSIX-style path relative to the repository root.
    record: The wiki page record for the file (``source_id`` is
        filled in later by the build pipeline).
    imports: Dotted module names imported by the file (Python only),
        used to derive cross-file ``references`` edges.
