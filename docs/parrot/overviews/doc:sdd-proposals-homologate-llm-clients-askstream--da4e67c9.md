---
type: Wiki Overview
title: FEAT-174 — Homologate `ask_stream` Across All LLM Clients
id: doc:sdd-proposals-homologate-llm-clients-askstream-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All LLM clients in AI-Parrot should yield a uniform streaming contract from
---

---
id: FEAT-174
title: "Homologate ask_stream Across All LLM Clients"
type: feature
mode: enrichment
status: accepted
base_branch: dev
source:
  kind: inline
  jira_key: null
confidence: high
research_state: sdd/state/FEAT-174/
created_at: 2026-05-15
---

# FEAT-174 — Homologate `ask_stream` Across All LLM Clients

## §0 Origin

All LLM clients in AI-Parrot should yield a uniform streaming contract from
`ask_stream`: **N-1 yields of `str` (text chunks) followed by 1 final yield
of `AIMessage`** containing accumulated metadata (usage, tool_calls, turn_id,
provider, structured_output, etc.).

Currently only `GoogleGenAIClient` implements this pattern. The remaining
clients (`ClaudeClient`, `OpenAIClient`, `GroqClient`, `GrokClient`,
`Gemma4Client`, `TransformersClient`, `ClaudeAgentClient`) yield only `str`
chunks — forcing `BaseBot` to construct a degraded `AIMessage` with zero
usage stats as a fallback.

---

## §1 Synthesis Summary

**Mode**: enrichment (well-scoped refactor with clear reference implementation)
**Overall confidence**: **high**

The pattern is already proven in production via `GoogleGenAIClient`. The
downstream infrastructure (`BaseBot`, `StreamHandler`, `AgentHandler`,
`A2AServer`, Slack integration) already handles `Union[str, AIMessage]` via
`isinstance` checks. The change is additive — each client gains a final
`yield AIMessage(...)` after its streaming loop completes, using the same
`AIMessageFactory.from_<provider>()` methods already used by the non-streaming
`ask()` methods.

**Risk**: low. The new yield is appended *after* all text chunks, so existing
consumers that only iterate `str` chunks will see one extra non-`str` value at
the end. All known consumers already guard with `isinstance(chunk, AIMessage)`.

---

## §2 Codebase Findings

### §2.1 Localization — Files to Modify

| # | File | Lines | What changes |
|---|------|-------|-------------|
| 1 | `packages/ai-parrot/src/parrot/clients/base.py` | 1337 | Change abstract return type from `AsyncIterator[str]` to `AsyncIterator[Union[str, AIMessage]]` |
| 2 | `packages/ai-parrot/src/parrot/clients/claude.py` | 467-636 | Add final `AIMessage` yield after stream loop using `AIMessageFactory.from_claude()` |
| 3 | `packages/ai-parrot/src/parrot/clients/gpt.py` | 1162-1409 | Add final `AIMessage` yield (two paths: Responses API + Chat Completions) |
| 4 | `packages/ai-parrot/src/parrot/clients/groq.py` | 596-670 | Add final `AIMessage` yield using `AIMessageFactory.from_groq()` |
| 5 | `packages/ai-parrot/src/parrot/clients/grok.py` | 408-490 | Add final `AIMessage` yield using `AIMessageFactory.from_grok()` |
| 6 | `packages/ai-parrot/src/parrot/clients/gemma4.py` | 639-651+ | Add final `AIMessage` yield |
| 7 | `packages/ai-parrot/src/parrot/clients/hf.py` | 495-507+ | Add final `AIMessage` yield |
| 8 | `packages/ai-parrot/src/parrot/clients/claude_agent.py` | 526-593 | Add final `AIMessage` yield using `AIMessageFactory.from_claude_agent()` |

**Files that need NO changes** (already handle the dual type):

| File | Why safe |
|------|----------|
| `packages/ai-parrot/src/parrot/bots/base.py:1329-1367` | Already checks `isinstance(chunk, AIMessage)` and constructs fallback if none received |
| `packages/ai-parrot/src/parrot/handlers/stream.py:72,119,175,324` | Already checks `isinstance(chunk, AIMessage)` |
| `packages/ai-parrot/src/parrot/handlers/agent.py:2007` | Already checks `isinstance(chunk, AIMessage)` |
| `packages/ai-parrot/src/parrot/a2a/server.py:471` | Consumes via `BaseBot.ask_stream` which already handles it |
| `packages/ai-parrot/src/parrot/integrations/slack/assistant.py:252` | Consumes via bot wrapper |

**Derived clients (inherit from OpenAIClient — get the fix for free):**

| Client | File |
|--------|------|
| `OpenRouterClient` | `parrot/clients/openrouter.py` |
| `LocalLLMClient` | `parrot/clients/localllm.py` |
| `NvidiaClient` | `parrot/clients/nvidia.py` |
| `vLLMClient` | `parrot/clients/vllm.py` |

### §2.2 Constraints

1. **`AIMessageFactory` already has `from_<provider>()` for every client** — no new
   factory methods are needed. Each non-streaming `ask()` method already uses them.

2. **Metadata availability varies by provider SDK**:
   - **Claude**: `await stream.get_final_message()` returns full `Message` object with
     `usage`, `stop_reason`, `model`, `id` — already captured at line 554 but discarded.
   - **GPT (Responses API)**: `await stream.get_final_response()` at line 1339 — already
     captured but not used to build AIMessage.
   - **GPT (Chat Completions)**: No `get_final_message()` equivalent. Must accumulate
     usage from the final chunk (OpenAI includes `usage` in the last chunk when
     `stream_options={"include_usage": True}` is set) or construct with zeros.
   - **Groq**: Streaming chunks don't carry usage. Groq SDK supports
     `stream_options={"include_usage": True}` (same as OpenAI). Alternatively,
     construct with zeros and note limitation.
   - **Grok (xAI)**: Similar to OpenAI — depends on SDK support for stream usage.
   - **HuggingFace (Transformers)**: Local inference — token counts can be computed from
     the tokenizer after streaming.
   - **Gemma4**: Local inference — similar to HuggingFace.

3. **`BaseBot.ask_stream` fallback** (lines 1351-1366): Currently constructs a degraded
   `AIMessage` with `CompletionUsage(0, 0, 0)` when no AIMessage is yielded by the
   client. After this change, the fallback should rarely trigger — but must remain as
   a safety net.

4. **`CompletionUsage` factory methods** exist for all providers:
   - `CompletionUsage.from_claude()` — `basic.py:85-92`
   - `CompletionUsage.from_openai()` — `basic.py:63-69`
   - `CompletionUsage.from_groq()` — `basic.py:72-82`
   - `CompletionUsage.from_gemini()` — `basic.py:95-109`
   - Generic constructor for others

### §2.3 Reference Implementation — GoogleGenAIClient

**File**: `packages/ai-parrot/src/parrot/clients/google/client.py`
**Lines**: 2891-2910

```python
# After streaming loop completes, final_text is accumulated from all chunks
ai_message = AIMessageFactory.from_gemini(
    response=None,
    input_text=prompt,
    model=model,
    user_id=user_id,
    session_id=session_id,
    turn_id=turn_id,
    structured_output=final_output if final_output is not None else final_text,
    tool_calls=all_tool_calls_history,
    conversation_history=conversation_history,
    text_response=final_text,
    files=[],
    images=[],
    code=None
)
ai_message.provider = "google_genai"
yield ai_message
```

**Pattern**:
1. Accumulate `all_assistant_text` during streaming
2. Build `final_text = "".join(all_assistant_text)` after loop
3. Construct AIMessage via factory with all accumulated metadata
4. Yield the AIMessage as the last item

---

## §3 Hypothesis / Scope

### Primary Approach

For each client, add a final AIMessage yield at the end of the streaming loop:

**Claude** (highest value — has full metadata available):
```python
# After: final_message = await stream.get_final_message()
# ... existing max_tokens retry logic ...

# NEW: at end of method, build and yield AIMessage
ai_message = AIMessageFactory.from_claude(
    response=final_message.model_dump(),
    input_text=prompt,
    model=model_str,
    user_id=user_id,
    session_id=session_id,
    turn_id=turn_id,
    structured_output=None,  # streaming doesn't support structured output
    tool_calls=all_tool_calls  # if tool calls are tracked
)
yield ai_message
```

**GPT/OpenAI** (two streaming paths):
- **Responses API path**: Use `final_response` already captured at line 1339.
- **Chat Completions path**: Add `stream_options={"include_usage": True}` to request
  payload, capture the usage from the final chunk, then build AIMessage.

**Groq**: Add `stream_options={"include_usage": True}`, capture final chunk usage,
build AIMessage via `AIMessageFactory.from_groq()`.

**Grok/Gemma4/HF**: Build AIMessage with available metadata. For local models
(Gemma4, HF), usage may have zero tokens — acceptable since local inference
doesn't bill per token.

### Scope Boundary

- **In scope**: Modifying `ask_stream` in all 8 clients + abstract base type
- **Out of scope**: Modifying consumers (they already handle the dual type)
- **Out of scope**: Adding streaming tool-call support (separate feature)
- **Out of scope**: Changing the non-streaming `ask()` methods

---

## §4 Confidence Map

| Claim | Confidence | Evidence |
|-------|-----------|---------|
| GoogleGenAI pattern works as reference implementation | **high** | Production code, google/client.py:2891-2910 |
| All downstream consumers handle `Union[str, AIMessage]` | **high** | `isinstance` checks in base.py:1330, stream.py:72/119/175/324, agent.py:2007 |
| `AIMessageFactory.from_<provider>()` exists for all providers | **high** | responses.py:419 (openai), 468 (groq), 573 (claude), 858 (gemini) |
| Claude SDK provides full metadata via `get_final_message()` | **high** | claude.py:554-558, Anthropic SDK docs |
| OpenAI Responses API provides metadata via `get_final_response()` | **high** | gpt.py:1339 |
| OpenAI Chat Completions supports `stream_options.include_usage` | **medium** | OpenAI SDK docs; not yet used in codebase — needs verification |
| Groq SDK supports `stream_options.include_usage` | **medium** | Groq SDK mirrors OpenAI; needs runtime verification |
| Derived clients (OpenRouter, LocalLLM, Nvidia, vLLM) inherit fix | **high** | All extend OpenAIClient, none override ask_stream |

---

## §5 Open Questions

1. **Should clients that can't provide usage stats yield AIMessage with zeroed usage
   or skip the yield?**
   - **Answer**: Always yield AIMessage with best-effort metadata. Zeroed usage
     is better than no AIMessage — consumers get turn_id, provider, model, stop_reason.
   - **Status**: `[x]` resolved — always yield

---

## §6 Recommended Next Step

**`/sdd-spec FEAT-174`** — The localization is strong and the pattern is clear.
This is ready to be specified with tasks per client.

**Rationale**: High confidence across all claims. The reference implementation
exists and is proven. The infrastructure already supports the dual type. Each
client modification is self-contained and testable independently.

### Suggested Task Decomposition (for `/sdd-task`)

| Task | Scope | Depends On |
|------|-------|-----------|
| T1: Update AbstractClient type signature | `base.py` line 1337 | None |
| T2: ClaudeClient ask_stream AIMessage | `claude.py` | T1 |
| T3: OpenAIClient ask_stream AIMessage | `gpt.py` (both paths) | T1 |
| T4: GroqClient ask_stream AIMessage | `groq.py` | T1 |
| T5: GrokClient ask_stream AIMessage | `grok.py` | T1 |
| T6: Gemma4Client ask_stream AIMessage | `gemma4.py` | T1 |
| T7: TransformersClient ask_stream AIMessage | `hf.py` | T1 |
| T8: ClaudeAgentClient ask_stream AIMessage | `claude_agent.py` | T1 |
| T9: Integration tests | Verify all clients yield AIMessage | T2-T8 |

T2-T8 can run in parallel after T1.

---

## §7 Research Audit

| Metric | Value |
|--------|-------|
| Files read | 18 |
| Grep calls | 12 |
| Git calls | 0 |
| Findings | 11 |
| Budget consumed | 60% of default |
| Truncated | No |
| State directory | `sdd/state/FEAT-174/` |

---

## Alternatives

- **`/sdd-brainstorm FEAT-174`** — If you want to explore alternative streaming
  contracts (e.g., event-based SSE objects instead of Union type)
- **`/sdd-task FEAT-174`** — If the scope is trivial enough to skip the spec
  (not recommended — 8 clients is non-trivial coordination)
