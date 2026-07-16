---
type: Concept
title: install()
id: func:parrot.knowledge.wiki.claude_code.cli.install
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Install the wiki toolkit as Claude Code infrastructure.
---

# install

```python
def install(path_: Optional[str], git_hook: bool, gitignore: bool, build_now: bool) -> None
```

Install the wiki toolkit as Claude Code infrastructure.

Writes a small config plus assistant-facing wiring so Claude Code
consults the knowledge graph for codebase questions — preferring
scoped `wikitoolkit query "<question>"` calls over grepping raw
files — and keeps the graph fresh on every git commit.
