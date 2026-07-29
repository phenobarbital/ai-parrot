---
type: Concept
title: synthesize_results()
id: func:parrot.bots.flows.core.storage.synthesis.synthesize_results
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM-summarize all agent responses collected in a ``FlowResult``.
---

# synthesize_results

```python
async def synthesize_results(ctx: 'FlowContext', result: 'FlowResult', *, max_tokens: int=8192, temperature: float=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None) -> str
```

LLM-summarize all agent responses collected in a ``FlowResult``.

This is the single source of truth for synthesis used by both:
- ``AgentsFlow.run_flow(on_complete=[synthesize_results])`` hooks.
- ``SynthesisNode.execute()`` for in-graph summarization (TASK-1066).

The function mirrors ``SynthesisMixin._synthesize_results``'s prompt-
building and LLM-call logic, adapted for the new-style context-based API.

Args:
    ctx: The current flow execution context. Must have a
        ``synthesis_client`` attribute that is an ``AbstractClient``-
        compatible object (has ``ask(prompt=...) -> response``).
    result: The ``FlowResult`` (or duck-type) whose ``.responses``
        dict provides per-node results to synthesize.
    max_tokens: Maximum tokens for the LLM response.
    temperature: LLM sampling temperature.
    user_id: Optional user identifier forwarded to the LLM.
    session_id: Optional session identifier forwarded to the LLM.

Returns:
    Synthesized summary string.

Raises:
    RuntimeError: If ``ctx.synthesis_client`` is ``None`` or absent.
