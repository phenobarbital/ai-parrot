# TASK-4718: Gating dispatcher — addressing, protocol state, decision-needed without an LLM (M5)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4713, TASK-4717
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5**: the three questions per inbound message, in order and without an LLM — *is
this for me*, *does the protocol state accept it*, *does handling it need a decision*. This is the cost driver
the brainstorm attacks (spec G3, gate L-S1). Resolved decisions folded in: a directly addressed `inform` wakes
the receiver; a broadcast/capability-filtered `inform` is stored and wakes only when a registered handler with
`needs_decision=True` matches; a `cfp` on a fixed-price capability bids from contract annotations without a wake.

---

## Scope

- Create `parrot/roost/gating.py`: `DispatchDecision`, `Handler`, `HandlerRegistry`, `Dispatch`, `GatingDispatcher.addressed/dispatch/wakes`.
- Write `tests/roost/test_gating.py`.

**NOT in scope**: executing the decision (running tools, storing, waking — TASK-4725); sending replies

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/gating.py` | CREATE | Dispatcher |
| `packages/ai-parrot/tests/roost/test_gating.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.roost.messages import RoostMessage                          # TASK-4711
from parrot.roost.performatives import Performative                     # TASK-4711
from parrot.roost.protocols import ProtocolEngine, Transition           # TASK-4713
from parrot.roost.directory import RoostAgentConfig                     # TASK-4715
from parrot.roost.grant import GrantPolicy                              # TASK-4717
```

### Existing Signatures to Use
```python
# parrot/roost/messages.py (TASK-4711)
class AgentAddress(BaseModel): name: str; carrier: CarrierKind = IN_PROCESS; endpoint: Optional[str] = None
class RoostMessage(BaseModel):
    message_id; performative; protocol; conversation_id; in_reply_to; sender: AgentAddress; receivers: list[AgentAddress]
    capability_filter: Optional[str]; content: Any; content_type: Optional[str]; body: Optional[str]; envelope: Any
    failure: Optional[FailureInfo]; permission_context: Any; auth_token: Optional[str]; created_at: datetime
    def reply(self, performative, *, content=None, body=None, failure=None) -> RoostMessage
    def is_addressed_to(self, name: str) -> bool
    def trace_id(self) -> Optional[str]

# parrot/roost/protocols.py (TASK-4713)
class ProtocolEngine:
    def open(self, opener: RoostMessage, *, budget=None) -> ConversationState
    def accept(self, msg: RoostMessage, *, hops: int = 0) -> Transition   # kind: accepted | not_understood | closed
    def state(self, conversation_id: str) -> Optional[ConversationState]
```

### Does NOT Exist
- ~~an LLM call or embedding call in this module — forbidden (spec G3)~~
- ~~`GatingDispatcher` executing tools — it only decides; the endpoint executes~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/gating.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_gating.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Step 1 addressing: `msg.is_addressed_to(self_name)` ⇒ addressed; else `capability_filter` fnmatch-es one of `config.capabilities` ⇒ addressed-by-capability; else `IGNORE` (no engine call, no wake).
- Step 2 state: openers (`request`, `query`, `cfp`, `subscribe`, `inform`) ⇒ `engine.open(msg)` when the conversation is unknown; replies ⇒ `engine.accept(msg, hops=hops)`. `not_understood` ⇒ `NOT_UNDERSTOOD` with the transition's `emit`; `closed` ⇒ `CLOSED`.
- Step 3 decision: request/query → `RUN_TOOL` when `config.backing == 'deterministic'`, else `WAKE_LLM`; inform → `WAKE_LLM` if directly addressed, else handler lookup (`needs_decision` ⇒ `WAKE_LLM`, else `STORE`, none ⇒ `STORE`); cfp → `BID_FROM_CONTRACT` when `config.bid` is set, else `WAKE_LLM`; failure → `REPLAN`; agree/refuse/propose/accept/reject/subscribe/not_understood → engine bookkeeping only (`STORE` of nothing: use `DispatchDecision.STORE` with `handler=None`) — never a wake (AC-6).
- `wakes` counts only `WAKE_LLM` and `REPLAN` decisions (L-S1 metric).
- `HandlerRegistry.resolve`: exact `content_type` first, then `'*'`.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §2 Overview 'GatingDispatcher' paragraph
- brainstorm 'Gating and dispatch' steps 1-5

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write enums/registry/models.
2. Implement `addressed` and `dispatch` as one pure method.
3. Write tests.

### `packages/ai-parrot/src/parrot/roost/gating.py` (CREATE)
```python
"""LLM-free gating: who wakes, decided by performative + addressee + protocol state (FEAT-747 M5)."""
from __future__ import annotations

import fnmatch
import logging
from enum import Enum
from typing import Any, Awaitable, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .directory import RoostAgentConfig
from .grant import GrantPolicy
from .messages import RoostMessage
from .performatives import Performative
from .protocols import ProtocolEngine, Transition


class DispatchDecision(str, Enum):
    IGNORE = "ignore"; NOT_UNDERSTOOD = "not_understood"; RUN_TOOL = "run_tool"; STORE = "store"
    WAKE_LLM = "wake_llm"; BID_FROM_CONTRACT = "bid_from_contract"; REPLAN = "replan"; CLOSED = "closed"


class Handler(Protocol):
    def __call__(self, msg: RoostMessage) -> Awaitable[Optional[Any]]: ...


class HandlerRegistry:
    """Handlers keyed by ``content_type`` (dotted class name or media type; ``"*"`` wildcard)."""

    def __init__(self) -> None:
        self._handlers: dict[str, tuple[Handler, bool]] = {}

    def register(self, content_type: str, handler: Handler, *, needs_decision: bool = False) -> None:
        self._handlers[content_type] = (handler, needs_decision)

    def resolve(self, content_type: Optional[str]) -> Optional[tuple[Handler, bool]]:
        return self._handlers.get(content_type or "") or self._handlers.get("*")


class Dispatch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    decision: DispatchDecision
    transition: Optional[Transition] = None
    emit: list[RoostMessage] = Field(default_factory=list)
    handler: Any = None


class GatingDispatcher:
    def __init__(self, *, self_name: str, config: Optional[RoostAgentConfig], engine: ProtocolEngine,
                 handlers: HandlerRegistry, grant: GrantPolicy) -> None:
        self.logger = logging.getLogger(__name__)
        self.self_name = self_name
        self.config = config
        self.engine = engine
        self.handlers = handlers
        self.grant = grant
        self._wakes = 0

    def addressed(self, msg: RoostMessage) -> bool:
        """Step 1: named in receivers, or capability_filter matches one of our capabilities."""
        raise NotImplementedError  # FILL IN — Key Constraints bullet 1

    def dispatch(self, msg: RoostMessage, *, hops: int = 0) -> Dispatch:
        """Steps 1–3 as one call; the endpoint executes the decision."""
        raise NotImplementedError  # FILL IN — Key Constraints bullets 2-4

    @property
    def wakes(self) -> int:
        return self._wakes
```
**Why**: Decision names are a contract with TASK-4725 (endpoint) and the L-S1 gate test; keep them verbatim.

### FILL IN checklist
- [ ] `addressed` — bullet 1
- [ ] `dispatch` — bullets 2-4, AC-6, AC-7
- [ ] tests (spec §4 M5 rows)

---

## Acceptance Criteria

- [ ] Addressed deterministic request ⇒ RUN_TOOL, zero wakes
- [ ] Addressed inform ⇒ WAKE_LLM (1 wake)
- [ ] Broadcast inform, no handler ⇒ STORE, zero wakes; handler with needs_decision ⇒ WAKE_LLM
- [ ] cfp with `config.bid` ⇒ BID_FROM_CONTRACT without a wake
- [ ] Unaddressed message ⇒ IGNORE
- [ ] Out-of-state reply ⇒ NOT_UNDERSTOOD carrying the emitted reply
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/gating.py packages/ai-parrot/tests/roost/test_gating.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_gating.py -q`

---

## Test Specification

```python
from parrot.roost.directory import RoostAgentConfig
from parrot.roost.gating import DispatchDecision as D, GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P
from parrot.roost.protocols import ProtocolEngine


def _disp(**cfg):
    return GatingDispatcher(self_name="hr", config=RoostAgentConfig(capabilities=["hr.people.salary"], **cfg),
                            engine=ProtocolEngine(), handlers=HandlerRegistry(), grant=GrantPolicy())


def _m(perf, proto, to=("hr",), cap=None, cid="c"):
    return RoostMessage(performative=perf, protocol=proto, conversation_id=cid, sender=AgentAddress(name="a"),
                        receivers=[AgentAddress(name=n) for n in to], capability_filter=cap)


def test_addressed_deterministic_request_runs_tool():
    d = _disp(backing="deterministic")
    assert d.dispatch(_m(P.REQUEST, IP.REQUEST)).decision == D.RUN_TOOL and d.wakes == 0


def test_inform_addressed_wakes_broadcast_stores():
    d = _disp()
    assert d.dispatch(_m(P.INFORM, IP.INFORM, cid="1")).decision == D.WAKE_LLM
    assert d.dispatch(_m(P.INFORM, IP.INFORM, to=(), cap="hr.*", cid="2")).decision == D.STORE
    assert d.wakes == 1


def test_unaddressed_ignored():
    assert _disp().dispatch(_m(P.INFORM, IP.INFORM, to=("x",))).decision == D.IGNORE
# FILL IN: handler needs_decision, cfp BID_FROM_CONTRACT, out-of-state NOT_UNDERSTOOD
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4718 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

