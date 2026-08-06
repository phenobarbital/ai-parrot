---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Voice Agent Framework

**Feature ID**: FEAT-416
**Date**: 2026-08-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.25.32

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's voice stack has reached a working state for bidirectional
streaming (GeminiLiveClient + NovaAudio, protocol fidelity fixed in
FEAT-408), but seven structural gaps prevent voice from being a
first-class Agent capability:

1. **No session abstraction** — The `examples/clients/nova/audio.py`
   `NovaVoiceSession` class (~220 LOC, lines 116-338) implements turn
   lifecycle, audio queuing, and WebSocket relay, but lives in an example
   file. Every new deployment must copy or rewrite it. The integrations
   `VoiceChatHandler` (lines 226+, `parrot.voice.handler`) duplicates this
   logic separately.

2. **No `VoiceCapable` protocol** — `stream_voice()` is defined
   independently on `GeminiLiveClient` (line 729, `live.py`) and `NovaAudio`
   mixin (line 613, `nova/audio.py`). There is no shared Protocol, ABC, or
   type-check target. `VoiceBot._create_llm_client()` returns
   `AbstractClient` but then calls `.stream_voice()` on it without any
   type safety — a provider that lacks voice silently fails at runtime.

3. **Hardcoded inference parameters** — `NovaAudio.stream_voice()` sends
   `maxTokens: 1024, topP: 0.9, temperature: 0.7` at line 681 regardless
   of the `VoiceConfig` values (`max_tokens=4096`, `temperature=0.7`).
   Users cannot tune inference knobs for voice turns.

4. **No automatic reconnection** — Nova Sonic enforces an 8-minute
   connection limit (`_CONNECTION_LIMIT_SECONDS = 465s`). The client emits
   a `reconnect_required` metadata flag but nobody acts on it. Users must
   manually restart their session; the `VoiceChatHandler` does not reconnect.

5. **Sequential-only tool execution** — Both `GeminiLiveClient` (via
   `LiveToolAdapter.execute_tool()`, line 373) and `NovaAudio` (via
   `self._execute_tool()`, line 869) execute tool calls one at a time.
   Nova 2 Sonic supports parallel tool calling (multiple `toolUse` events
   in one turn), but all tool results must be sent back before the model
   resumes. Sequential execution adds unnecessary latency for independent
   tools.

6. **Duplicate `VoiceConfig`** — Two dataclasses with the same name exist:
   `parrot.models.voice.VoiceConfig` (core, 11 fields, `provider` is a
   plain string) and `parrot.voice.models.VoiceConfig` (integrations, 17
   fields, `provider` is a `VoiceProvider` enum, adds timeouts and VAD
   mode). Users importing one get different behavior from the other.

7. **VoiceBot not exported** — `VoiceBot` (line 80, `parrot/bots/voice.py`)
   is absent from `parrot.bots.__init__.__all__`. Users must know the
   private module path. `stt_only` mode is supported by `GeminiLiveClient`
   but not wired through `VoiceBot.ask_stream()`.

### Goals

- **G1**: Promote the `NovaVoiceSession` example into a provider-agnostic
  `VoiceSession` in the framework, reusable by `VoiceChatHandler` and any
  custom WebSocket handler.
- **G2**: Define a `VoiceCapable` `typing.Protocol` so that `VoiceBot` and
  type-checkers can verify that a client actually implements
  `stream_voice()`.
- **G3**: Thread `VoiceConfig` inference parameters (`temperature`,
  `max_tokens`, `top_p`) through `stream_voice()` down to the provider's
  session-start event.
- **G4**: Implement automatic reconnection in `VoiceSession` so the 8-min
  Nova Sonic limit (and any future provider limit) is transparent.
- **G5**: Add `asyncio.TaskGroup`-based parallel tool execution for voice
  turns, gated by a `parallel_tool_execution: bool` config flag.
- **G6**: Unify the two `VoiceConfig` classes into a single source of truth
  in `parrot.models.voice`, with `VoiceProvider` enum promoted to core.
- **G7**: Export `VoiceBot` from `parrot.bots` and wire `stt_only` through
  its `ask_stream()` signature.

### Non-Goals (explicitly out of scope)

- OpenAI Realtime API integration — the `VoiceProvider.OPENAI_REALTIME`
  variant is defined but no client exists; building one is a separate spec.
- Whisper + TTS pipeline — `VoiceProvider.WHISPER_TTS` is also a future spec.
- Multi-turn conversation memory for voice — already handled by
  `VoiceBot.ask_stream()` (lines 512-559); this spec does not change it.
- Avatar / lip-sync session management (`avatar_session` field on
  `WebSocketConnection`) — untouched.
- WebRTC or SIP transport — voice transport remains WebSocket-based.

---

## 2. Architectural Design

### Overview

The solution adds three new constructs and refactors two existing ones:

1. **`VoiceCapable` Protocol** (`parrot/clients/protocols.py`) — a
   `typing.Protocol` class declaring the `stream_voice()` signature.
   `GeminiLiveClient` and `NovaAudio` already satisfy it structurally;
   the Protocol makes it explicit and type-checkable.

2. **`VoiceSession`** (`parrot/voice/session.py`) — a provider-agnostic
   turn lifecycle manager promoted from the example's `NovaVoiceSession`.
   Owns the audio queue, turn task, relay logic, and automatic reconnection
   loop. Parameterized by a `VoiceCapable` client and a transport callback
   (async callable for sending JSON frames — typically a WebSocket
   `.send_json()`).

3. **Unified `VoiceConfig`** (`parrot/models/voice.py`) — merges the 11
   core fields and the 17 integrations fields into one dataclass with
   `VoiceProvider` enum (promoted from integrations). Adds `top_p: float`,
   `parallel_tool_execution: bool`, and `reconnect_on_limit: bool`.

4. **Parallel tool execution** — inside `NovaAudio.stream_voice()` and
   `GeminiLiveClient.stream_voice()`, when multiple `toolUse` events arrive
   in one turn, execute them concurrently with `asyncio.TaskGroup` and send
   all results before resuming the model.

5. **Reconnection loop** — `VoiceSession` monitors the
   `reconnect_required` metadata flag and, when `reconnect_on_limit=True`,
   transparently tears down and re-opens `stream_voice()` with the same
   `system_prompt` and `session_id`, resuming the audio queue.

### Component Diagram

```
                          ┌─────────────────────────┐
  Browser / Client        │     VoiceChatHandler     │  (integrations)
  ─────────────────       │  uses VoiceSession       │
  WebSocket frames ◄─────►│         ↓                │
                          │   VoiceSession           │  (core, NEW)
                          │   ├── audio queue        │
                          │   ├── turn task          │
                          │   ├── relay callback     │
                          │   └── reconnect loop     │
                          │         ↓                │
                          │   VoiceCapable client    │  (Protocol, NEW)
                          │   ┌─────┴──────┐        │
                          │   │            │        │
                          │ Gemini     NovaAudio    │  (existing)
                          │ LiveClient   mixin      │
                          └─────────────────────────┘

  VoiceConfig (unified)  ─── feeds ──→ VoiceBot, VoiceSession,
                                        stream_voice() inference params
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` | unmodified | VoiceCapable is a separate Protocol, not a new ABC method |
| `GeminiLiveClient` | implements VoiceCapable | Already satisfies structurally; add `stt_only` passthrough |
| `NovaAudio` | implements VoiceCapable | Thread VoiceConfig inference params to sessionStart |
| `NovaClient` | unmodified | Inherits from NovaAudio; gains voice config via mixin |
| `VoiceBot` | refactored | Uses unified VoiceConfig; exports from `parrot.bots`; passes `stt_only` |
| `VoiceChatHandler` | refactored | Delegates turn lifecycle to VoiceSession; removes duplicated logic |
| `ToolManager` | unmodified | Parallel execution is at the client level, not in ToolManager |

### Data Models

```python
# parrot/clients/protocols.py (NEW)
from typing import Protocol, AsyncIterator, Optional

class VoiceCapable(Protocol):
    """Protocol for clients that support bidirectional voice streaming."""

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...


# parrot/models/voice.py (UNIFIED)
@dataclass
class VoiceConfig:
    # Provider
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE

    # Audio formats
    input_format: AudioFormat = AudioFormat.PCM_16K
    output_format: AudioFormat = AudioFormat.PCM_24K
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000

    # Model & voice
    model: Optional[str] = None
    voice_name: str = "Puck"
    language: str = "en-US"

    # Inference
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9

    # VAD
    enable_vad: bool = True
    vad_mode: str = "server_vad"
    enable_interruption: bool = True

    # Transcription
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True

    # Session
    session_timeout_seconds: int = 1800
    silence_timeout_seconds: int = 30
    reconnect_on_limit: bool = True
    max_reconnects: int = 3

    # Tools
    parallel_tool_execution: bool = False
```

### New Public Interfaces

```python
# parrot/voice/session.py (NEW)
class VoiceSession:
    """Provider-agnostic voice turn lifecycle manager.

    One session serves many sequential turns over one transport connection.
    """

    def __init__(
        self,
        client: VoiceCapable,
        send_fn: Callable[[dict], Awaitable[None]],
        system_prompt: str,
        voice_config: Optional[VoiceConfig] = None,
        session_id: Optional[str] = None,
    ) -> None: ...

    async def start_turn(self) -> None: ...
    async def push_audio(self, pcm: bytes) -> None: ...
    async def end_turn(self) -> None: ...
    async def close(self) -> None: ...

    # Internal:
    # _run_turn(), _relay(), _audio_iterator(),
    # _reconnect() — transparent reconnection loop
```

---

## 3. Module Breakdown

### Module 1: VoiceCapable Protocol

- **Path**: `parrot/clients/protocols.py` (new file; or extend existing if
  present)
- **Responsibility**: Define the `VoiceCapable` typing.Protocol with the
  `stream_voice()` signature.
- **Depends on**: `parrot.clients.live.LiveVoiceResponse` (for return type
  annotation)
- **Scope**: ~20 lines. Import `LiveVoiceResponse`, declare Protocol.

### Module 2: VoiceConfig Unification

- **Path**: `parrot/models/voice.py` (modify)
- **Responsibility**: Merge both VoiceConfig classes into one. Promote
  `VoiceProvider` enum from integrations to core. Add `top_p`,
  `parallel_tool_execution`, `reconnect_on_limit` fields.
- **Depends on**: None (leaf module)
- **Migration**: `parrot.voice.models.VoiceConfig` in the integrations
  package becomes a re-export / deprecation shim that imports from
  `parrot.models.voice`.

### Module 3: Inference Parameter Threading

- **Path**: `parrot/clients/nova/audio.py` (modify)
- **Responsibility**: Replace hardcoded `maxTokens: 1024, topP: 0.9,
  temperature: 0.7` at line 681 with values from `VoiceConfig` passed via
  `**kwargs` to `stream_voice()`.
- **Depends on**: Module 2 (unified VoiceConfig)

### Module 4: Parallel Tool Execution

- **Path**: `parrot/clients/nova/audio.py` (modify), `parrot/clients/live.py`
  (modify)
- **Responsibility**: When multiple `toolUse` events arrive before the next
  model response, collect them and execute concurrently with
  `asyncio.TaskGroup`. Gate on `parallel_tool_execution` kwarg. Send all
  tool results before allowing the model to resume.
- **Depends on**: Module 2 (config flag)

### Module 5: VoiceSession

- **Path**: `parrot/voice/session.py` (new file in core package)
- **Responsibility**: Promote `NovaVoiceSession` from
  `examples/clients/nova/audio.py:116-338` into a provider-agnostic
  `VoiceSession`. Replace `NovaClient`-specific attributes with
  `VoiceCapable` protocol. Replace `ws.send_json()` with an injected
  `send_fn` callback.
- **Depends on**: Module 1 (VoiceCapable), Module 2 (VoiceConfig)

### Module 6: Automatic Reconnection

- **Path**: `parrot/voice/session.py` (extend Module 5)
- **Responsibility**: In `_run_turn()`, detect `reconnect_required`
  metadata from `LiveVoiceResponse` and, when `reconnect_on_limit=True`,
  transparently re-open `stream_voice()` and re-send `system_prompt`.
  Emit a `reconnect` frame to the transport so the UI can show status.
- **Depends on**: Module 5 (VoiceSession)

### Module 7: VoiceBot Refinements

- **Path**: `parrot/bots/voice.py` (modify), `parrot/bots/__init__.py`
  (modify)
- **Responsibility**:
  - Use unified `VoiceConfig` with `VoiceProvider` enum.
  - Add `stt_only: bool` parameter to `ask_stream()` and pass it through
    to the client's `stream_voice()`.
  - Export `VoiceBot` from `parrot.bots.__init__`.
  - Type-annotate the client as `VoiceCapable` in `_create_llm_client()`.
- **Depends on**: Module 1, Module 2

### Module 8: VoiceChatHandler Refactor

- **Path**: `parrot/voice/handler.py` (in ai-parrot-integrations)
- **Responsibility**: Replace the inlined turn lifecycle in
  `_run_voice_session()` (lines 1320+) with a `VoiceSession` instance.
  Replace the integrations `VoiceConfig` import with the unified core one.
  Move `VoiceProvider` import to `parrot.models.voice`.
- **Depends on**: Module 5, Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_voice_capable_protocol_satisfied_gemini` | 1 | Verify `GeminiLiveClient` satisfies `VoiceCapable` via `isinstance()` check |
| `test_voice_capable_protocol_satisfied_nova` | 1 | Verify `NovaClient` satisfies `VoiceCapable` via `isinstance()` check |
| `test_voice_capable_protocol_rejected` | 1 | Verify a plain `AbstractClient` subclass without `stream_voice()` does NOT satisfy `VoiceCapable` |
| `test_voice_config_unified_fields` | 2 | Verify all 22+ fields exist with correct defaults |
| `test_voice_config_provider_enum` | 2 | Verify `provider` accepts `VoiceProvider` enum values |
| `test_voice_config_backward_compat` | 2 | Verify `parrot.voice.models.VoiceConfig` re-exports the unified class |
| `test_nova_inference_params_from_config` | 3 | Verify `sessionStart` event uses VoiceConfig values, not hardcoded `1024/0.9/0.7` |
| `test_parallel_tool_execution_nova` | 4 | Verify two concurrent `toolUse` events execute via `TaskGroup`, not sequentially |
| `test_sequential_tool_execution_default` | 4 | Verify `parallel_tool_execution=False` keeps sequential behavior |
| `test_voice_session_turn_lifecycle` | 5 | Verify `start_turn → push_audio → end_turn` produces correct relay frames |
| `test_voice_session_cancel_turn` | 5 | Verify cancelling a running turn cleans up correctly |
| `test_voice_session_silence_injection` | 5 | Verify `end_turn()` injects paced silence frames for VAD |
| `test_reconnect_on_limit` | 6 | Verify `reconnect_required=True` triggers a new `stream_voice()` call |
| `test_reconnect_disabled` | 6 | Verify `reconnect_on_limit=False` does not reconnect |
| `test_reconnect_max_retries_exhausted` | 6 | Verify `max_reconnects=3` exhausted → error frame emitted + session closes |
| `test_voicebot_exports` | 7 | Verify `from parrot.bots import VoiceBot` works |
| `test_voicebot_stt_only` | 7 | Verify `ask_stream(stt_only=True)` passes through to client |
| `test_voicebot_voice_capable_typecheck` | 7 | Verify `_create_llm_client()` returns a `VoiceCapable` instance |

### Integration Tests

| Test | Description |
|---|---|
| `test_voice_session_with_mock_client` | Full turn: mock `VoiceCapable` client → `VoiceSession` → verify relay frames |
| `test_reconnect_loop_integration` | Mock client yields `reconnect_required` → verify session re-opens and continues |
| `test_parallel_tools_integration` | Two tools with mocked 100ms latency → verify wall-clock < 150ms (not 200ms) |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_voice_client():
    """A minimal VoiceCapable implementation for testing."""
    class MockVoiceClient:
        async def stream_voice(
            self, audio_iterator, system_prompt=None,
            session_id=None, user_id=None, **kwargs
        ):
            async for chunk in audio_iterator:
                if chunk is None:
                    break
            yield LiveVoiceResponse(text="Hello", is_complete=True)
    return MockVoiceClient()

@pytest.fixture
def mock_send_fn():
    """Collects sent frames for assertion."""
    frames = []
    async def send(payload):
        frames.append(payload)
    send.frames = frames
    return send

@pytest.fixture
def voice_config():
    return VoiceConfig(
        provider=VoiceProvider.NOVA,
        temperature=0.5,
        max_tokens=2048,
        top_p=0.95,
        parallel_tool_execution=True,
        reconnect_on_limit=True,
    )
```

---

## 5. Acceptance Criteria

- [ ] `VoiceCapable` Protocol exists; `isinstance(GeminiLiveClient(...), VoiceCapable)` and `isinstance(NovaClient(...), VoiceCapable)` pass at runtime (using `runtime_checkable`)
- [ ] `VoiceConfig` is a single class in `parrot.models.voice` with all fields from both former classes; `parrot.voice.models.VoiceConfig` re-exports it
- [ ] `VoiceProvider` enum is in `parrot.models.voice`; integrations re-exports it
- [ ] Nova Sonic `sessionStart` uses `VoiceConfig.temperature`, `.max_tokens`, `.top_p` — NOT hardcoded values
- [ ] `parallel_tool_execution=True` causes concurrent tool execution in Nova and Gemini voice turns (measured: 2 × 100ms tools complete in < 150ms wall-clock)
- [ ] `VoiceSession` is importable from `parrot.voice.session` and handles start_turn / push_audio / end_turn / close lifecycle
- [ ] `VoiceSession` silence injection uses 20ms-paced frames (matching working `sonic_e2e_demo.py` pattern)
- [ ] `reconnect_on_limit=True` + `reconnect_required` metadata triggers transparent re-open of `stream_voice()`
- [ ] `max_reconnects=3` exhausted → session emits error frame and closes (no infinite loop)
- [ ] `VoiceBot` is importable from `parrot.bots` (`from parrot.bots import VoiceBot`)
- [ ] `VoiceBot.ask_stream(stt_only=True)` passes `stt_only=True` to the underlying client's `stream_voice()`
- [ ] `VoiceChatHandler._run_voice_session()` delegates to `VoiceSession` (no duplicated turn lifecycle)
- [ ] All unit tests pass: `pytest tests/ -k voice -v`
- [ ] No breaking changes to existing `GeminiLiveClient.stream_voice()` or `NovaAudio.stream_voice()` public signatures
- [ ] No breaking changes to `VoiceChatHandler.handle_websocket()` WebSocket frame protocol

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# AbstractClient — parrot/clients/base.py:253
from parrot.clients.base import AbstractClient  # verified

# LiveVoiceResponse + supporting dataclasses — parrot/clients/live.py
from parrot.clients.live import (
    LiveVoiceResponse,       # line 156
    LiveToolCall,            # line 117
    LiveCompletionUsage,     # line 60
    VoiceTurnMetadata,       # line 138
)

# GeminiLiveClient — parrot/clients/live.py:488
from parrot.clients.live import GeminiLiveClient

# NovaClient — parrot/clients/nova/client.py:30
from parrot.clients.nova import NovaClient
# NovaAudio mixin — parrot/clients/nova/audio.py:245
from parrot.clients.nova.audio import NovaAudio

# VoiceBot — parrot/bots/voice.py:80
from parrot.bots.voice import VoiceBot

# VoiceConfig (core) — parrot/models/voice.py:19
from parrot.models.voice import VoiceConfig, AudioFormat

# VoiceProvider + VoiceConfig (integrations) — parrot/voice/models.py
from parrot.voice.models import VoiceProvider  # line 24

# VoiceChatHandler — parrot/voice/handler.py:226
from parrot.voice.handler import VoiceChatHandler

# ToolManager — parrot/tools/manager.py:233
from parrot.tools.manager import ToolManager

# AbstractTool — parrot/tools/abstract.py
from parrot.tools.abstract import AbstractTool
```

### Existing Class Signatures

```python
# parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                 # line 253
    def __init__(self, conversation_memory=None, preset=None,
                 tools=None, use_tools=False, debug=True,
                 tool_manager=None, **kwargs):                # line 289
    async def _execute_tool(                                  # line 1415
        self, tool_name: str, parameters: Dict[str, Any],
        tool_context: Optional[Dict[str, Any]] = None,
    ) -> Any: ...
    # stream_voice() does NOT exist on AbstractClient

# parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                                      # line 156
    text: str = ""                                            # line 164
    audio_data: Optional[bytes] = None                        # line 165
    audio_format: str = "audio/pcm;rate=24000"                # line 166
    is_complete: bool = False                                 # line 169
    is_interrupted: bool = False                              # line 170
    tool_calls: List[LiveToolCall] = field(...)               # line 173
    usage: Optional[LiveCompletionUsage] = None               # line 176
    turn_metadata: Optional[VoiceTurnMetadata] = None         # line 179
    session_id: Optional[str] = None                          # line 182
    turn_id: Optional[str] = None                             # line 183
    user_id: Optional[str] = None                             # line 184
    role: Optional[str] = None                                # line 187
    metadata: Dict[str, Any] = field(...)                     # line 192

@dataclass
class LiveToolCall:                                           # line 117
    id: str                                                   # line 119
    name: str                                                 # line 120
    arguments: Dict[str, Any]                                 # line 121
    result: Optional[Any] = None                              # line 122
    error: Optional[str] = None                               # line 123
    execution_time_ms: float = 0.0                            # line 124

class GeminiLiveClient(AbstractClient):                       # line 488
    client_type: str = 'google_live'                          # line 531
    async def stream_voice(                                   # line 729
        self, audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stt_only: bool = False,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...

# parrot/clients/nova/audio.py
@dataclass
class _TurnState:                                             # line 127
    role: Optional[str] = None
    generation_stage: Optional[str] = None
    pending_tool: Optional[LiveToolCall] = None
    pending_tool_raw_input: Optional[str] = None

class NovaAudio:                                              # line 245
    _CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15           # line 265
    INPUT_SAMPLE_RATE_HZ: int = 16000                        # line 274
    OUTPUT_SAMPLE_RATE_HZ: int = 24000                       # line 275
    async def stream_voice(                                   # line 613
        self, audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...
    def _build_tool_configuration(self) -> Optional[Dict]: ...  # line 486
    async def _send_tool_result(self, stream, prompt_name,
        tool_use_id, result) -> None: ...                     # line 563

# parrot/clients/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):  # line 30
    client_type: str = "nova"                                 # line 62
    voice_id: str = "matthew"  # constructor kwarg            # line 75

# parrot/bots/voice.py
class VoiceBot(A2AEnabledMixin, BaseBot):                     # line 80
    def __init__(self, name="Voice Assistant",
        system_prompt=None, llm=None, tools=None,
        voice_config=None, **kwargs):                         # line 106
    def _resolve_llm_config(self, llm=None, model=None,
        preset=None, model_config=None, **kwargs):            # line 151
    def _create_llm_client(self, config,
        conversation_memory=None) -> AbstractClient:          # line 214
    async def ask_stream(self,
        audio_input: Union[bytes, AsyncIterator[bytes]],
        session_id=None, user_id=None,
        **kwargs) -> AsyncIterator[LiveVoiceResponse]:        # line 400

# parrot/models/voice.py
@dataclass
class VoiceConfig:                                            # line 19
    model: str = GoogleVoiceModel.DEFAULT                     # line 23
    provider: str = "google_live"                             # line 38
    voice_name: str = "Puck"                                  # line 41
    language: str = "en-US"                                   # line 42
    input_format: AudioFormat = AudioFormat.PCM_16K           # line 45
    output_format: AudioFormat = AudioFormat.PCM_24K          # line 46
    temperature: float = 0.7                                  # line 49
    max_tokens: int = 4096                                    # line 50
    enable_vad: bool = True                                   # line 53
    enable_input_transcription: bool = True                   # line 56
    enable_output_transcription: bool = True                  # line 57

# parrot/voice/models.py (integrations — DUPLICATE VoiceConfig)
class VoiceProvider(Enum):                                    # line 24
    GOOGLE_LIVE = "google_live"
    OPENAI_REALTIME = "openai_realtime"
    WHISPER_TTS = "whisper_tts"
    NOVA = "nova"

@dataclass
class VoiceConfig:                                            # line 156
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE        # line 163
    # ... 17 fields total (see §1 for details)

# parrot/voice/handler.py (integrations)
class VoiceChatHandler:                                       # line 226
    def __init__(self, bot_factory=None, default_config=None,
        *, require_auth=False, ...):                          # line 267
    async def _run_voice_session(                             # line 1320
        self, connection: WebSocketConnection) -> None: ...
@dataclass
class WebSocketConnection:                                    # line 154
    ws: web.WebSocketResponse
    audio_queue: asyncio.Queue
    voice_task: Optional[asyncio.Task]
    shutdown_event: asyncio.Event
    # ... ~20 fields total

# parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):                       # line 233
    async def execute_tool(self, tool_name, parameters,
        permission_context=None) -> Any:                      # line 1431
    # No parallel execution support (no TaskGroup/gather usage)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VoiceCapable` | `GeminiLiveClient.stream_voice()` | Protocol structural match | `live.py:729` |
| `VoiceCapable` | `NovaAudio.stream_voice()` | Protocol structural match | `nova/audio.py:613` |
| `VoiceSession` | `VoiceCapable.stream_voice()` | Calls in `_run_turn()` | (new code) |
| `VoiceSession` | `LiveVoiceResponse` | Consumes in `_relay()` | `live.py:156` |
| Unified `VoiceConfig` | `NovaAudio.stream_voice()` | kwargs → `sessionStart` | `nova/audio.py:681` |
| Unified `VoiceConfig` | `VoiceBot.__init__()` | Constructor param | `voice.py:106` |
| `VoiceBot` export | `parrot.bots.__init__` | `__all__` addition | `bots/__init__.py:11` |
| `VoiceChatHandler` | `VoiceSession` | Replaces inlined turn logic | `handler.py:1320` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.protocols`~~ — no `protocols.py` exists yet in `parrot/clients/`; must be created
- ~~`AbstractClient.stream_voice()`~~ — NOT an abstract method; NOT defined on AbstractClient at all
- ~~`VoiceCapable`~~ — does not exist anywhere in the codebase; must be created
- ~~`VoiceSession`~~ — does not exist; `NovaVoiceSession` is example-only at `examples/clients/nova/audio.py:116`
- ~~`parrot.voice.session`~~ — no `session.py` in core voice package; must be created
- ~~`ToolManager.execute_tools_parallel()`~~ — no parallel method exists
- ~~`VoiceConfig.top_p`~~ — does not exist on either VoiceConfig class
- ~~`VoiceConfig.parallel_tool_execution`~~ — does not exist
- ~~`VoiceConfig.reconnect_on_limit`~~ — does not exist
- ~~`VoiceConfig.max_reconnects`~~ — does not exist
- ~~`VoiceBot` in `parrot.bots.__all__`~~ — NOT exported; requires import from `parrot.bots.voice`
- ~~`VoiceBot.ask_stream(stt_only=...)`~~ — `stt_only` parameter does not exist on VoiceBot

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Protocol pattern**: Use `typing.Protocol` with `@runtime_checkable` so
  that `isinstance(client, VoiceCapable)` works without explicit
  registration. This matches the existing `AnthropicBackendProtocol`
  pattern in `parrot/clients/anthropic_backends.py:39`.

- **Silence injection**: The working `sonic_e2e_demo.py` (line 85) and
  `NovaVoiceSession.end_turn()` (line 196) both inject ~1.5s of silence
  with 1024-sample frames at 20ms pacing. This is critical: dumping all
  frames at once causes VAD to miss end-of-speech. Preserve this pattern
  exactly in `VoiceSession.end_turn()`.

- **Transport-agnostic callback**: `NovaVoiceSession` uses
  `self.ws.send_json(payload)` directly. `VoiceSession` should accept a
  `send_fn: Callable[[dict], Awaitable[None]]` so it works with any
  transport (aiohttp WS, FastAPI WS, raw TCP, test mock).

- **Reconnection**: On `reconnect_required=True`, the session should:
  1. Complete relaying the current turn's remaining frames.
  2. Emit a `{"type": "reconnect", "session_id": ...}` frame to the client.
  3. Close the old `stream_voice()` async generator.
  4. Open a new one with the same `system_prompt` and `session_id`.
  5. Resume accepting audio from the queue.

- **Parallel tool execution**: Collect all `toolUse` contentEnd events
  between the start of tool dispatch and the next non-tool event. Execute
  the batch with `async with asyncio.TaskGroup() as tg:` and send all
  results back. Gate on `parallel_tool_execution` kwarg passed through from
  VoiceConfig.

- **VoiceConfig migration**: The integrations `VoiceConfig` re-export
  should use a deprecation warning:
  ```python
  # parrot/voice/models.py (integrations)
  import warnings
  from parrot.models.voice import VoiceConfig as _VoiceConfig

  def __getattr__(name):
      if name == "VoiceConfig":
          warnings.warn(
              "Import VoiceConfig from parrot.models.voice instead",
              DeprecationWarning, stacklevel=2,
          )
          return _VoiceConfig
      raise AttributeError(name)
  ```

### Known Risks / Gotchas

- **AWS SDK Python 3.12+ requirement**: `aws_sdk_bedrock_runtime==0.7.0`
  requires Python ≥ 3.12. The `NovaAudio` mixin already imports it
  conditionally. Parallel tool execution must not break on providers that
  don't support it (i.e., when `toolUse` events arrive one at a time).

- **8-minute reconnection race**: If the reconnection happens mid-tool-
  execution, tool results from the old stream are lost. The reconnection
  should wait for any pending tool execution to complete before tearing
  down the old stream.

- **Backward compatibility**: The unified `VoiceConfig` must accept both
  `provider="google_live"` (string, current core) and
  `provider=VoiceProvider.GOOGLE_LIVE` (enum, current integrations).
  Use a `__post_init__` coercion.

- **Nova Sonic `stt_only`**: Unlike GeminiLiveClient which supports
  `stt_only` natively (empty `response_modalities`), Nova Sonic does not
  document a speech-to-text-only mode. The `stt_only` passthrough for Nova
  should raise `NotImplementedError` with a clear message until/unless AWS
  adds support.

- **Gemini tool stacking**: GeminiLiveClient uses `LiveToolAdapter` (line
  373) which wraps the Google SDK's tool calling. Parallel execution there
  requires collecting `function_call` parts from a single `model_turn` and
  dispatching them concurrently — verify that the Google SDK sends multiple
  `function_call` parts in one turn.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aws_sdk_bedrock_runtime` | `==0.7.0` | Pre-Alpha SDK for Nova Sonic HTTP/2 duplex (existing) |
| `google-genai` | `>=1.0` | Gemini Live API (existing) |
| No new dependencies | — | All additions use stdlib (`asyncio.TaskGroup`, `typing.Protocol`) |

---

## 8. Open Questions

- [x] Should `VoiceCapable` also declare `close()` or `disconnect()` for
  session teardown? — *Resolved*: No. Keep `VoiceCapable` minimal —
  declares only `stream_voice()`. Session-level cleanup stays in
  `VoiceSession.close()`, which cancels the turn task and triggers the
  client's own `finally` blocks.
- [x] Should `VoiceSession` support multi-turn conversation history
  internally (carry context across reconnections) or leave that to
  `VoiceBot`? — *Resolved*: Leave it to `VoiceBot`. `VoiceSession` is
  stateless w.r.t. conversation history — it passes `system_prompt` and
  `session_id` on reconnect; `VoiceBot` owns memory persistence.
- [ ] For Gemini Live, does the Google SDK actually send multiple
  `function_call` parts in a single `model_turn` (parallel tool calls)?
  — *Owner: implementer* — verify during Module 4 implementation. If
  Gemini sends single calls, the `TaskGroup` path is a no-op (still
  correct). Non-blocking for spec approval.
- [x] Should the reconnection loop have a max-retries limit to prevent
  infinite reconnection on persistent server errors? — *Resolved*: Yes.
  Add `max_reconnects: int = 3` to `VoiceConfig` (configurable). After
  exhausting retries, emit `{"type": "error", "message": "max
  reconnections reached"}` and close the session.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all 8 modules run sequentially in one
  worktree.
- **Rationale**: Modules have tight dependencies (2→3→4→5→6→7→8) and all
  touch the voice subsystem. Parallel worktrees would create merge conflicts.
- **Cross-feature dependencies**: FEAT-408 (Nova Sonic Protocol Fidelity)
  should be merged first — this spec builds on the corrected protocol layer.

```bash
# After /sdd-task, create worktree from dev:
git worktree add -b feat-416-voice-agent-framework \
  .claude/worktrees/feat-416-voice-agent-framework HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-06 | Jesus Lara | Initial draft from gap analysis |
| 0.2 | 2026-08-06 | Jesus Lara | Resolve open questions Q1/Q2/Q4; add max_reconnects; mark approved |
