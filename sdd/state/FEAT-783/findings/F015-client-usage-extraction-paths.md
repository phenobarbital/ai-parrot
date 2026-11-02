---
id: F015
query_id: Q016
type: grep
intent: "Locate every place a provider usage payload is parsed in the client layer."
executed_at: 2026-10-30T23:08:00Z
duration_ms: 450
parent_id: null
depth: 0
lane: codebase
merged_from: ['FC-015']
---

# F015 — Client usage is normalised to TWO counters through a `CompletionUsage` shim; `raw_usage` is the only place cache tokens could survive

## Summary

Every provider's usage in `parrot/clients/` is funnelled into an OpenAI-shaped
`CompletionUsage` (`prompt_tokens` / `completion_tokens` / `total_tokens`) and then flattened
to `input_tokens` / `output_tokens` on the lifecycle events. `AbstractClient` documents the
mapping explicitly (base.py:684-687). `openai_base.py` does the same translation in four
places (lines 1084-1085, 1561-1562, 1699-1700, 1717-1718), including a synthesized
`CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)` fallback
(openai_base.py:1533) that **fabricates zeros when the provider reports nothing** — the exact
failure `UsageRecord.usage_reported` exists to flag downstream (FC-007).

A grep for `cache_read|cache_creation|cached_input` across the whole client package returns
**zero matches**: cache tokens are dropped at the normalisation boundary. The only survivor
is `ClientRoundEvent.raw_usage` — "Provider-native usage payload for this round, JSON-safe
(plain dict). Passed through as-is" (base.py:688-689). Any four-counter design must read
`raw_usage` per provider, because the normalised path has thrown the information away.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 682-689
  symbol: `_emit_round` docstring
  excerpt: |
    usage: This round's :class:`CompletionUsage`, or ``None`` when
        the provider reported no usage for the round. Flat token
        counts are extracted from it (``prompt_tokens`` ->
        ``input_tokens``, ``completion_tokens`` -> ``output_tokens``,
        ``total_tokens`` -> ``total_tokens``); all ``None`` when
        ``usage is None``.
    raw_usage: Provider-native usage payload for this round,
        JSON-safe (plain dict). Passed through as-is.

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 702-721
  symbol: `ClientRoundEvent construction`
  excerpt: |
    event = ClientRoundEvent(
        trace_context=tc, client_name=client_name, model=model or "",
        round_number=round_number,
        input_tokens=usage.prompt_tokens if usage is not None else None,
        output_tokens=usage.completion_tokens if usage is not None else None,
        total_tokens=usage.total_tokens if usage is not None else None,
        tool_calls=tuple(tool_calls), duration_ms=duration_ms, raw_usage=raw_usage,
        agent_name=current_agent_name.get(), user_id=current_user_id.get(),
        session_id=current_session_id.get(), )

- path: `packages/ai-parrot/src/parrot/clients/openai_base.py`
  lines: 1533
  symbol: `zero-usage fallback`
  excerpt: |
    usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

- path: `packages/ai-parrot/src/parrot/clients/openai_base.py`
  lines: 1561-1562
  symbol: `usage flattening`
  excerpt: |
    input_tokens=getattr(usage, "prompt_tokens", None),
    output_tokens=getattr(usage, "completion_tokens", None),

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 757, 789
  symbol: `cost on the call path`
  excerpt: |
    cost_usd = self._compute_call_cost(client_name, model, input_tokens, output_tokens)
    ...
    last_call_cost.set(cost_usd)

- path: `packages/ai-parrot/src/parrot/clients/`
  lines: n/a
  symbol: `cache-token grep`
  excerpt: |
    grep -rn "cache_read|cache_creation|cached_input" packages/ai-parrot/src/parrot/clients/
    -> no matches (only budget.py / budget_scope.py / openai_base.py / base.py
       hits for plain input_tokens / output_tokens / prompt_tokens)

## Notes

- `_emit_round` and `_emit_after_call` both `forward_to_global`, and `_emit_after_call` does
  so **awaited** to close a FEAT-548 race where fire-and-forget forwarding was dropped at
  shutdown (base.py:780-788). A usage sink registered globally is therefore guaranteed to
  observe the call before the caller proceeds — a stronger delivery guarantee than the
  source's hook-based design can offer.
- `ClientRoundEvent` carries `session_id`/`user_id` but `UsageRecord` deliberately drops
  them (FC-007). The per-round event is the richer surface; the per-call record is the
  privacy-filtered one.
