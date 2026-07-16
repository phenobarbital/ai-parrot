---
type: Wiki Entity
title: NavigatorPageIndex
id: class:parrot_tools.navigator.prompt.NavigatorPageIndex
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manages the PageIndex tree for Navigator knowledge base.
---

# NavigatorPageIndex

Defined in [`parrot_tools.navigator.prompt`](../summaries/mod:parrot_tools.navigator.prompt.md).

```python
class NavigatorPageIndex
```

Manages the PageIndex tree for Navigator knowledge base.

Indexes all markdown files in agents/navigator/kb/ into a single
hierarchical tree. Provides:
- tree_context: compact node summaries for system prompt (Layer 1)
- retrieve(query): detailed context for a specific query (Layer 2)

Usage:
    page_index = NavigatorPageIndex()
    await page_index.build(adapter)  # Index all KB docs

    # Layer 1: compact tree for prompt
    tree_context = page_index.get_tree_context()

    # Layer 2: detailed retrieval per query
    context = await page_index.retrieve("How to configure api-card?")

## Methods

- `async def build(self, adapter: PageIndexLLMAdapter) -> None` — Build or load the PageIndex tree from KB markdown files.
- `def get_tree_context(self) -> str` — Get compact tree context for system prompt (Layer 1).
- `async def retrieve(self, query: str) -> dict[str, Any]` — Retrieve detailed context for a query (Layer 2).
- `def is_built(self) -> bool`
- `def get_tree_json(self) -> Optional[dict]`
