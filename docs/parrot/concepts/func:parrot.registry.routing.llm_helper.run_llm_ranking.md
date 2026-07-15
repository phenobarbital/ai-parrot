---
type: Concept
title: run_llm_ranking()
id: func:parrot.registry.routing.llm_helper.run_llm_ranking
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Call *invoke_fn* with *prompt*, apply a timeout, and parse JSON output.
---

# run_llm_ranking

```python
async def run_llm_ranking(invoke_fn: Callable, prompt: str, timeout_s: float) -> Optional[dict]
```

Call *invoke_fn* with *prompt*, apply a timeout, and parse JSON output.

On timeout, exception, or un-parseable output the function logs a WARNING
and returns ``None``.  It **never** raises.

Args:
    invoke_fn: An async callable that accepts a ``str`` prompt and returns
        an ``AIMessage``-like object.
    prompt: The prompt to pass to the LLM.
    timeout_s: Maximum seconds to wait for the LLM response.

Returns:
    Parsed ``dict`` from the LLM response, or ``None`` on failure.
