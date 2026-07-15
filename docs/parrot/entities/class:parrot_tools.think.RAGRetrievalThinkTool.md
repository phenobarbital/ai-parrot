---
type: Wiki Entity
title: RAGRetrievalThinkTool
id: class:parrot_tools.think.RAGRetrievalThinkTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Specialized thinking tool for RAG retrieval strategy.
relates_to:
- concept: class:parrot_tools.think.ThinkTool
  rel: extends
---

# RAGRetrievalThinkTool

Defined in [`parrot_tools.think`](../summaries/mod:parrot_tools.think.md).

```python
class RAGRetrievalThinkTool(ThinkTool)
```

Specialized thinking tool for RAG retrieval strategy.

Guides the agent to plan retrieval approach based on query type,
expected document relevance, and retrieval method selection.

Particularly useful for Adaptive Agentic RAG implementations.

Example:
    >>> tool = RAGRetrievalThinkTool()
    >>> result = await tool.execute(
    ...     thoughts="User query is factual and specific. Dense retrieval "
    ...              "should work well. Will use top-5 chunks with "
    ...              "reranking. No need for hybrid search here."
    ... )
