---
id: F002
query_id: Q002
type: read
intent: Read AbstractClient._emit_round_event and ClientRoundEvent to learn the primitives Bedrock/Nova must reuse
executed_at: 2026-08-03T00:06:00Z
parent_id: null
depth: 0
---

# F002 — `_emit_round_event` is provider-agnostic and already on the base class

## Summary

`AbstractClient._emit_round_event()` (`clients/base.py:488`) is fully
provider-agnostic: it takes a `TraceContext`, `round_number`, an optional
`CompletionUsage`, a provider-native `raw_usage` dict, tool names and a
duration, then short-circuits when neither the client-local nor the global
registry has `ClientRoundEvent` subscribers. Because `BedrockConverseBase`
subclasses `AbstractClient` (F004), the primitive is ALREADY inherited —
Bedrock/Nova need call sites, not new infrastructure. `ClientRoundEvent`
itself lives in `core/events/lifecycle/events/client.py:177`.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 488-499
  symbol: `AbstractClient._emit_round_event`
  excerpt: |
    def _emit_round_event(
        self,
        tc: "TraceContext",
        *,
        client_name: str,
        model: str,
        round_number: int,
        usage: "Optional[CompletionUsage]",
        raw_usage: "Optional[dict]",
        tool_calls: "Sequence[str]",
        duration_ms: float,
    ) -> None:

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 531-537
  symbol: `_emit_round_event` (subscriber short-circuit)
  excerpt: |
    if not self.events.has_subscribers(ClientRoundEvent):
        # FEAT-397 (TASK-2040 fix): client registries never carry direct
        # subscribers in production — fall back to checking the current
        # global registry before giving up ...
        if not get_global_registry().has_subscribers(ClientRoundEvent):
            return

- path: `packages/ai-parrot/src/parrot/clients/base.py`
  lines: 544-546
  symbol: `_emit_round_event` (None-usage semantics)
  excerpt: |
    input_tokens=usage.prompt_tokens if usage is not None else None,
    output_tokens=usage.completion_tokens if usage is not None else None,
    total_tokens=usage.total_tokens if usage is not None else None,

- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py`
  lines: 177
  symbol: `ClientRoundEvent`

## Notes

Zero changes required in `base.py`. The emission guard already handles the
"no subscribers" hot path, so adding call sites in Bedrock costs nothing
when observability is off.
