---
type: Concept
title: find_project_root()
id: func:parrot.knowledge.wiki.project.find_project_root
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Walk upwards from ``start`` to the nearest configured repo root.
---

# find_project_root

```python
def find_project_root(start: Optional[Path]=None) -> Optional[Path]
```

Walk upwards from ``start`` to the nearest configured repo root.

A directory is a wiki project root when it contains
``.parrot/wiki.json``; as a fallback, the nearest ``.git`` root is
returned so ``wikitoolkit build`` can bootstrap a fresh repo.

Args:
    start: Directory to start from (defaults to CWD).

Returns:
    The project root, or ``None`` when neither marker is found.
