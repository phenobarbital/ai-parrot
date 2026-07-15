---
type: Wiki Entity
title: WebSearchAgent
id: class:parrot.bots.search.WebSearchAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: An agent specialized in performing web searches.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# WebSearchAgent

Defined in [`parrot.bots.search`](../summaries/mod:parrot.bots.search.md).

```python
class WebSearchAgent(BasicAgent)
```

An agent specialized in performing web searches.

By default, it is equipped with several search tools:
- GoogleSearchTool
- GoogleSiteSearchTool
- DdgSearchTool
- BingSearchTool
- SerpApiSearchTool

If `use_builtin_search` is True, it will fallback to using
Gemini's built-in Google Search functionality via `tool_type='builtin_tools'`.

If `contrastive_search` is True, performs a two-step search:
first the original query, then a contrastive analysis of
competitors/alternatives based on the initial results.

If `synthesize` is True, an additional LLM call (with `use_tools=False`)
analyzes and synthesizes the search results using a synthesis prompt.

## Methods

- `async def ask(self, question: str, **kwargs) -> AIMessage` — Override ask to support contrastive search and synthesis.
