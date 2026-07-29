---
type: Wiki Summary
title: parrot.knowledge.pageindex.llm_adapter
id: mod:parrot.knowledge.pageindex.llm_adapter
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM adapter for PageIndex — wraps any AbstractClient for LLM-agnostic calls.
relates_to:
- concept: class:parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter
  rel: defines
- concept: func:parrot.knowledge.pageindex.llm_adapter.extract_json
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.knowledge.pageindex.llm_adapter`

LLM adapter for PageIndex — wraps any AbstractClient for LLM-agnostic calls.

## Classes

- **`PageIndexLLMAdapter`** — Wraps any AbstractClient for PageIndex-compatible LLM calls.

## Functions

- `def extract_json(content: str) -> Any` — Extract JSON from LLM text that may contain ```json fences.
