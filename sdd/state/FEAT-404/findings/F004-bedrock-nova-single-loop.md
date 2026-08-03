---
id: F004
query_id: Q004,Q005
type: read
intent: Read BedrockConverseBase.ask() and NovaClient to locate where per-round usage must be accumulated, and whether Nova shares that loop
executed_at: 2026-08-03T00:08:00Z
parent_id: null
depth: 0
---

# F004 — Nova inherits Bedrock's `ask()` verbatim: ONE loop covers both clients

## Summary

`NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration)` (`nova/client.py:30`)
is 121 lines of `__init__` and class attributes only — its docstring states
text (`ask`/`ask_stream`/`invoke`/`resume`) is "INHERITED ... no delegation
object, no reimplementation". `BedrockConverseClient` (`bedrock.py:1217`) is
likewise a thin subclass. Therefore instrumenting `BedrockConverseBase.ask()`
ONCE covers BedrockConverseClient AND NovaClient. The loop is already shaped
identically to Anthropic's: `while True:` at `bedrock.py:738`, SDK call at
740, `stopReason == "tool_use"` branch at 756, tool results appended at
805-807, `AIMessageFactory.from_bedrock` at 836, `_emit_after_call` at 853.
`_emit_before_call` already runs at 659 producing `_lc_tc`, and `_lc_t0` is
already set at 667 — both prerequisites for round emission are in place.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/nova/client.py`
  lines: 11-16
  symbol: `NovaClient` (module docstring)
  excerpt: |
    Text (``ask``/``ask_stream``/``invoke``/``resume``) is INHERITED from
    :class:`~parrot.clients.bedrock.BedrockConverseBase` — no delegation
    object, no reimplementation (resolved spec §8 U1).

- path: `packages/ai-parrot/src/parrot/clients/nova/client.py`
  lines: 30
  symbol: `NovaClient`
  excerpt: |
    class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 56
  symbol: `BedrockConverseBase`
  excerpt: |
    class BedrockConverseBase(AbstractClient):

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 659-667
  symbol: `BedrockConverseBase.ask` (trace context already available)
  excerpt: |
    _lc_tc = self._emit_before_call(
        client_name=self.client_name,
        model=resolved_model,
        ...
    )
    _lc_t0 = time.perf_counter()

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 738-756
  symbol: `BedrockConverseBase.ask` (the uninstrumented tool loop)
  excerpt: |
    while True:
        try:
            result = await self._sdk_create(payload)
        except Exception as e:
            if self._should_use_fallback(payload["modelId"], e):
                ...
        message = result.get("output", {}).get("message", {})
        content_blocks = message.get("content", [])
        if result.get("stopReason") == "tool_use":

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 800-810
  symbol: `BedrockConverseBase.ask` (end of tool_use branch — emission point)
  excerpt: |
                all_tool_calls.append(tc)
            bedrock_messages.append({"role": "assistant", "content": content_blocks})
            bedrock_messages.append({"role": "user", "content": tool_result_blocks})
            payload["messages"] = bedrock_messages
        else:
            bedrock_messages.append({"role": "assistant", "content": content_blocks})
            break

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 836-845
  symbol: `AIMessageFactory.from_bedrock` call (accumulated-total override point)

- path: `packages/ai-parrot/src/parrot/clients/bedrock.py`
  lines: 1217-1229
  symbol: `BedrockConverseClient`

## Notes

The tool loop tracks `all_tool_calls` globally but has NO per-round tool-name
list — the equivalent of Anthropic's `_lc_round_tool_names` must be added
inside the `for block in content_blocks` loop at 759-800.
