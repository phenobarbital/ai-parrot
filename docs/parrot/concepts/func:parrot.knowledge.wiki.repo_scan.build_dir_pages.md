---
type: Concept
title: build_dir_pages()
id: func:parrot.knowledge.wiki.repo_scan.build_dir_pages
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Derive directory overview pages and ``contains`` edges.
---

# build_dir_pages

```python
def build_dir_pages(files: list[FileSlice]) -> tuple[list[WikiPageRecord], list[tuple[str, str, str]]]
```

Derive directory overview pages and ``contains`` edges.

Args:
    files: Scanned file slices.

Returns:
    Tuple ``(dir_records, edges)``; edges connect each directory
    page to its child directory/file pages.
