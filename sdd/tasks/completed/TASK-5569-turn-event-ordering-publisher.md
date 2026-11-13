# TASK-5569: Turn event, emitter-owned ordering field, `TurnPresentation` and `BusTurnPublisher`

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 2)
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / §2 "Piece 1" and "Piece 3". This task adds the vocabulary the rest of FEAT-886 builds on:

- `TurnCompletedEvent` — the payload type of one saved, raw, pre-normalization turn.
- `ConversationTurn.sequence` — the emitter-owned monotonic ordering field (G4).
- `parrot.memory.persistence` — `TurnPresentation` (built from the round's `AIMessage`), the `TurnPublisher`
  protocol, `BusTurnPublisher` (turns an event into one bus envelope with `event_id == turn_id`) and the two topic names.

It is a leaf: TASK-5573 (`ChatStorageTurn`), TASK-5581 (turn bus), TASK-5583 (bot integration) and TASK-5580
(hydration, `ConversationTurn.sequence`) all import from here. The event is published to the turn bus ONLY — it is
never passed to `EventRegistry.emit()` because it carries conversation content.

---

## Scope

- Add `TurnCompletedEvent(LifecycleEvent)` to `parrot/core/events/lifecycle/events/memory.py`.
- Add `ConversationTurn.sequence: Optional[int] = None`, round-tripping through `to_dict()` / `from_dict()`
  (a legacy dict without the key loads with `None`).
- Create `parrot/memory/persistence.py` with `TURN_COMPLETED_TOPIC`, `CONVERSATION_DELETED_TOPIC`, `TurnPresentation`
  (+ `from_ai_message`), `TurnPublisher` (Protocol) and `BusTurnPublisher`.
- Export the new public names from `parrot/memory/__init__.py`.
- Write `test_turn_persistence_event.py` covering `test_turn_sequence_round_trip`, `test_presentation_from_ai_message`,
  `test_publisher_envelope_shape`.

**NOT in scope**: stamping `timestamp` / `sequence` in `save_conversation_turn`, building the event from a live turn,
calling the publisher (TASK-5583); the bus itself and subscriptions (TASK-5581); `ChatStorageTurn` (TASK-5573);
`SequenceAllocator` / `install_history` in `memory/abstract.py` (TASK-5580, which edits the same file later);
exporting `TurnCompletedEvent` from `parrot/core/events/lifecycle/events/__init__.py` (that file is not in this task's table —
import it from `parrot.core.events.lifecycle.events.memory`); changing the `ConversationTurn.timestamp` default factory.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py` | MODIFY | add `TurnCompletedEvent` |
| `packages/ai-parrot/src/parrot/memory/abstract.py` | MODIFY | `ConversationTurn.sequence` + (de)serialization |
| `packages/ai-parrot/src/parrot/memory/persistence.py` | CREATE | topics, `TurnPresentation`, `TurnPublisher`, `BusTurnPublisher` |
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY | export the new names |
| `packages/ai-parrot/tests/unit/memory/test_turn_persistence_event.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`).

### Verified Imports
```python
from dataclasses import dataclass, field                              # verified: core/events/lifecycle/events/memory.py:9 (dataclass); stdlib
from navigator_eventbus.lifecycle.base import LifecycleEvent          # verified: core/events/lifecycle/events/memory.py:10
from parrot.core.events.lifecycle import TraceContext                 # verified: bots/abstract.py:128 (used for TurnCompletedEvent(trace_context=...) in tests)
from parrot.core.events.lifecycle.events.memory import TurnCompletedEvent   # NEW — created by THIS task
from parrot.memory import ConversationTurn                            # verified: memory/__init__.py:3
from parrot.models.responses import AIMessage                         # verified: models/responses.py:94
from parrot.models.basic import CompletionUsage                       # verified: models/basic.py:48 (also re-exported by parrot.models.responses, see tests/unit/bots/test_bot_history_wiring.py:21)
from navigator_eventbus import EventBus                               # verified: navigator_eventbus/__init__.py:27 (>=0.4.0 — see drift note)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py
@dataclass(frozen=True)
class Stage2CompactionNeededEvent(LifecycleEvent):                    # :14   (1 occurrence)
    agent_name: str = ""; session_id: str = ""; history_estimate: int = 0; ...

# navigator_eventbus/lifecycle/base.py
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext          # REQUIRED, no default
    event_id: str = <uuid4 factory>; timestamp: datetime = <utc now>; source_type: str = ""; source_name: str = ""
    def to_dict(self) -> dict[str, Any]  # strict json.dumps validation; adds "event_class"

# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass
class ConversationTurn:                                                # :102  (1 occurrence of `class ConversationTurn:`)
    ...; norm_version: Optional[str] = None                            # :132  last field today
    def to_dict(self) -> Dict[str, Any]                                # :134  last key `"norm_version": self.norm_version,` (:151)
    @classmethod
    def from_dict(cls, data) -> "ConversationTurn"                     # :155  last kwarg `norm_version=data.get("norm_version"),` (:174)
    timestamp: datetime = field(default_factory=datetime.now)          # :109  NAIVE local time — leave unchanged here

# navigator_eventbus (>=0.4.0)   evb.py
class EventBus:
    async def emit(self, event_type: str, payload: Dict[str, Any], **kwargs) -> int   # kwargs forwarded to Event(...)
class Event:  event_type, payload, event_id=<uuid4>, timestamp, source=None, priority, correlation_id=None, metadata
    # envelope conversion keeps event_id:  converters.from_legacy_event  (event_id=event.event_id)
EventBus.subscribe(pattern, handler: Callable[[Event], Any], *, priority=0, filter_fn=None, min_severity=None) -> str
EventBus.close()

# packages/ai-parrot/src/parrot/models/responses.py  — AIMessage fields used by TurnPresentation
output: Any; response: Optional[str]; data: Optional[Any]; code: Optional[str]; model: str; provider: str
usage: CompletionUsage (.model_dump(), .estimated_cost: Optional[float] — models/basic.py:91)
source_documents: Optional[List[SourceDocument]]   # SourceDocument.to_dict() — responses.py:32/51
# handler reference for the field mapping (current degraded path):   packages/ai-parrot-server/src/parrot/handlers/agent.py:2813-2849
#   output=ai_message.response or str(ai_message.output); code=str(ai_message.code) if ai_message.code else None;
#   sources=[s if isinstance(s, dict) else s.to_dict() for s in getattr(ai_message, "source_documents", [])]
```

### Does NOT Exist
- ~~`TurnCompletedEvent`~~, ~~`parrot.memory.persistence`~~, ~~`TurnPresentation`~~, ~~`TurnPublisher`~~, ~~`BusTurnPublisher`~~ — created by THIS task.
- ~~`ConversationTurn.sequence`~~ — added here.
- ~~`TurnCompletedEvent` exported from `parrot.core.events.lifecycle.events`~~ — `events/__init__.py:41` imports only `Stage2CompactionNeededEvent`; not edited here.
- ~~`AIMessage.sources`~~ / ~~`AIMessage.cost`~~ — the fields are `source_documents` and `usage.estimated_cost`.
- ~~`EventBus.publish(envelope)`~~ taking an `EventEnvelope` — `EventBus.publish` takes a legacy `Event`; envelopes go to `BusCore.publish`. Use `EventBus.emit(..., event_id=...)`.
- ~~A `sequence` guarantee in the bus~~ — the bus stream id is not the ordering key; the turn's own `timestamp`/`sequence` are.

**Drift to report (not blocking)**: the checked-out `packages/ai-parrot` venv (`.venv/lib/python3.11/site-packages`) has
`navigator_eventbus 0.3.0`, whereas the spec and `packages/ai-parrot/pyproject.toml:201` require `>=0.4.0`
(`EventBus(transport=...)`, `outbox=`). `test_publisher_envelope_shape` needs `transport="memory"`; run it in an environment
synced to the pin (`uv sync`), or the test must `pytest.importorskip` on the version — see the FILL IN below.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/persistence.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/memory/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/memory/test_turn_persistence_event.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py#Stage2CompactionNeededEvent",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn.to_dict",
    "sym:packages/ai-parrot/src/parrot/memory/abstract.py#ConversationTurn.from_dict",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `TurnCompletedEvent` is `@dataclass(frozen=True)`, all fields JSON-serializable (`LifecycleEvent.to_dict()` validates strictly).
- `persistence.py` must not import the heavy bus or `parrot.bots` at module level: `parrot.memory` is documented
  import-cycle free (`memory/abstract.py:21-23`). Import `TurnCompletedEvent` and `AIMessage` under `TYPE_CHECKING` only;
  `BusTurnPublisher` only needs `event.to_dict()`.
- `TurnPresentation.from_ai_message` NEVER raises on a missing attribute: use `getattr(..., None)`; absent → `None`.
- `BusTurnPublisher.publish` is the only place that touches the bus; it raises only when the bus/outbox rejects the write
  (spec skeleton). It does not swallow — the bot (TASK-5583) logs at ERROR and keeps the round alive.
- Timestamps: this task adds none. `sequence` is `Optional[int]`, `None` on legacy turns.
- Pydantic v2 for `TurnPresentation` (spec §7); Google-style docstrings; `self.logger` where a class holds one.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/abstract.py:134-176` — `to_dict`/`from_dict` pattern (tolerant `data.get`).
- `packages/ai-parrot/src/parrot/observability/fanout.py:90-120` — how this repo builds/uses an `EventBus` (pattern for TASK-5581, not needed here).
- `packages/ai-parrot/tests/roost/test_codec_bus.py:114-135` — real `EventBus(transport="memory")` + `asyncio.Event` + `wait_for` test pattern.

---

## Implementation Blueprint

### Steps (in order)
1. Add `sequence` to `ConversationTurn` and its (de)serialization — *why*: the one field every other task imports.
2. Add `TurnCompletedEvent` — *why*: `persistence.py` and tests reference it.
3. Create `persistence.py` — *why*: depends on neither of the above at import time.
4. Export names in `memory/__init__.py` — *why*: downstream tasks import from `parrot.memory`.
5. Write the tests; mutation-check each — *why*: spec AC (round-trip, mapping, envelope identity).

### `packages/ai-parrot/src/parrot/memory/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    norm_version: Optional\[str\] = None' packages/ai-parrot/src/parrot/memory/abstract.py)
# AFTER — insert below the `norm_version: Optional[str] = None` field of ConversationTurn (abstract.py:132), still inside the dataclass:
    #: Emitter-owned monotonic sequence within ``(agent, user, session)`` (FEAT-886).
    #: ``None`` on legacy turns. Round-trips through ``to_dict()``/``from_dict()``;
    #: ``from_dict()`` tolerates its absence.
    sequence: Optional[int] = None
```
```python
# occurrences: 1 (verified: grep -c '            "norm_version": self.norm_version,' packages/ai-parrot/src/parrot/memory/abstract.py)
# AFTER — insert below `"norm_version": self.norm_version,` (abstract.py:151), inside ConversationTurn.to_dict():
            "sequence": self.sequence,
```
```python
# occurrences: 1 (verified: grep -c '            norm_version=data.get("norm_version"),' packages/ai-parrot/src/parrot/memory/abstract.py)
# AFTER — insert below `norm_version=data.get("norm_version"),` (abstract.py:174), inside ConversationTurn.from_dict():
            sequence=data.get("sequence"),
```
**Why**: `sequence` is the LAST dataclass field with a default, so no positional call site changes. `grep -c 'norm_version: Optional\[str\] = None'`
must be 1 inside `ConversationTurn` — re-run it (other classes in `compaction/models.py` are different files). TASK-5580 later edits
`ConversationMemory` in this same file; do not touch it.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/memory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from dataclasses import dataclass' memory.py)  -> REPLACE with:
from dataclasses import dataclass, field
from typing import Any, Dict

# APPEND at the end of the file (after Stage2CompactionNeededEvent, memory.py:14-37):
@dataclass(frozen=True)
class TurnCompletedEvent(LifecycleEvent):
    """One saved conversation turn, raw and pre-normalization (FEAT-886).

    Published to the turn bus only; never passed to ``EventRegistry.emit()`` —
    the payload contains conversation content and must not reach the
    observability fan-out.

    Attributes:
        agent_name: The agent NAME — the ChatStorage key.
        chatbot_id: The bot's ``memory_key_id`` (explicit ``chatbot_id`` or the name).
        user_id: Owner of the conversation.
        session_id: Conversation session.
        turn: ``ConversationTurn.to_dict()`` taken BEFORE ``add_turn`` normalization.
        presentation: ``TurnPresentation.model_dump()`` (output, usage, tenant, ...).
    """

    agent_name: str = ""
    chatbot_id: str = ""
    user_id: str = ""
    session_id: str = ""
    turn: Dict[str, Any] = field(default_factory=dict)
    presentation: Dict[str, Any] = field(default_factory=dict)
```
**Why**: frozen dataclass subclass of the lifecycle base, same shape as `Stage2CompactionNeededEvent`; the base's
required `trace_context` stays first. Update the module docstring's "Covers:" paragraph with one sentence for the turn event.

### `packages/ai-parrot/src/parrot/memory/persistence.py` (CREATE)
```python
"""Turn persistence vocabulary: topics, presentation model, publisher (FEAT-886).

The bot hands the RAW turn plus a :class:`TurnPresentation` to an optional
:class:`TurnPublisher`; ChatStorage subscribes on the other side of the bus.
This module holds no bus lifecycle — see ``parrot.storage.turn_bus``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only; keeps parrot.memory import-cycle free
    from parrot.core.events.lifecycle.events.memory import TurnCompletedEvent
    from parrot.models.responses import AIMessage

TURN_COMPLETED_TOPIC: str = "conversation.turn.completed"
CONVERSATION_DELETED_TOPIC: str = "conversation.deleted"


class TurnPresentation(BaseModel):
    """Presentation and usage fields the bot derives from the round's ``AIMessage``."""

    output: Any = None
    output_mode: Optional[str] = None
    data: Any = None
    code: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    response_time_ms: Optional[int] = None
    tenant: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    cost_usd: Optional[float] = None

    @classmethod
    def from_ai_message(
        cls,
        response: "AIMessage",
        *,
        output_mode: Optional[str],
        response_time_ms: Optional[int],
        tenant: Optional[str],
    ) -> "TurnPresentation":
        """Build from a round's ``AIMessage``. Never raises on a missing attribute; absent → ``None``.

        Args:
            response: The round's final ``AIMessage``.
            output_mode: The resolved output mode (string value), if any.
            response_time_ms: The bot's own elapsed time for the round.
            tenant: The bound request tenant (``current_tenant.get()``).

        Returns:
            A populated presentation; every field the message lacks is ``None`` / ``[]``.
        """
        # FILL IN: field mapping — bounded by the AIMessage fields in the Codebase Contract and by the handler's
        #   current mapping (handlers/agent.py:2813-2849):
        #     output  = getattr(response, "response", None) or str(getattr(response, "output", ""))  (None if both absent)
        #     data    = getattr(response, "data", None)
        #     code    = str(code) if code else None
        #     sources = [s if isinstance(s, dict) else s.to_dict() for s in (getattr(response, "source_documents", None) or [])]
        #     model/provider = getattr(..., None)
        #     usage   = usage.model_dump() when usage is not None else None;  cost_usd = usage.estimated_cost
        #   AC: test_presentation_from_ai_message.
        raise NotImplementedError


@runtime_checkable
class TurnPublisher(Protocol):
    """Hands one completed turn to the turn bus."""

    async def publish(self, event: "TurnCompletedEvent") -> None:
        """Hand the event to the bus. Raises only when the outbox rejects the write."""
        ...


class BusTurnPublisher:
    """``TurnPublisher`` over a ``navigator_eventbus.EventBus``."""

    def __init__(self, bus: Any) -> None:
        """Wrap ``bus`` (an ``EventBus``; duck-typed on ``emit``)."""
        self._bus = bus

    async def publish(self, event: "TurnCompletedEvent") -> None:
        """Emit one envelope on :data:`TURN_COMPLETED_TOPIC` with ``event_id == turn_id``.

        Args:
            event: The completed-turn event; ``event.turn["turn_id"]`` becomes the envelope id.

        Raises:
            KeyError: If the turn dict carries no ``turn_id``.
            Exception: Whatever the bus raises when the outbox rejects the write — never swallowed.
        """
        # FILL IN: await self._bus.emit(TURN_COMPLETED_TOPIC, event.to_dict(), event_id=event.turn["turn_id"],
        #   source=<event.agent_name or None>) — bounded by spec §3 M2 ("event_id == turn_id": the at-least-once
        #   dedup key) and the verified EventBus.emit(event_type, payload, **kwargs) signature. Do NOT call
        #   EventRegistry.emit and do NOT build an EventEnvelope by hand (EventBus.emit converts it keeping event_id).
        raise NotImplementedError
```
**Why this shape**: signatures and names are fixed by spec §3 M2. `event_id == turn_id` is what lets the subscriber and the
Streams relay deduplicate at-least-once delivery. The payload is `event.to_dict()` (JSON-validated, includes `turn` and
`presentation`).

### `packages/ai-parrot/src/parrot/memory/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .file import FileConversationMemory' packages/ai-parrot/src/parrot/memory/__init__.py)
# AFTER — insert below `from .file import FileConversationMemory` (__init__.py:20). Do NOT anchor on the `.render` import line (TASK-5572 owns it):
from .persistence import (
    CONVERSATION_DELETED_TOPIC,
    TURN_COMPLETED_TOPIC,
    BusTurnPublisher,
    TurnPresentation,
    TurnPublisher,
)

# __all__ (alphabetical, one entry each) — insert using these single-occurrence anchors:
#   `"AnswerMemory",`   (occurrences: 1)  -> add after it:  "BusTurnPublisher",   (check ordering vs "BrainStore")
#   `"ConversationTurn",` (occurrences: 1) -> add after it:  "CONVERSATION_DELETED_TOPIC",
#   `"TokenCount",`     (occurrences: 1)  -> add after it:  "TURN_COMPLETED_TOPIC",
#   `"TurnState",`      (occurrences: 1)  -> add before it: "TurnPresentation", "TurnPublisher",
# FILL IN: exact __all__ placement — keep the list's existing rough alphabetical order; verify with
#   `python -c "import parrot.memory as m; print(m.TurnPresentation, m.BusTurnPublisher)"` and that no name is duplicated.
```
**Why**: `parrot.memory` is the documented public surface (`memory/__init__.py:3-27`). The persistence module has no eager
heavy imports, so this stays import-cycle free.

### `packages/ai-parrot/tests/unit/memory/test_turn_persistence_event.py` (CREATE)
```python
"""FEAT-886 M2 — sequence round-trip, presentation mapping, publisher envelope."""
from __future__ import annotations

import asyncio

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events.memory import TurnCompletedEvent
from parrot.memory import ConversationTurn
from parrot.memory.persistence import (
    TURN_COMPLETED_TOPIC,
    BusTurnPublisher,
    TurnPresentation,
)
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage


def test_turn_sequence_round_trip():
    """``sequence`` survives to_dict/from_dict; a legacy dict (no key) loads with None."""
    # FILL IN: ConversationTurn(..., sequence=7).to_dict() -> from_dict -> .sequence == 7;
    #   drop the "sequence" key from the dict -> from_dict(...).sequence is None. Bounded by AC-1.
    #   Mutation: remove `sequence=data.get("sequence")` from from_dict -> RED.


def test_presentation_from_ai_message():
    """All mapped fields populate; attributes the message lacks become None / []."""
    # FILL IN: AIMessage(input=..., output=..., response=..., data=..., code=..., model=..., provider=...,
    #   usage=CompletionUsage(prompt_tokens=3, completion_tokens=5, estimated_cost=0.42), source_documents=[...])
    #   -> TurnPresentation.from_ai_message(msg, output_mode="default", response_time_ms=120, tenant="acme");
    #   assert every field, cost_usd == 0.42, usage dict == msg.usage.model_dump(). Then a bare AIMessage
    #   (no data/code/sources) -> those fields are None / []. Bounded by AC-2.


async def test_publisher_envelope_shape():
    """Topic, event_id == turn_id and the RAW turn reach a real in-memory bus subscriber."""
    # FILL IN: from navigator_eventbus import EventBus; bus = EventBus(transport="memory"); received = []; delivered = asyncio.Event();
    #   async handler(event): received.append(event); delivered.set(); bus.subscribe(TURN_COMPLETED_TOPIC, handler);
    #   build TurnCompletedEvent(trace_context=TraceContext.new_root(), agent_name="agent-a", chatbot_id="bot-uuid",
    #   user_id="u", session_id="s", turn=ConversationTurn(...).to_dict(), presentation=TurnPresentation(...).model_dump());
    #   await BusTurnPublisher(bus).publish(event); await asyncio.wait_for(delivered.wait(), timeout=1);
    #   assert received[0].event_type == TURN_COMPLETED_TOPIC and received[0].event_id == turn.turn_id
    #   and received[0].payload["turn"]["user_message"] == <the raw, un-normalized text>; finally await bus.close().
    #   If the installed navigator_eventbus is < 0.4.0 (the repo .venv has 0.3.0), skip with a reason naming the pin
    #   (packages/ai-parrot/pyproject.toml:201) — never fake the bus. Bounded by AC-3 and R6 (real bus, no Mock).
    #   Mutation: publish with the default event_id instead of turn_id -> the id assert goes RED.
```
**Why this shape**: real `EventBus(transport="memory")` (same retry/DLQ core, no Redis — spec §4 fixtures `memory_bus`);
no `Mock` buses.

### FILL IN checklist
- [ ] `persistence.py::TurnPresentation.from_ai_message` — field mapping; bounded by AC-2 and the Codebase Contract.
- [ ] `persistence.py::BusTurnPublisher.publish` — the `emit(...)` call with `event_id=turn_id`; bounded by AC-3.
- [ ] `memory/__init__.py` `__all__` placement; bounded by "no duplicates, import works".
- [ ] The three test bodies; bounded by AC-1..AC-3 and the mutation checks.

---

## Acceptance Criteria

- [ ] AC-1: `sequence` round-trips through `to_dict`/`from_dict`; legacy dicts without it load (`None`) — `test_turn_sequence_round_trip` (spec §4 M2).
- [ ] AC-2: every `TurnPresentation` field maps from an `AIMessage`; absent attributes become `None` (sources `[]`) and nothing raises — `test_presentation_from_ai_message`.
- [ ] AC-3: `BusTurnPublisher.publish` emits on `conversation.turn.completed` with `event_id == turn_id` and carries the raw (pre-normalization) turn — `test_publisher_envelope_shape`.
- [ ] `from parrot.memory import TurnPresentation, TurnPublisher, BusTurnPublisher, TURN_COMPLETED_TOPIC, CONVERSATION_DELETED_TOPIC` works; `import parrot.memory` stays free of `parrot.bots` / `parrot.models` imports at module level (check: `python -c "import sys, parrot.memory; assert 'parrot.bots' not in sys.modules"`).
- [ ] Mutation checks (note evidence in the Completion Note): (1) drop `sequence` from `from_dict` → AC-1 test RED; (2) drop `cost_usd` mapping → AC-2 test RED; (3) emit with default `event_id` → AC-3 test RED.
- [ ] Existing `tests/unit/memory/` suites (`test_conversation_turn_attribution.py`, `test_render_history.py`) still pass — adding a trailing dataclass field must not break positional construction.
- [ ] `ruff check` clean on all five files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/memory/test_turn_persistence_event.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/test_conversation_turn_attribution.py -q`
- `pytest packages/ai-parrot/tests/unit/memory/test_render_history.py -q`

---

## Test Specification

Spec §4 rows for M2 (fixtures written inside the test file):

```python
def test_turn_sequence_round_trip(): ...        # sequence survives to_dict/from_dict; legacy dicts load
def test_presentation_from_ai_message(): ...    # all fields map; absent attributes become None
async def test_publisher_envelope_shape(): ...  # topic, event_id == turn_id, raw pre-normalization turn
```
Fixture: a real `EventBus(transport="memory")` (spec §4 `memory_bus`), closed in `finally`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run every `grep -c`; confirm the installed `navigator_eventbus` version before running the publisher test
5. **Update status** in `sdd/tasks/index/durable-conversation-memory.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria — run the Validation Commands and the mutation checks
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5569 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Added TurnCompletedEvent, ConversationTurn.sequence (round-trips), memory/persistence.py (topics, TurnPresentation.from_ai_message, TurnPublisher, BusTurnPublisher) and exports.

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-12
**Tests**: new file 3 passed (real EventBus(transport="memory"), navigator-eventbus 0.4.1); test_conversation_turn_attribution + test_render_history pass (36 total); ruff clean on new/changed files. tests/unit/memory/compaction/test_compact.py and test_normalize.py error at collection (`hypothesis` not installed in the venv) — pre-existing, verified identical with my changes stashed; NOT run.
**Mutation evidence**: sequence dropped from from_dict -> RED; cost_usd dropped -> RED; event_id default instead of turn_id -> RED. Restored by re-applying the edit.

**Deviations from spec**: none. `import parrot.memory` still pulls parrot.models transitively (pre-existing via compaction), parrot.bots not imported.
