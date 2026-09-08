# TASK-2960: Broadcast WebSocket route — lease-bound control sockets, floor validation, handoff barrier

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2959
**Parallel**: false
**Parallelism notes**: Second sequential edit of `voice/handler.py` (after TASK-2959). Also creates `broadcast/floor.py`. No other task edits handler.py after this except TASK-2961's small service hook.

---

## Context

Spec §2 "New participant control/input route: `/ws/voice/broadcast/{agent_id}/{broadcast_id}`. Require existing WebSocket authentication plus an owned admitted lease. All participants may receive control state, but only the granted speaker may bind microphone input…" plus the whole "Moderation and exclusive speaking floor" section (epochs, 409 `speaker_connection_exists`, `floor_not_granted`, `stale_floor_epoch`, barrier ≤ 3 s, heartbeat 5 s / expiry 15 s). Module 4 second half; AC12–AC14 server side.

## Scope

- `broadcast/floor.py`: pure helpers `validate_audio_authority(descriptor, lease, *, floor_epoch, socket_id) -> None` (raises `FloorNotGranted`/`StaleFloorEpoch`/`SpeakerConnectionExists`), `class FloorCoordinator` orchestrating the handoff: `async handoff(registry, session: BroadcastSession, *, moderator_lease_id, target_lease_id | None, expected_version) -> BroadcastDescriptor` = `registry.grant_floor(...)` (→ `switching`, epoch+1) → notify old speaker socket `{"type":"floor_revoked","floor_epoch":…}` → `session.switch_speaker(target, new_epoch)` (producer barrier) → `registry.commit_floor(...)` (→ `granted`); on barrier failure/timeout `registry.abort_floor` and raise `BroadcastError(stale_floor_epoch)` with a retryable flag. Also `release(registry, session, speaker_lease_id)` (Finish Speaking / disconnect → floor back to moderator via the same barrier) and `succeed_moderator(...)`.
- `voice/handler.py`: `VoiceChatHandler.setup_routes` additionally mounts `ws_broadcast_route = "/ws/voice/broadcast/{agent_id}/{broadcast_id}"` **only when `broadcast_service` is set**. New `handle_broadcast_websocket(request)`:
  1. authenticate exactly like `handle_websocket` (`_authenticate_from_protocol`/`_authenticate_from_query` :772/:808 — no credentials in URL path; query token accepted only because the legacy route does; document it); resolve `ParticipantPrincipal` via `broadcast_service.resolve_principal(user, agent_id)`; require `lease_id` in the first `{"type":"attach","lease_id":…}` message and verify `lease.principal.user_id == principal.user_id` (else close 4403).
  2. register the socket as a **control socket** for that lease: heartbeat every 5 s expected (`{"type":"ping"}` reuse `_handle_ping` :1065) → `registry.heartbeat_control`; push `{"type":"broadcast_state", "state": public_state}` on attach and on every change the service publishes (`broadcast_service.subscribe(broadcast_id, send_fn)`).
  3. message handling: `start_session` attaches to the existing broadcast voice session (never creates a bot); `start_recording`/`audio_data`/`audio_chunk`/`stop_recording` require `message["floor_epoch"]` and pass `validate_audio_authority` **before** any provider call; first `start_recording` binds the socket via `registry.bind_speaker_socket` (duplicate ⇒ send `{"type":"error","code":"speaker_connection_exists"}` and ignore); rejected frames counted and dropped, never broadcast; `end_session` from a non-moderator releases only their speaking binding; `{"type":"finish_speaking"}` → `FloorCoordinator.release`.
  4. socket close: `unbind_speaker_socket`; if it was the speaker → release floor to moderator; heartbeat expiry handled by the service's reconciliation (TASK-2961) but the handler must stop accepting audio when `descriptor.floor_state != granted` or the lease heartbeat is > 15 s old.
  - Generic `ready_to_speak` is still sent, but broadcast sockets additionally receive `{"type":"floor_state", "granted": bool, "floor_epoch": int}` so the browser can gate the mic (TASK-2965).
- Tests `tests/voice/test_voice_broadcast_floor.py` (helpers/coordinator with in-memory registry + fake `BroadcastSession`) and additions to `test_voice_broadcast_relay.py` for the route using `aiohttp.test_utils.TestClient` with a fake service (attach, floor_epoch gating, duplicate socket 409, revoke stops audio, heartbeat).

**NOT in scope**: HTTP REST endpoints (TASK-2962), cross-worker relay (TASK-2961), browser.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/floor.py` | CREATE | Authority validation + `FloorCoordinator` |
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | `handle_broadcast_websocket`, route mount, floor-gated audio handlers |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_floor.py` | CREATE | Coordinator/authority tests |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_relay.py` | MODIFY | Route tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web, WSMsgType                                   # handler.py:33
from parrot.core.ws_auth import AuthenticatedUser, TokenValidator    # handler.py:74 ; ws_auth.py:34/:44 (validate(token) -> Optional[AuthenticatedUser] :77)
from parrot.integrations.liveavatar.broadcast import errors, models, BroadcastRegistry  # TASK-2951/2952
from parrot.integrations.liveavatar.broadcast.session import BroadcastSession          # TASK-2958
from parrot.integrations.liveavatar.broadcast.voice_relay import BroadcastVoiceSession # TASK-2959
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/handler.py
class VoiceChatHandler:
    def setup_routes(self, app, prefix="", *, include_health=True, include_static=True, static_dir=None)  # :700
    async def _authenticate_from_protocol(self, request) -> tuple[Optional[str], Optional[AuthenticatedUser]]  # :772 (Sec-WebSocket-Protocol "jwt, <token>")
    async def _authenticate_from_query(self, request) -> Optional[AuthenticatedUser]                          # :808 (?token=)
    async def handle_websocket(self, request) -> web.WebSocketResponse                                         # :819 (protocol doc :824-836)
    async def _handle_message(self, connection, message)   # :958 dispatch dict :980-992 incl. aliases "audio_chunk"→_handle_audio_data, "text_message"→_handle_send_text
    async def _handle_ping(self, connection, message)      # :1065
    async def _handle_start_recording / _handle_stop_recording / _handle_audio_data  # :1313 / :1354 / :1411 (audio_data reads message["data"] b64 :1437)
    async def _send_message(self, ws, message); async def _send_error(self, ws, error_message)  # :1880 / :1887
    async def _cleanup_connection(self, connection)        # :1898
@dataclass class WebSocketConnection: ws, session_id, authenticated, user: Optional[AuthenticatedUser], bot, streaming_mode, is_recording, session_active, voice_task, voice_session, shutdown_event, config, stt_only, avatar_session  # :184-256
```

### Does NOT Exist
- ~~`/ws/voice/broadcast/...` route, `handle_broadcast_websocket`, `FloorCoordinator`~~ — new.
- ~~A `floor_epoch` field in today's `start_recording`/`audio_data` messages~~ — you add it (broadcast route only; legacy route ignores it).
- ~~Authorization by "holds a valid LiveKit viewer JWT" or "is moderator"~~ — insufficient for mic input (spec).
- ~~`request["user_id"]`~~ — never set by navigator-auth; use the handler's own `AuthenticatedUser`.

## Implementation Notes

- Reuse a `WebSocketConnection` per broadcast socket but with `bot=None`; keep `connections` dict semantics (`:623`) so `_cleanup_all_connections` still works.
- Barrier ordering matters: `grant_floor` (switching) → revoke notify → `switch_speaker` → `commit_floor`. Never set the new speaker before the producer acks.
- Rate/size limits: reject `audio_data` payloads > 64 KiB b64 and > 50 msgs/s per socket with `error code="rate_limited"`.

## Acceptance Criteria

- [ ] Attach with a lease owned by another user ⇒ socket closed with code 4403; correct lease ⇒ `broadcast_state` pushed.
- [ ] `audio_data` without/with stale `floor_epoch`, or from a non-speaker ⇒ dropped + `error code` (`stale_floor_epoch`/`floor_not_granted`), no `push_audio` on the session; counted.
- [ ] Second `start_recording` socket for the same lease ⇒ `speaker_connection_exists`; first stays bound.
- [ ] Handoff: old speaker gets `floor_revoked`, its next frame is rejected, new speaker accepted only after `commit_floor`; barrier failure ⇒ floor `idle` + retryable error, zero frames admitted from either.
- [ ] Speaker socket close ⇒ floor returns to moderator; moderator cannot send audio while another holds the floor.
- [ ] Legacy `/ws/voice` behaviour unchanged (existing handler suites green).
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_floor.py packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_relay.py -q` green; `ruff check` clean.

## Test Specification

```python
async def test_validate_audio_authority_rejects_non_speaker_and_stale_epoch(): ...
async def test_handoff_orders_switching_barrier_commit(): ...
async def test_handoff_barrier_timeout_leaves_floor_idle(): ...
async def test_ws_attach_wrong_owner_closes_4403(aiohttp_client): ...
async def test_ws_duplicate_speaker_socket_409(aiohttp_client): ...
async def test_ws_revoke_stops_old_speaker_audio(aiohttp_client): ...
```

## Agent Instructions
1. Read spec §2 "Moderation and exclusive speaking floor" (all bullets) + route paragraph. 2. Verify anchors after TASK-2959 (lines shift). 3. Index → `in-progress`. 4. Implement + tests; run all `tests/voice/` suites. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
