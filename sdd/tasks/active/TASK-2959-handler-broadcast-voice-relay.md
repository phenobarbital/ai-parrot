# TASK-2959: Broadcast-owned VoiceSession and response relay in VoiceChatHandler

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2958
**Parallel**: false
**Parallelism notes**: Edits the shared hot spot `voice/handler.py` (FEAT-536 owns its baseline). TASK-2960 edits the same file afterwards — strictly sequential.

---

## Context

Spec §2 End-to-end step 7: "Refactor the broadcast branch so the producer session and response task are owned by `BroadcastSession`, not the first participant's connection. Existing `_HandlerVoiceSession._relay` behavior remains the non-broadcast path; shared response translation may be extracted with regression coverage. The broadcast path preserves text, tool and lifecycle events but suppresses duplicate local PCM playback and the old connection-local avatar tee." Module 4 first half. Also §2 moderation: per-turn speaker identity in audit metadata; tool context from the **current speaker**, fail closed; stable conversation key per broadcast.

## Scope

- `voice/handler.py`:
  - Extract frame construction already in `_HandlerVoiceSession.build_frames()` (`:395`) into a module-level `build_voice_frames(resp, turn_no, *, stt_only, dedup_state) -> list[dict]` used by both the legacy `_HandlerVoiceSession` (unchanged behaviour; `test_handler_refactor.py` must stay green) and the new broadcast relay.
  - New `class BroadcastVoiceSession(VoiceSession)` (in a new module `broadcast/voice_relay.py` to keep `handler.py` growth bounded; handler imports it lazily): constructed once per broadcast by the owner with `client=_AskStreamVoiceClient(bot, user_id=None)`, `session_id=descriptor.voice_session_id` (stable conversation key), `send_fn=fan_out` (a callable that the control-socket layer of TASK-2960 will attach: sends text/tool/lifecycle frames to **all** participant sockets, PCM to none). Overrides `_relay(resp, turn_no)`: builds frames with `build_voice_frames`, **strips** `audio_data` from the wire frames (no local PCM playback), forwards `resp.audio_data` exactly once as a `BroadcastAudioFrame(owner_epoch, speaker_lease_id, floor_epoch, turn_id, output_epoch, sequence, pcm)` to `BroadcastSession.push_audio`, calls `BroadcastSession.interrupt()` on `resp.is_interrupted`, `finish_turn()` on `resp.is_complete`. No connection-local `avatar_session` tee.
  - Speaker context: `BroadcastVoiceSession.begin_speaker_turn(lease_id, principal, floor_epoch)` sets the per-turn `user_id` passed to `ask_stream()` to the **current speaker's** `principal.user_id` (so `VoiceBot` tool-permission/context resolution runs as the speaker — verify how `VoiceBot.ask_stream(user_id=…)` is consumed by the merged FEAT-536 Nova adapter before relying on it; if a speaker context cannot be established, refuse the turn with `BroadcastError(floor_not_granted)` — fail closed). Record `{"speaker_lease_id", "speaker_user_id", "floor_epoch"}` into `resp.metadata["broadcast"]` before frames are built so transcripts/audit carry the speaker.
  - Suppress late tool/display events from a previous floor epoch (compare `resp.turn_id`/turn generation captured at `begin_speaker_turn`).
  - `VoiceChatHandler.__init__` gains keyword `broadcast_service: Optional[Any] = None` (typed loosely to avoid a hard import; TASK-2961 defines `BroadcastService`) and an explicit `nova_bot_factory: Optional[Callable[[], VoiceBot]] = None` used only for broadcasts.
- Tests `tests/voice/test_voice_broadcast_relay.py`: exercise `BroadcastVoiceSession._relay` with real `LiveVoiceResponse` objects (text, tool_calls, audio, is_interrupted, is_complete) against a fake `BroadcastSession`; regression that `_HandlerVoiceSession._relay` still sends `audio` frames and still tees to `connection.avatar_session` (non-broadcast path).

**NOT in scope**: the `/ws/voice/broadcast/...` route, floor validation at ingress, heartbeats (TASK-2960); worker relay (TASK-2961).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | Extract `build_voice_frames`; `broadcast_service`/`nova_bot_factory` kwargs |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/voice_relay.py` | CREATE | `BroadcastVoiceSession` |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_relay.py` | CREATE | Relay + regression tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.voice import VoiceBot, create_voice_bot            # handler.py:47 ; VoiceBot class bots/voice.py:89
from parrot.models.voice import VoiceConfig, LiveVoiceResponse       # handler.py:48 ; LiveVoiceResponse models/voice.py:361
from parrot.voice.session import VoiceSession                        # handler.py:52 ; class session.py:36
from parrot.voice.handler import VoiceChatHandler, WebSocketConnection, BotConfig, _AskStreamVoiceClient, _HandlerVoiceSession  # :584/:184/:131/:307/:364
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
class _AskStreamVoiceClient:                                           # :307
    def __init__(self, bot: "VoiceBot", user_id: Optional[str] = None) # :323
    async def stream_voice(self, audio_iterator, system_prompt=None, session_id=None, user_id=None, options=None, **kwargs)  # :333 → bot.ask_stream(audio_input=..., session_id=..., user_id=user_id or self._user_id, stt_only=...)
class _HandlerVoiceSession(VoiceSession):                              # :364
    def __init__(self, *args, handler, connection, **kwargs)           # :368 ; _tool_dedup_turn_no, _sent_tool_call_ids (:383-384)
    async def _send(self, payload: dict)                               # :387 → handler._send_message(connection.ws, payload)
    def build_frames(self, resp, turn_no: int) -> list                 # :395 (response_chunk/response_complete/transcription/tool_call/display_data; STT gating; thought filter)
    async def _relay(self, resp, turn_no: int)                         # :549 → super()._relay(); then avatar tee via connection.avatar_session.speak/interrupt/finish_turn
class VoiceChatHandler:
    def __init__(self, bot_factory=None, default_config=None, *, require_auth=False, token_validator=None, secret_key=None, auth_timeout=30.0, ws_route="/ws/voice", health_route="/health")  # :625
    async def _run_voice_session(self, connection)                     # :1687 (bot._llm lazy init :1704-1706; client=_AskStreamVoiceClient(bot, user_id=connection.user_id) :1715; _HandlerVoiceSession(client=, send_fn=, system_prompt=bot.system_prompt, voice_config=bot.voice_config, session_id=connection.session_id, stt_only=, handler=, connection=) :1726)
    async def _send_message(self, ws, message)                         # :1880

# packages/ai-parrot/src/parrot/voice/session.py
class VoiceSession: __init__(self, client: VoiceCapable, send_fn, system_prompt: str, voice_config=None, session_id=None, stt_only=False)  # :65
    async def start_turn(); push_audio(pcm); end_turn(); close(); _cancel_turn()  # :164/:180/:188/:226/:230 ; _run_turn calls self._relay(resp, turn_no)

# packages/ai-parrot/src/parrot/bots/voice.py
async def ask_stream(self, audio_input, session_id=None, user_id=None, stt_only=False, **kwargs) -> AsyncIterator[LiveVoiceResponse]  # :475

# packages/ai-parrot/src/parrot/models/voice.py:361
@dataclass class LiveVoiceResponse: text, audio_data: Optional[bytes], audio_format, is_complete, is_interrupted, tool_calls: List[LiveToolCall], usage, turn_metadata, session_id, turn_id, user_id, role, metadata: Dict[str, Any]
```
- Regression suite to keep green: `tests/voice/test_handler_refactor.py` (`TestFrameProtocolUnchanged :148`, `TestDeduplication :275` asserts `"_relay" in _HandlerVoiceSession.__dict__`), `tests/voice/test_voice_handler_avatar.py`, `tests/voice/test_voicechat_avatar_integration.py`.

### Does NOT Exist
- ~~`BroadcastVoiceSession`, `build_voice_frames`, `VoiceChatHandler(broadcast_service=…)`~~ — you add them.
- ~~A per-speaker conversation key~~ — forbidden; memory key is the broadcast's `voice_session_id`.
- ~~Using the creator/moderator's `user_id` for another speaker's tools~~ — forbidden; fail closed.

## Implementation Notes

- `build_voice_frames` must be a pure function; keep `_HandlerVoiceSession.build_frames` as a thin wrapper so dedup state stays on the instance.
- `BroadcastVoiceSession.send_fn` default is a no-op collector until TASK-2960 attaches the fan-out; design `set_fanout(callable)`.
- Sequence numbers for `BroadcastAudioFrame` restart per turn; `output_epoch`/`owner_epoch` read from the `BroadcastSession` at send time.

## Acceptance Criteria

- [ ] `BroadcastVoiceSession._relay` with a response carrying text+audio+tool_call emits `response_chunk`/`tool_call` frames **without** `audio`, and pushes exactly one `BroadcastAudioFrame` with the PCM.
- [ ] `is_interrupted` ⇒ `BroadcastSession.interrupt()` once; `is_complete` ⇒ `finish_turn()` once.
- [ ] `begin_speaker_turn()` sets the per-turn `user_id` to the speaker; a turn without an established speaker context raises `BroadcastError(floor_not_granted)` before any provider call.
- [ ] Late response from a superseded turn generation produces no frames.
- [ ] `_HandlerVoiceSession._relay` regression: still sends `audio` frame and still tees to `connection.avatar_session` (existing tests + one explicit new test).
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_relay.py packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py -q` green; `ruff check` clean.

## Test Specification

```python
from parrot.models.voice import LiveVoiceResponse
from parrot.integrations.liveavatar.broadcast.voice_relay import BroadcastVoiceSession

class FakeBroadcastSession:  # push_audio/interrupt/finish_turn recorders, owner_epoch/output_epoch attrs

async def test_relay_strips_pcm_from_wire_and_pushes_once(): ...
async def test_interrupt_and_complete_forwarded(): ...
async def test_turn_without_speaker_context_fails_closed(): ...
async def test_stale_generation_frames_suppressed(): ...
async def test_legacy_relay_still_sends_audio_and_tees(handler, connection): ...
```

## Agent Instructions
1. Read spec §2 steps 6–7 and "Moderation" bullet on shared memory/tool context. 2. Verify anchors (FEAT-536 shifted lines; re-grep). 3. Index → `in-progress`. 4. Implement + tests; run the three regression suites. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
