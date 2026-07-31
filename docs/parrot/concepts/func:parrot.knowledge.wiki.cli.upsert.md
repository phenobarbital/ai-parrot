---
type: Concept
title: upsert()
id: func:parrot.knowledge.wiki.cli.upsert
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Incrementally re-ingest specific files (or last-commit changes).
---

# upsert

```python
def upsert(paths: tuple[str, ...], path_: Optional[str], changed: bool, quiet: bool) -> None
```

Incrementally re-ingest specific files (or last-commit changes).

Used by the git post-commit hook installed via
`parrot claude install` to keep the wiki fresh. Deleted files have
their pages removed. Directory overview pages are refreshed by the
next full `wikitoolkit build`.
