---
id: F001
query_id: Q001
type: read
intent: Read the FEAT-397 spec to extract the exact per-round observability contract that Bedrock/Nova must satisfy
executed_at: 2026-08-03T00:05:00Z
parent_id: null
depth: 0
---

# F001 — FEAT-397 contract and its explicit non-goal list

## Summary

`sdd/specs/tokens-observability.spec.md` §"Non-Goals" names the deferred
clients verbatim: `BedrockClient`, `TransformersClient`, `Gemma4Client`,
`ClaudeAgentClient`, `GeminiLiveClient`. `NovaClient` is NOT named — it did
not exist when FEAT-397 was written (Nova landed in FEAT-315). Per-round
instrumentation of `ask_stream()` is ALSO an explicit non-goal for every
client, and the spec fixes the semantics for missing usage: the round event
fires with token fields `None`. The spec also records that `Gemma4Client`
already accumulates totals and only lacks event emission.

## Citations

- path: `sdd/specs/tokens-observability.spec.md`
  lines: 63-75
  symbol: `Non-Goals (explicitly out of scope)`
  excerpt: |
    ### Non-Goals (explicitly out of scope)
    - Pricing/cost computation — OpenTelemetry + OpenLIT own cost accounting;
      this feature reports tokens only.
    - `usage_history` list on `AIMessage` (brainstorm Option B rejected ...)
    - Per-round instrumentation of `ask_stream()` — streaming rounds where
      providers do not report intermediate usage are a follow-up evaluation.
      Where a round's usage is unavailable, the event fires with token fields
      `None` (decided in brainstorm).
    - Non-priority clients (`BedrockClient`, `TransformersClient`,
      `Gemma4Client`, `ClaudeAgentClient`, `GeminiLiveClient`) — follow-up.
      (Gemma4 already accumulates totals; it only lacks the event emission.)

## Notes

The user's framing ("BedrockClient and NovaClient") maps onto exactly one
of the five deferred clients plus one client the spec never contemplated.
The other four holdouts remain open — see F008.
