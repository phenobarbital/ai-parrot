# TASK-2479: AppService Room Primitives

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2478
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Verified gap: `MatrixAppService` can only invite/join into pre-existing
room ids — there is **no** room creation, alias, leave, or bot-side state helper. Channels
(TASK-2480) and tunnels (TASK-2481) need them. Also widens custom-event routing so
`m.parrot.feedback` reaches the callback and the callback learns `room_id` + `sender`.

---

## Scope

- Add to `MatrixAppService`: `create_room_as_bot()`, `set_room_state_as_bot()`,
  `get_room_state_as_bot()`, `leave_as_agent()`, `resolve_alias()`.
- Route `ParrotEventType.FEEDBACK` in `_handle_event` alongside TASK/RESULT.
- Custom-event callback now receives `(event_type, content, room_id, sender)`. Keep the
  2-arg `HybridDelegator.on_custom_event` working: in `set_custom_event_callback`, inspect
  the callable's arity (`inspect.signature`) and wrap 2-arg callbacks in an adapter.
- Tests.

**NOT in scope**: channel/tunnel logic, transport wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py` | MODIFY | new methods, FEEDBACK routing, callback adapter |
| `packages/ai-parrot-integrations/tests/test_matrix_appservice_rooms.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.appservice import MatrixAppService     # appservice.py:36
from parrot.integrations.matrix.events import ParrotEventType           # events.py:21
from parrot.integrations.matrix.models import MatrixAppServiceConfig    # models.py:7
from mautrix.types import EventType, RoomID, UserID, RoomCreatePreset, RoomDirectoryVisibility   # mautrix 0.21.1 (installed)
from mautrix.appservice import IntentAPI
```

### Existing Signatures to Use
```python
# appservice.py
class MatrixAppService:                                                   # :36
    def __init__(self, config: MatrixAppServiceConfig) -> None            # :64  sets self._config, self._registered_agents: Dict[str,str]
    @property bot_intent -> IntentAPI                                     # :136
    async def ensure_agent_in_room(self, agent_name: str, room_id: str) -> None   # :196 — bot_intent.invite_user(RoomID, UserID) :218 ; intent.ensure_joined :224
    async def send_custom_event_as_agent(self, agent_name, room_id, event_type: str, content: dict) -> Optional[str]   # :316
    def set_custom_event_callback(self, callback: Callable) -> None       # :444  stores self._custom_event_callback
    async def _handle_event(self, event: Event) -> None                   # :456
        # :461  if event_type_str in (ParrotEventType.TASK, ParrotEventType.RESULT): ... await self._custom_event_callback(event_type_str, content_dict); return
        # :474  if event.type != EventType.ROOM_MESSAGE: return
        # :485-488 drop own virtual users / bot ; :491-494 drop m.replace
    def _get_intent(self, mxid: str) -> IntentAPI                         # :526  self._appservice.intent.user(UserID(mxid))

# mautrix 0.21.1 — IntentAPI (verified via inspect.signature)
create_room(alias_localpart: str | None = None, visibility: RoomDirectoryVisibility = PRIVATE,
            preset: RoomCreatePreset = PRIVATE, name: str | None = None, topic: str | None = None,
            is_direct: bool = False, invitees: list[UserID] | None = None,
            initial_state: list[StateEvent | dict] | None = None, ...) -> RoomID
leave_room(room_id: RoomID, reason: str | None = None, ...) -> None
send_state_event(room_id: RoomID, event_type: EventType, content: StateEventContent | dict, state_key: str = "") -> EventID
get_state_event(room_id, event_type, state_key="")
add_room_alias(room_id: RoomID, alias_localpart: str, override: bool = False) -> None
RoomCreatePreset: PRIVATE="private_chat", TRUSTED_PRIVATE="trusted_private_chat", PUBLIC="public_chat"
```

### Does NOT Exist
- ~~`MatrixAppService.create_room*`, `leave_*`, `resolve_alias`~~ — you add them.
- ~~`MatrixClientWrapper` in crew code~~ — do not use the single-user client; everything goes through intents.
- ~~routing of `m.parrot.status` / `m.parrot.agent_card`~~ — still not routed; leave as is.

---

## Implementation Notes

### Skeleton
```python
async def create_room_as_bot(
    self, *, name: Optional[str] = None, alias_localpart: Optional[str] = None,
    topic: Optional[str] = None, is_direct: bool = False, preset: str = "private_chat",
    visibility: str = "private", invitees: Optional[List[str]] = None,
    initial_state: Optional[List[dict]] = None,
) -> str:
    """Create a room as the AppService bot and return its room_id.

    ``preset`` / ``visibility`` are the Matrix string values (mapped to mautrix enums).
    Alias collisions (M_ROOM_IN_USE) raise ``ValueError`` — callers reconcile via resolve_alias().
    """
    from mautrix.types import RoomCreatePreset, RoomDirectoryVisibility, UserID
    room_id = await self.bot_intent.create_room(
        alias_localpart=alias_localpart, name=name, topic=topic, is_direct=is_direct,
        preset=RoomCreatePreset(preset), visibility=RoomDirectoryVisibility(visibility),
        invitees=[UserID(u) for u in invitees or []], initial_state=initial_state,
    )
    self.logger.info("Created room %s (alias=%s, direct=%s)", room_id, alias_localpart, is_direct)
    return str(room_id)

async def set_room_state_as_bot(self, room_id: str, event_type: str, content: dict, state_key: str = "") -> str:
    from mautrix.types import EventType, RoomID
    et = EventType.find(event_type, t_class=EventType.Class.STATE)
    return str(await self.bot_intent.send_state_event(RoomID(room_id), et, content, state_key=state_key))

async def get_room_state_as_bot(self, room_id: str, event_type: str, state_key: str = "") -> Optional[dict]: ...
async def resolve_alias(self, alias: str) -> Optional[str]:
    """'#name:server' → room_id, or None. Use self.bot_intent.get_room_alias(...) (verify attr; fallback: HTTP /directory/room/{alias})."""
async def leave_as_agent(self, agent_name: str, room_id: str, reason: Optional[str] = None) -> None:
    intent = self._get_intent(self._registered_agents[agent_name]); await intent.leave_room(RoomID(room_id), reason=reason)
```

### `_handle_event` change
```python
_CUSTOM_ROUTED = (ParrotEventType.TASK, ParrotEventType.RESULT, ParrotEventType.FEEDBACK)
if event_type_str in _CUSTOM_ROUTED:
    if self._custom_event_callback:
        await self._custom_event_callback(event_type_str, content_dict, str(event.room_id), str(event.sender))
    return
```
and in `set_custom_event_callback`:
```python
params = inspect.signature(callback).parameters
if len(params) <= 2:   # legacy HybridDelegator.on_custom_event(event_type, content)
    async def _adapter(event_type, content, room_id, sender): await callback(event_type, content)
    self._custom_event_callback = _adapter
else:
    self._custom_event_callback = callback
```

### Key Constraints
- Own-virtual-user filter must NOT apply to custom events (tunnel events are sent by virtual users) — keep the early `return` before the sender check, as today.
- Mock `bot_intent` with `AsyncMock` in tests (pattern: `tests/test_matrix_appservice.py`).

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_appservice_rooms.py packages/ai-parrot-integrations/tests/test_matrix_appservice.py packages/ai-parrot-integrations/tests/test_matrix_delegation.py -v` passes
- [ ] `HybridDelegator.on_custom_event` (2-arg) still receives TASK/RESULT via the adapter
- [ ] `m.parrot.feedback` is delivered to the callback with `room_id` and `sender`

---

## Test Specification

```python
# tests/test_matrix_appservice_rooms.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.integrations.matrix.appservice import MatrixAppService
from parrot.integrations.matrix.models import MatrixAppServiceConfig
from parrot.integrations.matrix.events import ParrotEventType

@pytest.fixture
def svc():
    s = MatrixAppService(MatrixAppServiceConfig(as_token="a", hs_token="h"))
    s._appservice = MagicMock(); s._appservice.intent = AsyncMock()
    s._appservice.intent.create_room.return_value = "!new:parrot.local"
    s._appservice.intent.send_state_event.return_value = "$state"
    s._registered_agents = {"analyst": "@parrot-analyst:parrot.local"}
    return s

async def test_create_room_as_bot_forwards_args(svc):
    rid = await svc.create_room_as_bot(name="general", alias_localpart="general", preset="public_chat", visibility="public", invitees=["@x:parrot.local"])
    assert rid == "!new:parrot.local"
    kw = svc._appservice.intent.create_room.call_args.kwargs
    assert kw["alias_localpart"] == "general" and str(kw["preset"].value) == "public_chat" and kw["invitees"] == ["@x:parrot.local"]

async def test_set_room_state_as_bot(svc):
    assert await svc.set_room_state_as_bot("!r:s", ParrotEventType.CHANNEL, {"name": "g"}) == "$state"

async def test_leave_as_agent(svc):
    intent = AsyncMock(); svc._appservice.intent.user = MagicMock(return_value=intent)
    await svc.leave_as_agent("analyst", "!r:s"); intent.leave_room.assert_awaited_once()

def _evt(etype, sender="@parrot-analyst:parrot.local", room="!t:s", content=None):
    e = MagicMock(); e.type = etype; e.sender = sender; e.room_id = room; e.content = content or {"task_id": "1"}; return e

async def test_feedback_routed_with_room_and_sender(svc):
    cb = AsyncMock(); svc.set_custom_event_callback(cb)
    await svc._handle_event(_evt(ParrotEventType.FEEDBACK))
    cb.assert_awaited_once_with(ParrotEventType.FEEDBACK, {"task_id": "1"}, "!t:s", "@parrot-analyst:parrot.local")

async def test_legacy_two_arg_callback_adapted(svc):
    seen = []
    async def legacy(event_type, content): seen.append((event_type, content))
    svc.set_custom_event_callback(legacy)
    await svc._handle_event(_evt(ParrotEventType.TASK))
    assert seen == [(ParrotEventType.TASK, {"task_id": "1"})]
```

---

## Agent Instructions

Same as TASK-2478 (read spec, verify contract, implement, test, move file, update index, completion note).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
