---
id: F006
query_id: Q004,Q011
type: read
intent: Check the Bedrock streaming and resume paths for usage surfaces per-round observability would also need to cover
executed_at: 2026-08-03T00:10:00Z
parent_id: null
depth: 0
---

# F006 — `ask_stream()` and `resume()` are separate, currently-uninstrumented loops

## Summary

`BedrockConverseBase` has a SECOND tool loop in `resume()` at `bedrock.py:1063`
(`while True:` … `stopReason == "tool_use"` at 1068), structurally identical
to `ask()`'s. `ask_stream()` (864) collects usage from the terminal
`metadata` event into `usage_dict` (963/975) and synthesizes a result at
988-989 — it has exactly one usage payload per stream, no per-round usage.
The reference clients set the precedent for both: FEAT-397 instrumented
`ask()` ONLY — `AnthropicClient.resume()` (`claude.py:745+`) contains no
`_emit_round_event` and no accumulator — and the FEAT-397 spec lists
per-round `ask_stream()` as an explicit non-goal for all clients (F001).
`NovaAudio` (`nova/audio.py`, 419 lines) is the bidirectional voice path and
has no Converse tool loop at all.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 1063-1077
  symbol: `BedrockConverseBase.resume` (second, uninstrumented tool loop)
  excerpt: |
    while True:
        ...
        if result.get("stopReason") == "tool_use":
            for block in content_blocks:
                if "toolUse" not in block:
                    continue
                tool_use = block["toolUse"]
                tool_name = tool_use.get("name")

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 963-989
  symbol: `BedrockConverseBase.ask_stream` (single terminal usage payload)
  excerpt: |
    usage_dict: Dict[str, Any] = {}
    ...
        stop_reason = event["messageStop"].get("stopReason")
    ...
        usage_dict = event["metadata"].get("usage", {})
    ...
    "stopReason": stop_reason,
    "usage": usage_dict,

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 745-800
  symbol: `AnthropicClient.resume` (no FEAT-397 instrumentation — precedent)

- path: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
  lines: 1-40
  symbol: `NovaAudio`

## Notes

Recommendation implied by precedent: scope this feature to `ask()` for
parity with the five migrated clients, and record `resume()` + `ask_stream()`
as carried-forward non-goals rather than silently omitting them. Instrumenting
`resume()` would actually put Bedrock AHEAD of Anthropic, creating a new
inconsistency in the opposite direction.
