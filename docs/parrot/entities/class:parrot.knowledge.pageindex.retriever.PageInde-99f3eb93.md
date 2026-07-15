---
type: Wiki Entity
title: PageIndexRetriever
id: class:parrot.knowledge.pageindex.retriever.PageIndexRetriever
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tree-search retriever using an LLM to navigate a PageIndex tree.
---

# PageIndexRetriever

Defined in [`parrot.knowledge.pageindex.retriever`](../summaries/mod:parrot.knowledge.pageindex.retriever.md).

```python
class PageIndexRetriever
```

Tree-search retriever using an LLM to navigate a PageIndex tree.

Given a query, the retriever asks an LLM to reason over the tree
structure and identify which nodes are most likely to contain
relevant information.

## Methods

- `async def search(self, query: str) -> TreeSearchResult` — Execute LLM tree search to find relevant nodes.
- `async def retrieve(self, query: str, pdf_pages: Optional[list[tuple[str, int]]]=None) -> str` — Search tree and return concatenated text of matching nodes.
- `def get_tree_context(self, include_summaries: bool=True) -> str` — Return the tree structure as formatted context for system prompts.
- `def get_tree_json(self) -> dict` — Return the full tree data as a dictionary.
- `def from_json(cls, json_data: dict | str, adapter: PageIndexLLMAdapter, expert_knowledge: Optional[str]=None, model: str='gemini-3.1-flash-lite-preview') -> PageIndexRetriever` — Create a retriever from a JSON file path or dict.
