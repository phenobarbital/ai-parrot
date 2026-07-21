---
type: Concept
title: build()
id: func:parrot.knowledge.wiki.cli.build
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generate (or refresh) the KB graph from the current repository.
---

# build

```python
def build(path_: Optional[str], name: Optional[str], backend: Optional[str], force: bool, no_git: bool, quiet: bool) -> None
```

Generate (or refresh) the KB graph from the current repository.

Deterministic and offline: scans source files (respecting
.gitignore), extracts summaries/API outlines, and writes pages +
typed edges into the wiki retrieval plane under .parrot/wiki.
