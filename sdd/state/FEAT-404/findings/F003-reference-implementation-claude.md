---
id: F003
query_id: Q006,Q008
type: read
intent: Find the reference FEAT-397 implementation in an already-migrated client to copy the accumulation + emission pattern verbatim
executed_at: 2026-08-03T00:07:00Z
parent_id: null
depth: 0
---

# F003 — The five migrated clients follow one identical four-part pattern

## Summary

`grep -rn "_emit_round_event"` returns exactly five call sites — `grok.py:342`,
`groq.py:528`, `claude.py:641`, `gpt.py:1028`, `google/client.py:2062` — plus
the definition at `base.py:488`. `AnthropicClient.ask()` is the cleanest
template: (1) init `_lc_round_number = 0` and `_lc_accumulated_usage = None`
before the `while True` loop, (2) time each SDK call and build/accumulate the
round's `CompletionUsage` via `__add__`, (3) call `_emit_round_event` inside
the tool-use branch after tools execute, (4) after the loop, stamp
`extra_usage["rounds"]` when `round_number > 1` and overwrite
`ai_message.usage` with the accumulated total. Notably the emission sits
INSIDE the `stop_reason == "tool_use"` branch, so the final (non-tool) round
does not emit a round event — only `AfterClientCallEvent`.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 533-535
  symbol: `AnthropicClient.ask` (accumulator init)
  excerpt: |
    # FEAT-397: per-round token usage accumulation across the tool loop
    _lc_round_number = 0
    _lc_accumulated_usage: "Optional[CompletionUsage]" = None

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 557-572
  symbol: `AnthropicClient.ask` (per-round accumulate)
  excerpt: |
    _lc_round_number += 1
    _lc_round_duration_ms = (_lc_time.perf_counter() - _lc_round_t0) * 1000
    _lc_round_raw_usage = result.get("usage") or None
    if _lc_round_raw_usage:
        _lc_round_usage = CompletionUsage.from_claude(_lc_round_raw_usage)
        _lc_accumulated_usage = (
            _lc_round_usage if _lc_accumulated_usage is None
            else _lc_accumulated_usage + _lc_round_usage
        )
    else:
        _lc_round_usage = None

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 640-650
  symbol: `AnthropicClient.ask` (emission, inside the tool_use branch)
  excerpt: |
    # FEAT-397: emit ClientRoundEvent after tool execution for this round
    self._emit_round_event(
        _lc_tc,
        client_name=self._telemetry_client_name,
        model=model,
        round_number=_lc_round_number,
        usage=_lc_round_usage,
        raw_usage=_lc_round_raw_usage,
        tool_calls=_lc_round_tool_names,
        duration_ms=_lc_round_duration_ms,
    )

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 715-722
  symbol: `AnthropicClient.ask` (accumulated total onto AIMessage)
  excerpt: |
    # FEAT-397: replace the last-round-only usage with the accumulated
    # multi-round total. ...
    if _lc_accumulated_usage is not None:
        if _lc_round_number > 1:
            _lc_accumulated_usage.extra_usage["rounds"] = _lc_round_number
        ai_message.usage = _lc_accumulated_usage

- path: `packages/ai-parrot/src/parrot/clients/grok.py`
  lines: 342, 393
- path: `packages/ai-parrot/src/parrot/clients/groq.py`
  lines: 528, 661
- path: `packages/ai-parrot/src/parrot/clients/gpt.py`
  lines: 1028, 1113
- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 2062, 3695

## Notes

`AIMessage.total_usage()` (`models/responses.py:281`) is the read-side
accessor. `resume()` in `claude.py:745+` has NO FEAT-397 instrumentation —
the pattern was applied to `ask()` only, which is a precedent Bedrock can
follow (see F006).
