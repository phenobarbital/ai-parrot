# TASK-4727: Matrix carrier and room-state blackboard over m.parrot.* events (M12a)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4719, TASK-4720
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 12** (carrier + blackboard half). Matrix is one carrier among four, chosen when humans
share the channel (spec L9). Resolved: the namespace stays `m.parrot.*`; the human-readable `body` is **mandatory**
(FEAT-195's rejection of Matrix pub/sub as the *primary* path is respected by making this opt-in per registry entry).
Room state events are the blackboard — one `m.parrot.blackboard` state event per key (`state_key=<key>`), replaced,
never appended; `m.relates_to` carries `in_reply_to`. Content on Matrix is JSON (humans read it).

---

## Scope

- Add `ROOST`/`BLACKBOARD` to `ParrotEventType` and `RoostEventContent` / `BlackboardStateContent` models to `events.py`.
- Create `parrot/integrations/matrix/roost/{__init__,carrier,blackboard}.py`.
- Write `tests/test_matrix_roost_carrier.py` and `tests/test_matrix_roost_blackboard.py` with a mocked `MatrixClientWrapper` (no homeserver).

**NOT in scope**: `ask_agent` subsumption (TASK-4728); the live L-S6 gate (TASK-4730); AppService changes

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` | MODIFY | Event types + two content models |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/__init__.py` | CREATE | Exports MatrixCarrier, MatrixBlackboard |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/carrier.py` | CREATE | MatrixCarrier |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/blackboard.py` | CREATE | MatrixBlackboard |
| `packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py` | CREATE | Carrier tests |
| `packages/ai-parrot-integrations/tests/test_matrix_roost_blackboard.py` | CREATE | Blackboard tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.integrations.matrix.events import ParrotEventType            # verified: matrix/events.py:27
from parrot.integrations.matrix.client import MatrixClientWrapper        # verified: matrix/client.py:32 (TYPE_CHECKING only)
from parrot.roost.carriers.base import Carrier, Inbound                  # TASK-4720
from parrot.roost.blackboard import Blackboard, BlackboardEntry, KeyACL, StaleWriteError, WriterPolicy   # TASK-4719
from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage
from parrot.roost.performatives import CarrierKind, InteractionProtocol, Performative
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py  (imports: datetime; Any, Dict, List, Optional; BaseModel, Field)
class ParrotEventType:                                   # line 27
    TUNNEL = "m.parrot.tunnel"                           # line 41 — anchor
class ChannelStateContent(BaseModel): ... version: int = 1   # line 269 — replace-not-append precedent
class TunnelStateContent(BaseModel):                     # line 283 — anchor (insert new models BEFORE it)
# packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py
class MatrixClientWrapper:                               # line 32
    async def send_event(self, room_id: str, event_type: str, content: Dict[str, Any]) -> str              # line 193
    async def set_room_state(self, room_id: str, event_type: str, content: Dict[str, Any], state_key: str = "") -> str  # 217
    async def get_room_state_event(self, room_id: str, event_type: str, state_key: str = "") -> Optional[Dict[str, Any]]  # 244
    def on_custom_event(self, event_type: str, callback: Callable[..., Coroutine[Any, Any, None]]) -> None  # line 289

# parrot/roost/messages.py (TASK-4711)
class AgentAddress(BaseModel): name: str; carrier: CarrierKind = IN_PROCESS; endpoint: Optional[str] = None
class RoostMessage(BaseModel):
    message_id; performative; protocol; conversation_id; in_reply_to; sender: AgentAddress; receivers: list[AgentAddress]
    capability_filter: Optional[str]; content: Any; content_type: Optional[str]; body: Optional[str]; envelope: Any
    failure: Optional[FailureInfo]; permission_context: Any; auth_token: Optional[str]; created_at: datetime
    def reply(self, performative, *, content=None, body=None, failure=None) -> RoostMessage
    def is_addressed_to(self, name: str) -> bool
    def trace_id(self) -> Optional[str]
```

### Does NOT Exist
- ~~`ai.parrot.*` namespace — the namespace is `m.parrot.*`~~
- ~~`m.parrot.roost`, `m.parrot.blackboard`, `RoostEventContent`, `BlackboardStateContent` — created here~~
- ~~an `off_custom_event` / handler-removal API on `MatrixClientWrapper` — absent; `unsubscribe` flips a local flag the callback checks~~
- ~~starting a homeserver in unit tests — mock `MatrixClientWrapper`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/carrier.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/blackboard.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/test_matrix_roost_blackboard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py#ParrotEventType",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py#TunnelStateContent",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py#MatrixClientWrapper"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `RoostEventContent.body: str` has no default — Pydantic rejects a missing body (AC-25).
- `to_content`: content as `model_dump(mode='json')` for models, raw for JSON values, else the handle id in `content_ref` (a non-JSON, non-handle object ⇒ `ValueError`); `envelope` as the envelope's fields dict; add `m.relates_to: {'m.in_reply_to': {'event_id': ...}}` when the in_reply_to maps to a known Matrix event id (keep a bounded message_id → event_id dict).
- Default `render`: `f"[{performative}] {sender} → {receivers or capability_filter}: {short content}"`.
- `MatrixBlackboard.put`: read the state event, compare its `version` to `expected_version`, then `set_room_state(room_id, BLACKBOARD, content, state_key=key)`; StaleWriteError on mismatch; then `_notify`. A per-key asyncio.Lock serialises local writers (cross-process races are bounded by the read-compare-set window — document it).
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py:269-293` — state content shape
- `packages/ai-parrot-integrations/tests/test_matrix_swarm_events.py` — model test style
- `packages/ai-parrot-integrations/tests/test_matrix_tunnel.py` — how MatrixClientWrapper / AppService are mocked

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Edit `events.py` (two constants + two models).
2. Write carrier and blackboard.
3. Write tests with `AsyncMock` clients: round trip, mandatory body, relates_to, state replace + stale refusal.

### `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    TUNNEL = "m.parrot.tunnel"' matrix/events.py)
# AFTER — insert below `    TUNNEL = "m.parrot.tunnel"` (verified: matrix/events.py:41)
    ROOST = "m.parrot.roost"  # FEAT-747: Roost message event (typed envelope + mandatory human body)
    BLACKBOARD = "m.parrot.blackboard"  # FEAT-747: state event, state_key = blackboard key

# occurrences: 1 (verified: grep -c 'class TunnelStateContent(BaseModel):' matrix/events.py)
# BEFORE — insert above `class TunnelStateContent(BaseModel):` (verified: matrix/events.py:283)
class RoostEventContent(BaseModel):
    """Content of m.parrot.roost. ``body`` is mandatory (humans read it); ``envelope`` holds the envelope fields."""

    body: str
    performative: str
    protocol: str
    conversation_id: str
    message_id: str
    in_reply_to: Optional[str] = None
    sender: str
    receivers: List[str] = Field(default_factory=list)
    capability_filter: Optional[str] = None
    content: Optional[Any] = None
    content_ref: Optional[str] = None
    envelope: Dict[str, Any] = Field(default_factory=dict)
    failure: Optional[Dict[str, Any]] = None


class BlackboardStateContent(BaseModel):
    """Content of m.parrot.blackboard (``state_key`` = key). Replaced, never accumulated."""

    key: str
    value: Any
    version: int
    writer: str
    acl: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime
    provenance: Dict[str, Any] = Field(default_factory=dict)
```
**Why**: `content: Optional[Any]` (spec said Dict) because a JSON scalar result is legal; all names are fixed by spec M12.

### `packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/carrier.py` (CREATE)
```python
"""Matrix carrier for Roost (FEAT-747 M12). One carrier among four; body is mandatory."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence

from parrot.roost.carriers.base import Carrier, Inbound
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import CarrierKind

from ..events import ParrotEventType, RoostEventContent

if TYPE_CHECKING:
    from ..client import MatrixClientWrapper


class MatrixCarrier(Carrier):
    kind = CarrierKind.MATRIX

    def __init__(self, client: "MatrixClientWrapper", *, room_id: str, agent_name: str,
                 render: Optional[Callable[[RoostMessage], str]] = None) -> None:
        self.logger = logging.getLogger(__name__)
        self._client, self._room_id, self._agent_name = client, room_id, agent_name
        self._render = render or self._default_render
        self._subs: dict[str, tuple[AgentAddress, Inbound, tuple[str, ...], bool]] = {}
        self._event_ids: dict[str, str] = {}   # message_id -> Matrix event_id (bounded, FILL IN eviction)

    async def send(self, msg: RoostMessage) -> None:
        raise NotImplementedError  # FILL IN — to_content + client.send_event(room_id, ParrotEventType.ROOST, ...)

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        raise NotImplementedError  # FILL IN — client.on_custom_event(ROOST, cb); cb filters receivers/capabilities

    async def unsubscribe(self, subscription_id: str) -> bool:
        raise NotImplementedError  # FILL IN — flip the active flag (no removal API exists)

    async def close(self) -> None:
        self._subs.clear()

    @staticmethod
    def _default_render(msg: RoostMessage) -> str:
        raise NotImplementedError  # FILL IN — Key Constraints bullet 3

    @staticmethod
    def to_content(msg: RoostMessage, *, body: str) -> RoostEventContent:
        raise NotImplementedError  # FILL IN — bullet 2

    @staticmethod
    def from_content(content: Dict[str, Any], *, event_id: str) -> RoostMessage:
        raise NotImplementedError  # FILL IN — LocalEnvelope from content["envelope"]
```
**Why**: Mirrors the core Carrier contract; `MatrixBlackboard` (blackboard.py) follows the same pattern over `set_room_state`/`get_room_state_event` with the CAS rule in Key Constraints bullet 4, and `roost/__init__.py` simply re-exports both classes.

### FILL IN checklist
- [ ] carrier method bodies
- [ ] `blackboard.py` (`MatrixBlackboard(Blackboard)`: get/put/keys)
- [ ] `roost/__init__.py` exports
- [ ] both test files

---

## Acceptance Criteria

- [ ] `RoostEventContent` without `body` fails validation
- [ ] to_content/from_content round trip keeps every field
- [ ] A reply carries `m.relates_to.m.in_reply_to` when the original event id is known
- [ ] Blackboard put replaces the state event and bumps `version`; a stale version raises `StaleWriteError`
- [ ] Existing Matrix event/swarm tests stay green
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/__init__.py packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/carrier.py packages/ai-parrot-integrations/src/parrot/integrations/matrix/roost/blackboard.py packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py packages/ai-parrot-integrations/tests/test_matrix_roost_blackboard.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_carrier.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_roost_blackboard.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_matrix_swarm_events.py -q`

---

## Test Specification

```python
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from parrot.integrations.matrix.events import ParrotEventType, RoostEventContent
from parrot.integrations.matrix.roost import MatrixCarrier
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P


def test_body_mandatory():
    with pytest.raises(ValidationError):
        RoostEventContent(performative="inform", protocol="inform", conversation_id="c", message_id="m", sender="a")


async def test_send_uses_roost_event():
    client = MagicMock(); client.send_event = AsyncMock(return_value="$ev1")
    car = MatrixCarrier(client, room_id="!r", agent_name="a")
    await car.send(RoostMessage(performative=P.INFORM, protocol=IP.INFORM, conversation_id="c",
                                sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], content={"x": 1}))
    room, etype, content = client.send_event.await_args.args
    assert etype == ParrotEventType.ROOST and content["body"]
# FILL IN: from_content round trip, relates_to, MatrixBlackboard replace + stale (test_matrix_roost_blackboard.py)
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4727 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

