---
type: Concept
title: discover_python_files()
id: func:parrot.knowledge.graphindex.cli.discover_python_files
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Recursively find Python source files under ``root``.
---

# discover_python_files

```python
def discover_python_files(root: Path, ignore_spec: Optional[pathspec.PathSpec]=None) -> list[Path]
```

Recursively find Python source files under ``root``.

Skips well-known noise directories (``.git``, ``__pycache__``,
``node_modules``, virtualenvs, build output, …) and any path matching the
optional gitignore-style ``ignore_spec``.

Args:
    root: Repository root (or a single ``.py`` file).
    ignore_spec: Optional compiled ``pathspec`` for ``.graphindexignore``.

Returns:
    A sorted list of ``.py`` file paths (deterministic order).
