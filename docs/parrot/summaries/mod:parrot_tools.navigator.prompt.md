---
type: Wiki Summary
title: parrot_tools.navigator.prompt
id: mod:parrot_tools.navigator.prompt
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Navigator context provider using PageIndex (vectorless, LLM-driven RAG).
relates_to:
- concept: class:parrot_tools.navigator.prompt.NavigatorPageIndex
  rel: defines
- concept: func:parrot_tools.navigator.prompt.get_navigator_layers
  rel: defines
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.knowledge.pageindex
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot_tools.navigator.prompt`

Navigator context provider using PageIndex (vectorless, LLM-driven RAG).

Replaces the previous LocalKB + FAISS approach with PageIndex tree-search:
- Layer 1: tree_context (node summaries) injected into CONFIGURE phase prompt
- Layer 2: retriever.retrieve(query) for on-demand detailed context per request
- Layer 3: get_widget_schema() tool for exact DB lookups (unchanged)

PageIndex advantages over embedding-based RAG:
- No FAISS/vector DB required
- LLM reasons over document structure (hierarchy-aware)
- Works with any LLM (uses gemini-flash-lite by default)
- Transparent: thinking field explains retrieval decisions
- Markdown headers map naturally to tree nodes

## Classes

- **`NavigatorPageIndex`** — Manages the PageIndex tree for Navigator knowledge base.

## Functions

- `def get_navigator_layers(page_index: NavigatorPageIndex=None) -> list[PromptLayer]` — Return all custom Navigator prompt layers.
