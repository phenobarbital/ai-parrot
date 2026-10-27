# TASK-4713: Protocol engine — five interaction-protocol state machines and conversation budget (M2)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4711, TASK-4712
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** `parrot/roost/protocols.py`: one deterministic state machine per
`conversation_id` (Inform, Request, Query, Contract Net, Subscribe), `ConversationBudget` enforcement and
`not_understood` for out-of-state messages. The LLM is never asked where a conversation stands (spec G2).
Machines are **pure** (no I/O, clock injected) so every transition is unit-testable without asyncio.

---

## Scope

- Create `parrot/roost/protocols.py` with `TerminalState`, `ConversationBudget`, `ConversationState`, `Transition`, `ConversationExistsError`, `ProtocolMachine` + the five machines, and `ProtocolEngine`.
- Write `tests/roost/test_protocols.py` covering every row of the spec §4 M2 unit tests.

**NOT in scope**: deciding who wakes (TASK-4718); sending messages (carriers, endpoint); the scorer itself (TASK-4712)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/protocols.py` | CREATE | State machines + engine |
| `packages/ai-parrot/tests/roost/test_protocols.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage           # created by TASK-4711
from parrot.roost.performatives import FailureCode, InteractionProtocol, Performative  # created by TASK-4711
from parrot.roost.scoring import Award, Bid, BidScorer, rank_bids                   # created by TASK-4712
```

### Existing Signatures to Use
```python
# parrot/roost/messages.py (TASK-4711)
class RoostMessage(BaseModel):
    message_id: str; performative: Performative; protocol: InteractionProtocol; conversation_id: str
    in_reply_to: Optional[str]; sender: AgentAddress; receivers: list[AgentAddress]; content: Any; envelope: Any
    def reply(self, performative, *, content=None, body=None, failure=None) -> RoostMessage  # not_understood always allowed
# parrot/roost/scoring.py (TASK-4712)
def rank_bids(bids: Sequence[Bid], scorer: Optional[BidScorer] = None, *, tie_epsilon: float = 1e-6) -> Award
```

### Does NOT Exist
- ~~`class ProtocolEngine` anywhere today — 0 hits~~
- ~~a `cancel` Performative — Subscribe/Request cancellation is `ProtocolEngine.close(..., CANCELLED)`, and on the wire a `reject` with `failure.code=CANCELLED` (no new act; the twelve are fixed)~~
- ~~reading `datetime.now()` inside a machine — the engine passes `now`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/protocols.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_protocols.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- State labels (fixed so the dispatcher and tests can reference them): Request `awaiting_agree` → `awaiting_result` → terminal; Query `awaiting_result` → terminal; Contract Net `collecting_bids` → `awarded` (then the award opens a Request with the SAME conversation_id) / NO_BIDS; Subscribe `active`; Inform: terminal DONE on open.
- `accept()` never raises on protocol errors: unknown conversation, closed conversation or an act not allowed in the current state ⇒ `Transition(kind='not_understood', emit=[msg.reply(NOT_UNDERSTOOD)])` (AC-4).
- Budget: `hops > hop_limit` ⇒ close with `failure(HOP_LIMIT)` addressed to the initiator; `charge()` past `token_budget` ⇒ `failure(TOKEN_BUDGET)`; `expire(now)` past `deadline` ⇒ `failure(TIMEOUT)` to the requester (AC-5). Deadline = open time + `envelope.budget_ms` when present.
- `award()` delegates to `rank_bids` over `state.proposals` (converted to `Bid` from `content` dict/model fields cost/time_ms/confidence) with the engine's scorer and `tie_epsilon`.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/` — flows FSM precedent
- spec §3 Module 2 skeleton (authoritative)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write models and `ProtocolMachine` ABC — *why*: machines share one `step()` contract.
2. Implement the five machines as transition tables — *why*: small dicts are easier to audit than if-chains.
3. Implement `ProtocolEngine` (state dict keyed by conversation_id, budget checks before machine step).
4. Write the tests listed in spec §4 for M2.

### `packages/ai-parrot/src/parrot/roost/protocols.py` (CREATE)
```python
"""Roost interaction protocols — pure per-conversation state machines (FEAT-747 M2)."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, ClassVar, Literal, Optional

from pydantic import BaseModel, Field

from .messages import AgentAddress, FailureInfo, RoostMessage
from .performatives import FailureCode, InteractionProtocol, Performative
from .scoring import Award, Bid, BidScorer, rank_bids

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TerminalState(str, Enum):
    DONE = "done"; INFORMED = "informed"; REFUSED = "refused"; FAILED = "failed"; CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"; AWARDED = "awarded"; NO_BIDS = "no_bids"; EXPIRED = "expired"


class ConversationExistsError(ValueError):
    """``ProtocolEngine.open`` on an id that is already open."""


class ConversationBudget(BaseModel):
    hop_limit: int = 8
    hops: int = 0
    token_budget: Optional[int] = None
    tokens_used: int = 0
    deadline: Optional[datetime] = None
    bid_window_ms: Optional[int] = None


class ConversationState(BaseModel):
    conversation_id: str
    protocol: InteractionProtocol
    initiator: AgentAddress
    state: str
    terminal: Optional[TerminalState] = None
    budget: ConversationBudget = Field(default_factory=ConversationBudget)
    last_message_id: Optional[str] = None
    proposals: list[RoostMessage] = Field(default_factory=list)
    opened_at: datetime = Field(default_factory=_utcnow)


class Transition(BaseModel):
    kind: Literal["accepted", "not_understood", "closed"]
    state: ConversationState
    obligations: tuple[Performative, ...] = ()
    emit: list[RoostMessage] = Field(default_factory=list)


class ProtocolMachine(ABC):
    """State machine for one protocol. Pure: no I/O, no clock reads."""

    protocol: ClassVar[InteractionProtocol]

    @abstractmethod
    def initial_state(self, opener: RoostMessage) -> str: ...

    @abstractmethod
    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition: ...


# FILL IN: InformMachine, RequestMachine, QueryMachine, ContractNetMachine, SubscribeMachine —
#          state labels and terminals exactly as in Key Constraints; one module-level MACHINES dict keyed by protocol
```
**Why**: Models and the ABC are fixed by the spec skeleton. The machines are left to you because their tables are fully specified in Key Constraints and the brainstorm 'Interaction protocols' table — write them as data.

### `packages/ai-parrot/src/parrot/roost/protocols.py` (CREATE (continued — engine, same file))
```python
class ProtocolEngine:
    """Owns ConversationState per conversation_id and applies the machines deterministically."""

    def __init__(self, *, default_hop_limit: int = 8, scorer: Optional[BidScorer] = None,
                 tie_epsilon: float = 1e-6, clock: Callable[[], datetime] = _utcnow) -> None:
        self.logger = logging.getLogger(__name__)
        self._states: dict[str, ConversationState] = {}
        self._default_hop_limit = default_hop_limit
        self._scorer = scorer
        self._tie_epsilon = tie_epsilon
        self._clock = clock

    def open(self, opener: RoostMessage, *, budget: Optional[ConversationBudget] = None) -> ConversationState:
        """Create state for ``opener.conversation_id``; budget defaults from ``opener.envelope``.

        Raises:
            ConversationExistsError: the id is already open.
        """
        # FILL IN: derive budget (hop_limit, token_budget, deadline=now+budget_ms) from envelope when budget is None
        raise NotImplementedError

    def accept(self, msg: RoostMessage, *, hops: int = 0) -> Transition:
        """Apply *msg*; never raises on protocol errors (unknown/closed/out-of-state ⇒ not_understood)."""
        # FILL IN: hop check first (HOP_LIMIT), then machine.step; log not_understood at INFO
        raise NotImplementedError

    def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]:
        """Consume LLM tokens; returns a closing Transition with failure(TOKEN_BUDGET) when exhausted."""
        raise NotImplementedError  # FILL IN

    def expire(self, *, now: Optional[datetime] = None) -> list[Transition]:
        """Close conversations past deadline (failure TIMEOUT to the initiator) or past the bid window (award/NO_BIDS)."""
        raise NotImplementedError  # FILL IN

    def award(self, conversation_id: str) -> Award:
        """Score collected proposals with ``rank_bids``; ``decided_by='llm'`` when the rule cannot decide."""
        raise NotImplementedError  # FILL IN

    def state(self, conversation_id: str) -> Optional[ConversationState]:
        return self._states.get(conversation_id)

    def close(self, conversation_id: str, terminal: TerminalState, *, reason: str = "") -> Transition:
        """Force a terminal state (cancel)."""
        raise NotImplementedError  # FILL IN
```
**Why**: Signatures are verbatim from spec §3 M2; `_states` is a plain dict because the engine is per endpoint and single-event-loop.

### FILL IN checklist
- [ ] five machine classes + `MACHINES` — bounded by Key Constraints / brainstorm protocol table
- [ ] `ProtocolEngine.open/accept/charge/expire/award/close` — bounded by AC-4, AC-5, AC-8
- [ ] `test_protocols.py` — every M2 row of spec §4

---

## Acceptance Criteria

- [ ] Request happy path ends INFORMED; refuse ⇒ REFUSED; failure ⇒ FAILED
- [ ] Query skips agree; `agree` on a Query ⇒ not_understood
- [ ] Any act after a terminal state ⇒ not_understood with an emitted reply
- [ ] Hop limit / token budget / deadline close with typed failures addressed to the initiator
- [ ] Contract Net awards via `rank_bids`; empty window ⇒ NO_BIDS; tie ⇒ `decided_by='llm'`
- [ ] Subscribe stays `active` across N informs and ends CANCELLED/EXPIRED
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/protocols.py packages/ai-parrot/tests/roost/test_protocols.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_protocols.py -q`

---

## Test Specification

```python
from datetime import datetime, timedelta, timezone

from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import FailureCode, InteractionProtocol as IP, Performative as P
from parrot.roost.protocols import ProtocolEngine, TerminalState


def _msg(perf, proto, cid="c1", sender="a", to="b", envelope=None, **kw):
    return RoostMessage(performative=perf, protocol=proto, conversation_id=cid, sender=AgentAddress(name=sender),
                        receivers=[AgentAddress(name=to)], envelope=envelope, **kw)


def test_request_happy_path(envelope):
    eng = ProtocolEngine()
    req = _msg(P.REQUEST, IP.REQUEST, envelope=envelope)
    eng.open(req)
    assert eng.accept(req.reply(P.AGREE)).kind == "accepted"
    t = eng.accept(req.reply(P.INFORM))
    assert t.state.terminal == TerminalState.INFORMED


def test_out_of_state_not_understood(envelope):
    eng = ProtocolEngine()
    q = _msg(P.QUERY, IP.QUERY, envelope=envelope)
    eng.open(q)
    t = eng.accept(_msg(P.AGREE, IP.QUERY, sender="b", to="a"))  # agree is not part of Query
    assert t.kind == "not_understood" and t.emit[0].performative == P.NOT_UNDERSTOOD


def test_timeout(envelope):
    now = datetime.now(timezone.utc)
    eng = ProtocolEngine(clock=lambda: now)
    eng.open(_msg(P.REQUEST, IP.REQUEST, envelope=envelope))
    closed = eng.expire(now=now + timedelta(seconds=10))
    assert closed[0].emit[0].failure.code == FailureCode.TIMEOUT

# FILL IN: hop limit, token budget, closed conversation, contract net (award / no bids / tie), subscribe
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4713 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Delivered by engine; merge-tier green.
Seat: gpt-5.6-terra (codex) · Attempts: 1

**Deviations from spec**: none
