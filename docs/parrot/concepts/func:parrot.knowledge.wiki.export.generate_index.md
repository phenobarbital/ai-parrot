---
type: Concept
title: generate_index()
id: func:parrot.knowledge.wiki.export.generate_index
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render the root ``index.md`` (title, relative path, summary).
---

# generate_index

```python
def generate_index(wiki_name: str, entries: list[tuple[str, str, str]]) -> str
```

Render the root ``index.md`` (title, relative path, summary).
