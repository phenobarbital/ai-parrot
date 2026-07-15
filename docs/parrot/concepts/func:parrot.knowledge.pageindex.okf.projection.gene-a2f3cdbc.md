---
type: Concept
title: generate_index_md()
id: func:parrot.knowledge.pageindex.okf.projection.generate_index_md
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generate a deterministic root-level index.md view of the JSON ToC.
---

# generate_index_md

```python
def generate_index_md(tree: dict, tree_name: str) -> str
```

Generate a deterministic root-level index.md view of the JSON ToC.

Lists **top-level concepts only** — children are intentionally omitted to
keep the index concise (per OKF spec §6: "root index lists all top-level
concepts with links").  Deeply nested sub-concepts are discoverable via
their parent's sidecar body or ``get_related`` traversal.

No YAML frontmatter in ``index.md`` (per OKF §6).  Entries are ordered
by their position in the ``structure`` list (preserving JSON ToC order).

Args:
    tree: OKF-enriched PageIndex tree dict.
    tree_name: PageIndex tree name (used in links).

Returns:
    Deterministic Markdown string for the ``index.md`` file.
