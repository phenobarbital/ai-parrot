---
type: Concept
title: parse_frontmatter()
id: func:parrot.knowledge.okf.frontmatter.parse_frontmatter
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse YAML frontmatter from a sidecar string back into a model.
---

# parse_frontmatter

```python
def parse_frontmatter(text: str) -> ConceptFrontmatter
```

Parse YAML frontmatter from a sidecar string back into a model.

The ``text`` must begin with ``---`` and contain a closing ``---``.
CRLF line-endings are normalised to LF before parsing.

Args:
    text: Sidecar file content starting with YAML frontmatter.

Returns:
    Parsed ``ConceptFrontmatter`` instance.

Raises:
    ValueError: If the frontmatter block cannot be found or parsed.
