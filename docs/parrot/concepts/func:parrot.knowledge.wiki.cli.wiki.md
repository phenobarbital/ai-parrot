---
type: Concept
title: wiki()
id: func:parrot.knowledge.wiki.cli.wiki
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM Wiki — codebase knowledge base for agents (FEAT-260).
---

# wiki

```python
def wiki() -> None
```

LLM Wiki — codebase knowledge base for agents (FEAT-260).

Build a machine-first knowledge graph of the current repository
and query it with scoped, token-budgeted questions instead of
grepping raw files.
