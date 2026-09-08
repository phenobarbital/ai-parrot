# TASK-2957: VoiceAvatarSession — injected room credentials, lifecycle callbacks, startup deadline

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2955
**Parallel**: false
**Parallelism notes**: Touches `voice_session.py` + its tests; consumes TASK-2955's `AvatarWebSocket` kwargs. No overlap with TASK-2954/2956 files.

---

## Context

Spec §2 Integration Points "Allocated shared room": "Current `VoiceAvatarSession.start` mints its own tokens and uses the verified `livekit_config` keys. Add optional injected credentials without breaking existing callers." In broadcast mode the room and both publisher identities are allocated **before** the avatar starts (TASK-2954/2958), and the avatar must join with its **own** publisher token, not the fixed `avatar-agent`. Module 3.

## Scope

- Extend `VoiceAvatarSession.start(cls, *, agent_id, session_id, tenant_id, avatar_id=None, **new)` with keyword-only optional args:
  - `livekit_url: str | None`, `room_name: str | None`, `avatar_publisher_token: str | None`, `viewer_token: str | None = None` — when the three are given, **skip** `LiveKitRoomManager().mint_room_tokens` and build `livekit_config = {"livekit_url": livekit_url, "livekit_room": room_name, "livekit_client_token": avatar_publisher_token}` (keys verified against the OpenAPI `LiveKitConfigSchema`; do not rename).
  - `on_event`, `on_close` → forwarded to `AvatarWebSocket(handle, on_event=..., on_close=..., auto_reconnect=False, aggregate=True, send_timeout_s=send_timeout_s)` when `broadcast=True`; otherwise construct exactly as today (`AvatarWebSocket(handle)`).
  - `startup_deadline_s: float | None = None` — wrap steps 3–6 in `asyncio.wait_for`; on timeout clean up partial resources (existing except-block pattern `:186-198`) and raise `AvatarStartupTimeout(RuntimeError)`.
  - `max_session_duration_s: int | None = None` → `LiveAvatarConfig(max_session_duration=...)` (field exists, `models.py:42`).
  - `is_sandbox`, `base_url`, `api_key`, `avatar_id` resolution unchanged.
- New read-only properties: `liveavatar_session_id` (audit id only, from `handle.liveavatar_session_id`), `room_name`, `avatar_identity` (caller-supplied identity string passed as `avatar_identity: str | None`), `closed: bool`.
- `viewer_credentials` unchanged for legacy path; when tokens were injected, it returns `{"livekit_url", "room", "client_token": viewer_token or ""}` — broadcast callers never use it (participants get per-lease tokens).
- Tests: extend `tests/voice/conftest.py::patched_stack` to assert the room manager is **not** called when credentials are injected; new tests in `tests/voice/test_voice_avatar_session.py`.

**NOT in scope**: `BroadcastSession`, handler wiring, HTML.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` | MODIFY | Optional injected credentials, callbacks, deadline, audit props |
| `packages/ai-parrot-integrations/tests/voice/test_voice_avatar_session.py` | MODIFY | New tests (existing 4 stay green) |
| `packages/ai-parrot-integrations/tests/voice/conftest.py` | MODIFY (if needed) | `patched_stack` captures `AvatarWebSocket` kwargs |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket          # voice_session.py:45
from parrot.integrations.liveavatar.client import LiveAvatarClient            # :46
from parrot.integrations.liveavatar.models import LiveAvatarConfig, LiveKitRoomTokens, AvatarSessionHandle  # :47-51
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager    # :52
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py
class VoiceAvatarSession:                                                        # :55
    def __init__(self, *, tokens: LiveKitRoomTokens, client: LiveAvatarClient, handle: AvatarSessionHandle, ws: AvatarWebSocket)  # :73
    @classmethod async def start(cls, *, agent_id: str, session_id: str, tenant_id: str | None, avatar_id: str | None = None) -> "VoiceAvatarSession"  # :91
        # :137-149 env → LiveAvatarConfig(api_key, avatar_id, base_url, is_sandbox)
        # :154-157 tokens = await asyncio.to_thread(room_manager.mint_room_tokens, session_id, agent_id)
        # :161-165 livekit_config = {"livekit_url": tokens.livekit_url, "livekit_room": tokens.room, "livekit_client_token": tokens.agent_token}
        # :168-169 client = LiveAvatarClient(cfg); await client.aopen()
        # :175-184 handle = await client.create_session_token(cfg, livekit_config=...); handle.session_id=...; handle.tenant_id=...; await client.start_session(handle); ws = AvatarWebSocket(handle); await ws.__aenter__(); await ws.start_speaking()
        # :186-198 except Exception: cleanup ws/handle/client then raise
    @property def viewer_credentials(self) -> dict[str, str]                       # :208 → {livekit_url, client_token, room}
    async def speak(self, pcm: bytes); async def finish_turn(self); async def interrupt(self); async def aclose(self)  # :223/:235/:243/:252

# models.py
class LiveAvatarConfig(BaseModel):  api_key, avatar_id, base_url, is_sandbox, max_session_duration: Optional[int], quality, encoding  # :18-56
class AvatarSessionHandle(BaseModel): session_id, liveavatar_session_id, session_token, ws_url, tenant_id, agent_name       # :86-127

# TASK-2955 (verify landed): AvatarWebSocket(handle, *, session=None, assume_connected=False, on_event=None, on_close=None, auto_reconnect=True, send_timeout_s=None, aggregate=False)
```
- Test fixture: `tests/voice/conftest.py:12 patched_stack(mocker)` patches `voice_session.LiveKitRoomManager`, `.LiveAvatarClient`, `.AvatarWebSocket` and env; returns `(rm, client, ws, tokens)`.

### Does NOT Exist
- ~~`VoiceAvatarSession.start(livekit_tokens=...)`~~ — baseline mints internally; you add the injected path.
- ~~`VoiceAvatarSession.liveavatar_session_id` / `avatar_identity` / `closed`~~ — new.
- ~~A LiveAvatar "shorthand" key set (`url`/`room`/`token`)~~ — spec §2: preserve `livekit_url`, `livekit_room`, `livekit_client_token`.

## Implementation Notes

- Build a `LiveKitRoomTokens(livekit_url=..., room=..., client_token=viewer_token or "", agent_token=avatar_publisher_token)` for the injected path so `__init__` stays unchanged; document that `agent_token` here is the **avatar** publisher token, never the direct one.
- `startup_deadline_s` covers `aopen` + `create_session_token` + `start_session` + WS connected gate; measure and log elapsed.
- Keep `aclose()` idempotent; call `client.stop_session` even when the WS already closed.

## Acceptance Criteria

- [ ] Injected credentials → `LiveKitRoomManager` never instantiated; `create_session_token` receives `livekit_config` with exactly the three verified keys and the injected publisher token.
- [ ] Legacy call (no injection) behaves exactly as before (existing 4 tests green).
- [ ] `startup_deadline_s=0.01` with a stalled `start_session` → `AvatarStartupTimeout`, `stop_session`+`aclose` awaited (cleanup), `ws.__aexit__` awaited if opened.
- [ ] `broadcast=True` passes `auto_reconnect=False, aggregate=True, on_event, on_close` to `AvatarWebSocket`.
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_avatar_session.py -q` green; `ruff check` clean.

## Test Specification

```python
async def test_start_with_injected_room_skips_minting(patched_stack):
    rm, client, ws, _ = patched_stack
    s = await VoiceAvatarSession.start(agent_id="ag", session_id="b1", tenant_id="t",
        livekit_url="wss://x", room_name="room-b1", avatar_publisher_token="avatar-jwt", avatar_identity="avatar-b1", broadcast=True)
    rm.mint_room_tokens.assert_not_called()
    cfg = client.create_session_token.await_args.kwargs["livekit_config"]
    assert cfg == {"livekit_url": "wss://x", "livekit_room": "room-b1", "livekit_client_token": "avatar-jwt"}

async def test_startup_deadline_cleans_up(patched_stack): ...
async def test_broadcast_mode_configures_ws_callbacks(patched_stack, mocker): ...
```

## Agent Instructions
1. Read spec §2 "Vendor contract" + Integration Points row "Allocated shared room". 2. Verify TASK-2955 kwargs exist. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
