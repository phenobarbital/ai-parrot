---
type: Wiki Entity
title: CodeExtractor
id: class:parrot.knowledge.graphindex.extractors.code.CodeExtractor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract code structure from Python source files using tree-sitter.
---

# CodeExtractor

Defined in [`parrot.knowledge.graphindex.extractors.code`](../summaries/mod:parrot.knowledge.graphindex.extractors.code.md).

```python
class CodeExtractor
```

Extract code structure from Python source files using tree-sitter.

Emits ``UniversalNode`` instances for modules, classes, and functions
(``kind=NodeKind.SYMBOL``) and ``Rationale`` nodes from docstrings and
tagged comments (``kind=NodeKind.RATIONALE``).

Edges emitted: ``contains``, ``defines``, ``explains``.
Import edges (``references``) are emitted for ``import`` statements.

Args:
    tag_set: Set of comment tags to extract as Rationale nodes.
        Defaults to ``{"NOTE", "WHY", "HACK", "TODO", "FIXME", "XXX"}``.
    ignore_file: Path to a ``.graphindexignore`` file.  If provided, files
        matching the patterns will be filtered out by ``is_ignored()``.

## Methods

- `async def extract(self, file_path: str, source: str, *, mtime: Optional[float]=None) -> tuple[list[UniversalNode], list[UniversalEdge]]` — Parse a Python source file and return nodes and edges.
- `def is_ignored(self, file_path: str) -> bool` — Check if a file path matches ``.graphindexignore`` patterns.
