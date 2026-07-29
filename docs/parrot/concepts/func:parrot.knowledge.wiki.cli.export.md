---
type: Concept
title: export()
id: func:parrot.knowledge.wiki.cli.export
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Export the wiki as a human-readable markdown bundle.
---

# export

```python
def export(path_: Optional[str], output: str) -> None
```

Export the wiki as a human-readable markdown bundle.

Writes one markdown file per page (YAML frontmatter + body) plus a
root index.md — the `--wiki` action of the /parrotwiki command.
