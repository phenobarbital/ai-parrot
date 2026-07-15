---
type: Wiki Entity
title: LocalKB
id: class:parrot.stores.kb.local.LocalKB
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Local Knowledge Base that loads markdown and text documents from a local
  directory.
relates_to:
- concept: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
  rel: extends
---

# LocalKB

Defined in [`parrot.stores.kb.local`](../summaries/mod:parrot.stores.kb.local.md).

```python
class LocalKB(AbstractKnowledgeBase)
```

Local Knowledge Base that loads markdown and text documents from a local directory.

Uses FAISS for semantic search with disk persistence for fast loading.
Ideal for agent-specific knowledge like:
- Database query patterns
- Tool usage examples
- Domain-specific procedures
- Analysis templates

Example structure:
    AGENTS_DIR/
    └── my_agent/
        └── kb/
            ├── database_queries.md
            ├── prophet_forecast.md
            └── tool_examples.md

## Methods

- `async def should_activate(self, query: str, context: Dict[str, Any]) -> Tuple[bool, float]` — Determine if KB should activate.
- `async def load_documents(self, force_reload: bool=False) -> int` — Load markdown documents from kb_directory into FAISS.
- `async def search(self, query: str, k: int=5, score_threshold: float=0.5, user_id: str=None, session_id: str=None, ctx: RequestContext=None, **kwargs) -> List[Dict[str, Any]]` — Search for relevant knowledge in markdown files.
- `def format_context(self, results: List[Dict]) -> str` — Format search results for prompt injection.
- `async def close(self)` — Cleanup resources.
