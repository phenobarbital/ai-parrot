---
id: FEAT-302
title: Native Bedrock Client (Converse API) + Nova 2 Sonic Voice Integration
slug: bedrock-client-llm
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-07-11
  summary_oneline: Native Bedrock client (Converse API) + Nova 2 Sonic voice for ai-parrot
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-302/
created: 2026-07-11
updated: 2026-07-11
---

# FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic Voice Integration

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/compass_artifact_wf-766f01e9-ac55-5ac0-86a0-78dd7870fc59_text_markdown.md`
> **Audit**: [`sdd/state/FEAT-302/`](../state/FEAT-302/)

---

## 0. Origin

Build a native AWS Bedrock client for ai-parrot using `aioboto3` and the Converse API (`converse`/`converse_stream`) as the primary route, with `invoke_model` fallback for models without ARN-versioned IDs. Additionally, integrate Amazon Nova 2 Sonic (bidirectional speech-to-speech) as an experimental voice client using the Pre-Alpha `aws_sdk_bedrock_runtime` SDK.

The source research document provides a comprehensive design guide covering:
- Converse API feature parity matrix (tool use, extended thinking, prompt caching, structured output, guardrails)
- Async patterns with `aioboto3`/`aiobotocore`
- Nova 2 Sonic bidirectional streaming protocol
- PII/guardrails architecture for text and voice

**Initial signals**:
- Verbs: "develop", "support" → new feature (enrichment mode)
- Named entities: AWS Bedrock, Converse API, Nova 2 Sonic, aioboto3
- Components: clients, tools, integrations, models
- Acceptance criteria provided: yes (via research document recommendations)

---

## 1. Synthesis Summary

AI-Parrot currently accesses Bedrock via the Anthropic SDK's `AsyncAnthropicBedrock` transport (FEAT-232), which routes through the Messages API and limits the system to Claude-only models without Bedrock-native features (guardrails, multi-provider, Converse envelope). This proposal introduces a new `BedrockConverseClient` subclass of `AbstractClient` that uses `aioboto3` to call the Bedrock Runtime Converse API directly — gaining access to guardrails (`guardrailConfig`), prompt caching (`cachePoint`), structured output (`outputConfig.textFormat`), extended thinking (`reasoningContent`), and multi-provider model support (Claude, Nova, Llama, Mistral, DeepSeek). A separate `NovaSonicClient` in `ai-parrot-integrations[voice]` handles the bidirectional HTTP/2 speech-to-speech protocol using the experimental SDK, following the same `stream_voice()` pattern established by `GeminiLiveClient`. Both coexist with the existing `AnthropicClient` bedrock backend.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-302/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot/clients/base.py` | `AbstractClient` | 244+ | Base class — 5 abstract methods: `get_client`, `ask`, `ask_stream`, `resume`, `invoke` | F001, F009 |
| 2 | `parrot/clients/claude.py` | `AnthropicClient` | 67+ | Reference implementation — `_sdk_create()`/`_sdk_stream()` thin wrappers, tool loop pattern, streaming convention | F009 |
| 3 | `parrot/clients/anthropic_backends.py` | `BedrockBackend` | 98+ | Existing Bedrock transport via Anthropic SDK — coexist, not replace | F002 |
| 4 | `parrot/clients/factory.py` | `SUPPORTED_CLIENTS` | 48-72 | Client registry — add new `bedrock-converse` entry | F002 |
| 5 | `parrot/clients/live.py` | `GeminiLiveClient` | — | Only bidirectional voice client — `stream_voice()` pattern for Nova Sonic | F011 |
| 6 | `parrot/models/bedrock_models.py` | `translate()`, `PUBLIC_TO_BEDROCK` | 37-131 | Model ID translator — extend with Nova model IDs | F003 |
| 7 | `parrot/models/responses.py` | `AIMessage`, `AIMessageFactory` | 72+, 389+ | Response models — need `from_bedrock()` factory method | F010 |
| 8 | `parrot/models/basic.py` | `CompletionUsage`, `ToolCall` | 48+, 23+ | Usage tracking — need `from_bedrock()` classmethod | F010 |
| 9 | `parrot/tools/manager.py` | `ToolFormat`, `ToolSchemaAdapter` | 43-80 | Tool schema adaptation — add `BEDROCK` format | F004 |
| 10 | `parrot/conf.py` | AWS config vars | 464-480 | Credential resolution — reuse existing vars | F006 |
| 11 | `pyproject.toml` | `bedrock` extra | 348-353 | Dependencies — extend or add `bedrock-native` extra | F005 |
| 12 | `parrot/voice/models.py` | `VoiceProvider` enum | — | Voice provider registry — add `BEDROCK_NOVA_SONIC` | F011 |
| 13 | `parrot/voice/handler.py` | `VoiceChatHandler` | — | WebSocket handler — Nova Sonic must yield compatible `LiveVoiceResponse` | F011 |
| 14 | `parrot/bots/voice.py` | `VoiceBot` | — | Voice bot — hardcodes GeminiLiveClient; needs provider-awareness or subclass | F011 |

### 2.2 Constraints Discovered

- **Existing bedrock entry in factory.** The `"bedrock"` key in `SUPPORTED_CLIENTS` already maps to `AnthropicClient`. The new native client needs a distinct key (`bedrock-converse` or `bedrock-native`) OR the existing entry must be replaced.
  *Implication*: provider string choice affects backward compatibility for users currently using `bedrock:claude-sonnet-4-6`.
  *Evidence*: F002

- **AbstractClient contract.** The new client must implement 5 abstract methods: `get_client()`, `ask()`, `ask_stream()`, `resume()`, `invoke()`. Streaming must yield `str` chunks then an `AIMessage` sentinel. Tool execution uses `_prepare_tools()` and `_execute_tool()` from the base class.
  *Implication*: must handle Bedrock's event-stream format (`messageStart`, `contentBlockDelta`, etc.) and map to the str-chunk convention.
  *Evidence*: F001, F007, F009

- **AnthropicClient SDK wrappers.** The `_sdk_create()` and `_sdk_stream()` methods (claude.py:310-320) are thin wrappers around the Anthropic SDK. The new client should follow the same thin-wrapper pattern but call `self.client.converse()` and `self.client.converse_stream()` instead.
  *Evidence*: F009

- **Tool loop is unbounded.** AnthropicClient's tool loop is `while True` with no max_iterations guard. Bedrock client should follow the same pattern (stop on `stopReason != "tool_use"`) but also preserve `reasoningContent.signature` blocks when re-sending messages.
  *Evidence*: F009, Research document §1

- **Tool schema format divergence.** Bedrock Converse expects `{"toolSpec": {"name": ..., "inputSchema": {"json": ...}}}` while ai-parrot tools produce `{"name": ..., "parameters": {...}}`. The `ToolFormat` enum has no `BEDROCK` variant.
  *Implication*: need a `ToolFormat.BEDROCK` and `_clean_for_bedrock()` adapter in `ToolSchemaAdapter`.
  *Evidence*: F004

- **Response model gaps.** No `CompletionUsage.from_bedrock()` or `AIMessageFactory.from_bedrock()` exist. Bedrock Converse returns `inputTokens`/`outputTokens` (camelCase), `cacheReadInputTokens`/`cacheWriteInputTokens`, and tool-use blocks as `{"toolUse": {"toolUseId": ..., "name": ..., "input": ...}}`.
  *Implication*: must add both factory methods to map Bedrock's response shape to ai-parrot's models.
  *Evidence*: F010

- **Structured output is schema-in-system-prompt.** AnthropicClient injects JSON schema instructions into the system prompt and post-processes with `_parse_structured_output()`. Bedrock Converse also supports native structured output via `outputConfig.textFormat` with JSON schema — the new client can use either or both approaches.
  *Evidence*: F009, Research document §1

- **Prompt caching differs between APIs.** AnthropicClient uses `cache_control: {"type": "ephemeral"}` (max 4 blocks). Bedrock Converse uses `cachePoint: {"type": "default"}` with optional TTL. The caching mechanism must be re-implemented for Bedrock's format.
  *Evidence*: F009, Research document §1

- **Extended thinking not first-class in AnthropicClient.** `ask()` and `ask_stream()` don't have a `thinking` parameter — it's handled defensively in `_sanitize_payload_for_model()`. The new client has an opportunity to make extended thinking first-class via `additionalModelRequestFields` in the Converse API.
  *Evidence*: F009, Research document §1

- **Voice client must yield `LiveVoiceResponse`.** `VoiceChatHandler` iterates `LiveVoiceResponse` objects from the streaming client. Nova Sonic must yield the same shape for handler compatibility.
  *Implication*: `NovaSonicClient.stream_voice()` must yield `LiveVoiceResponse` with `text`, `audio_data` (bytes), `is_complete`, `is_interrupted`, `tool_calls`.
  *Evidence*: F011

- **VoiceBot hardcodes GeminiLiveClient.** `_resolve_llm_config()` always returns `GeminiLiveClient` config regardless of the `llm` parameter.
  *Implication*: either make `VoiceBot` provider-aware or create a `NovaSonicVoiceBot` subclass.
  *Evidence*: F011

- **Audio format alignment.** GeminiLiveClient uses 16kHz PCM input / 24kHz PCM output — same as Nova Sonic's default. LiveAvatar and RoomAudioPublisher expect 24kHz output. No resampling needed if Nova Sonic outputs at 24kHz.
  *Evidence*: F011

- **Nova Sonic 8-minute connection limit.** Connections must be renewed by passing conversation history. The client must implement reconnection logic with state preservation.
  *Evidence*: Research document §3

- **Nova Sonic SDK is Pre-Alpha.** `aws_sdk_bedrock_runtime==0.7.0` requires Python >= 3.12 and has breaking-change risk between minors. Must be pinned strictly and marked experimental.
  *Evidence*: Research document §2, F005

- **Async-first convention.** All public methods must be async. `aioboto3` provides async context managers and async iterators for streaming, aligning naturally.
  *Evidence*: F001

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `b9df4a0` | recent | Jesus | fixing issues with permission with msagent sdk | `parrot/bots/abstract.py` |
| FEAT-232 | prior | — | Bedrock backend via Anthropic SDK | `anthropic_backends.py`, `factory.py`, `bedrock_models.py` |

No recent changes to the `clients/` architecture. FEAT-232 established the current Bedrock-via-Anthropic-SDK pattern.

---

## 3. Probable Scope

### What's New

- **`parrot/clients/bedrock.py`** — `BedrockConverseClient(AbstractClient)`: native Bedrock client using `aioboto3`, implementing Converse API (`converse`/`converse_stream`) as primary route with `invoke_model` fallback. Features: guardrails (`guardrailConfig`), prompt caching (`cachePoint`), structured output (`outputConfig.textFormat`), extended thinking (`reasoningContent` with signature preservation), and multi-provider model support. Key methods:
  - `get_client()`: returns `aioboto3` Bedrock Runtime client with adaptive retries
  - `ask()`: builds Converse payload, runs tool-use loop preserving `reasoningContent.signature`, returns `AIMessage` via `AIMessageFactory.from_bedrock()`
  - `ask_stream()`: uses `converse_stream()`, maps `contentBlockDelta` events to str chunks, yields `AIMessage` sentinel
  - `invoke()`: lightweight stateless call via `converse()` without memory/history
  - `resume()`: resumes suspended tool-use flows
  - `_invoke_native()`: `invoke_model` fallback for models without ARN-versioned IDs

- **`parrot/clients/bedrock_nova_sonic.py`** (or in `ai-parrot-integrations[voice]`) — `NovaSonicClient`: experimental bidirectional speech-to-speech client using `aws_sdk_bedrock_runtime`. Follows `GeminiLiveClient.stream_voice()` pattern with sender/receiver tasks. Handles `InvokeModelWithBidirectionalStream`, PCM 16kHz input / 24kHz output, barge-in, tool use mid-conversation, and `ApplyGuardrail` for PII on transcriptions. Key features:
  - `stream_voice(audio_iterator, ...)`: yields `LiveVoiceResponse` for `VoiceChatHandler` compatibility
  - `_audio_sender()`: background task feeding PCM chunks as base64 `audioInput` events
  - `_apply_pii_guardrail()`: runs `ApplyGuardrail` on `textOutput`/ASR transcriptions before logging/display
  - 8-minute connection renewal with history replay
  - Turn detection sensitivity configuration (`endpointingSensitivity`: HIGH/MEDIUM/LOW)

- **`AIMessageFactory.from_bedrock()`** in `parrot/models/responses.py` — factory method mapping Bedrock Converse response shape to `AIMessage`: extracts text from `response['output']['message']['content']`, maps `stopReason`, converts `toolUse` blocks to `ToolCall`.

- **`CompletionUsage.from_bedrock()`** in `parrot/models/basic.py` — classmethod mapping `inputTokens`/`outputTokens` (camelCase) + `cacheReadInputTokens`/`cacheWriteInputTokens` to `CompletionUsage`.

- **`ToolFormat.BEDROCK`** in `parrot/tools/manager.py` — schema adapter mapping ai-parrot tool schemas to Bedrock's `toolSpec`/`inputSchema.json` envelope.

### What Changes

- **`parrot/clients/factory.py`::SUPPORTED_CLIENTS** — add `bedrock-converse` key pointing to `BedrockConverseClient` (lazy import). Existing `bedrock` key remains for backward compatibility.
  *Evidence*: F002

- **`parrot/models/bedrock_models.py`::PUBLIC_TO_BEDROCK** — extend with Nova model IDs (`amazon.nova-sonic-v1:0`, `amazon.nova-2-sonic-v1:0`) and optionally other Bedrock models (Llama, Mistral, etc.).
  *Evidence*: F003

- **`parrot/tools/manager.py`::ToolFormat** — add `BEDROCK` enum value and `_clean_for_bedrock()` in `ToolSchemaAdapter`.
  *Evidence*: F004

- **`parrot/voice/models.py`::VoiceProvider** — add `BEDROCK_NOVA_SONIC` enum value.
  *Evidence*: F011

- **`parrot/bots/voice.py`::VoiceBot`** — make `_resolve_llm_config()` provider-aware (or create `NovaSonicVoiceBot` subclass).
  *Evidence*: F011

- **`pyproject.toml`** — add `bedrock-native` extra with `aioboto3>=13.0`. Add `nova-sonic` extra (Python >= 3.12 only) with `aws_sdk_bedrock_runtime==0.7.0` (pinned).
  *Evidence*: F005

- **`parrot/conf.py`** — add `BEDROCK_GUARDRAIL_ID`, `BEDROCK_GUARDRAIL_VERSION` config vars.
  *Evidence*: F006

### What's Untouched (Non-Goals)

- **`AnthropicClient` and its backends** — the existing `bedrock`/`anthropic-aws` paths via the Anthropic SDK remain unchanged.
- **Other LLM clients** — OpenAI, Google, Groq, etc. are not affected.
- **Existing voice integrations** — LiveKit, LiveAvatar, MS Teams voice remain orthogonal.
- **STT/TTS subsystems** — `AbstractTranscriberBackend` and `AbstractTTSBackend` are file-based; Nova Sonic bypasses them with native bidirectional audio.
- **"Claude in Amazon Bedrock" Messages API** — out of scope; handled by existing Anthropic SDK backend.

### Patterns to Follow

- **AnthropicClient's `_sdk_create()`/`_sdk_stream()` thin wrappers** — the new client should have equivalent `_converse()`/`_converse_stream()` wrappers that call the Bedrock Converse API with payload sanitization.
  *Evidence*: F009

- **GeminiLiveClient's `stream_voice()` sender/receiver pattern** — sender task reads from `AsyncIterator[bytes]`, receiver iterates session responses yielding `LiveVoiceResponse`.
  *Evidence*: F011

- **Audio queue + None sentinel** — `VoiceChatHandler` uses `audio_queue.put(None)` as end-of-turn marker. Nova Sonic must follow the same pattern.
  *Evidence*: F011

- **Lazy import for heavy SDKs** — `aioboto3` and `aws_sdk_bedrock_runtime` imported inside `get_client()` to avoid penalizing non-Bedrock users.
  *Evidence*: F005, F002

- **`_ensure_client()` per-loop cache** — base class handles per-event-loop SDK client caching.
  *Evidence*: F001

- **`AIMessageFactory` provider methods** — follow the `from_claude()`, `from_openai()`, `from_gemini()` pattern for `from_bedrock()`.
  *Evidence*: F010

- **`CompletionUsage` provider classmethods** — follow `from_claude()`, `from_openai()` pattern for `from_bedrock()`.
  *Evidence*: F010

- **Error classification** — override `_is_capacity_error()` to detect `ThrottlingException`. Use `botocore.Config(retries={"mode": "adaptive"})`.
  *Evidence*: Research document §Manejo de errores

- **Graceful audio sink failures** — catch and log without breaking text stream (established pattern across all voice integrations).
  *Evidence*: F011

- **`aclose()` idempotent and never raises** — consistent across `VoiceAvatarSession`, `RoomAudioPublisher`, `AvatarWebSocket`.
  *Evidence*: F011

### Integration Risks

- **Provider key collision**: If `bedrock-converse` replaces the existing `bedrock` key, users would be silently migrated. *Mitigation*: use a distinct key and deprecate gradually.
  *Evidence*: F002

- **aioboto3 EventStream bugs**: `converse_stream` may not continue after `toolResult` in some cases. *Mitigation*: use non-streaming `converse()` for the tool-use loop; streaming only for final responses (same pattern as AnthropicClient which doesn't handle tools in streaming).
  *Evidence*: Research document §2, F009

- **ReasoningContent signature corruption**: Tool-use loops must re-send `reasoningContent` blocks with `signature` intact. Frameworks that reconstruct assistant turns without the reasoning block trigger `ValidationException`. *Mitigation*: preserve the full `output.message` dict from Converse responses and re-append without modification.
  *Evidence*: Research document §1, F009

- **Nova Sonic SDK stability**: Pre-Alpha SDK with breaking changes between minors. *Mitigation*: pin strictly (`==0.7.0`), gate behind optional extra, mark as experimental.
  *Evidence*: Research document §2

- **Structured output + citations incompatibility**: Bedrock returns 400 if both enabled simultaneously. *Mitigation*: validate at call time and raise clear error.
  *Evidence*: Research document §1

- **VoiceBot hardcoded to GeminiLiveClient**: Adding Nova Sonic requires modifying `_resolve_llm_config()` or creating a subclass. *Mitigation*: provider-dispatch pattern with a registry similar to `SUPPORTED_CLIENTS`.
  *Evidence*: F011

- **Nova Sonic 8-minute limit**: Long conversations require reconnection with history replay. *Mitigation*: implement a `_reconnect()` method that re-sends `sessionStart` + prior turns.
  *Evidence*: Research document §3

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | AbstractClient requires 5 abstract methods (get_client, ask, ask_stream, resume, invoke) | F001, F009 | high | Direct read of base class source, confirmed by AnthropicClient |
| C2 | Existing "bedrock" factory key maps to AnthropicClient with BedrockBackend | F002 | high | Direct read of factory.py and anthropic_backends.py |
| C3 | bedrock_models.py translator is reusable and needs Nova ID extension | F003 | high | Direct read; translator is provider-agnostic |
| C4 | ToolFormat enum lacks BEDROCK; adapter needs `_clean_for_bedrock()` | F004 | high | Direct read of manager.py |
| C5 | aioboto3 is not a dependency; new extra group needed | F005 | high | grep confirmed absence |
| C6 | AWS credential config vars already exist in conf.py | F006 | high | Direct read |
| C7 | Streaming must yield str chunks + AIMessage sentinel | F007, F009 | high | Pattern consistent across all existing clients; confirmed in AnthropicClient |
| C8 | Converse API has feature parity with Messages API for Claude in 2026 | Research doc | medium | Based on research document citing AWS docs; not independently verified |
| C9 | Nova 2 Sonic requires the experimental aws_sdk_bedrock_runtime SDK | Research doc | high | AWS documentation confirms boto3 does not support bidirectional streaming |
| C10 | PII guardrails are text-only; Nova Sonic needs ApplyGuardrail on transcriptions | Research doc | medium | Based on research document citing AWS guardrails docs |
| C11 | The experimental SDK (v0.7.0) is safe for production with strict pinning | Research doc | low | AWS explicitly warns against production use |
| C12 | AnthropicClient tool loop has no max_iterations; new client follows same pattern | F009 | high | Direct read of claude.py; unbounded while True |
| C13 | No `AIMessageFactory.from_bedrock()` or `CompletionUsage.from_bedrock()` exist | F010 | high | Direct read of responses.py and basic.py |
| C14 | GeminiLiveClient is the only bidirectional voice client; stream_voice() is the pattern | F011 | high | Direct read of live.py |
| C15 | VoiceBot hardcodes GeminiLiveClient in _resolve_llm_config() | F011 | high | Direct read of voice.py |
| C16 | VoiceChatHandler expects LiveVoiceResponse shape from streaming clients | F011 | high | Direct read of handler.py |
| C17 | Audio format (16kHz in, 24kHz out) is consistent between Gemini Live and Nova Sonic | F011, Research doc | high | Both confirmed in docs |
| C18 | AnthropicClient structured output is schema-in-system-prompt, not response_format | F009 | high | Direct read; `format_schema_instruction()` appended to system prompt |
| C19 | AnthropicClient prompt caching uses `cache_control: ephemeral` (max 4 blocks); Bedrock uses `cachePoint` | F009, Research doc | high | Direct read + research doc comparison |
| C20 | Extended thinking is NOT first-class in AnthropicClient; only handled defensively | F009 | high | Direct read; no `thinking` param on ask()/ask_stream() |

Distribution: **16** high, **2** medium, **2** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Where should Nova Sonic live?** — *Resolved*: in `ai-parrot-integrations[voice]` alongside existing voice integrations (liveavatar, msteams/voice), consistent with the satellite-package pattern.
  *Resolves claims*: C9

- [x] **Should the new client replace the existing "bedrock" factory entry?** — *Resolved*: No. Use a distinct key (`bedrock-converse`) for the native client. The existing `bedrock` key continues to use `AnthropicClient` + `BedrockBackend` for backward compatibility.
  *Resolves claims*: C2

- [x] **How should tool schemas be mapped?** — *Resolved*: Add `ToolFormat.BEDROCK` and `_clean_for_bedrock()` that wraps existing schemas in the `toolSpec`/`inputSchema.json` envelope. Closest to Anthropic format with a small restructuring.
  *Resolves claims*: C4

- [x] **Should the new client support extended thinking?** — *Resolved*: Yes, as a first-class feature via `additionalModelRequestFields` in the Converse API. This is an improvement over AnthropicClient which only handles it defensively.
  *Resolves claims*: C20

### Unresolved (defer to spec / implementation)

- [ ] **Should guardrail config be per-client or per-call?** — *Owner*: tbd
  *Blocks claims*: C10
  *Plausible answers*: a) per-client (set at init, applied to all calls) · b) per-call (passed as kwargs) · c) both (default at init, override per call)

- [ ] **Which non-Anthropic models should the client support at launch?** — *Owner*: tbd
  *Blocks claims*: C8
  *Plausible answers*: a) Claude-only initially (same as existing) · b) Claude + Nova (text + voice) · c) Claude + Nova + Llama/Mistral (full multi-provider)

- [ ] **Should Nova Sonic be in the same package or a separate one?** — *Owner*: tbd
  *Blocks claims*: C9, C11
  *Plausible answers*: a) `ai-parrot-integrations[voice]` (consistent with liveavatar) · b) new `ai-parrot-nova` package · c) in core `ai-parrot[nova-sonic]` extra

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-302`** — *Rationale*: Localization is high-confidence (16 of 20 claims are high). The architecture is thoroughly understood from deep research into AnthropicClient internals, response models, and voice integration patterns. The spec should decompose into 3 phases:

1. **Phase 1 — BedrockConverseClient** (core): `ask()`, `ask_stream()`, `invoke()`, `resume()` with Converse API, tool support, `AIMessageFactory.from_bedrock()`, `CompletionUsage.from_bedrock()`, `ToolFormat.BEDROCK`, factory registration, dependency extra.
2. **Phase 2 — Advanced features**: Extended thinking (first-class), prompt caching (`cachePoint`), structured output (`outputConfig.textFormat`), guardrails (`guardrailConfig`), `invoke_model` fallback for edge-case models.
3. **Phase 3 — NovaSonicClient** (experimental): Bidirectional voice streaming, `stream_voice()`, `LiveVoiceResponse` compatibility, `VoiceProvider.BEDROCK_NOVA_SONIC`, PII guardrails on transcriptions, VoiceBot provider-awareness.

### Alternatives

- **`/sdd-brainstorm FEAT-302`** — if you want to explore alternative architectures (e.g., extend `AnthropicClient` with a `ConverseBackend` instead of a standalone client, or use `AsyncAnthropicBedrock` + `aioboto3` hybrid).
- **`/sdd-task FEAT-302`** — not recommended; this feature spans 14+ code locations and benefits from a full spec.
- **Manual review** — if you want to validate the research document claims against the live AWS API before specifying.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-302/state.json` |
| Source (raw) | `sdd/state/FEAT-302/source.md` |
| Research plan | (inline — no separate plan file for this run) |
| Findings (digests) | `sdd/state/FEAT-302/findings/F001-*.md` through `F011-*.md` |
| External research | `sdd/proposals/compass_artifact_wf-766f01e9-ac55-5ac0-86a0-78dd7870fc59_text_markdown.md` |

**Budget consumed**:
- Files read: 28 / 40
- Grep calls: 12 / 25
- Git calls: 2 / 10
- Research agents: 4 (1 initial codebase scan + 3 deep dives)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (new feature, no existing bug).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| External research | Compass artifact research (Bedrock async-first design guide, mid-2026) |
| Synthesis prompt | Enriched via 4 parallel research agents (AnthropicClient, response models, voice patterns, initial codebase) |
| Operator | Jesus (jlara@trocglobal.com) |
