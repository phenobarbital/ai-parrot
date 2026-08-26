# TASK-2480: Channel Manager (+ optional Space)

**Feature**: FEAT-463 — Matrix Agents Swarm
**Spec**: `sdd/specs/matrix-agents-swarm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2478, TASK-2479
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Materialises `MatrixCrewConfig.channels` into rooms with alias, join rule,
membership and `m.parrot.channel` state; resolves `room_id ↔ ChannelConfig` for the
transport (TASK-2484); optionally creates a Matrix Space and links channels/tunnels as
children (`space.enabled: false` by default — resolved brainstorm decision).

---

## Scope

- Create `crew/channels.py` with `ChannelManager`.
- `ensure_channels()`: for each `ChannelConfig` — use `room_id` if set, else
  `resolve_alias("#<name>:<server>")`, else `create_room_as_bot(...)` with preset/visibility
  from `visibility` (`public` → `public_chat`/`public`; `private` → `private_chat`/`private`);
  invite+join member agents via `ensure_agent_in_room`; publish `ChannelStateContent`
  (reconcile: if existing state differs, overwrite and `logger.warning`).
- `ensure_space()` / `link_to_space(room_id)`: when `space.enabled`, create/resolve the
  Space room (`creation_content={"type": "m.space"}` via `initial_state`-free path:
  pass `creation_content` through a new kwarg on `create_room_as_bot` — add it) and write
  `m.space.child` on the space + `m.space.parent` on the child.
- Lookup helpers: `channel_for_room`, `room_for_channel`, `is_member`, `list_channels()`.
- Tests with mocked `MatrixAppService`.

**NOT in scope**: tunnels (TASK-2481), transport dispatch (TASK-2484).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/channels.py` | CREATE | `ChannelManager` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py` | MODIFY | add `creation_content` kwarg to `create_room_as_bot` |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/__init__.py` | MODIFY | export `ChannelManager` |
| `packages/ai-parrot-integrations/tests/test_matrix_channels.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.config import ChannelConfig, MatrixCrewConfig, SpaceConfig   # TASK-2478
from parrot.integrations.matrix.events import ChannelStateContent, ParrotEventType                 # TASK-2478
from parrot.integrations.matrix.appservice import MatrixAppService                                 # appservice.py:36
```

### Existing Signatures to Use
```python
# appservice.py (existing + TASK-2479)
async def ensure_agent_in_room(self, agent_name: str, room_id: str) -> None                  # :196
async def create_room_as_bot(self, *, name=None, alias_localpart=None, topic=None, is_direct=False,
                             preset="private_chat", visibility="private", invitees=None, initial_state=None) -> str   # TASK-2479
async def set_room_state_as_bot(self, room_id: str, event_type: str, content: dict, state_key: str = "") -> str     # TASK-2479
async def get_room_state_as_bot(self, room_id: str, event_type: str, state_key: str = "") -> Optional[dict]        # TASK-2479
async def resolve_alias(self, alias: str) -> Optional[str]                                                          # TASK-2479
# crew/config.py
class MatrixCrewConfig: server_name: str; agents: Dict[str, MatrixCrewAgentEntry]; channels; space   # :139 (+TASK-2478)
class ChannelConfig: name, visibility, agents, answer_policy, room_id, topic                           # TASK-2478
```
Matrix spec facts (no code): Space rooms are created with `creation_content: {"type": "m.space"}`;
child link = state `m.space.child` on the space with `state_key=<child_room_id>` and content
`{"via": [server_name]}`; parent link = `m.space.parent` on the child with `state_key=<space_id>`.

### Does NOT Exist
- ~~`ChannelManager`~~ — you create it.
- ~~any existing room-topology code~~ — `MatrixCrewTransport.start()` only joins `general_room_id` and per-agent `dedicated_room_id` (`transport.py:154/:165`); do not touch it here.
- ~~`m.space.*` helpers in mautrix wrapper~~ — write plain state dicts.

---

## Implementation Notes

### Skeleton
```python
class ChannelManager:
    """Materialise declared channels as Matrix rooms and resolve room ↔ channel."""

    def __init__(self, config: MatrixCrewConfig, appservice: MatrixAppService) -> None:
        self._config, self._as = config, appservice
        self._room_by_name: Dict[str, str] = {}
        self._channel_by_room: Dict[str, ChannelConfig] = {}
        self._space_id: Optional[str] = None
        self.logger = logging.getLogger("parrot.matrix.channels")

    async def ensure_channels(self) -> Dict[str, str]:
        if self._config.space.enabled:
            await self.ensure_space()
        for ch in self._config.channels:
            room_id = ch.room_id or await self._as.resolve_alias(self.alias_for(ch.name))
            if room_id is None:
                public = ch.visibility == "public"
                room_id = await self._as.create_room_as_bot(
                    name=ch.name, alias_localpart=ch.name, topic=ch.topic,
                    preset="public_chat" if public else "private_chat",
                    visibility="public" if public else "private",
                    initial_state=[{"type": ParrotEventType.CHANNEL, "state_key": "",
                                    "content": self._state(ch).model_dump()}])
            else:
                await self._reconcile_state(room_id, ch)
            for agent in ch.agents:
                await self._as.ensure_agent_in_room(agent, room_id)
            self._room_by_name[ch.name] = room_id; self._channel_by_room[room_id] = ch
            if self._space_id: await self.link_to_space(room_id)
        return dict(self._room_by_name)

    def alias_for(self, name: str) -> str: return f"#{name}:{self._config.server_name}"
    def channel_for_room(self, room_id: str) -> Optional[ChannelConfig]: return self._channel_by_room.get(room_id)
    def room_for_channel(self, name: str) -> Optional[str]: return self._room_by_name.get(name)
    def is_member(self, agent_name: str, channel: str) -> bool: ...
    def list_channels(self) -> List[dict]: ...   # [{name, visibility, answer_policy, agents, room_id}]
    async def ensure_space(self) -> Optional[str]: ...
    async def link_to_space(self, room_id: str) -> None: ...
```

### Key Constraints
- Idempotent: running `ensure_channels()` twice must not create rooms twice (alias resolution first).
- Never delete or leave rooms here.
- `answer_policy` is stored in room state so external tooling can read it, but the transport reads it from config (source of truth).

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot-integrations/tests/test_matrix_channels.py -v` passes
- [ ] Rooms created only when neither `room_id` nor alias resolves; alias/preset/visibility match `visibility`
- [ ] Existing rooms get reconciled `m.parrot.channel` state with a warning when it differs
- [ ] `space.enabled=True` → space created once and every channel linked via `m.space.child` + `m.space.parent`
- [ ] `space.enabled=False` (default) → no space calls at all

---

## Test Specification

```python
# tests/test_matrix_channels.py
import pytest
from unittest.mock import AsyncMock
from parrot.integrations.matrix.crew.channels import ChannelManager
from parrot.integrations.matrix.crew.config import ChannelConfig, CollaborativeConfig, MatrixCrewAgentEntry, MatrixCrewConfig, SpaceConfig
from parrot.integrations.matrix.events import ParrotEventType

def _cfg(**over):
    agents = {n: MatrixCrewAgentEntry(chatbot_id=n, display_name=n, mxid_localpart=f"parrot-{n}") for n in ("analyst", "writer")}
    base = dict(homeserver_url="http://hs", server_name="parrot.local", as_token="a", hs_token="h",
                bot_mxid="@parrot:parrot.local", general_room_id="!gen:parrot.local", agents=agents,
                collaborative=CollaborativeConfig(),
                channels=[ChannelConfig(name="general", agents=["analyst", "writer"], answer_policy="swarm"),
                          ChannelConfig(name="finance", visibility="private", agents=["analyst"], room_id="!fin:parrot.local")])
    base.update(over); return MatrixCrewConfig(**base)

@pytest.fixture
def svc():
    s = AsyncMock(); s.resolve_alias.return_value = None; s.create_room_as_bot.return_value = "!gen-new:parrot.local"
    s.get_room_state_as_bot.return_value = None; return s

async def test_creates_missing_and_reuses_existing(svc):
    cm = ChannelManager(_cfg(), svc); rooms = await cm.ensure_channels()
    svc.create_room_as_bot.assert_awaited_once()
    kw = svc.create_room_as_bot.call_args.kwargs
    assert kw["alias_localpart"] == "general" and kw["preset"] == "public_chat" and kw["visibility"] == "public"
    assert rooms == {"general": "!gen-new:parrot.local", "finance": "!fin:parrot.local"}
    assert svc.ensure_agent_in_room.await_count == 3
    assert cm.channel_for_room("!fin:parrot.local").answer_policy == "mention"

async def test_alias_resolution_prevents_duplicate(svc):
    svc.resolve_alias.return_value = "!gen-old:parrot.local"
    cm = ChannelManager(_cfg(), svc); await cm.ensure_channels()
    svc.create_room_as_bot.assert_not_awaited()

async def test_reconcile_existing_state_warns(svc, caplog):
    svc.get_room_state_as_bot.return_value = {"name": "finance", "visibility": "public", "answer_policy": "swarm", "agents": [], "version": 1}
    cm = ChannelManager(_cfg(), svc); await cm.ensure_channels()
    assert any(c.args and c.args[1] == ParrotEventType.CHANNEL for c in svc.set_room_state_as_bot.await_args_list)
    assert "reconcil" in caplog.text.lower()

async def test_space_links_children(svc):
    svc.create_room_as_bot.side_effect = ["!space:parrot.local", "!gen-new:parrot.local"]
    cm = ChannelManager(_cfg(space=SpaceConfig(enabled=True)), svc); await cm.ensure_channels()
    types = [c.args[1] for c in svc.set_room_state_as_bot.await_args_list]
    assert types.count("m.space.child") == 2 and types.count("m.space.parent") == 2

async def test_no_space_by_default(svc):
    cm = ChannelManager(_cfg(), svc); await cm.ensure_channels()
    assert all(c.args[1] != "m.space.child" for c in svc.set_room_state_as_bot.await_args_list)
```

---

## Agent Instructions

Same as TASK-2478.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Created `crew/channels.py` with `ChannelManager` per the
skeleton: `ensure_channels()` resolves `room_id` → alias → creates a new
room (initial `m.parrot.channel` state on creation, reconciled state with
a `logger.warning` for pre-existing rooms), joins member agents, and links
to the optional Space. Added `ensure_space()` / `link_to_space()` writing
`m.space.child` (on the Space, keyed by child room id) / `m.space.parent`
(on the child, keyed by the Space id). Added `creation_content` kwarg to
`MatrixAppService.create_room_as_bot` (passed through to
`IntentAPI.create_room`) so the Space room can be created with
`{"type": "m.space"}`. Exported `ChannelManager` from `crew/__init__.py`.
5/5 new tests pass; full matrix regression 197/203 pass (6 pre-existing
`test_matrix_hook.py` failures unrelated to this task, confirmed via
`git stash` baseline in TASK-2478). `ruff check` shows only pre-existing
baseline lint categories, no new ones.
**Deviations from spec**: none
