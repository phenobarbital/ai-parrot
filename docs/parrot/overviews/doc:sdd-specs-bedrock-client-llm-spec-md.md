---
type: Wiki Overview
title: 'Feature Specification: Native Bedrock Client (Converse API) + Nova 2 Sonic'
id: doc:sdd-specs-bedrock-client-llm-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot currently accesses AWS Bedrock exclusively via the Anthropic SDK's
relates_to:
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.clients.bedrock
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.models.basic
  rel: mentions
- concept: mod:parrot.models.bedrock_models
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Native Bedrock Client (Converse API) + Nova 2 Sonic

**Feature ID**: FEAT-302
**Date**: 2026-07-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.x (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot currently accesses AWS Bedrock exclusively via the Anthropic SDK's
`AsyncAnthropicBedrock` transport (FEAT-232). This wraps the Anthropic Messages
API over a Bedrock credential chain, which limits the system to:

- **Claude-only models** — no access to Nova, Llama, Mistral, DeepSeek, or
  other Bedrock-hosted models.
- **No Bedrock-native features** — guardrails (`guardrailConfig`), Bedrock
  prompt caching (`cachePoint`), native structured output
  (`outputConfig.textFormat`), and the uniform Converse envelope are all
  unavailable.
- **No voice/speech** — Amazon Nova 2 Sonic provides bidirectional
  speech-to-speech, but its `InvokeModelWithBidirectionalStream` API
  requires a separate experimental SDK that boto3 does not support.

### Goals

- G1: Provide a native `BedrockConverseClient` using `aioboto3` and the Converse
  API as the primary route for text-based LLM interaction on Bedrock.
- G2: Support tool use, extended thinking (`reasoningContent`), prompt caching
  (`cachePoint`), structured output, and guardrails via the Converse API.
- G3: Provide an `invoke_model` fallback for models without ARN-versioned IDs
  (Opus 4.8, Fable 5).
- G4: Integrate Amazon Nova 2 Sonic as an experimental voice client following
  the `GeminiLiveClient.stream_voice()` pattern.
- G5: Coexist with the existing `AnthropicClient` bedrock backend — no
  backward-compatibility breaks.

### Non-Goals (explicitly out of scope)

- Replacing or deprecating `AnthropicClient` + `BedrockBackend` (FEAT-232).
- Supporting "Claude in Amazon Bedrock" Messages API (`/anthropic/v1/messages`
  SSE) — the existing Anthropic SDK backend handles this.
- Modifying existing voice integrations (LiveKit, LiveAvatar, MS Teams voice).
- Implementing STT/TTS subsystems — Nova Sonic provides native bidirectional
  audio, bypassing `AbstractTranscriberBackend` / `AbstractTTSBackend`.

---

## 2. Architectural Design

### Overview

The feature introduces two new client classes:

1. **`BedrockConverseClient(AbstractClient)`** — async-first client using
   `aioboto3` to call the Bedrock Runtime Converse API directly. Registered
   in the factory as `bedrock-converse`. Uses the existing `bedrock_models.py`
   translator for model ID resolution. Implements the full `AbstractClient`
   contract: `get_client()`, `ask()`, `ask_stream()`, `resume()`, `invoke()`.
   Extended thinking is a first-class feature (improvement over AnthropicClient
   which only handles it defensively).

2. **`NovaSonicClient`** — experimental bidirectional speech-to-speech client
   using the Pre-Alpha `aws_sdk_bedrock_runtime` SDK (v0.7.0, Python >= 3.12).
   Follows `GeminiLiveClient.stream_voice()` pattern: sender task reads PCM
   chunks from `AsyncIterator[bytes]`, receiver yields `LiveVoiceResponse`
   for `VoiceChatHandler` compatibility. Located in `ai-parrot-integrations[voice]`
   alongside existing voice integrations.

### Component Diagram

```
                        ┌────────────────────────────────┐
                        │      LLMFactory.create()       │
                        │   SUPPORTED_CLIENTS registry   │
                        └─────────┬──────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
     ┌─────────────────┐ ┌───────────────────┐ ┌──────────────┐
     │ AnthropicClient │ │BedrockConverseClient│ │ OpenAIClient │
     │ (bedrock/direct)│ │ (bedrock-converse) │ │   (openai)   │
     │   [FEAT-232]    │ │     [FEAT-302]     │ │              │
     └───────┬─────────┘ └───────┬───────────┘ └──────────────┘
             │                   │
             │                   ├──→ aioboto3.client("bedrock-runtime")
             │                   │      ├── converse()
             │                   │      ├── converse_stream()
             │                   │      ├── invoke_model()        (fallback)
             │                   │      └── apply_guardrail()     (PII)
             │                   │
             ▼                   ▼
     AsyncAnthropicBedrock   ToolSchemaAdapter
     (Anthropic SDK)         ToolFormat.BEDROCK
                             _clean_for_bedrock()

     ┌───────────────────────────────────────────────┐
     │            NovaSonicClient [experimental]     │
     │     (ai-parrot-integrations[voice])           │
     │                                               │
     │  aws_sdk_bedrock_runtime (Pre-Alpha v0.7.0)  │
     │  InvokeModelWithBidirectionalStream           │
     │  PCM 16kHz in / 24kHz out                    │
     │  stream_voice() → LiveVoiceResponse          │
     └──────────────────┬────────────────────────────┘
                        │
                        ▼
               VoiceChatHandler
               VoiceBot (provider-aware)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` (base.py:244) | extends | `BedrockConverseClient` subclasses it |
| `LLMFactory` (factory.py:48) | registers | `bedrock-converse` key + lazy import |
| `bedrock_models.translate()` (bedrock_models.py:87) | uses | Model ID translation; extend `PUBLIC_TO_BEDROCK` |
| `ToolFormat` (manager.py:43) | extends | Add `BEDROCK` enum value |
| `ToolSchemaAdapter` (manager.py:53) | extends | Add `_clean_for_bedrock()` |
| `AIMessageFactory` (responses.py:389) | extends | Add `from_bedrock()` static method |
| `CompletionUsage` (basic.py:48) | extends | Add `from_bedrock()` classmethod |
| `GeminiLiveClient` (live.py:467) | pattern | `NovaSonicClient` follows `stream_voice()` pattern |
| `LiveVoiceResponse` (live.py:156) | reuses | Nova Sonic yields same shape |
| `VoiceProvider` (voice/models.py:24) | extends | Add `BEDROCK_NOVA_SONIC` |
| `VoiceChatHandler` (voice/handler.py) | compatible | No changes needed if `LiveVoiceResponse` shape maintained |
| `parrot.conf` (conf.py:464) | uses | Reuse existing AWS credential config vars |

### Data Models

```python
# New: CompletionUsage.from_bedrock() — parrot/models/basic.py
@classmethod
def from_bedrock(cls, usage: Dict[str, Any]) -> "CompletionUsage":
    """Create from Bedrock Converse API usage dict."""
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)
    return cls(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        extra_usage={
            "cacheReadInputTokens": usage.get("cacheReadInputTokens", 0),
            "cacheWriteInputTokens": usage.get("cacheWriteInputTokens", 0),
        }
    )
```

```python
# New: AIMessageFactory.from_bedrock() — parrot/models/responses.py
@staticmethod
def from_bedrock(
    response: Dict[str, Any],
    input_text: str,
    model: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    structured_output: Any = None,
    tool_calls: List[ToolCall] = None
) -> AIMessage:
    """Create AIMessage from Bedrock Converse API response."""
    content = ""
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            content += block["text"]
    return AIMessage(
        input=input_text,
        output=structured_output or content,
        is_structured=structured_output is not None,
        structured_output=structured_output,
        model=model,
        provider="bedrock-converse",
        usage=CompletionUsage.from_bedrock(response.get("usage", {})),
        stop_reason=response.get("stopReason"),
        finish_reason=response.get("stopReason"),
        tool_calls=tool_calls or [],
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        raw_response=response,
        response=content if isinstance(content, str) else str(content)
    )
```

### New Public Interfaces

```python
# parrot/clients/bedrock.py
class BedrockConverseClient(AbstractClient):
    client_type: str = "bedrock-converse"
    client_name: str = "bedrock-converse"
    _default_model: str = "claude-sonnet-4-5"
    _fallback_model: str = "claude-haiku-4-5"
    _lightweight_model: str = "claude-haiku-4-5-20251001"
    _min_cache_tokens: int = 1024

    def __init__(
        self,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        region_prefix: Optional[str] = None,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        max_retries: int = 4,
        read_timeout: int = 120,
        **kwargs
    ): ...

    async def get_client(self) -> Any: ...
    async def ask(self, prompt, model=None, ...) -> AIMessage: ...
    async def ask_stream(self, prompt, model=None, ...) -> AsyncIterator[Union[str, AIMessage]]: ...
    async def resume(self, session_id, user_input, state) -> AIMessage: ...
    async def invoke(self, prompt, ...) -> InvokeResult: ...

    # Bedrock-specific
    async def _converse(self, payload: dict) -> dict: ...
    async def _converse_stream(self, payload: dict) -> AsyncIterator[dict]: ...
    async def _invoke_native(self, messages, ...) -> dict: ...
    async def apply_guardrail_text(self, text, source="OUTPUT") -> str: ...
```

---

## 3. Module Breakdown

### Module 1: Response Model Extensions
- **Path**: `parrot/models/basic.py`, `parrot/models/responses.py`
- **Responsibility**: Add `CompletionUsage.from_bedrock()` and `AIMessageFactory.from_bedrock()` factory methods
- **Depends on**: none (these are leaf data models)

### Module 2: Tool Schema Adapter
- **Path**: `parrot/tools/manager.py`
- **Responsibility**: Add `ToolFormat.BEDROCK` enum value and `_clean_for_bedrock()` adapter that maps ai-parrot tool schemas to Bedrock's `toolSpec`/`inputSchema.json` envelope
- **Depends on**: none

### Module 3: Model ID Extensions
- **Path**: `parrot/models/bedrock_models.py`
- **Responsibility**: Extend `PUBLIC_TO_BEDROCK` with Nova model IDs and optionally other multi-provider models
- **Depends on**: none

### Module 4: BedrockConverseClient — Core
- **Path**: `parrot/clients/bedrock.py`
- **Responsibility**: Implement `BedrockConverseClient(AbstractClient)` with `get_client()` (aioboto3 session), `ask()` (Converse API + tool loop), `ask_stream()` (ConverseStream → str chunks + AIMessage), `invoke()` (lightweight stateless), `resume()` (tool-use resumption). Includes `_converse()`/`_converse_stream()` thin wrappers, `_is_capacity_error()` override for `ThrottlingException`, and lazy import of `aioboto3`.
- **Depends on**: Module 1, Module 2, Module 3

### Module 5: BedrockConverseClient — Advanced Features
- **Path**: `parrot/clients/bedrock.py` (same file, additional methods/params)
- **Responsibility**: Add extended thinking (first-class `thinking` param via `additionalModelRequestFields`), prompt caching (`cachePoint` blocks), structured output (`outputConfig.textFormat` + schema-in-system-prompt fallback), guardrails (`guardrailConfig` + `apply_guardrail_text()`), and `_invoke_native()` fallback for models without ARN-versioned IDs.
- **Depends on**: Module 4

### Module 6: Factory Registration + Dependencies
- **Path**: `parrot/clients/factory.py`, `pyproject.toml`, `parrot/conf.py`
- **Responsibility**: Register `bedrock-converse` in `SUPPORTED_CLIENTS` with lazy import. Add `bedrock-native` extra with `aioboto3>=13.0`. Add `BEDROCK_GUARDRAIL_ID`/`BEDROCK_GUARDRAIL_VERSION` config vars.
- **Depends on**: Module 4

### Module 7: NovaSonicClient — Experimental Voice
- **Path**: `ai-parrot-integrations/src/parrot/integrations/bedrock/nova_sonic.py` (or `parrot/voice/nova_sonic.py`)
- **Responsibility**: Implement `NovaSonicClient` using `aws_sdk_bedrock_runtime` SDK. `stream_voice()` yields `LiveVoiceResponse`. Sender/receiver task pattern. Handles `sessionStart`, `promptStart`, `audioInput`, `toolUse`/`toolResult`, barge-in, 8-min reconnection. `_apply_pii_guardrail()` for transcription PII filtering.
- **Depends on**: Module 4 (shares guardrail helpers), Module 6 (dependencies)

### Module 8: Voice Integration — Provider Registration
- **Path**: `parrot/voice/models.py`, `parrot/bots/voice.py`
- **Responsibility**: Add `VoiceProvider.BEDROCK_NOVA_SONIC` enum. Make `VoiceBot._resolve_llm_config()` provider-aware (or create `NovaSonicVoiceBot` subclass).
- **Depends on**: Module 7

### Module 9: Tests
- **Path**: `tests/clients/test_bedrock_converse.py`, `tests/clients/test_nova_sonic.py`, `tests/models/test_bedrock_usage.py`
- **Responsibility**: Unit tests for all modules. Mock `aioboto3` client for Converse API responses. Test tool loop, streaming, thinking, caching, guardrails, factory registration. Mock Nova Sonic SDK for voice tests.
- **Depends on**: All prior modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_completion_usage_from_bedrock` | Module 1 | Maps camelCase `inputTokens`/`outputTokens` + cache tokens |
| `test_aimessage_factory_from_bedrock` | Module 1 | Constructs AIMessage from Converse response shape |
| `test_tool_format_bedrock` | Module 2 | Produces `toolSpec`/`inputSchema.json` envelope |
| `test_bedrock_model_translate_nova` | Module 3 | Translates Nova model IDs with region prefix |
| `test_bedrock_client_get_client` | Module 4 | Returns aioboto3 bedrock-runtime client |
| `test_bedrock_client_ask` | Module 4 | Calls converse(), returns AIMessage |
| `test_bedrock_client_ask_tool_loop` | Module 4 | Iterates on `stopReason=tool_use`, executes tools |
| `test_bedrock_client_ask_stream` | Module 4 | Yields str chunks + AIMessage sentinel |
| `test_bedrock_client_invoke` | Module 4 | Lightweight stateless call, returns InvokeResult |
| `test_bedrock_client_resume` | Module 4 | Resumes suspended tool-use flow |
| `test_bedrock_thinking` | Module 5 | Passes thinking config via `additionalModelRequestFields` |
| `test_bedrock_thinking_signature_preserved` | Module 5 | ReasoningContent signature survives tool loop |
| `test_bedrock_cache_point` | Module 5 | Adds cachePoint blocks to tools/system/messages |
| `test_bedrock_structured_output` | Module 5 | Uses `outputConfig.textFormat` with JSON schema |
| `test_bedrock_guardrail` | Module 5 | Passes `guardrailConfig` and processes guard blocks |
| `test_bedrock_invoke_native` | Module 5 | Fallback to invoke_model with Anthropic-native payload |
| `test_bedrock_factory_registration` | Module 6 | `LLMFactory.create("bedrock-converse:claude-sonnet-4-5")` works |
| `test_bedrock_throttling_error` | Module 4 | `_is_capacity_error()` detects ThrottlingException |
| `test_nova_sonic_stream_voice` | Module 7 | Yields LiveVoiceResponse with text/audio |
| `test_nova_sonic_tool_use` | Module 7 | Mid-conversation tool call and result flow |
| `test_nova_sonic_pii_guardrail` | Module 7 | ApplyGuardrail redacts PII from transcription |
| `test_voice_provider_enum` | Module 8 | BEDROCK_NOVA_SONIC added |

### Integration Tests

| Test | Description |
|---|---|
| `test_bedrock_converse_end_to_end` | Full ask() → tool_use → tool_result → end_turn cycle with mocked aioboto3 |
| `test_bedrock_stream_end_to_end` | Full ask_stream() → yield chunks → AIMessage cycle |
| `test_nova_sonic_session_lifecycle` | sessionStart → promptStart → audio → completionEnd |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_converse_response():
    return {
        "output": {"message": {
            "role": "assistant",
            "content": [{"text": "Hello, world!"}]
        }},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 100, "outputTokens": 50},
        "metrics": {"latencyMs": 200}
    }

@pytest.fixture
def mock_converse_tool_response():
    return {
        "output": {"message": {
            "role": "assistant",
            "content": [{"toolUse": {
                "toolUseId": "tu_123",
                "name": "get_weather",
                "input": {"location": "NYC"}
            }}]
        }},
        "stopReason": "tool_use",
        "usage": {"inputTokens": 150, "outputTokens": 30}
    }

@pytest.fixture
def mock_converse_thinking_response():
    return {
        "output": {"message": {
            "role": "assistant",
            "content": [
                {"reasoningContent": {
                    "reasoningText": {"text": "Let me think..."},
                    "signature": "sig_abc123"
                }},
                {"text": "The answer is 42."}
            ]
        }},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 200, "outputTokens": 100}
    }
```

---

## 5. Acceptance Criteria

- [ ] `BedrockConverseClient.ask()` returns `AIMessage` with correct usage, stop_reason, and text content from Converse API
- [ ] `BedrockConverseClient.ask()` handles tool-use loops: detects `stopReason=tool_use`, executes tools via `_execute_tool()`, feeds results back, preserves `reasoningContent.signature` intact across turns
- [ ] `BedrockConverseClient.ask_stream()` yields `str` chunks then a final `AIMessage` sentinel, following the streaming convention of all other clients
- [ ] `BedrockConverseClient.invoke()` returns `InvokeResult` via `_build_invoke_result()` for lightweight stateless calls
- [ ] `BedrockConverseClient.resume()` resumes suspended tool-use flows from `HumanInteractionInterrupt`
- [ ] Extended thinking works as first-class feature: `thinking` param passed via `additionalModelRequestFields`, `reasoningContent` blocks parsed in responses
- [ ] Prompt caching inserts `cachePoint` blocks in tools/system/messages positions per Bedrock convention
- [ ] Structured output uses Bedrock-native `outputConfig.textFormat` with JSON schema when available, falling back to schema-in-system-prompt
- [ ] Guardrails: `guardrailConfig` passed to Converse when configured; `apply_guardrail_text()` available for standalone PII filtering
- [ ] `_invoke_native()` fallback works for models without ARN-versioned IDs using Anthropic-native payload format
- [ ] `ToolFormat.BEDROCK` added to enum; `_clean_for_bedrock()` produces correct `toolSpec`/`inputSchema.json` envelope
- [ ] `CompletionUsage.from_bedrock()` maps camelCase fields + cache token fields
- [ ] `AIMessageFactory.from_bedrock()` constructs correct AIMessage from Converse response shape
- [ ] `bedrock_models.py` extended with Nova model IDs (`amazon.nova-sonic-v1:0`, `amazon.nova-2-sonic-v1:0`)
- [ ] Factory registration: `LLMFactory.create("bedrock-converse:claude-sonnet-4-5")` returns `BedrockConverseClient`; existing `bedrock:` provider unchanged
- [ ] `_is_capacity_error()` correctly detects `ThrottlingException` (botocore)
- [ ] `pyproject.toml` has `bedrock-native` extra with `aioboto3>=13.0`
- [ ] `NovaSonicClient.stream_voice()` yields `LiveVoiceResponse` compatible with `VoiceChatHandler`
- [ ] `VoiceProvider.BEDROCK_NOVA_SONIC` added to enum
- [ ] Nova Sonic client handles barge-in, tool use mid-conversation, and 8-min connection renewal
- [ ] All unit tests pass (`pytest tests/clients/test_bedrock_converse.py tests/models/test_bedrock_usage.py -v`)
- [ ] No breaking changes to existing `bedrock:` provider or any other client

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.clients.base import AbstractClient  # verified: parrot/clients/base.py:244
from parrot.models.responses import AIMessage, AIMessageFactory  # verified: parrot/models/responses.py:72, 389
from parrot.models.basic import CompletionUsage, ToolCall  # verified: parrot/models/basic.py:48, 23
from parrot.models.responses import InvokeResult  # verified: parrot/models/responses.py:1282
from parrot.models.bedrock_models import translate as translate_bedrock_model  # verified: parrot/models/bedrock_models.py:87
from parrot.tools.manager import ToolFormat, ToolSchemaAdapter  # verified: parrot/tools/manager.py:43, 53
from parrot.conf import (  # verified: parrot/conf.py:464-480
    AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_SESSION_TOKEN,
    BEDROCK_AWS_REGION, AWS_REGION_NAME
)
```

### Existing Class Signatures

```python
# parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):  # line 244
    client_type: str = "generic"  # line 250
    client_name: str = "generic"  # line 251
    _default_model: Optional[str] = None  # (set by subclasses)
    _fallback_model: Optional[str] = None
    _lightweight_model: Optional[str] = None  # line 256
    _min_cache_tokens: int = 0  # line 262

    @abstractmethod
    async def get_client(self) -> Any:  # line 846
    async def __aenter__(self):  # line 850
    async def __aexit__(self, *exc):  # line 864
    async def _ensure_client(self):  # line 652
    async def complete(self, prompt, ...) -> str:  # line 869
    def _prepare_tools(self, filter_names=None):  # line 1270
    async def _execute_tool(self, tool_name, parameters, ...):  # line 1330
    async def _prepare_conversation_context(self, ...):  # line 1858
    def _parse_structured_output(self, response_text, structured_output):  # line 2116
    def _build_invoke_result(self, output, output_type, model, usage, response):  # line 1731
    def _is_capacity_error(self, error) -> bool:  # line 831
    def _should_use_fallback(self, error) -> bool:  # line 831
    async def _emit_before_call(self):  # returns TraceContext
    async def _emit_after_call(self, trace, ...):  # awaited

# parrot/clients/claude.py
class AnthropicClient(AbstractClient):  # line 67
    client_type: str = "anthropic"  # line 70
    client_name: str = "claude"  # line 71
    _default_model: str = "claude-sonnet-4-5"  # line 73
    _min_cache_tokens: int = 1024  # line 77
    async def _sdk_create(self, payload: dict):  # line 310 — thin wrapper
    def _sdk_stream(self, payload: dict):  # line 316 — thin wrapper

# parrot/models/basic.py
class CompletionUsage(BaseModel):  # line 48
    prompt_tokens: int = 0  # line 70 (alias: input_tokens)
    completion_tokens: int = 0  # line 73 (alias: output_tokens)
    total_tokens: int = 0  # line 76
    extra_usage: Dict[str, Any] = {}  # line 88
    @classmethod def from_claude(cls, usage: Dict) -> "CompletionUsage":  # line 131
    @classmethod def from_openai(cls, usage: Any) -> "CompletionUsage":  # line 109

class ToolCall(BaseModel):  # line 23
    id: str; name: str; arguments: Dict[str, Any]
    result: Optional[Any] = None; error: Optional[str] = None

# parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    input: str; output: Any; model: str; provider: str
    usage: CompletionUsage; stop_reason: Optional[str]; finish_reason: Optional[str]
    tool_calls: List[ToolCall] = []; structured_output: Optional[Any]
    raw_response: Optional[Dict]; response: Optional[str]

class AIMessageFactory:  # line 389
    @staticmethod def from_claude(response: Dict, input_text, model, ...) -> AIMessage:  # line 573
    @staticmethod def from_openai(response, input_text, model, ...) -> AIMessage:  # line 425
    @staticmethod def create_message(...) -> AIMessage:  # line 993

class InvokeResult(BaseModel):  # line 1282
    output: Any; output_type: Optional[type]; model: str
    usage: CompletionUsage; raw_response: Optional[Any]

# parrot/tools/manager.py
class ToolFormat(Enum):  # line 43
    OPENAI = "openai"; ANTHROPIC = "anthropic"; GOOGLE = "google"
    GROQ = "groq"; VERTEX = "vertex"; GENERIC = "generic"

class ToolSchemaAdapter:  # line 53
    @staticmethod def clean_schema_for_provider(schema, provider: ToolFormat) -> Dict:  # line 59

# parrot/models/bedrock_models.py

…(truncated)…
