---
type: Concept
title: build_import_edges()
id: func:parrot.knowledge.wiki.repo_scan.build_import_edges
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Derive ``references`` edges between file pages from Python imports.
---

# build_import_edges

```python
def build_import_edges(files: list[FileSlice], index_paths: Optional[Iterable[str]]=None) -> list[tuple[str, str, str]]
```

Derive ``references`` edges between file pages from Python imports.

An import edge is emitted when an imported dotted module (or any
dotted prefix of it) resolves to another repository file.

Args:
    files: Scanned file slices (edge sources).
    index_paths: Relative paths used to build the import-target
        index; defaults to the scanned files themselves.  Pass the
        full repository file list on partial scans so imports still
        resolve to files outside the scanned subset.

Returns:
    Deduplicated ``(src_concept, dst_concept, "references")`` edges.
