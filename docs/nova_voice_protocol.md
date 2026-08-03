# Nova Sonic Voice Protocol Reference

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Scope**: `packages/ai-parrot/src/parrot/clients/nova/audio.py` (`NovaAudio`
mixin, composed into `NovaClient`)
**Status**: Verified against AWS's official samples and against
`aws_sdk_bedrock_runtime==0.7.0` / Python 3.13. **Not yet verified against a
live Bedrock session** — the account used for this feature returns HTTP 403
`AccessDeniedException` for Nova Sonic model access (an IAM/enablement
matter, tracked separately). Every claim below is either cited against a
specific AWS sample line, or explicitly marked unverified.

This is a **reference**, not a tutorial: each claim cites the authoritative
source. See `sdd/specs/nova-sonic-protocol-fidelity.spec.md` for the full
gap analysis and rationale.

**Authoritative samples**: `aws-samples/amazon-nova-samples`, path
`speech-to-speech/amazon-nova-2-sonic/sample-codes/console-python/`:
- `nova_sonic_simple.py` — session lifecycle, role tracking, generation stage
- `nova_sonic_tool_use.py` — tool configuration, tool-result envelope, usage events

---

## 1. Two Layers

`stream_voice()`'s implementation splits into two independent layers:

- **Transport layer** — how bytes reach Bedrock: the bidirectional-stream
  client class, `Config`-based construction, the credentials identity
  resolver, event-chunk wrapping, and `await_output()`/JSON-decode/
  envelope-unwrap on receive. Fixed on commit `89204b9f0`
  (`fix/nova-sonic-bidirectional-sdk`). Isolated behind four thin wrappers:
  `_open_stream()` / `_send_event()` / `_iter_events()` / `_close_stream()`.
- **Protocol layer** — which event frames are sent, and how received frames
  are interpreted. This is what FEAT-408 covers, and what this document
  describes. It operates entirely above the transport seam, on plain dicts —
  which is exactly what makes the tests in `test_nova_*.py` possible without
  any AWS credentials or model access.

`_iter_events()` already JSON-decodes each frame and unwraps Nova's
`{"event": {...}}` envelope one level, so protocol code sees
`{"textOutput": {...}}`, never `{"event": {"textOutput": {...}}}`.

---

## 2. Full Event Frame Sequence

### Opening sequence (sent once per turn, in order)

| # | Frame | Built by | Notes |
|---|-------|----------|-------|
| 1 | `sessionStart` | `stream_voice()` | Inference config (`maxTokens`, `topP`, `temperature`) |
| 2 | `promptStart` | `_build_prompt_start()` | `textOutputConfiguration`, `audioOutputConfiguration` (`audioType: "SPEECH"`), `toolUseOutputConfiguration`, and `toolConfiguration.tools[]` when the client has tools (`_build_tool_configuration()`) |
| 3 | `contentStart` (SYSTEM, TEXT) | `stream_voice()` | Only if `system_prompt` given; `interactive: false`, `textInputConfiguration` |
| 4 | `textInput` | `stream_voice()` | The system prompt text |
| 5 | `contentEnd` (SYSTEM) | `stream_voice()` | Closes the system text block |
| 6 | `contentStart` (AUDIO, USER) | `stream_voice()` | `interactive: true`, `audioInputConfiguration` (`audioType: "SPEECH"`) |

Frames 3–5 are the sample's system-prompt priming
(`nova_sonic_simple.py:78-175`). Frame 6 opens the audio content block that
`_audio_sender()` streams `audioInput` chunks into.

### Steady-state receive loop

| Frame | Handling |
|-------|----------|
| `contentStart` | Updates `_TurnState.role` and `_TurnState.generation_stage` (parsed from `additionalModelFields`, a JSON *string*). Governs the `textOutput` frames that follow — Nova reports the speaker and stage here, not on `textOutput` itself. |
| `textOutput` | Checked for barge-in first (§5), then attributed with `role` and filtered by `generation_stage` (§3), then yielded as `LiveVoiceResponse(text=..., role=...)`. |
| `audioOutput` | Base64-decoded (per `audioOutputConfiguration.encoding: "base64"`) and yielded as `LiveVoiceResponse(audio_data=...)`. Unchanged by FEAT-408. |
| `usageEvent` | Populates `LiveCompletionUsage` (§6). |
| `toolUse` | Stashed into `_TurnState.pending_tool` — **not executed yet** (§4). |
| `contentEnd` (`type == "TOOL"`) | Executes the stashed tool call and sends the three-frame result envelope (§4). |
| `completionEnd` | Terminal `LiveVoiceResponse(is_complete=True, tool_calls=..., usage=...)`. |

### Shutdown sequence (sent from `stream_voice()`'s `finally`, in order)

| # | Frame | Notes |
|---|-------|-------|
| 1 | `promptEnd` | Carries `promptName`. Sent via `_end_session()`. |
| 2 | `sessionEnd` | Empty object `{}`. |
| 3 | (transport close) | `_close_stream()` — pre-existing, unrelated to this feature. |

`_end_session()` runs **before** `_close_stream()` — sending frames after the
transport closes cannot work. It is best-effort: any exception is caught and
logged at `debug`, never propagated, so a shutdown failure can never mask
the turn's own original exception (`nova_sonic_simple.py:210-235`).

---

## 3. Role and Generation-Stage Semantics

Nova reports the speaker (`"USER"` / `"ASSISTANT"` / `"TOOL"`) and the
generation stage on `contentStart`, not on the `textOutput` frames they
govern (`nova_sonic_simple.py:250-269`). `NovaAudio` tracks this in a
module-private `_TurnState` local (never on `self` — `NovaAudio` is a shared
mixin that may serve concurrent sessions):

```python
@dataclass
class _TurnState:
    role: Optional[str] = None
    generation_stage: Optional[str] = None
    pending_tool: Optional[LiveToolCall] = None
    pending_tool_raw_input: Optional[str] = None
```

`generation_stage` comes from `additionalModelFields`, a **JSON string** (not
a dict) that must be `json.loads`'d defensively:

```python
{"contentStart": {
    "role": "ASSISTANT", "type": "TEXT",
    "additionalModelFields": '{"generationStage": "SPECULATIVE"}',
}}
```

**Suppression rule**: assistant `textOutput` is suppressed only when
`generation_stage is not None and generation_stage != "SPECULATIVE"`. A
**missing** stage always emits — a strict `== "SPECULATIVE"` test would
silently drop all assistant text the first time Nova omits
`additionalModelFields`. USER transcription is never suppressed (it carries
no generation stage).

`LiveVoiceResponse.role` (`clients/live.py`) carries this attribution to
callers — an **additive** field, `Optional[str] = None`, so
`GeminiLiveClient` (which never sets it) and existing consumers are
unaffected. `accumulated_text` (the terminal frame's running text) only
ever accumulates assistant text, so the user's transcription never leaks
into it.

---

## 4. Tool Calling — Three-Frame Result Envelope

### Declaring tools (`promptStart`)

`_build_tool_configuration()` converts the client's registered tools
(`self.tool_manager.all_tools()`) into:

```python
{"tools": [{"toolSpec": {
    "name": ..., "description": ...,
    "inputSchema": {"json": <JSON-Schema dict>},
}}, ...]}
```

included in `promptStart` **only when tools exist** — the key is omitted
entirely for tool-less sessions, matching `nova_sonic_simple.py` (spec §8
Q2: unverified against Bedrock whether an empty `tools: []` would also
work, but omission matches the simple sample). A tool whose `get_schema()`
raises is skipped with a `logger.warning`, never fatal
(`nova_sonic_tool_use.py:345-366`).

**Without `toolConfiguration`, Nova never emits `toolUse` at all** — this
was the audit's headline finding: the pre-FEAT-408 `toolUse`/`toolResult`
handling existed but was unreachable dead code.

### Execution timing

Execution happens on `contentEnd` with `type == "TOOL"`, **not** on the
`toolUse` frame itself (`nova_sonic_tool_use.py:644-652`):

```python
{"toolUse": {"toolName": "...", "toolUseId": "...", "content": '{"location": "Miami"}'}}
#   ^ stashed into _TurnState.pending_tool / pending_tool_raw_input — NOT executed
{"contentEnd": {"type": "TOOL"}}
#   ^ NOW: json.loads the stashed content, call self._execute_tool(name, args)
```

`toolUse.content` is a **JSON string**, not a dict — `_parse_tool_arguments()`
parses it (tolerating an already-parsed dict), raising `ValueError` for
anything that does not decode to a JSON object. A malformed payload is
reported as a `LiveToolCall.error` and still gets a well-formed result
envelope; it never crashes the turn. A `contentEnd(TOOL)` with no pending
tool is ignored, not raised on.

### Result envelope — exactly three frames, in order

```python
{"contentStart": {
    "type": "TOOL", "role": "TOOL", "interactive": False,
    "toolResultInputConfiguration": {
        "toolUseId": ...,             # ← toolUseId lives HERE
        "type": "TEXT",
        "textInputConfiguration": {"mediaType": "text/plain"},
    },
}}
{"toolResult": {"promptName": ..., "contentName": ..., "content": ...}}
#                              ^ NOT toolUseId — this inversion was the bug
{"contentEnd": {"promptName": ..., "contentName": ...}}
```

`nova_sonic_tool_use.py:261-285` (contentStart template), `:381-390`
(toolResult builder), `:719-721` (send order). `contentName` (a fresh UUID
per tool call) ties the three frames together and must match across all
three — it is *not* the `toolUseId`.

Execution stays **sequential** in this implementation (not
parallel/background tasks like the AWS sample) — a residual follow-up, not
yet needed by any caller.

---

## 5. Barge-In Detection

Nova signals interruption as an `{"interrupted": true}` payload **inside**
`textOutput.content`, not via any top-level frame key
(`nova_sonic_tool_use.py:632`):

```python
{"textOutput": {"content": '{ "interrupted" : true }'}}
```

Detection parses the content as JSON and checks the `interrupted` key,
falling back to a whitespace-insensitive substring test
(`'"interrupted":true' in "".join(content.split())`) when it does not parse
— the sample's exact spacing (`'{ "interrupted" : true }'`) is incidental,
not a required serialization. The payload itself is never yielded as
assistant text nor accumulated.

On detection: `is_interrupted=True`, `is_complete=True`,
`turn_metadata.was_interrupted = True`, and `accumulated_text` is reset —
the exact shape existing consumers (`VoiceBot`, `VoiceChatHandler`, this
example) already depend on.

**Anti-hallucination note**: neither `event["interruption"]` nor
`event["stopReason"] == "INTERRUPTED"` appears in any AWS Nova Sonic sample.
Both were the pre-FEAT-408 detection signal and almost certainly never
fired in production, since the transport that would have delivered a real
`textOutput` frame was itself broken until `89204b9f0`.

---

## 6. Usage Accounting — ⚠️ Unverified Frame Shape

Nova emits `usageEvent` frames (`nova_sonic_tool_use.py:659-660`), but the
sample only debug-prints the whole frame — **it does not document field
names**. This is the one gap in FEAT-408 whose frame *shape* is unverified
(spec §8 Q1).

Implemented defensively: several plausible key spellings are probed, most
likely first, and an unrecognized shape leaves the counters at zero rather
than raising:

```python
_USAGE_INPUT_KEYS = ("inputTokens", "promptTokens", "input_tokens")
_USAGE_OUTPUT_KEYS = ("outputTokens", "completionTokens", "output_tokens")
_USAGE_TOTAL_KEYS = ("totalTokens", "total_tokens")
```

One level of nesting under `details`/`totals`/`usage` sub-keys is also
flattened and probed. `total_tokens` is derived as
`prompt_tokens + completion_tokens` when no total key matches. Usage frames
are treated as **absolute** (assigned, not accumulated) — chosen as the
safe default since no evidence exists either way; if a real session proves
Nova sends *incremental* deltas instead, this should change to
accumulation.

The raw frame is preserved in `usage.extra["usage_event"]` and logged at
`debug` specifically so **the real schema can be read off the first live
session** and this guess list corrected — closing spec §8 Q1.

`tool_calls_executed` / `tool_execution_time_ms` accounting (populated when
a tool executes, §4) is a separate code path and unaffected by any of the
above.

---

## 7. Two SDK Gotchas That Cost the Most Time

These belong to the **transport layer** (fixed in `89204b9f0`, not part of
this feature), but are recorded here because they are exactly the kind of
mistake this protocol-fidelity audit was built to catch, and the next
person touching `NovaAudio` should not have to rediscover them:

1. **`BedrockAgentRuntimeClient` does not exist.** It belongs to the
   unrelated *bedrock-agent-runtime* service and exists in **no** release of
   `aws_sdk_bedrock_runtime`. The correct class is `BedrockRuntimeClient`
   (0.3.0/0.7.0) or `AsyncBedrockRuntimeClient` (0.8.0, renamed) — resolved
   by name via `_resolve_voice_client_class()` so a future rename fails
   loudly with an actionable message instead of an obscure `ImportError`.
   This exact wrong name is what made `stream_voice()` unable to open a
   stream at all before the transport fix.
2. **`Config.aws_credentials_identity_resolver` must be set explicitly.**
   This Pre-Alpha SDK is smithy-based, not botocore-based, and has **no**
   implicit default credential chain — leaving the resolver `None` causes
   SigV4 to raise `SmithyIdentityError` at the first send, not at
   construction. There is also no bearer-auth scheme (the
   `aws_bearer_token`/`AWS_NOVA_API_KEY` path the text engine uses has no
   voice equivalent) — `_open_stream()` warns and falls through to the
   SDK's default chain when only a bearer token is configured.

---

## 8. What This Document Does Not Cover

- The transport layer itself (SDK wrappers, `Config` construction, chunk
  encoding) — see `sdd/specs/novaclient-amazon-aws.spec.md` and commit
  `89204b9f0`.
- Reconnection across Nova's ~8-minute connection limit — the existing
  `reconnect_required` signal is unchanged; automatic re-establishment
  stays the caller's responsibility.
- `GeminiLiveClient` behaviour — `role` is populated by `NovaAudio` only;
  Gemini already separates transcripts via its own
  `input_audio_transcription`/`output_audio_transcription` config.
- Live verification against a real Bedrock Nova Sonic session — every claim
  above is verified against AWS's samples and offline synthesized frames
  (see `test_nova_*.py`), not against production traffic. Treat the first
  real session as a further test, especially for §6.
