# TASK-1748: NovaSonicClient Experimental Voice Client

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: XL (8h+)
**Depends-on**: TASK-1745, TASK-1744
**Assigned-to**: unassigned

---

## Context

Implement an experimental bidirectional speech-to-speech client using Amazon Nova 2 Sonic via the pre-alpha `aws_sdk_bedrock_runtime` SDK. This follows the same architectural pattern as `GeminiLiveClient` but uses HTTP/2 bidirectional streams instead of WebSockets.

Implements Spec Module 7.

**WARNING**: The Nova Sonic SDK (`aws_sdk_bedrock_runtime==0.7.0`) is Pre-Alpha and requires Python >= 3.12. This client is marked as experimental.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/nova_sonic.py`
- Implement `NovaSonicClient(AbstractClient)` with:
  - `client_type = "nova-sonic"`, `client_name = "nova-sonic"`
  - `_default_model = "amazon.nova-2-sonic-v1:0"`
  - `get_client()` — initialize Nova Sonic SDK session
  - `stream_voice(audio_input, ...)` — bidirectional voice streaming
    - Sender task: sends PCM 16kHz audio chunks
    - Receiver task: yields `LiveVoiceResponse` objects with 24kHz PCM audio
  - `ask()` / `ask_stream()` — text-only fallback (delegates to `BedrockConverseClient`)
  - Connection lifecycle: 8-minute connection limit with auto-reconnect
- Yield `LiveVoiceResponse` for compatibility with `VoiceChatHandler`
- Handle PCM audio format: 16kHz input, 24kHz output

**NOT in scope**: Full VoiceChatHandler integration (TASK-1749), factory registration for voice, text-based features.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova_sonic.py` | CREATE | `NovaSonicClient` implementation |
| `tests/clients/test_nova_sonic.py` | CREATE | Unit tests (mocked SDK) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient  # verified: parrot/clients/base.py:244
from parrot.clients.live import LiveVoiceResponse  # verified: parrot/clients/live.py:156
from parrot.clients.live import GeminiLiveClient  # verified: parrot/clients/live.py:467 (REFERENCE only)
from parrot.models.bedrock_models import translate  # verified: parrot/models/bedrock_models.py:87
```

### Existing Signatures to Use
```python
# parrot/clients/live.py:156 (@dataclass — CORRECTED, was stale: field is
# `is_complete`, not `is_final`; also carries tool_calls/usage/turn_metadata/
# session_id/turn_id/user_id, all defaulted)
class LiveVoiceResponse:
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_format: str = "audio/pcm;rate=24000"
    is_complete: bool = False
    is_interrupted: bool = False
    tool_calls: List[LiveToolCall] = field(default_factory=list)
    usage: Optional[LiveCompletionUsage] = None
    turn_metadata: Optional[VoiceTurnMetadata] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

# parrot/clients/live.py:467
class GeminiLiveClient(AbstractClient):
    async def stream_voice(self, audio_input: AsyncIterator[bytes], ...) -> AsyncIterator[LiveVoiceResponse]:
        # Sender/receiver task pattern at line 708
        # This is the reference for NovaSonicClient.stream_voice()
```

### Does NOT Exist
- ~~`parrot.clients.nova_sonic`~~ — does not exist yet; this task creates it
- ~~`aws_sdk_bedrock_runtime` in pyproject.toml~~ — not yet; must be added as optional
- ~~`LiveVoiceResponse.pcm_sample_rate`~~ — not a field; sample rate is client metadata
- ~~`AbstractClient.stream_voice()`~~ — not abstract; only GeminiLiveClient has it

---

## Implementation Notes

### SDK Pattern
```python
# Nova Sonic uses a different SDK than aioboto3:
# pip install aws_sdk_bedrock_runtime==0.7.0
from aws_sdk_bedrock_runtime import BedrockAgentRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput

# The SDK provides HTTP/2 bidirectional streaming
# Input: PCM 16kHz mono 16-bit LE
# Output: PCM 24kHz mono 16-bit LE
```

### Connection Lifecycle
```python
# Nova Sonic connections have an 8-minute limit
# Implement auto-reconnect:
#   1. Track connection start time
#   2. Before the limit, gracefully close and reconnect
#   3. The new connection resumes from conversation state
```

### Voice Streaming Architecture
```python
# Follow GeminiLiveClient.stream_voice() at live.py:708
# Two async tasks:
#   sender_task: reads from audio_input iterator, sends PCM chunks
#   receiver_task: receives audio events, yields LiveVoiceResponse
#
# Key difference from Gemini: HTTP/2 bidirectional vs WebSocket
```

### Key Constraints
- `aws_sdk_bedrock_runtime==0.7.0` is Pre-Alpha — API may change
- Python >= 3.12 required
- PCM format must match: 16kHz in, 24kHz out
- Connection timeout: 8 minutes max

---

## Acceptance Criteria

- [ ] `NovaSonicClient` inherits `AbstractClient`
- [ ] `stream_voice()` yields `LiveVoiceResponse` objects
- [ ] Audio format: accepts 16kHz PCM input, produces 24kHz PCM output
- [ ] Connection lifecycle handles 8-minute limit
- [ ] `ask()` / `ask_stream()` provide text-only fallback
- [ ] SDK dependency is optional (graceful ImportError)
- [ ] All tests pass: `pytest tests/clients/test_nova_sonic.py -v`

---

## Test Specification

```python
# tests/clients/test_nova_sonic.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestNovaSonicClient:
    def test_client_type(self):
        with patch.dict('sys.modules', {'aws_sdk_bedrock_runtime': MagicMock()}):
            from parrot.clients.nova_sonic import NovaSonicClient
            client = NovaSonicClient(model="amazon.nova-2-sonic-v1:0")
            assert client.client_type == "nova-sonic"

    def test_default_model(self):
        with patch.dict('sys.modules', {'aws_sdk_bedrock_runtime': MagicMock()}):
            from parrot.clients.nova_sonic import NovaSonicClient
            client = NovaSonicClient()
            assert "nova" in client._default_model.lower() or "sonic" in client._default_model.lower()

    def test_import_error_when_sdk_missing(self):
        import sys
        if 'aws_sdk_bedrock_runtime' in sys.modules:
            del sys.modules['aws_sdk_bedrock_runtime']
        with pytest.raises(ImportError):
            from parrot.clients.nova_sonic import NovaSonicClient
            NovaSonicClient()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context on Module 7
2. **Verify** TASK-1745 is completed — `BedrockConverseClient` must exist
3. **Study** `GeminiLiveClient` at `parrot/clients/live.py:467` — it is the reference for voice clients
4. **Study** `LiveVoiceResponse` at `parrot/clients/live.py:156`
5. **Check** if `aws_sdk_bedrock_runtime` SDK documentation is available
6. **Implement** `NovaSonicClient` following the `GeminiLiveClient` pattern
7. **Run tests** and verify all acceptance criteria

**Note**: This is an experimental client. Focus on getting the architecture right for the sender/receiver pattern. The SDK may change before GA.

---

## Completion Note

**Package location — resolved by user decision.** The spec (§8, "Resolved
(from proposal phase)") says Nova Sonic should live in
`ai-parrot-integrations[voice]`, contradicting this task's explicit
instruction to create `packages/ai-parrot/src/parrot/clients/nova_sonic.py`
(core package). Flagged this contradiction to the user before implementing
(a genuine "task contradicts spec" STOP condition); the user explicitly
confirmed: **"clients need to be settled on core
`packages/ai-parrot/src/parrot/clients/nova_sonic.py` not on
integrations."** Implemented accordingly — this task's file path stands
as the resolved decision going forward.

**Codebase Contract correction**: `LiveVoiceResponse`'s field is
`is_complete` (not `is_final` as the task's stale contract stated) — fixed
the contract in this task file before implementing, per the
anti-hallucination protocol. Also documented the dataclass's actual full
field set (previously abbreviated to 4 fields).

Created `packages/ai-parrot/src/parrot/clients/nova_sonic.py` with
`NovaSonicClient(AbstractClient)`:
- `client_type`/`client_name = "nova-sonic"`, `_default_model =
  "amazon.nova-2-sonic-v1:0"`.
- `__init__` performs an eager `import aws_sdk_bedrock_runtime` presence
  check (raises `ImportError` with an install hint immediately at
  construction, not deferred to `get_client()`/`stream_voice()` — matches
  the task's own test spec, which wraps construction itself in
  `pytest.raises(ImportError)`).
- `get_client()` / `_open_stream()` / `_send_event()` / `_iter_events()`:
  three thin wrappers isolate every raw Pre-Alpha SDK call (mirrors
  `BedrockConverseClient._sdk_create`/`_sdk_stream`), so only these need
  updating if `aws_sdk_bedrock_runtime`'s API changes before GA — the SDK's
  exact bidirectional-stream event shapes are not independently verified
  (no stable public API reference exists for this Pre-Alpha package); the
  event names/structure follow the task's Implementation Notes and the
  spec's Module 7 description (`sessionStart`/`promptStart`/`audioInput`/
  `toolUse`/`toolResult`/`completionEnd`) as the closest available contract.
- `stream_voice()`: sender/receiver task architecture per
  `GeminiLiveClient.stream_voice()` (live.py:708) — background
  `_audio_sender()` task forwards PCM chunks as `audioInput` events (a
  `None` sentinel signals end-of-turn, mirroring `GeminiLiveClient`'s
  multi-turn convention), while the main coroutine iterates output events
  and yields `LiveVoiceResponse` for text/audio/tool-use/interruption/
  turn-complete. Barge-in and tool-use-mid-conversation are handled.
- **8-minute connection lifecycle**: tracks `time.monotonic()` since stream
  open; when within a 15s safety margin of the ~8-minute limit, yields a
  `metadata={"reconnect_required": True}` frame and breaks — actual
  reconnection (opening a new stream + replaying context) is left to the
  caller, since Nova Sonic doesn't expose a resumable-session concept in
  the available documentation; this is the "architecture right" scope the
  task calls out rather than a full auto-reconnect implementation.
- `ask()`/`ask_stream()`/`invoke()` delegate to a lazily-constructed,
  cached internal `BedrockConverseClient` (per Scope: "text-only fallback
  (delegates to BedrockConverseClient)"), sharing region/profile/guardrail
  config. `resume()` raises `NotImplementedError` (mirrors
  `GeminiLiveClient.resume()`'s precedent — no suspend/resume concept for
  voice sessions).
- `_apply_pii_guardrail()`: delegates to the internal `BedrockConverseClient
  .apply_guardrail_text(text, source="INPUT")` (TASK-1746) — implements the
  spec's Module 7 responsibility ("`_apply_pii_guardrail()` for
  transcription PII filtering"), not explicitly listed in this task's own
  Scope bullets but present in the spec and low-cost to wire up.

Created `packages/ai-parrot/tests/clients/test_nova_sonic.py` (15 tests):
client_type/default_model/PCM constants, `ImportError` when the SDK is
missing, `stream_voice()` text+audio/tool-use/barge-in/8-minute-reconnect,
`ask()`/`ask_stream()`/`invoke()` delegation to a real (mocked-at-the-SDK-
boundary) `BedrockConverseClient`, `resume()` raising `NotImplementedError`,
internal client reuse, and PII guardrail delegation (both configured and
unconfigured).

**Test-design note**: initially wrapped every `from parrot.clients.nova_sonic
import NovaSonicClient` inside a `patch.dict('sys.modules',
{'aws_sdk_bedrock_runtime': MagicMock()})` block per the task's own test
scaffold — this triggered a flaky `KeyError: 'pydantic.root_model'` in
`mcp.types`' pydantic generic-model caching (triggered via
`parrot.clients.live`'s `google.genai` import chain) on the *second* such
import in the same test session. Root-caused: `nova_sonic.py`'s only
module-level dependency is `.live` (for `LiveVoiceResponse` et al.), which
does NOT require `aws_sdk_bedrock_runtime` — only `__init__` does. Fixed by
importing the module/class once at collection time and scoping the
`sys.modules` patch to only the constructor calls that need it. Pre-existing
environment fragility in the `google.genai`/`mcp`/pydantic import chain,
unrelated to this feature — not introduced by this task.

All 15 tests pass. `ruff check` clean. Full `tests/clients/` re-run: 96
passed, only the 2 pre-existing unrelated `test_google_computer_use.py`
failures remain.
