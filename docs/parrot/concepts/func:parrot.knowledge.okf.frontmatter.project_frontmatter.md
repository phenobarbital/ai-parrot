---
type: Concept
title: project_frontmatter()
id: func:parrot.knowledge.okf.frontmatter.project_frontmatter
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Produce a byte-deterministic YAML frontmatter string from a node dict.
---

# project_frontmatter

```python
def project_frontmatter(node: dict, tree_name: str) -> str
```

Produce a byte-deterministic YAML frontmatter string from a node dict.

The output starts with ``---\n`` and ends with ``---\n``.  Given the same
``node`` dict and ``tree_name``, this function MUST return byte-identical
output every time it is called (idempotency / determinism guarantee).

Fields extracted from ``node``:
- ``type`` (or ``"Section"`` as fallback)
- ``title``
- ``concept_id``
- ``node_id``
- ``summary`` (or empty string)
- ``categories`` → ``tags`` (sorted)
- ``timestamp`` (or empty string)
- ``relates_to`` list
- ``source`` dict (optional)

Args:
    node: PageIndex node dict (must have ``concept_id``, ``title``,
        ``node_id``).
    tree_name: Name of the PageIndex tree, used to build the resource URI.

Returns:
    YAML frontmatter string delimited by ``---\n``.
