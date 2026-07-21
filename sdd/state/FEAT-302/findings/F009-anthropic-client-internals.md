---
id: F009
slug: anthropic-client-internals
query: Deep dive into AnthropicClient ask/ask_stream/tool-loop/invoke/resume
type: read
---

## Finding: AnthropicClient Implementation Contract

**Path**: `packages/ai-parrot/src/parrot/clients/claude.py` (1909 lines)

### ask() (lines 412-698)
1. `_ensure_client()` → `_resolve_model()` → `_prepare_conversation_context()`
2. `_emit_before_call()` (fire-and-forget)
3. Structured output: schema-in-system-prompt (NOT response_format). `format_schema_instruction()` appended to system prompt
4. Prompt caching: `_apply_cache_hints()` converts CacheableSegments to `cache_control: {"type": "ephemeral"}` blocks (max 4)
5. Tool loop: unbounded `while True` driven by `stop_reason == "tool_use"`. NO max_iterations guard.
6. Tool execution: iterates content blocks with `type == "tool_use"`, calls `_execute_tool(name, input)`, feeds results back as `tool_result` messages
7. HumanInteractionInterrupt: captures messages + tool_call_id for `resume()`
8. Returns `AIMessageFactory.from_claude(result)` with `provider="claude"`
9. `_emit_after_call()` (awaited)

### ask_stream() (lines 810-1056)
1. Same setup as ask() but no structured_output parameter
2. Opens stream: `async with self._sdk_stream(payload) as stream:`
3. Iterates `stream.text_stream`, yields str chunks
4. `final_message = await stream.get_final_message()` for usage/stop_reason
5. NO tool loop in streaming — if Claude calls tools, stream just completes
6. Rate limit / server error retries with exponential backoff
7. Max tokens retry: increases max_tokens by `token_increase_factor`
8. Final `AIMessage` sentinel yielded last

### _sdk_create() / _sdk_stream() (lines 310-320)
- `_sdk_create()`: `await self.client.messages.create(**sanitized_payload)`
- `_sdk_stream()`: `self.client.messages.stream(**sanitized_payload)`
- `_sanitize_payload_for_model()`: drops temp/top_p/top_k for adaptive-only models

### invoke() (lines 1810-1905)
- Lightweight: no memory, no retry, no lifecycle events
- Bypasses `_sdk_create()` — calls `self.client.messages.create()` directly
- Returns `InvokeResult` via `_build_invoke_result()` (base class helper)

### resume() (lines 700-808)
- Resumes HumanInteractionInterrupt flows
- Injects user_input as tool_result, runs same tool loop

### Extended thinking: NOT implemented as first-class feature
- `_sanitize_payload_for_model()` handles `thinking` key defensively if present
- No `reasoningContent` / ThinkingBlock handling in response parsing
- ZaiClient has it; AnthropicClient does not

### Key patterns for BedrockClient:
- Override `_sdk_create()` → `await self.client.converse(**payload)` (Bedrock Converse)
- Override `_sdk_stream()` → `await self.client.converse_stream(**payload)` (Bedrock ConverseStream)
- Use same tool loop structure but with Bedrock's `stopReason` and `toolUse` content blocks
- Preserve `reasoningContent.signature` in tool loop (Bedrock requirement not in AnthropicClient)
- Add `AIMessageFactory.from_bedrock()` for Converse response shape
