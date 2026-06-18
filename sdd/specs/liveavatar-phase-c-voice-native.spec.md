---
type: feature
base_branch: dev
---

# Feature Specification: LiveAvatar — Phase C (voice-native hybrid, ai-parrot as the brain)

**Feature ID**: FEAT-243
**Date**: 2026-06-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Input brainstorm: `sdd/proposals/liveavatar-integration.brainstorm.md` (Option C).
> **Depends on FEAT-242** (`sdd/specs/liveavatar-phase-a-mouth.spec.md`) — must merge first.
> Phase C reuses Phase A's `LiveKitRoomManager` (M3) and `SpeakableFlattener` (M4).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Phase A (FEAT-242) gives AgentChat a talking avatar but **drives turn-taking manually** —
there is no native STT/VAD/turn-detection/barge-in, so the spoken conversation is less fluent
than a real voice assistant.

Phase C makes the avatar **voice-native**: it keeps the LiveKit Agents voice pipeline
(STT + VAD + turn-detection + TTS + avatar) from the starter, but the **brain stays
ai-parrot** by overriding `llm_node` to call ai-parrot instead of LiveKit's LLM. The response
bifurcates: plain text → spoken by the avatar; structured outputs (charts/data/`tool_calls`/
canvas) → published to the existing AgentChat UI channel, sharing `session_id`.

This reuses Phase A's media transport (**BYO + LiveKit Cloud**) wholesale — no migration —
and the LiveKit Agents worker is deployable via `lk agent deploy` because the room is ours.

### Goals
- Fluent voice conversation: STT, VAD, turn-detection and barge-in come from the LiveKit pipeline.
- `LiveAvatarAgent` overrides `llm_node` to call ai-parrot (`ask_stream`); `yield` speakable
  text → LiveKit TTS → avatar.
- Bifurcate structured outputs → AgentChat UI via `UserSocketManager.broadcast_to_channel()`
  keyed by `session_id` (the same conversation the avatar is speaking).
- Reuse the **same** LiveKit Cloud room/token layer as FEAT-242 (M3 `LiveKitRoomManager`).
- Reuse FEAT-242's `SpeakableFlattener` (M4) for filtering what gets spoken.
- Inject `tenant_id`/`agent_name`/`session_id` via LiveKit job metadata.
- Avoid dead air during long `tool_calls` (filler utterance / "thinking" state).

### Non-Goals (explicitly out of scope)
- Re-implementing the avatar audio bridge or LiveAvatar client — Phase C uses LiveKit's TTS
  node directly (own TTS optional later), so the Phase A `AvatarWebSocket` push path is not the
  primary mechanism here.
- **FULL Mode + Custom LLM** — rejected (see brainstorm Option B).
- **Self-hosted LiveKit SFU** — out of scope; LiveKit Cloud only.
- Changing FEAT-242's Phase A behavior.

---

## 2. Architectural Design

### Overview

The LiveKit Agents pipeline runs in a long-lived worker that joins the **same** LiveKit Cloud
room as the avatar participant. `build_session()` keeps STT (Deepgram/nova-3), VAD (Silero),
turn-detection (MultilingualModel) and TTS (LiveKit inference), but the LLM node is replaced:
`LiveAvatarAgent.llm_node()` extracts the last user message from `chat_ctx`, calls ai-parrot
via `ask_stream()`, and:
- `yield`s speakable text (run through the FEAT-242 `SpeakableFlattener`) so LiveKit's TTS node
  speaks it through the avatar;
- routes structured outputs to the AgentChat UI through an **output bridge** that calls
  `UserSocketManager.broadcast_to_channel()` keyed by `session_id`.

`worker.py` parses `ctx.job.metadata` (JSON) to inject `tenant_id`, `agent_name` and
`session_id`. The LiveAvatar session is opened with `livekit_config` pointing at our room
(FEAT-242 `LiveKitRoomManager`), and `stop_session` is registered as a shutdown callback.

### Component Diagram

```
[Browser] mic ──→ our LiveKit Cloud room ──→ AgentSession(STT / VAD / turn-detection)
                                                          │
                                              llm_node override ◄────┘  (LiveAvatarAgent)
                                                    │
                                                    ▼
                                   ai-parrot  ask_stream(agent_name, query, session_id, tenant_id)
                                       │                                  │
                          speakable text (SpeakableFlattener)      structured outputs
                                       │                                  │
                                 yield str → LiveKit TTS → avatar   OutputBridge
                                                                          │
                                                    broadcast_to_channel(session_id)
                                                                          ▼
                                                                   AgentChat UI (existing WS)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseBot.ask_stream` (`base.py:1456`) | uses | Token stream consumed inside `llm_node`. |
| `UserSocketManager.broadcast_to_channel` (`user.py:357`) | uses | Output bridge → AgentChat UI keyed by `session_id`. |
| `web_hitl.py` (`ws_channel_id` / `current_web_session`) | uses | Channel-routing pattern for the output bridge. |
| `AIMessage` (`responses.py:72`) | uses | Final stream sentinel; structured outputs / `tool_calls` / `artifact_id`. |
| FEAT-242 `LiveKitRoomManager` (`parrot/integrations/liveavatar/room_manager.py`) | uses | Reused room/token minting (shared transport). |
| FEAT-242 `SpeakableFlattener` (`parrot/integrations/liveavatar/speakable.py`) | uses | Reused markdown→speakable filter. |
| FEAT-242 `LiveAvatarClient` (`parrot/integrations/liveavatar/client.py`) | uses | Session lifecycle (`create_session_token` with `livekit_config`, `stop_session`). |
| LiveKit Agents `Agent.llm_node` | overrides | 1.x replacement for `before_llm_cb`; may `yield` plain `str`. |

### Data Models

```python
# parrot/integrations/liveavatar/livekit_agent/models.py — to create

class AvatarJobMetadata(BaseModel):     # parsed from ctx.job.metadata (JSON)
    ws_url: str
    session_id: str
    agent_name: str
    tenant_id: Optional[str] = None

class StructuredOutputMessage(BaseModel):   # the output-bridge contract (P4)
    type: str                               # e.g. "chart" | "data" | "canvas" | "tool_call"
    session_id: str
    payload: dict
    turn_id: Optional[str] = None
```

### New Public Interfaces

```python
# parrot/integrations/liveavatar/livekit_agent/ — signatures illustrative, confirm vs pinned livekit-agents (P5)

class LiveAvatarAgent(Agent):
    async def llm_node(self, chat_ctx, tools, model_settings):
        user_text = _last_user_text(chat_ctx)          # last ChatMessage role=user
        async for chunk in ai_parrot_ask_stream(agent_name=self._agent_name,
                                                 query=user_text,
                                                 session_id=self._session_id,
                                                 tenant_id=self._tenant_id):
            # speakable str → yield (TTS → avatar); structured → output bridge
            ...

def build_session(vad) -> AgentSession: ...            # adapt starter pipeline.py

class OutputBridge:                                    # new — Phase C
    async def publish(self, msg: StructuredOutputMessage) -> None: ...   # → broadcast_to_channel
```

---

## 3. Module Breakdown

### Module 1: LiveKit Agents worker + pipeline
- **Path**: `parrot/integrations/liveavatar/livekit_agent/worker.py`, `pipeline.py`
- **Responsibility**: adapt starter `worker.py`/`pipeline.py`; `build_session(vad)` with STT/VAD/
  turn-detection/TTS; parse `ctx.job.metadata` → `AvatarJobMetadata`; register `stop_session`
  shutdown callback; open LiveAvatar session with `livekit_config` (FEAT-242 client + room manager).
  (capability `llm-node-aiparrot-bridge`)
- **Depends on**: FEAT-242 M3 (`LiveKitRoomManager`), M1 (`LiveAvatarClient`); new dep `livekit-agents` (pinned).

### Module 2: `llm_node` ai-parrot bridge
- **Path**: `parrot/integrations/liveavatar/livekit_agent/agent.py`
- **Responsibility**: `LiveAvatarAgent` overriding `llm_node` — extract last user text, call
  `ask_stream()`, `yield` speakable text (via FEAT-242 `SpeakableFlattener`), route structured
  outputs to the output bridge; filler utterance during long `tool_calls`.
  (capability `llm-node-aiparrot-bridge`)
- **Depends on**: Module 1; `ask_stream`; FEAT-242 M4 (`SpeakableFlattener`).

### Module 3: Structured-output → AgentChat UI bridge
- **Path**: `parrot/integrations/liveavatar/output_bridge.py`
- **Responsibility**: define the `StructuredOutputMessage` contract (P4); publish to the AgentChat
  UI channel via `broadcast_to_channel()` keyed by `session_id`.
  (capability `llm-node-aiparrot-bridge`)
- **Depends on**: Module 2; `UserSocketManager.broadcast_to_channel`.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_job_metadata_parsing` | M1 | `ctx.job.metadata` JSON → `AvatarJobMetadata` (tenant_id/agent_name/session_id) |
| `test_build_session_components` | M1 | session wires STT/VAD/turn-detection/TTS as configured |
| `test_stop_session_shutdown_callback` | M1 | `stop_session` registered + called on shutdown |
| `test_llm_node_yields_speakable_str` | M2 | `llm_node` yields plain str from ai-parrot stream |
| `test_llm_node_last_user_text` | M2 | extracts last `role=user` message from `chat_ctx` |
| `test_llm_node_filler_on_tool_calls` | M2 | emits filler/"thinking" during long `tool_calls` |
| `test_output_bridge_contract` | M3 | structured outputs published with agreed schema to `session_id` channel |
| `test_speakable_flatten_reused` | M2 | FEAT-242 flattener strips markdown before TTS |

### Integration Tests
| Test | Description |
|---|---|
| `test_phase_c_voice_roundtrip_sandbox` | mic → STT → `llm_node`→ai-parrot → TTS → avatar; outputs to UI (`is_sandbox=true`) |
| `test_phase_c_barge_in_native` | LiveKit VAD/turn-detection interrupts mid-utterance |
| `test_phase_c_shares_session_id` | avatar speech and AgentChat canvas share the same `session_id` |

### Test Data / Fixtures
```python
@pytest.fixture
def avatar_job_metadata():
    return AvatarJobMetadata(ws_url="wss://...", session_id="s1",
                             agent_name="demo", tenant_id="t1")
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] FEAT-242 (Phase A) is merged; M3 room manager + M4 flattener are reused (not duplicated)
- [ ] `livekit-agents` version is pinned in `pyproject.toml` and the `llm_node` signature validated against it (P5)
- [ ] `LiveAvatarAgent.llm_node` calls ai-parrot via `ask_stream` and `yield`s speakable text
- [ ] Speakable text is filtered through FEAT-242 `SpeakableFlattener` before TTS
- [ ] Structured outputs are bridged to AgentChat UI via `broadcast_to_channel()` keyed by `session_id` (contract defined — P4)
- [ ] Avatar speech and AgentChat UI share the same `session_id` (one conversation)
- [ ] `ctx.job.metadata` injects `tenant_id`/`agent_name`/`session_id`; avatar is opt-in per tenant
- [ ] Transport is the **same** BYO + LiveKit Cloud room as FEAT-242 (no new transport layer)
- [ ] Long `tool_calls` do not produce dead air (filler/"thinking" state)
- [ ] `stop_session` registered as a shutdown callback; runs on worker teardown
- [ ] Phase C unit + integration tests pass in LiveAvatar sandbox (`is_sandbox=true`)
- [ ] No breaking changes to FEAT-242 Phase A behavior

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified in this session (2026-06-18). Phase C also
> depends on FEAT-242 artifacts — those are listed as "to be created by FEAT-242", not verified
> here. Implementation agents MUST NOT reference imports/attributes/methods not listed without
> verifying first.

### Verified Imports (existing codebase)
```python
# Streaming source consumed inside llm_node:
# packages/ai-parrot/src/parrot/bots/base.py:1456  -> BaseBot.ask_stream(...)
# UI bridge:
# packages/ai-parrot-server/src/parrot/handlers/user.py:357 -> UserSocketManager.broadcast_to_channel(...)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/base.py
async def ask_stream(self, question, ...) -> AsyncIterator[Union[str, AIMessage]]: ...  # line 1456
# abstract decl: packages/ai-parrot/src/parrot/bots/abstract.py:3740

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                 # line 72
    response: Optional[str]; output: Any; data: Optional[Any]; code: Optional[str]
    tool_calls: List[ToolCall]; output_mode: OutputMode; artifact_id: Optional[str]
    @property
    def to_text(self) -> str: ...                           # line 249

# packages/ai-parrot-server/src/parrot/handlers/user.py
class UserSocketManager(WebSocketManager):                  # line 27
    async def broadcast_to_channel(self, channel, message, exclude_ws=None): ...  # line 357

# packages/ai-parrot-server/src/parrot/handlers/web_hitl.py
# current_web_session: ContextVar[Optional[str]]   — channel-routing pattern (lines ~54-93)
# ws_channel_id wired at agent.py:1703-1708
```

### Provided by FEAT-242 (must merge first — NOT verified here, created by Phase A)
```python
# parrot/integrations/liveavatar/room_manager.py  -> LiveKitRoomManager.mint_room_tokens(...)
# parrot/integrations/liveavatar/speakable.py      -> SpeakableFlattener.feed(...)/flush(...)
# parrot/integrations/liveavatar/client.py         -> LiveAvatarClient.create_session_token(...) / stop_session(...)
# parrot/integrations/liveavatar/models.py         -> LiveAvatarConfig, LiveKitRoomTokens, AvatarSessionHandle
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LiveAvatarAgent.llm_node` | `BaseBot.ask_stream()` | async iteration of chunks | `base.py:1456` |
| `LiveAvatarAgent.llm_node` | `SpeakableFlattener` (FEAT-242) | filter speakable text | created by FEAT-242 |
| `OutputBridge.publish` | `UserSocketManager.broadcast_to_channel()` | publish keyed by `session_id` | `user.py:357` |
| `worker.py` | `LiveKitRoomManager` / `LiveAvatarClient` (FEAT-242) | room tokens + session lifecycle | created by FEAT-242 |

### Does NOT Exist (Anti-Hallucination)
- ~~any `livekit-agents` / `llm_node` override / `AgentSession` code~~ — does not exist; created here (P5).
- ~~a structured-output → UI bridge~~ — does not exist; created here (P4).
- ~~`tenant_id` threaded through the chat endpoint~~ — only `user_id`/`session_id` today; inject via job metadata + ai-parrot call args.
- ~~`SpeakableFlattener` / `LiveKitRoomManager` in the current tree~~ — created by FEAT-242; this spec assumes they exist after that merge.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout; `aiohttp` for any HTTP (not `requests`/`httpx`).
- Pydantic models for all structured data (`AvatarJobMetadata`, `StructuredOutputMessage`).
- `self.logger` for logging; no `print`.
- New code under `parrot/integrations/liveavatar/livekit_agent/`.
- Add `livekit-agents` + `livekit-plugins-*` as an **optional extra** in `pyproject.toml`; pin versions.
- `llm_node` may `yield` plain `str` (TTS node consumes it) — emit ai-parrot text token-by-token or by sentence.
- Secrets via env only (same as FEAT-242, plus any plugin provider keys: Deepgram STT, Cartesia TTS).

### Known Risks / Gotchas
- **`livekit-agents` version drift** → the `llm_node` signature changed across versions; pin and validate (P5).
- **Streaming vs block** → if ai-parrot returned only whole responses, TTFB would be high; we stream via `ask_stream`.
- **Long `tool_calls`** → avatar may go silent → filler utterance / "thinking" state.
- **Output bridge contract** → must be defined (P4) so the AgentChat UI can render charts/data/canvas from the voice turn.
- **Cost** → Phase C uses the LiveKit inference gateway (STT/TTS) billed to LiveKit Cloud credits; use `is_sandbox=true` in dev.
- **Deployment** → long-lived stateful worker; `lk agent deploy` applies (room is ours). spawn-per-session vs warm pool unresolved (Q-deploy).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `livekit-agents` | `~=1.5` (pin at impl) | Voice pipeline (`AgentSession`, STT/VAD/turn/TTS) + `llm_node` override |
| `livekit-plugins-*` | pin at impl | Deepgram STT, Cartesia TTS, Silero VAD, MultilingualModel turn-detection |
| `livekit-api` | (via FEAT-242) | Room/token minting (shared transport) |
| Supertonic (existing) | existing | Optional own TTS later (default here = LiveKit inference) |

---

## 8. Open Questions

> Resolved items (from brainstorm) are `[x]`; unresolved are `[ ]`.

- [x] P1 — Does ai-parrot stream partial tokens? — *Resolved in brainstorm*: Yes, via `ask_stream()`. Consumed inside `llm_node`.
- [x] P3 — Any avatar integration code today? — *Resolved in brainstorm*: None. Clean slate.
- [x] Media transport — *Resolved in brainstorm*: BYO + LiveKit Cloud, **same room as FEAT-242** (no migration).
- [x] TTS choice — *Resolved in brainstorm*: LiveKit inference in Phase C (own TTS optional later).
- [x] Tenant model — *Resolved in brainstorm*: opt-in per program/tenant; injected via LiveKit job metadata.
- [ ] P4 — Define the structured-outputs → AgentChat UI bridge contract (`StructuredOutputMessage` schema + channel; via `broadcast_to_channel()` keyed by `session_id`). — *Owner: Jesús / Claude Code*
- [ ] P5 — Pin `livekit-agents` version and validate the exact `llm_node` signature against it. — *Owner: Jesús*
- [ ] Q-deploy — spawn-per-session vs warm worker pool (`lk agent deploy`) for the long-lived stateful worker. — *Owner: Jesús*
- [ ] Q-filler — design the "thinking"/filler behavior during long `tool_calls` (text utterances vs UI state). — *Owner: Jesús / Claude Code*
- [ ] Q-plugins — confirm STT/TTS plugin choices (Deepgram/Cartesia vs alternatives) and their provider keys. — *Owner: Jesús*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential).
- **Rationale**: Phase C is a single integration seam (worker + `llm_node` bridge + output bridge)
  built on top of FEAT-242 artifacts. M1 → M2 → M3 are tightly coupled and best implemented
  sequentially in one worktree.
- **Cross-feature dependencies**: **FEAT-242 (Phase A) MUST be merged first** — Phase C reuses its
  `LiveKitRoomManager`, `SpeakableFlattener`, `LiveAvatarClient` and models. Do not start Phase C
  task execution until FEAT-242 lands on `dev`. P4 and P5 should be resolved before/early in implementation.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-18 | Jesus Lara | Initial draft — Phase C split from combined liveavatar-integration spec (depends on FEAT-242) |
