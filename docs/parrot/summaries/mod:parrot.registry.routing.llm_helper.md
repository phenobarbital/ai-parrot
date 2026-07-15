---
type: Wiki Summary
title: parrot.registry.routing.llm_helper
id: mod:parrot.registry.routing.llm_helper
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared LLM-route helper utilities (FEAT-111 Module 3).
relates_to:
- concept: func:parrot.registry.routing.llm_helper.extract_json_from_response
  rel: defines
- concept: func:parrot.registry.routing.llm_helper.run_llm_ranking
  rel: defines
---

# `parrot.registry.routing.llm_helper`

Shared LLM-route helper utilities (FEAT-111 Module 3).

Extracted from ``IntentRouterMixin._parse_invoke_response`` to be reused by
both the strategy-level router and the new store-level ``StoreRouter``.

Usage::

    from parrot.registry.routing import extract_json_from_response, run_llm_ranking

    raw_dict = extract_json_from_response(ai_message)
    result = await run_llm_ranking(bot.invoke, prompt, timeout_s=1.0)

## Functions

- `def extract_json_from_response(response: Any) -> Optional[dict]` — Extract the first JSON object from an LLM response.
- `async def run_llm_ranking(invoke_fn: Callable, prompt: str, timeout_s: float) -> Optional[dict]` — Call *invoke_fn* with *prompt*, apply a timeout, and parse JSON output.
