---
type: Concept
title: query()
id: func:parrot.knowledge.wiki.cli.query
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Scoped question against the codebase KB (lexical BM25 search).
---

# query

```python
def query(question: str, path_: Optional[str], top_k: int, budget: int, category: Optional[str], store_opt: Optional[str], backend_opt: Optional[str], as_table: bool, show_body: bool, as_json: bool) -> None
```

Scoped question against the codebase KB (lexical BM25 search).

Returns a token-budgeted context pack of page stubs (or a
human-facing Rich table with `--table`). Point `--store` at any
pre-built wiki (e.g. `docs/parrot`) to query it directly. Follow up
with `wikitoolkit page <id>` to read a full page, or
`wikitoolkit related <id>` to walk the graph.
