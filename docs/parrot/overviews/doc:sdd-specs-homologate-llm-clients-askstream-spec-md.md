---
type: Wiki Overview
title: 'Feature Specification: Homologate `ask_stream` Across All LLM Clients'
id: doc:sdd-specs-homologate-llm-clients-askstream-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All LLM clients in AI-Parrot implement `ask_stream` as an async generator,
  but
relates_to:
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.basic
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Homologate `ask_stream` Across All LLM Clients

**Feature ID**: FEAT-174
**Date**: 2026-05-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Proposal**: `sdd/proposals/homologate-llm-clients-askstream.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

All LLM clients in AI-Parrot implement `ask_stream` as an async generator, but
their streaming contracts diverge:

- **GoogleGenAIClient** yields `str` text chunks followed by a final `AIMessage`
  carrying full metadata (usage, tool_calls, turn_id, provider, stop_reason).
- **Every other client** (Claude, GPT, Groq, Grok, Gemma4, HF, ClaudeAgent)
  yields only `str` chunks — no final AIMessage.

This forces `BaseBot.ask_stream` to construct a **degraded fallback** `AIMessage`
with zeroed usage stats (`CompletionUsage(0, 0, 0)`) whenever the underlying
client doesn't yield one. Consumers (handlers, integrations) receive incomplete
metadata for 6 out of 7 providers.

### Goals

- **G1**: Every LLM client's `ask_stream` yields `Union[str, AIMessage]` — N-1
  `str` chunks followed by 1 final `AIMessage` with best-effort metadata.
- **G2**: Update the abstract return type in `AbstractClient` to reflect the
  uniform contract.
- **G3**: Consumers (`BaseBot`, `StreamHandler`, `AgentHandler`, etc.) require
  **zero changes** — they already handle the dual type via `isinstance` checks.
- **G4**: Clients that cannot provide usage stats (e.g., local inference) still
  yield an `AIMessage` with zeroed usage — always yield, never skip.

### Non-Goals (explicitly out of scope)

- Modifying consumers/handlers — they already support `Union[str, AIMessage]`.
- Adding streaming tool-call support (separate feature).
- Changing the non-streaming `ask()` methods.
- Modifying `GoogleGenAIClient` — it's the reference, already correct.
- Runtime fallback-on-failure strategies (rejected — the approach is additive,
  not fallback-based; see `sdd/proposals/homologate-llm-clients-askstream.proposal.md`).

---

## 2. Architectural Design

### Overview

The approach is uniform across all clients. After the streaming loop completes
(all text chunks yielded), each client:

1. Assembles the accumulated text into `final_text`.
2. Extracts available metadata from the provider SDK's final message/response
   object (usage, stop_reason, model, etc.).
3. Calls the existing `AIMessageFactory.from_<provider>()` factory method —
   the same one used by the non-streaming `ask()` — to build an `AIMessage`.
4. Yields that `AIMessage` as the last item.

This is the exact pattern already in production via `GoogleGenAIClient`
(`google/client.py:2891-2910`).

### Component Diagram

```
ask_stream() generator
  │
  ├── [1..N-1] yield str          ← text chunks from provider stream
  │
  └── [N]      yield AIMessage    ← metadata from SDK final message
                   │
                   ├── usage: CompletionUsage.from_<provider>()
                   ├── stop_reason / finish_reason
                   ├── model, provider, turn_id
                   ├── tool_calls (if accumulated during stream)
                   ├── user_id, session_id
                   └── raw_response (provider-specific dict)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient.ask_stream` | modifies return type | `AsyncIterator[str]` → `AsyncIterator[Union[str, AIMessage]]` |
| `AIMessageFactory.from_<provider>()` | reuses | Already exists for all 7 providers — no new factories |
| `CompletionUsage.from_<provider>()` | reuses | Already exists for all providers |
| `BaseBot.ask_stream` | unchanged | Already checks `isinstance(chunk, AIMessage)` at line 1330 |
| `StreamHandler` | unchanged | Already checks `isinstance(chunk, AIMessage)` at lines 72, 119, 175, 324 |
| `AgentHandler` | unchanged | Already checks `isinstance(chunk, AIMessage)` at line 2007 |

### Data Models

No new data models. Reuses existing:

```python
# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    input: str
    output: Any
    model: str
    provider: str
    usage: CompletionUsage
    stop_reason: Optional[str]
    finish_reason: Optional[str]
    tool_calls: List[ToolCall]
    user_id: Optional[Union[str, int]]
    session_id: Optional[str]
    turn_id: Optional[str]
    raw_response: Optional[Dict[str, Any]]
    # ... (32 fields total)
```

### New Public Interfaces

No new classes or public methods. The only signature change is the abstract
method's return type:

```python
# packages/ai-parrot/src/parrot/clients/base.py:1322-1337
# BEFORE:
async def ask_stream(...) -> AsyncIterator[str]:

# AFTER:
async def ask_stream(...) -> AsyncIterator[Union[str, AIMessage]]:
```

---

## 3. Module Breakdown

### Module 1: AbstractClient Type Signature Update
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py`
- **Responsibility**: Change the abstract `ask_stream` return type from
  `AsyncIterator[str]` to `AsyncIterator[Union[str, AIMessage]]`
- **Depends on**: none

### Module 2: ClaudeClient `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/claude.py`
- **Responsibility**: After streaming loop and retry logic, build and yield
  `AIMessage` using `AIMessageFactory.from_claude()` with `final_message`
  data already captured at line 555.
- **Depends on**: Module 1

### Module 3: OpenAIClient `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/gpt.py`
- **Responsibility**: Handle two streaming paths:
  - **Responses API**: Use `final_response` already captured at line 1339.
  - **Chat Completions**: Add `stream_options={"include_usage": True}` to
    request, capture usage from final chunk, build AIMessage.
- **Depends on**: Module 1

### Module 4: GroqClient `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/groq.py`
- **Responsibility**: Build and yield `AIMessage` via
  `AIMessageFactory.from_groq()`. Attempt `stream_options.include_usage`
  for usage stats; fall back to zeroed usage.
- **Depends on**: Module 1

### Module 5: GrokClient `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/grok.py`
- **Responsibility**: Build and yield `AIMessage` via
  `AIMessageFactory.from_grok()` with best-effort metadata.
- **Depends on**: Module 1

### Module 6: Gemma4Client `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/gemma4.py`
- **Responsibility**: Build and yield `AIMessage` with zeroed usage (local
  inference). Use `AIMessageFactory.create_message()` or direct construction.
- **Depends on**: Module 1

### Module 7: TransformersClient `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/hf.py`
- **Responsibility**: Build and yield `AIMessage` with zeroed usage (local
  inference). Use `AIMessageFactory.create_message()` or direct construction.
- **Depends on**: Module 1

### Module 8: ClaudeAgentClient `ask_stream` AIMessage Yield
- **Path**: `packages/ai-parrot/src/parrot/clients/claude_agent.py`
- **Responsibility**: After streaming text blocks, build and yield `AIMessage`
  via `AIMessageFactory.from_claude_agent()`.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_client_type_hint` | Module 1 | Verify `ask_stream` return annotation is `AsyncIterator[Union[str, AIMessage]]` |
| `test_claude_ask_stream_yields_aimessage` | Module 2 | Mock Anthropic SDK stream; verify final yield is AIMessage with usage |
| `test_gpt_ask_stream_responses_api_yields_aimessage` | Module 3 | Mock OpenAI Responses API stream; verify final AIMessage |
| `test_gpt_ask_stream_chat_completions_yields_aimessage` | Module 3 | Mock OpenAI Chat Completions stream; verify final AIMessage |
| `test_groq_ask_stream_yields_aimessage` | Module 4 | Mock Groq stream; verify final AIMessage |
| `test_grok_ask_stream_yields_aimessage` | Module 5 | Mock xAI stream; verify final AIMessage |
| `test_gemma4_ask_stream_yields_aimessage` | Module 6 | Mock local model; verify final AIMessage with zeroed usage |
| `test_hf_ask_stream_yields_aimessage` | Module 7 | Mock transformers pipeline; verify final AIMessage |
| `test_claude_agent_ask_stream_yields_aimessage` | Module 8 | Mock Claude Agent SDK; verify final AIMessage |

### Integration Tests

| Test | Description |
|---|---|
| `test_all_clients_stream_contract` | Parametrized test — for each client class, verify `ask_stream` yields ≥1 `str` then exactly 1 `AIMessage` as last item |
| `test_basebot_receives_client_aimessage` | Verify `BaseBot.ask_stream` uses the client-provided `AIMessage` instead of constructing the fallback |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_stream_chunks():
    """Simulate provider stream: 3 text chunks."""
    return ["Hello", " world", "!"]

@pytest.fixture
def expected_aimessage_fields():
    """Fields every final AIMessage must have populated."""
    return {"model", "provider", "turn_id", "usage"}
```

---

## 5. Acceptance Criteria

- [ ] `AbstractClient.ask_stream` return type is `AsyncIterator[Union[str, AIMessage]]`
- [ ] `ClaudeClient.ask_stream` yields a final `AIMessage` with `usage.prompt_tokens > 0` and `usage.completion_tokens > 0`
- [ ] `OpenAIClient.ask_stream` (Responses API path) yields a final `AIMessage` with usage stats
- [ ] `OpenAIClient.ask_stream` (Chat Completions path) yields a final `AIMessage` (usage best-effort)
- [ ] `GroqClient.ask_stream` yields a final `AIMessage`
- [ ] `GrokClient.ask_stream` yields a final `AIMessage`
- [ ] `Gemma4Client.ask_stream` yields a final `AIMessage` (zeroed usage acceptable)
- [ ] `TransformersClient.ask_stream` yields a final `AIMessage` (zeroed usage acceptable)
- [ ] `ClaudeAgentClient.ask_stream` yields a final `AIMessage`
- [ ] Derived clients (`OpenRouterClient`, `LocalLLMClient`, `NvidiaClient`, `vLLMClient`) inherit the new behavior without code changes
- [ ] `BaseBot.ask_stream` fallback `AIMessage` construction still works as safety net but is no longer exercised by any built-in client
- [ ] No breaking changes to existing streaming consumers (`StreamHandler`, `AgentHandler`, `A2AServer`, Slack integration)
- [ ] All existing tests continue to pass
- [ ] New unit tests for each client's final AIMessage yield

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every path, class, method, and line number below has been verified via `read`.

### Verified Imports

```python
from parrot.models import AIMessage, AIMessageFactory, CompletionUsage  # verified: parrot/models/__init__.py
from parrot.models.basic import ToolCall  # verified: parrot/models/basic.py
from typing import AsyncIterator, Union  # verified: all client files import these
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    @abstractmethod
    async def ask_stream(                          # line 1322
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
    ) -> AsyncIterator[str]:                       # line 1337 — TO CHANGE
        ...

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessageFactory:
    @staticmethod
    def from_claude(response, input_text, model, user_id=None,
                    session_id=None, turn_id=None,
                    structured_output=None,
                    tool_calls=None) -> AIMessage:     # line 573
    @staticmethod
    def from_openai(response, input_text, model, user_id=None,
                    session_id=None, turn_id=None,
                    structured_output=None) -> AIMessage: # line 419
    @staticmethod
    def from_groq(response, input_text, model, user_id=None,
                  session_id=None, turn_id=None,
                  structured_output=None) -> AIMessage:   # line 468
    @staticmethod
    def from_grok(response, input_text, model, user_id=None,
                  session_id=None, turn_id=None,
                  structured_output=None) -> AIMessage:   # line 515
    @staticmethod
    def from_gemini(response, input_text, model, ...,
                    text_response=None, ...) -> AIMessage: # line 858
    @staticmethod
    def from_claude_agent(messages, input_text, model=None,
                          ...) -> AIMessage:               # line 623
    @staticmethod
    def create_message(response, input_text, model, ...,
                       usage=None, ...) -> AIMessage:      # line 952

# packages/ai-parrot/src/parrot/models/basic.py
class CompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    completion_time: Optional[float]
    extra_usage: Dict[str, Any]

    @classmethod
    def from_openai(cls, usage) -> "CompletionUsage":   # line 63
    @classmethod
    def from_groq(cls, usage) -> "CompletionUsage":     # line 72
    @classmethod
    def from_claude(cls, usage) -> "CompletionUsage":   # line 85
    @classmethod
    def from_gemini(cls, usage) -> "CompletionUsage":   # line 95
    @classmethod
    def from_grok(cls, usage) -> "CompletionUsage":     # line 172
```

### Provider-Specific Metadata Access Points

```python
# packages/ai-parrot/src/parrot/clients/claude.py:555
final_message = await stream.get_final_message()  # Anthropic SDK
# returns: Message(id, type, role, content, model, stop_reason, usage)
# usage has: input_tokens, output_tokens
stop_reason = final_message.stop_reason            # line 556

# packages/ai-parrot/src/parrot/clients/gpt.py:1337-1341
final_response = None                              # line 1337
try:
    final_response = await stream.get_final_response()  # line 1339
except Exception:
    final_response = None                          # line 1341
# Responses API only — Chat Completions path has no equivalent

# packages/ai-parrot/src/parrot/clients/groq.py:643
response_stream = await self.client.chat.completions.create(**request_args)
# No final message object — must use stream_options or construct zeroed usage

# packages/ai-parrot/src/parrot/clients/grok.py:466
async for token in chat.stream():
# xAI chat SDK — no final message object, construct with available metadata
```

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| Claude `ask_stream` yield | `AIMessageFactory.from_claude()` | static method call | `responses.py:573` |
| GPT `ask_stream` yield | `AIMessageFactory.from_openai()` | static method call | `responses.py:419` |
| Groq `ask_stream` yield | `AIMessageFactory.from_groq()` | static method call | `responses.py:468` |
| Grok `ask_stream` yield | `AIMessageFactory.from_grok()` | static method call | `responses.py:515` |
| Gemma4 `ask_stream` yield | `AIMessageFactory.create_message()` | static method call | `responses.py:952` |
| HF `ask_stream` yield | `AIMessageFactory.create_message()` | static method call | `responses.py:952` |
| ClaudeAgent `ask_stream` yield | `AIMessageFactory.from_claude_agent()` | static method call | `responses.py:623` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AIMessageFactory.from_hf()`~~ — does not exist; use `create_message()` instead
- ~~`AIMessageFactory.from_gemma()`~~ — does not exist; use `create_message()` instead
- ~~`AIMessageFactory.from_transformers()`~~ — does not exist; use `create_message()` instead
- ~~`CompletionUsage.from_hf()`~~ — does not exist; use default constructor
- ~~`CompletionUsage.from_gemma()`~~ — does not exist; use default constructor
- ~~`AbstractClient.build_stream_aimessage()`~~ — no such helper; each client builds its own
- ~~`stream_options` parameter in Grok xAI SDK~~ — not confirmed; verify at runtime

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

1. **Reference implementation**: `GoogleGenAIClient.ask_stream` at
   `google/client.py:2891-2910`. Every client should follow this same pattern:
   accumulate text, call factory, yield AIMessage.

2. **Use the existing factory for each provider** — do NOT construct `AIMessage`
   directly. The factories handle provider-specific field mappings.

3. **For Claude**: `final_message.model_dump()` converts the Anthropic SDK
   `Message` object into the `Dict[str, Any]` that `from_claude()` expects.

4. **For GPT Responses API**: `final_response` may be `None` if the try-except
   caught an error. Guard with `if final_response:` before extracting metadata;
   fall back to zeroed usage.

5. **For GPT Chat Completions**: Add `stream_options={"include_usage": True}` to
   the `create()` call. The final chunk will have a `usage` attribute. If the SDK
   version doesn't support this, fall back to zeroed usage.

6. **For local models (Gemma4, HF)**: Use `AIMessageFactory.create_message()`
   with `usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)`.

7. **Update return type annotations** in each client's `ask_stream` method
   signature from `AsyncIterator[str]` to `AsyncIterator[Union[str, AIMessage]]`.

### Known Risks / Gotchas

- **Risk**: `stream_options={"include_usage": True}` may not be supported by
  older OpenAI/Groq SDK versions. **Mitigation**: Wrap in try-except; zeroed
  usage is an acceptable fallback per the resolved design decision.

- **Risk**: Some consumers may iterate `ask_stream` with a `for` loop that
  doesn't check types and would break on a non-`str` yield. **Mitigation**:
  Research found all consumers use `isinstance` checks. The `BaseBot` fallback
  at `base.py:1351-1366` is the primary gateway — it already handles both types.

- **Risk**: GPT's Chat Completions path has no `get_final_response()` equivalent.
  **Mitigation**: Extract usage from the final chunk (it's included when
  `stream_options.include_usage` is True) or construct with accumulated data.

### External Dependencies

No new external dependencies. All changes use existing SDK capabilities:

| Package | Already Installed | Feature Used |
|---|---|---|
| `anthropic` | Yes | `stream.get_final_message()` |
| `openai` | Yes | `stream.get_final_response()`, `stream_options` |
| `groq` | Yes | `stream_options` (to verify) |

---

## 8. Open Questions

- [x] Should clients that can't provide usage stats yield AIMessage with zeroed
  usage or skip? — *Resolved in proposal*: Always yield AIMessage with best-effort
  metadata. Zeroed usage is better than no AIMessage — consumers still get turn_id,
  provider, model, stop_reason.

---

## Worktree Strategy

- **Isolation unit**: per-spec (all tasks run sequentially in one worktree)
- **Rationale**: All 8 modules touch different files with no cross-file conflicts,
  but they share the same abstract base type change (Module 1). Sequential
  execution is simplest — Module 1 first, then Modules 2-8 in any order.
- **Cross-feature dependencies**: none
- **Parallelism note**: Modules 2-8 are independent of each other after Module 1.
  If using multiple worktrees, ensure Module 1 is committed and merged first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-15 | Jesus Lara / Claude | Initial draft from FEAT-174 proposal |
