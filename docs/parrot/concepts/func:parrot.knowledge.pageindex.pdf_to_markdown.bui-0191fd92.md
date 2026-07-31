---
type: Concept
title: build_node_markdown_map()
id: func:parrot.knowledge.pageindex.pdf_to_markdown.build_node_markdown_map
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Walk a node tree and return ``{node_id: concatenated_markdown}``.'
---

# build_node_markdown_map

```python
def build_node_markdown_map(structure: object, pages: list[tuple[int, str]]) -> dict[str, str]
```

Walk a node tree and return ``{node_id: concatenated_markdown}``.

Uses ``start_index``/``end_index`` semantics identical to
:func:`parrot.knowledge.pageindex.utils.add_node_text` (1-based, inclusive
range). Folder/synthetic nodes without page ranges contribute the
empty string.
