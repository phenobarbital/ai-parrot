---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Nova Sonic Protocol Fidelity

**Feature ID**: FEAT-408
**Date**: 2026-08-03
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.25.31

---

## 1. Motivation & Business Requirements

### Problem Statement

`NovaAudio.stream_voice()` (`parrot/clients/nova/audio.py`) implements the Nova
Sonic bidirectional event protocol, but it diverges from AWS's official samples
in ten verified ways. The divergences fall into two layers:

- **Transport layer** — how bytes reach Bedrock. Already fixed on branch
  `fix/nova-sonic-bidirectional-sdk` (commit `89204b9f0`): the client class,
  `Config`-based construction, the credentials identity resolver, event-chunk
  wrapping, and `await_output()`/JSON-decode/envelope-unwrap on receive. Before
  that fix no voice turn could open a stream at all.
- **Protocol layer** — which event frames are sent, and how received frames are
  interpreted. **This spec covers only this layer.**

None of the protocol defects were observable before the transport fix, because
the stream never opened. Three of them (role, generation stage, barge-in) mean
that even with Bedrock model access granted, the transcript a caller receives
would be *wrong* rather than merely absent — so this is not cosmetic polish.

Root cause context: the original implementation (FEAT-302 `nova_sonic.py`, ported
verbatim by FEAT-315/TASK-1807) was derived from AWS's own working samples. The
samples are correct; the divergences were introduced in transcription. Every gap
below is stated as a diff against a specific sample line, not against an opinion.

**Reference implementations** (authoritative for this spec):
`aws-samples/amazon-nova-samples`, path
`speech-to-speech/amazon-nova-2-sonic/sample-codes/console-python/`:
- `nova_sonic_simple.py` — session lifecycle, role tracking, generation stage
- `nova_sonic_tool_use.py` — tool configuration, tool-result envelope, usage events

### Goals

- Send the event frames Nova Sonic actually requires, so tool use is reachable
  and audio/text configuration is complete.
- Interpret received frames correctly, so callers can distinguish the user's
  transcription from the assistant's reply, are not served duplicated assistant
  text, and see real token usage.
- Detect barge-in the way Nova actually signals it.
- Shut a session down gracefully instead of dropping the connection.
- Keep every existing consumer of `LiveVoiceResponse` working — all changes to
  that dataclass are **additive**.
- Make every acceptance criterion verifiable **offline**, against synthesized
  event frames, since no Bedrock Nova Sonic access exists in CI or in the
  development environment.

### Non-Goals (explicitly out of scope)

- The transport layer. Fixed in `89204b9f0`; this spec assumes it.
- Obtaining AWS Bedrock Nova Sonic model access. The account currently returns
  HTTP 403 `AccessDeniedException`; that is an IAM/enablement matter, tracked
  separately, and is **not** a precondition for completing this spec.
- Bearer-token (Bedrock API key) auth for voice. The Pre-Alpha SDK is
  smithy-based with only a SigV4 auth scheme and has no bearer scheme, so the
  `aws_bearer_token`/`AWS_NOVA_API_KEY` path used by the text engine has no
  voice equivalent. Already documented and warned about in `_open_stream`.
- `GeminiLiveClient` behaviour. The `role` field added here is populated by
  `NovaAudio` only; Gemini already separates transcripts via its own
  `input_audio_transcription`/`output_audio_transcription` config.
- Reconnection across the 8-minute connection limit. The existing
  `reconnect_required` signal is unchanged; automatic re-establishment stays
  the caller's responsibility.

---

## 2. Architectural Design

### Overview

`stream_voice()` keeps its current shape — an async generator that sends a fixed
opening sequence, spawns `_audio_sender`, then iterates normalized frames from
`_iter_events()` and yields `LiveVoiceResponse` objects. The changes are:

1. **Richer opening sequence.** `promptStart` gains `toolUseOutputConfiguration`
   and, when the client has tools registered, `toolConfiguration.tools[]` built
   from the existing tool manager. `contentStart`/audio configs gain the
   `audioType`, `interactive`, and `textInputConfiguration` fields the samples
   send.
2. **A small receive-side state machine.** Nova's `contentStart` frames carry
   `role` and `additionalModelFields.generationStage`, and those apply to the
   `textOutput` frames that follow. A `_TurnState` helper tracks the current
   role and generation stage so `textOutput` can be attributed and filtered.
3. **A correct tool-result sequence.** Tool execution moves from the `toolUse`
   frame to the `contentEnd type=="TOOL"` frame, and the result is sent as the
   three-frame `contentStart`/`toolResult`/`contentEnd` envelope.
4. **Real usage accounting.** `usageEvent` frames populate
   `LiveCompletionUsage`.
5. **Graceful shutdown.** `promptEnd` + `sessionEnd` before closing the input
   stream, in a new `_end_session()` wrapper invoked from `stream_voice()`'s
   `finally`.

`LiveVoiceResponse` gains one optional field, `role`, defaulting to `None`.
Existing consumers that ignore it are unaffected.

### Component Diagram

```
stream_voice()
  │
  ├─ _build_prompt_start()      NEW  ─→ toolConfiguration (from ToolManager)
  │                                     toolUseOutputConfiguration
  ├─ _send_event() × opening sequence   (audioType / interactive /
  │                                      textInputConfiguration added)
  ├─ _audio_sender()                    (unchanged)
  │
  ├─ async for frame in _iter_events()  (unchanged — transport layer)
  │     │
  │     └─→ _TurnState            NEW  ─→ role, generation_stage
  │            │                            from contentStart
  │            ├─ textOutput  ─→ attribute role, drop non-SPECULATIVE
  │            │                 assistant text, detect barge-in payload
  │            ├─ audioOutput ─→ (unchanged)
  │            ├─ toolUse     ─→ stash pending call (do NOT execute)
  │            ├─ contentEnd type==TOOL ─→ execute + _send_tool_result()  NEW
  │            ├─ usageEvent  ─→ LiveCompletionUsage                      NEW
  │            └─ completionEnd ─→ terminal LiveVoiceResponse
  │
  └─ finally: _end_session()      NEW  ─→ promptEnd, sessionEnd
             _close_stream()            (existing)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LiveVoiceResponse` (`clients/live.py:156`) | extends (additive) | new optional `role: Optional[str] = None`; `to_websocket_message()` gains a `"role"` key |
| `NovaAudio` (`clients/nova/audio.py:125`) | modifies | all protocol changes land here |
| `BedrockConverseBase` | uses | unchanged; already supplies `_region` + credentials to the transport layer |
| `ToolManager` / `self.tool_manager` | uses | source of `toolConfiguration.tools[]` — same tool set the text path exposes |
| `self._execute_tool(name, input)` | uses | unchanged signature; called later in the frame sequence and with parsed args |
| `VoiceBot` (`bots/voice.py`) | consumes | must keep working unchanged; may optionally surface `role` later |
| `VoiceChatHandler` (`ai-parrot-integrations/voice/handler.py`) | consumes | must keep working unchanged; `role` flows through `to_websocket_message()` |
| `examples/clients/nova/audio.py` | consumes | its documented "role is indistinguishable" limitation is removed by this spec |

### Data Models

```python
# parrot/clients/live.py — ADDITIVE change to the existing dataclass
@dataclass
class LiveVoiceResponse:
    # ... all existing fields unchanged ...
    role: Optional[str] = None
    """Speaker this frame is attributed to: "USER", "ASSISTANT", "TOOL",
    or None when the provider does not report one (e.g. GeminiLiveClient).
    Populated by NovaAudio from Nova Sonic's contentStart.role."""


# parrot/clients/nova/audio.py — NEW, module-private
@dataclass
class _TurnState:
    """Receive-side state carried across frames within one Nova Sonic turn.

    Nova reports the speaker and the generation stage on ``contentStart``,
    not on the ``textOutput`` frames they govern, so this must persist
    between frames.
    """
    role: Optional[str] = None
    generation_stage: Optional[str] = None
    pending_tool: Optional[LiveToolCall] = None
    pending_tool_raw_input: Optional[str] = None
```

### New Public Interfaces

No new public classes. One new public field (`LiveVoiceResponse.role`) and one
new key in `LiveVoiceResponse.to_websocket_message()` output (`"role"`).

New module-private helpers on `NovaAudio`:

```python
def _build_prompt_start(self, prompt_name: str, voice_id: str) -> Dict[str, Any]: ...
def _build_tool_configuration(self) -> Optional[Dict[str, Any]]: ...
async def _send_tool_result(self, stream, prompt_name, tool_use_id, result) -> None: ...
async def _end_session(self, stream, prompt_name) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: `LiveVoiceResponse.role` (additive dataclass field)
- **Path**: `packages/ai-parrot/src/parrot/clients/live.py`
- **Responsibility**: Carry speaker attribution to callers. Add
  `role: Optional[str] = None` and emit `"role"` from
  `to_websocket_message()` (line 189).
- **Depends on**: nothing. Must land first — Modules 3 and 4 populate it.

### Module 2: Opening-sequence fidelity
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gap 10 and the non-tool half of Gap 1. Add
  `audioType: "SPEECH"` to `audioOutputConfiguration` (line 415) and
  `audioInputConfiguration` (line 440); add `interactive: true` to the AUDIO
  `contentStart` (line 437); add `interactive: false` and
  `textInputConfiguration: {"mediaType": "text/plain"}` to the SYSTEM text
  `contentStart` (line 425); add `toolUseOutputConfiguration` to `promptStart`
  (line 412). Extract `_build_prompt_start()`.
- **Depends on**: nothing.

### Module 3: Receive-side turn state — role + generation stage
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gaps 5 and 6. Add `_TurnState`; handle the `contentStart`
  frame to record `role` and
  `json.loads(additionalModelFields).generationStage`; attribute every
  `textOutput` frame (line 488) with `role`; suppress assistant `textOutput`
  when `generation_stage != "SPECULATIVE"`. `accumulated_text` must accumulate
  assistant text only, so the terminal frame's `text` is not polluted with the
  user's transcription.
- **Depends on**: Module 1.

### Module 4: Barge-in detection
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gap 8. Replace the `"interruption" in event or
  event.get("stopReason") == "INTERRUPTED"` check (line 473) with detection of
  the literal `{ "interrupted" : true }` payload inside `textOutput` content, as
  the sample does. Keep yielding `is_interrupted=True` with
  `turn_metadata.was_interrupted` set, so existing consumers are unaffected.
- **Depends on**: Module 3 (barge-in is observed on a `textOutput` frame).

### Module 5: Tool configuration (makes the tool path reachable)
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gap 1. `_build_tool_configuration()` converts the
  client's registered tools into
  `toolConfiguration.tools[].toolSpec{name, description, inputSchema.json}`
  and includes it in `promptStart` when tools exist. Returns `None` when the
  client has no tools, so the frame is unchanged for tool-less sessions.
- **Depends on**: Module 2.

### Module 6: Tool-result envelope + execution timing + argument parsing
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gaps 2, 3, 4. On `toolUse` (line 522) stash the pending
  call instead of executing. On `contentEnd` with `type == "TOOL"`, parse the
  stashed `content` with `json.loads` into the kwargs dict `_execute_tool`
  expects, execute, then send the three-frame envelope via
  `_send_tool_result()`: `contentStart{type:"TOOL", role:"TOOL",
  interactive:false, toolResultInputConfiguration:{toolUseId, type:"TEXT",
  textInputConfiguration}}` → `toolResult{promptName, contentName, content}` →
  `contentEnd`. A non-JSON or non-object `content` must be reported as a tool
  error, never crash the turn.
- **Depends on**: Module 5.

### Module 7: Usage accounting from `usageEvent`
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gap 7. Populate `LiveCompletionUsage` prompt/completion/
  total token fields from `usageEvent` frames, preserving the existing
  `tool_calls_executed`/`tool_execution_time_ms` accounting (line 397).
- **Depends on**: nothing.

### Module 8: Graceful shutdown
- **Path**: `packages/ai-parrot/src/parrot/clients/nova/audio.py`
- **Responsibility**: Gap 9. `_end_session()` sends `promptEnd` then
  `sessionEnd`, called from `stream_voice()`'s `finally` before
  `_close_stream()`. Must be best-effort: a stream already torn down by the
  service must not raise out of `finally` and mask the real error.
- **Depends on**: nothing.

### Module 9: Documentation + example follow-up
- **Path**: `docs/` (Nova voice section), `examples/clients/nova/audio.py`
- **Responsibility**: Remove the "role is indistinguishable" known-limitation
  note from the example now that Module 3 fixes it; render user vs assistant
  bubbles using the new `role`; document the protocol contract.
- **Depends on**: Modules 3, 4, 6, 7.

---

## 4. Test Specification

All tests are **offline**. Nova Sonic frames are synthesized as dicts and fed
through the wrapper seam established by `test_nova_audio_sdk.py`, so no AWS
credentials or model access are required.

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_live_voice_response_role_defaults_to_none` | 1 | Existing construction without `role` still works; default is `None` |
| `test_to_websocket_message_includes_role` | 1 | Serialized payload carries `"role"` |
| `test_prompt_start_declares_audio_type_speech` | 2 | Both audio configs carry `audioType: "SPEECH"` |
| `test_content_start_interactive_flags` | 2 | AUDIO `contentStart` is `interactive: true`; SYSTEM text is `false` with `textInputConfiguration` |
| `test_prompt_start_declares_tool_use_output_configuration` | 2 | `toolUseOutputConfiguration` present |
| `test_text_output_attributed_to_content_start_role` | 3 | USER `contentStart` → `textOutput` yields `role="USER"`; ASSISTANT → `role="ASSISTANT"` |
| `test_assistant_text_suppressed_when_not_speculative` | 3 | `generationStage != "SPECULATIVE"` assistant text is not yielded |
| `test_assistant_text_emitted_when_speculative` | 3 | The SPECULATIVE frame IS yielded |
| `test_accumulated_text_excludes_user_transcription` | 3 | Terminal frame `text` contains assistant text only |
| `test_barge_in_detected_from_interrupted_payload` | 4 | `{ "interrupted" : true }` in `textOutput` content → `is_interrupted=True`, `was_interrupted` set |
| `test_legacy_interruption_key_no_longer_required` | 4 | Regression: detection does not depend on an `"interruption"` key |
| `test_tool_configuration_built_from_registered_tools` | 5 | `toolSpec` name/description/`inputSchema.json` derived from the tool's schema |
| `test_tool_configuration_absent_when_no_tools` | 5 | `promptStart` has no `toolConfiguration` key |
| `test_tool_not_executed_on_tool_use_frame` | 6 | `_execute_tool` not called until `contentEnd type=="TOOL"` |
| `test_tool_executed_on_tool_content_end` | 6 | Execution happens on that frame |
| `test_tool_use_content_json_string_parsed_to_kwargs` | 6 | `content` as a JSON string becomes the kwargs dict |
| `test_tool_result_sends_three_frame_envelope` | 6 | Exactly `contentStart`(TOOL) → `toolResult` → `contentEnd`, in order |
| `test_tool_result_carries_content_name_not_tool_use_id` | 6 | Regression: `toolResult` has `contentName`; `toolUseId` is in the `contentStart` |
| `test_malformed_tool_content_reported_as_tool_error` | 6 | Non-JSON `content` → tool error, turn survives |
| `test_usage_event_populates_token_counts` | 7 | Prompt/completion/total tokens non-zero |
| `test_usage_event_preserves_tool_counters` | 7 | Tool counters not clobbered |
| `test_end_session_sends_prompt_end_then_session_end` | 8 | Order asserted |
| `test_end_session_errors_do_not_mask_turn_error` | 8 | A raising `_end_session` does not replace the original exception |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_turn_frame_sequence_matches_aws_sample` | Drive a complete synthesized turn (contentStart USER → textOutput → contentStart ASSISTANT SPECULATIVE → textOutput → audioOutput → usageEvent → completionEnd) and assert the yielded `LiveVoiceResponse` sequence, roles, text, and usage |
| `test_full_tool_turn_frame_sequence` | Complete turn including `toolUse` → `contentEnd(TOOL)` → tool executed → three-frame result → `completionEnd` |
| `test_existing_consumers_unaffected` | `VoiceBot` and `VoiceChatHandler` paths still work against the new response shape |
| `test_example_server_relays_role` | `examples/clients/nova/audio.py` relays `role` to the browser |

### Test Data / Fixtures

```python
# Synthesized Nova Sonic frames — the SAME shape _iter_events() yields
# (envelope already unwrapped), so these exercise stream_voice() without
# any SDK or network.
@pytest.fixture
def user_transcription_frames():
    return [
        {"contentStart": {"role": "USER", "type": "TEXT"}},
        {"textOutput": {"content": "what is the weather"}},
    ]

@pytest.fixture
def assistant_speculative_frames():
    return [
        {"contentStart": {
            "role": "ASSISTANT", "type": "TEXT",
            "additionalModelFields": '{"generationStage": "SPECULATIVE"}',
        }},
        {"textOutput": {"content": "It is sunny."}},
    ]

@pytest.fixture
def barge_in_frames():
    return [
        {"contentStart": {"role": "ASSISTANT", "type": "TEXT"}},
        {"textOutput": {"content": '{ "interrupted" : true }'}},
    ]
```

---

## 5. Acceptance Criteria

- [ ] `promptStart` includes `toolUseOutputConfiguration`, and includes
      `toolConfiguration.tools[]` whenever the client has registered tools —
      verified by asserting the captured frame, not by a live call.
- [ ] A tool round-trip is reachable end to end against synthesized frames:
      `toolUse` → `contentEnd(type="TOOL")` → `_execute_tool` invoked with a
      dict parsed from the JSON-string `content` → three-frame
      `contentStart`/`toolResult`/`contentEnd` envelope sent in that order,
      with `contentName` (not `toolUseId`) in the `toolResult`.
- [ ] `LiveVoiceResponse.role` is populated as `"USER"`/`"ASSISTANT"`/`"TOOL"`
      from `contentStart.role`, and `to_websocket_message()` emits it.
- [ ] Assistant `textOutput` is yielded only when
      `generationStage == "SPECULATIVE"`; a full synthesized turn yields the
      assistant's reply exactly once (no duplication).
- [ ] The terminal frame's `text` contains assistant text only — the user's
      transcription never appears in it.
- [ ] Barge-in is detected from the `{ "interrupted" : true }` payload in
      `textOutput` content, and no longer relies on an `"interruption"` key or
      `stopReason == "INTERRUPTED"`.
- [ ] `usageEvent` frames populate `LiveCompletionUsage` prompt/completion/total
      tokens, while `tool_calls_executed`/`tool_execution_time_ms` keep working.
- [ ] `promptEnd` then `sessionEnd` are sent before the stream is closed, and a
      failure in that path never masks the turn's original exception.
- [ ] Both audio configs carry `audioType: "SPEECH"`; the AUDIO `contentStart`
      carries `interactive: true`; the SYSTEM text `contentStart` carries
      `interactive: false` and `textInputConfiguration`.
- [ ] **No breaking changes**: every change to `LiveVoiceResponse` is additive.
      The full existing suite passes unchanged —
      `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock"` and
      `pytest packages/ai-parrot-integrations/tests/voice/`.
- [ ] All new tests pass on **both** interpreters: Python 3.13 with
      `aws_sdk_bedrock_runtime==0.7.0` installed, and Python 3.11 without it
      (where SDK-dependent modules skip cleanly, never fail).
- [ ] `examples/clients/nova/audio.py` renders user vs assistant separately and
      its "role is indistinguishable" known-limitation note is removed.
- [ ] No acceptance criterion requires AWS Bedrock access to verify.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

All line numbers below refer to branch `fix/nova-sonic-bidirectional-sdk` at
commit `89204b9f0`, which this spec builds on. If this feature is based on `dev`
before that branch merges, `nova/audio.py` line numbers will differ and the
transport layer will still be broken — **verify the base first**.

### Verified Imports

```python
from parrot.clients.nova import NovaClient                    # verified: clients/nova/__init__.py:10
from parrot.clients.nova import audio as audio_mod            # verified: module exists
from parrot.clients.live import (                             # verified: clients/live.py
    LiveCompletionUsage,                                      #   line 60
    LiveToolCall,                                             #   line 128
    LiveVoiceResponse,                                        #   line 156
    VoiceTurnMetadata,                                        #   line 140
)
from parrot.models.bedrock_models import translate            # verified: used at audio.py:389
# Pre-Alpha voice SDK — import ONLY inside methods, never at module scope:
from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient          # verified 0.7.0
from aws_sdk_bedrock_runtime.config import Config                        # verified 0.7.0
from aws_sdk_bedrock_runtime.models import (                             # verified 0.7.0
    BidirectionalInputPayloadPart,
    InvokeModelWithBidirectionalStreamInputChunk,
    InvokeModelWithBidirectionalStreamOperationInput,
)
from smithy_aws_core.identity.chain import create_default_chain          # verified
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                              # line 156
    text: str = ""                                    # line 164
    audio_data: Optional[bytes] = None                # line 165
    audio_format: str = "audio/pcm;rate=24000"        # line 166
    is_complete: bool = False                         # line 169
    is_interrupted: bool = False                      # line 170
    tool_calls: List[LiveToolCall] = field(default_factory=list)   # line 173
    usage: Optional[LiveCompletionUsage] = None       # line 176
    turn_metadata: Optional[VoiceTurnMetadata] = None # line 179
    session_id: Optional[str] = None                  # line 182
    turn_id: Optional[str] = None                     # line 183
    user_id: Optional[str] = None                     # line 184
    metadata: Dict[str, Any] = field(default_factory=dict)         # line 187
    def to_websocket_message(self) -> Dict[str, Any]: ...          # line 189

# packages/ai-parrot/src/parrot/clients/nova/audio.py  @ 89204b9f0
_VOICE_CLIENT_CLASS_NAMES: tuple[str, ...]            # line 87
def _resolve_voice_client_class() -> type: ...        # line 93
class NovaAudio:                                      # line 125
    _CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15    # line 145
    _OUTPUT_READY_TIMEOUT_SECONDS: float = 30.0       # line 151
    INPUT_SAMPLE_RATE_HZ: int = 16000                 # line 154
    OUTPUT_SAMPLE_RATE_HZ: int = 24000                # line 155
    async def _open_stream(self, model_id: str) -> Any: ...              # line 162
    async def _send_event(self, stream, event: Dict[str, Any]) -> None:  # line 234
    async def _iter_events(self, stream) -> AsyncIterator[Dict[str, Any]]:  # line 259
    async def _close_stream(self, stream: Any) -> None: ...              # line 313
    async def _apply_pii_guardrail(self, text: str) -> str: ...          # line 329
    async def stream_voice(self, audio_iterator, system_prompt=None,
                           session_id=None, user_id=None, **kwargs
                           ) -> AsyncIterator[LiveVoiceResponse]: ...    # line 343
    async def _audio_sender(self, stream, audio_iterator,
                            prompt_name, content_name) -> None: ...      # line 599
```

### Gap Sites (exact lines to modify)

| Gap | Site | File:line |
|---|---|---|
| 1, 10 | `promptStart` frame | `nova/audio.py:412` |
| 10 | `audioOutputConfiguration` | `nova/audio.py:415` |
| 10 | SYSTEM text `contentStart` | `nova/audio.py:425` |
| 10 | AUDIO `contentStart` | `nova/audio.py:437` |
| 10 | `audioInputConfiguration` | `nova/audio.py:440` |
| 8 | barge-in check | `nova/audio.py:473` |
| 5, 6 | `textOutput` handling | `nova/audio.py:488` |
| 2, 3, 4 | `toolUse` handling | `nova/audio.py:522` |
| 3 | `_execute_tool` call | `nova/audio.py:531` |
| 7 | usage init | `nova/audio.py:397` |
| 5 | `accumulated_text` | `nova/audio.py:398`, `461`, `476`, `485`, `491` |

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_TurnState` | `stream_voice()` receive loop | local state | `nova/audio.py:453` |
| `_build_prompt_start()` | `_send_event()` | frame dict | `nova/audio.py:412` |
| `_build_tool_configuration()` | `self.tool_manager` | tool schemas | `clients/live.py:236` shows the `get_schema()` pattern |
| `_send_tool_result()` | `_send_event()` | three frames | `nova/audio.py:234` |
| `_end_session()` | `stream_voice()` `finally` | frames + close | `nova/audio.py:582` |
| `role` | `LiveVoiceResponse` | dataclass field | `clients/live.py:156` |

### Consumers That Must Not Break (verified to reference `stream_voice`/`LiveVoiceResponse`)

- `packages/ai-parrot/src/parrot/bots/voice.py`
- `packages/ai-parrot/src/parrot/clients/factory.py`
- `packages/ai-parrot/src/parrot/clients/nova/client.py`
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py`
- `packages/ai-parrot-advisors/src/parrot/advisors/mixin.py`
- tests: `ai-parrot-integrations/tests/voice/{test_nova_provider,test_voicechat_avatar_integration,test_voice_handler_avatar}.py`,
  `ai-parrot-server/tests/handlers/{test_voice_ws_stt_only_integration,test_agent_voice_stt_only}.py`

### Does NOT Exist (Anti-Hallucination)

- ~~`aws_sdk_bedrock_runtime.BedrockAgentRuntimeClient`~~ — belongs to the
  unrelated *bedrock-agent-runtime* service; exists in **no** release of this
  package. This exact name is what broke the voice path. 0.3.0/0.7.0 export
  `BedrockRuntimeClient`; 0.8.0 renamed it `AsyncBedrockRuntimeClient`.
- ~~`Config(region=...)` as the client constructor arg~~ — the client takes
  `config=Config(...)`; `Config` itself takes `region=`.
- ~~an implicit default credential chain~~ — `Config.aws_credentials_identity_resolver`
  defaults to `None` and SigV4 then raises `SmithyIdentityError`. It must be set
  explicitly.
- ~~`stream.output_stream` before `await_output()`~~ — it is `None` until
  `await stream.await_output()` has been awaited.
- ~~`LiveVoiceResponse.role`~~ — does not exist yet; **Module 1 creates it**.
- ~~`event["stopReason"] == "INTERRUPTED"`~~ / ~~`event["interruption"]`~~ —
  neither appears in any AWS Nova Sonic sample; do not preserve them as the
  barge-in signal.
- ~~a bearer-token auth scheme in the voice SDK~~ — SigV4 only.
- ~~`parrot.clients.nova_sonic`~~ — deleted in FEAT-315/TASK-1811.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep the SDK isolated behind the four existing thin wrappers
  (`_open_stream`/`_send_event`/`_iter_events`/`_close_stream`). Protocol work
  belongs **above** that seam, operating on plain dicts, which is exactly what
  makes the offline tests possible.
- `_iter_events()` already normalizes frames (JSON-decoded, `{"event": …}`
  envelope unwrapped). Handlers therefore see `{"textOutput": {...}}`, not
  `{"event": {"textOutput": {...}}}`. Do not re-unwrap.
- Mirror `GoogleGeneration`/`GeminiLiveClient` conventions for anything shared,
  since `VoiceBot` switches providers at runtime.
- `NovaAudio` is a plain mixin and defines **no** `__init__` (MRO constraint,
  `novaclient-amazon-aws.spec.md` §7). Per-turn state lives in local variables
  or `_TurnState`, never on `self`.
- Read host attributes defensively via `getattr` — a mixin cannot assume its
  host ran a particular resolution.
- Google-style docstrings, strict type hints, `self.logger` (never `print`).

### Known Risks / Gotchas

- **Base-branch ordering.** This spec assumes `89204b9f0`. Starting it from
  `dev` before that branch merges means the transport is still broken and every
  line number in §6 is wrong. Merge the transport fix first.
- **`generationStage` filtering could suppress everything.** If Nova ever omits
  `additionalModelFields`, a strict `== "SPECULATIVE"` test would drop all
  assistant text. Treat a *missing* stage as emit-and-attribute; only an
  explicitly non-SPECULATIVE stage suppresses. Cover both with tests.
- **`additionalModelFields` is a JSON string, not a dict** — the sample calls
  `json.loads` on it. Guard against malformed JSON.
- **Barge-in via string matching is brittle.** Matching `{ "interrupted" : true }`
  is what the sample does, but it is a payload-format dependency. Parse the
  content as JSON and check the `interrupted` key when it parses, falling back
  to a whitespace-insensitive substring test. Do not hard-code the sample's
  exact spacing.
- **Tool-schema conversion is unverified against Nova.** `toolSpec.inputSchema.json`
  takes a JSON-Schema object; the samples pass hand-written schemas. Converting
  `AbstractTool.get_schema()` output may need the same key-stripping the
  `LiveToolAdapter` does for Google (`clients/live.py:236`). Tools cannot be
  confirmed working without model access — mark that residual risk in the task.
- **`usageEvent` field names are not in the simple sample.** `nova_sonic_tool_use.py`
  only debug-prints the whole frame. Field names must be read off a real frame
  or the Nova docs; until then, populate defensively and treat unknown shapes as
  zero rather than raising. This is the one gap whose *shape* is unverified.
- **Shared checkout.** `HEAD` moved mid-session during the investigation that
  produced this spec. Re-verify §6 line numbers before editing.
- **Offline-only verification is a real limitation.** Passing every criterion
  here proves conformance to AWS's *samples*, not to the live service. The first
  run with real model access should be treated as a further test.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aws_sdk_bedrock_runtime` | `==0.7.0` | Pre-Alpha bidirectional voice SDK; Python >= 3.12 only. Tests must skip cleanly without it |
| `smithy_aws_core` | (transitive) | `create_default_chain` credential resolver |
| `aioboto3` | `>=15.1.0` | Text path floor set by `a62803899`; unchanged here |

---

## 8. Open Questions

- [ ] `usageEvent` frame field names — must be confirmed against a real frame or
      AWS docs before Module 7 can assert exact keys. Implement defensively
      until then. — *Owner: Jesus Lara*
- [ ] Does Nova require `toolConfiguration` to be *absent* (rather than an empty
      `tools: []`) for tool-less sessions? Spec assumes absent, matching the
      simple sample. — *Owner: Jesus Lara*
- [ ] Should `role` also be surfaced on `VoiceBot`'s public response and in
      `VoiceChatHandler`'s WebSocket protocol as a documented field, or stay an
      opt-in passthrough? Spec keeps it a passthrough. — *Owner: Jesus Lara*
- [ ] Whether to convert `AbstractTool.get_schema()` via the existing
      `LiveToolAdapter._clean_schema_for_google()` logic or a Nova-specific
      cleaner. — *Owner: Jesus Lara*

---

## Worktree Strategy

**Isolation unit**: `per-spec`. All modules touch one file
(`nova/audio.py`) except Module 1 (`live.py`) and Module 9 (docs/example), so
parallel worktrees would conflict constantly. Run tasks sequentially in a single
worktree.

**Cross-feature dependency**: branch `fix/nova-sonic-bidirectional-sdk`
(commit `89204b9f0`, the transport fix) **must be merged to `dev` first**. This
spec's line numbers and its entire premise depend on it.

```bash
git worktree add -b feat-408-nova-sonic-protocol-fidelity \
  .claude/worktrees/feat-408-nova-sonic-protocol-fidelity HEAD
```

**Suggested task order**: 1 → 2 → 5 → 6 (tool chain) and 3 → 4 (transcript
chain) may interleave; 7 and 8 are independent; 9 last.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-03 | Jesus Lara | Initial draft — protocol layer split out from the transport fix in `89204b9f0`; ten gaps verified against AWS's official Nova Sonic samples |
