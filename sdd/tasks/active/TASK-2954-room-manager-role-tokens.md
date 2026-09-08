# TASK-2954: LiveKitRoomManager role-specific tokens and room admin operations

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Parallel**: true
**Parallelism notes**: Touches only `room_manager.py` and its existing test module; no overlap with any other FEAT-537 task's files.

---

## Context

Spec §2: "Allocate the LiveKit room and a **distinct** direct-audio publisher before starting LiveAvatar … Pass the room's **separate avatar publisher token** to LiveAvatar … Each browser connection gets a fresh identity … Tokens grant room join and subscription only, with publishing and data publishing disabled". Spec §6 Does-NOT-Exist: "The fixed `avatar-agent` token must not be reused for the direct publisher." Today `mint_room_tokens()` mints one viewer token + one fixed-identity publish token (`room_manager.py:78-137`). Module 2 extension.

## Scope

- Extend `LiveKitRoomManager` (keep `mint_room_tokens` unchanged for FEAT-245/536 callers):
  - `mint_viewer_token(room: str, identity: str, *, ttl_s: int = 60) -> str` — grants `room_join=True, room=room, can_publish=False, can_subscribe=True, can_publish_data=False`, `.with_ttl(timedelta(seconds=ttl_s))`, `.with_identity(identity)`; no admin grants.
  - `mint_publisher_token(room: str, identity: str, *, ttl_s: int = 3600, name: str | None = None) -> str` — `can_publish=True, can_subscribe=True, can_publish_data=False`; identity is caller-supplied (e.g. `avatar-<bid8>`, `direct-<bid8>`), never the fixed `avatar-agent`.
  - `async create_room(room: str, *, max_participants: int = 12, empty_timeout_s: int = 60) -> None`, `async remove_participant(room, identity)`, `async list_participant_identities(room) -> list[str]`, `async delete_room(room)` — via `livekit.api.LiveKitAPI(url, api_key, api_secret)` room service (`create_room`, `remove_participant`, `list_participants`, `delete_room` verified on livekit-api 1.2.0), each wrapped with `aclose()` of the API client and lazy import through `_require_livekit_api()`.
  - `http_url` derivation from `wss://` → `https://` for `LiveKitAPI` (document it).
- Tests appended to `tests/integrations/liveavatar/test_room_manager.py` using its `_jwt_payload()` helper (line 82): viewer token has `video.canPublish == False` and `video.canPublishData == False`, TTL ≈ 60 s (`exp - nbf`), publisher token identity equals the argument and ≠ `"avatar-agent"`; room-admin calls covered with a fake `LiveKitAPI` injected via `mocker.patch.object(room_manager_module, "_require_livekit_api")`.

**NOT in scope**: registry, publisher/session changes, viewer HTTP endpoints.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py` | MODIFY | Add role-specific mint + room admin ops |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_manager.py` | MODIFY | Add tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.models import LiveKitRoomTokens   # room_manager.py:24
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager, _require_livekit_api  # :47, :27
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py
def _require_livekit_api() -> object:                                     # :27 — lazy `from livekit import api`
class LiveKitRoomManager:                                                 # :47
    _AGENT_IDENTITY: str = "avatar-agent"                                 # :64  (legacy fixed identity — keep for mint_room_tokens only)
    def __init__(self, *, url: Optional[str] = None, api_key: Optional[str] = None, api_secret: Optional[str] = None)  # :66
        self.url: str; self._key: str; self._secret: str; self.logger     # :73-76
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens  # :78 — builds VideoGrants(room_join, room, can_publish, can_subscribe) + AccessToken(...).with_identity().with_grants().to_jwt()

# livekit.api (installed 1.2.0, verified via inspect)
api.VideoGrants(room_join: bool|None, room: str, can_publish: bool = True, can_subscribe: bool = True, can_publish_data: bool = True, hidden: bool|None, room_admin: bool|None, ...)
api.AccessToken(key, secret).with_identity(str).with_name(str).with_grants(VideoGrants).with_ttl(datetime.timedelta).to_jwt()
api.LiveKitAPI(url, api_key, api_secret).room  -> RoomService: create_room, delete_room, list_participants, remove_participant, list_rooms, ...
api.LiveKitAPI.aclose()
```
- Test helper: `tests/integrations/liveavatar/test_room_manager.py:82 _jwt_payload(token) -> dict` (base64 decode, no verify) and `:92 test_client_token_remains_subscribe_only` (asserts `grants["canPublish"] is False`).

### Does NOT Exist
- ~~`LiveKitRoomManager.mint_viewer_token` / `mint_publisher_token` / `create_room`~~ — you add them.
- ~~`livekit.api.RoomService` as a top-level attribute~~ — reach it via `LiveKitAPI(...).room` (verified `hasattr(api,'RoomService') is False`).
- ~~`max_participants=10` as the seat limit~~ — spec §7: room capacity is 10 viewers **plus** both producers; application reservations enforce the ten-seat rule.

## Implementation Notes

- Keep the class sync for JWT minting (callers already offload with `asyncio.to_thread`, `voice_session.py:155`); room-admin methods are `async` because `LiveKitAPI` is aiohttp-based.
- Use `livekit.api.CreateRoomRequest(name=room, max_participants=…, empty_timeout=…)` / `RoomParticipantIdentity(room=…, identity=…)` / `ListParticipantsRequest(room=…)` / `DeleteRoomRequest(room=…)` — verify the exact request classes in `livekit.api` (`python -c "from livekit import api; print([n for n in dir(api) if 'Request' in n])"`) before use.
- Log identities, never tokens.

## Acceptance Criteria

- [ ] Viewer token: `canPublish is False`, `canPublishData is False`, `canSubscribe is True`, `exp-nbf ≈ 60`, identity as given.
- [ ] Publisher token: `canPublish is True`, identity as given; two publisher identities differ; `mint_room_tokens` behaviour unchanged (existing tests still pass).
- [ ] `create_room`/`remove_participant`/`list_participant_identities`/`delete_room` call the fake API with expected args and always `aclose()`.
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_room_manager.py -q` green; `ruff check` clean.

## Test Specification

```python
def test_viewer_token_is_subscribe_only_with_ttl(mgr):
    tok = mgr.mint_viewer_token("room-x", "viewer-abc", ttl_s=60)
    p = _jwt_payload(tok)
    assert p["video"]["canPublish"] is False and p["video"]["canPublishData"] is False
    assert p["sub"] == "viewer-abc" and 55 <= p["exp"] - p["nbf"] <= 65

def test_publisher_tokens_have_distinct_identities(mgr):
    a = _jwt_payload(mgr.mint_publisher_token("room-x", "avatar-1234"))
    d = _jwt_payload(mgr.mint_publisher_token("room-x", "direct-1234"))
    assert a["sub"] != d["sub"] and "avatar-agent" not in (a["sub"], d["sub"])

async def test_create_room_uses_api_and_closes(mgr, mocker): ...
```

## Agent Instructions
1. Read spec §2 "Ownership, admission and cleanup" bullets on identities/tokens. 2. Verify signatures. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
