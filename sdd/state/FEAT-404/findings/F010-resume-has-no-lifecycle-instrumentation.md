---
id: F010
query_id: Q004
type: grep
intent: Verify whether BedrockConverseBase.resume() has a TraceContext available for round emission (follow-up after U2 was resolved in favour of instrumenting resume)
executed_at: 2026-08-03T00:20:00Z
parent_id: F006
depth: 1
---

# F010 — `resume()` has NO lifecycle instrumentation at all, not just no round events

## Summary

Grepping `_emit_before_call|_lc_tc|_lc_t0` across `bedrock.py` returns matches
ONLY inside `ask()` (659, 667, 854, 857). `resume()` (1000-1128) and `invoke()`
(1130+) have none — meaning `resume()` today emits neither
`BeforeClientCallEvent` nor `AfterClientCallEvent`, let alone `ClientRoundEvent`.
This materially raises the cost of the U2 decision: instrumenting `resume()`
for per-round usage is not a copy of the four-part pattern onto an
already-traced method, it first requires establishing the whole call-level
lifecycle span (`_emit_before_call` → `_lc_tc`, `_lc_t0`, and a matching
`_emit_after_call`) that `ask()` already has.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 578, 659, 667, 854, 857
  symbol: `BedrockConverseBase.ask` (the only instrumented method)
  excerpt: |
    578:    async def ask(
    659:        _lc_tc = self._emit_before_call(
    667:        _lc_t0 = time.perf_counter()
    854:            _lc_tc,
    857:            duration_ms=(time.perf_counter() - _lc_t0) * 1000,

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 1000
  symbol: `BedrockConverseBase.resume` (no _emit_before_call / _lc_tc / _lc_t0)

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 1130
  symbol: `BedrockConverseBase.invoke` (likewise uninstrumented)

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 864
  symbol: `BedrockConverseBase.ask_stream` (likewise uninstrumented)

## Notes

Implication for task decomposition: the resume() work is a strictly larger
task than the ask() work and should be a SEPARATE task in `/sdd-task`, not a
few extra lines folded into the ask() task. It also raises a fair question for
the spec — whether adding call-level lifecycle events to `resume()` is itself
in scope, or whether round events should be emitted against a locally-created
`TraceContext.new_root()`. The first is more correct; the second is narrower.
