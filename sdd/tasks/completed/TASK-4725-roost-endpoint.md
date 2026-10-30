# TASK-4725: RoostEndpoint — inbound dispatch loop, outbound protocol helpers, find_and_mount (M11b)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-4716, TASK-4718, TASK-4719, TASK-4720, TASK-4723, TASK-4724
**Assigned-to**: unassigned

---

## Context

Implements the endpoint of spec §3 **Module 11**: the runtime unit per agent that composes engine, dispatcher,
carriers, blackboard, ledger and the agent's `ToolManager`. Inbound: carrier → dispatcher → execute the decision
(`execute_tool(permission_context=resolve_authority(msg))` for RUN_TOOL, `store_result(..., data_type='auto')` for
STORE, the `wake` callback for WAKE_LLM, a fixed-price `propose` for BID_FROM_CONTRACT). Outbound: `send`, `inform`,
`request`, `query`, `cfp`, `subscribe`, `cancel`. Harness-side `find_and_mount` = grant-filtered
`find_capability` → `squawk_bridge.mount_capabilities` (planner pre-mount, no LLM turn).

---

## Scope

- Create `parrot/roost/endpoint.py` with `WakeCallback`, `RoostFailure`, `RoostEndpoint`.
- Write `tests/roost/test_endpoint.py` (two endpoints on one `InProcessCarrier`, stub ToolManager / WorkingMemory with `AsyncMock`).

**NOT in scope**: the LLM-facing toolkit and AgentTool (TASK-4726); Matrix wiring (TASK-4727/4728); the L-S gates (TASK-4729)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/endpoint.py` | CREATE | RoostEndpoint |
| `packages/ai-parrot/tests/roost/test_endpoint.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage
from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from parrot.roost.protocols import ConversationBudget, ProtocolEngine, TerminalState, Transition   # TASK-4713
from parrot.roost.scoring import Award, BidScorer                                                  # TASK-4712
from parrot.roost.gating import Dispatch, DispatchDecision, GatingDispatcher, Handler, HandlerRegistry   # TASK-4718
from parrot.roost.grant import GrantDenied, GrantPolicy                                            # TASK-4717
from parrot.roost.directory import RoostAgentConfig                                                # TASK-4715
from parrot.roost.blackboard import Blackboard                                                     # TASK-4719
from parrot.roost.carriers.base import Carrier, Undeliverable                                      # TASK-4720
from parrot.roost.audit import RoostAuditLedger                                                    # TASK-4723
from parrot.roost import squawk_bridge                                                             # TASK-4724
# TYPE_CHECKING only:
from parrot.tools.manager import ToolManager                         # verified: tools/manager.py:289
from parrot.tools.working_memory.tool import WorkingMemoryToolkit    # verified: tools/working_memory/tool.py:47
from parrot.registry import AgentRegistry                            # verified: registry/__init__.py:2
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional["PermissionContext"] = None,
                       *, return_tool_result: bool = False) -> Any        # line 1787 — PBACToolCallGuardrail is the first guard
def get_tool(self, tool_name: str) -> Optional[Any]                       # line 1392
# packages/ai-parrot/src/parrot/tools/working_memory/tool.py
async def store_result(self, key: str, data: Any, data_type: str = "auto", description: str = "",
                       metadata: Optional[dict] = None, turn_id: Optional[str] = None) -> dict   # line 374
# parrot/registry/registry.py (after TASK-4716)
def find_capability(self, query: str, *, caller: Optional[str] = None, limit: int = 5, include_remote: bool = True) -> List[CapabilityMatch]
# parrot/roost/gating.py (TASK-4718): GatingDispatcher.dispatch(msg, *, hops=0) -> Dispatch(decision, transition, emit, handler)
# parrot/roost/protocols.py (TASK-4713): ProtocolEngine.open/accept/charge/expire/award/close/state
# parrot/roost/squawk_bridge.py (TASK-4724): new_envelope(...), mount_capabilities(tm, matches), resolve_authority(msg)
# parrot/roost/audit.py (TASK-4723): await RoostAuditLedger.record(msg, direction=..., self_name=...)
# parrot/roost/blackboard.py (TASK-4719): Blackboard.subscribe(key, cb, *, subscriber_name) ; WriterPolicy.record_request_closed(name)
```

### Does NOT Exist
- ~~`tool._execute` direct calls — always `ToolManager.execute_tool` (PBAC first guard)~~
- ~~a `RoostEndpoint` on `AbstractBot` today — this task does not modify `AbstractBot`; bots opt in by setting `bot.roost_endpoint = RoostEndpoint(...)` (read by TASK-4726)~~
- ~~`squawk_bridge` symbols beyond the six listed~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/endpoint.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_endpoint.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit.store_result"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Carrier selection on send: the receiver's `AgentAddress.carrier` picks from `carriers`; a missing carrier ⇒ `Undeliverable`. Broadcasts go to every configured carrier.
- Every outbound message is audited `received`-side (sender's ledger) and every inbound one `served`-side, including `not_understood` replies (AC-27).
- `request()` opens a Request conversation, awaits an `asyncio.Future` keyed by conversation_id resolved by the inbound loop on INFORM (result = `content`) or rejected with `RoostFailure` on refuse/failure/timeout; `timeout` defaults to `envelope.budget_ms`. A deterministic serving side replies agree then inform.
- RUN_TOOL: tool name = the cap_id's mounted tool name (`cap_id.replace('.', '_')` unless the content carries `tool`); parameters = `msg.content` dict; result goes back as INFORM `content` **by reference** (AC-18).
- WAKE_LLM: call `wake(msg, dispatch)`; if it returns a message, send it; charge `engine.charge(cid, tokens)` with `tokens` from the returned message's `content_type == 'usage'`-free heuristic: FILL IN using the wake callback's optional `.tokens` attribute; default 0.
- STORE: `working_memory.store_result(key=f'roost:{msg.conversation_id}:{msg.message_id}', data=msg.content, data_type='auto', metadata={'performative': ..., 'sender': ...})` when a WorkingMemory is bound; a handler from the dispatch is awaited first.
- On a Request reaching INFORMED, call `blackboard.policy.record_request_closed(self.agent_name)` when a blackboard is bound (digest ownership, resolved).
- `find_and_mount` raises nothing when the satellite is missing (returns `[]`); `GrantDenied` only if the caller itself has no grant config at all AND `grant.default_deny` — no: return `[]` (find_capability is already fail-closed). Keep it total.
- `metrics`: counters messages_in, messages_out, wakes, not_understood, stored.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §3 M11 endpoint skeleton (authoritative signatures)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write constructor/start/stop/address and the inbound `_on_message` dispatch executor.
2. Write `send` then the protocol helpers on top of it.
3. Write `find_and_mount`, `register_handler`, `metrics`.
4. Tests: request round trip returns the native object; refuse ⇒ RoostFailure; addressed inform wakes once; broadcast inform stored; find_and_mount degrades to [].

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (CREATE)
```python
"""RoostEndpoint — one per agent instance (FEAT-747 M11)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, Optional, Sequence

from . import squawk_bridge
from .audit import RoostAuditLedger
from .blackboard import Blackboard
from .carriers.base import Carrier, Undeliverable
from .directory import RoostAgentConfig
from .gating import Dispatch, DispatchDecision, GatingDispatcher, Handler, HandlerRegistry
from .grant import GrantPolicy
from .messages import AgentAddress, FailureInfo, RoostMessage
from .performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from .protocols import ProtocolEngine, TerminalState
from .scoring import Award, BidScorer

if TYPE_CHECKING:
    from parrot.registry import AgentRegistry
    from parrot.tools.manager import ToolManager
    from parrot.tools.working_memory.tool import WorkingMemoryToolkit

WakeCallback = Callable[[RoostMessage, Dispatch], Awaitable[Optional[RoostMessage]]]


class RoostFailure(Exception):
    def __init__(self, failure: FailureInfo) -> None:
        super().__init__(f"{failure.code.value}: {failure.detail}")
        self.failure = failure


class RoostEndpoint:
    def __init__(self, *, agent_name: str, config: Optional[RoostAgentConfig], engine: ProtocolEngine,
                 dispatcher: GatingDispatcher, carriers: Mapping[CarrierKind, Carrier], tool_manager: "ToolManager",
                 blackboard: Optional[Blackboard] = None, ledger: Optional[RoostAuditLedger] = None,
                 working_memory: Optional["WorkingMemoryToolkit"] = None, wake: Optional[WakeCallback] = None,
                 registry: Optional["AgentRegistry"] = None, grant: Optional[GrantPolicy] = None) -> None:
        self.logger = logging.getLogger(__name__)
        self.agent_name, self.config, self.engine, self.dispatcher = agent_name, config, engine, dispatcher
        self.carriers, self.tool_manager, self.blackboard = dict(carriers), tool_manager, blackboard
        self.ledger = ledger or RoostAuditLedger()
        self.working_memory, self.wake, self.registry = working_memory, wake, registry
        self.grant = grant or GrantPolicy()
        self._pending: dict[str, asyncio.Future] = {}
        self._subs: list[tuple[Carrier, str]] = []
        self._metrics = {"messages_in": 0, "messages_out": 0, "wakes": 0, "not_understood": 0, "stored": 0}

    def address(self) -> AgentAddress:
        carrier = self.config.carrier if self.config else CarrierKind.IN_PROCESS
        return AgentAddress(name=self.agent_name, carrier=carrier)

    async def start(self) -> None:
        """Subscribe this endpoint's address (and capabilities) on every carrier."""
        raise NotImplementedError  # FILL IN

    async def stop(self) -> None:
        raise NotImplementedError  # FILL IN — unsubscribe, cancel pending futures with CANCELLED

    async def _on_message(self, msg: RoostMessage) -> None:
        """Inbound: audit served, dispatch, execute the decision (Key Constraints 4-7)."""
        raise NotImplementedError  # FILL IN
```
**Why**: Constructor signature is spec M11 verbatim; `_on_message` is private and owns every decision branch.

### `packages/ai-parrot/src/parrot/roost/endpoint.py` (CREATE (continued, same file))
```python
    async def send(self, performative: Performative, *, receivers: Sequence[AgentAddress] = (),
                   capability_filter: Optional[str] = None, content: Any = None,
                   protocol: Optional[InteractionProtocol] = None, conversation_id: Optional[str] = None,
                   in_reply_to: Optional[str] = None, body: Optional[str] = None, envelope: Any = None) -> RoostMessage:
        """Build, audit (received-side), route by receiver carrier and deliver. Raises GrantDenied / Undeliverable."""
        raise NotImplementedError  # FILL IN — Key Constraints 1-2; envelope default squawk_bridge.new_envelope(...)

    async def inform(self, *, receivers: Sequence[AgentAddress] = (), capability_filter: Optional[str] = None,
                     content: Any, body: Optional[str] = None) -> RoostMessage:
        return await self.send(Performative.INFORM, receivers=receivers, capability_filter=capability_filter,
                               content=content, protocol=InteractionProtocol.INFORM, body=body)

    async def request(self, cap_id: str, args: Mapping[str, Any], *, timeout: Optional[float] = None,
                      receiver: Optional[AgentAddress] = None) -> Any:
        """Request protocol end to end; returns the native result; raises RoostFailure."""
        raise NotImplementedError  # FILL IN — Key Constraint 3 (receiver None ⇒ registry.find_capability(cap_id, caller=self))

    async def query(self, question: Any, *, receiver: AgentAddress, timeout: Optional[float] = None,
                    expected_schema: Optional[dict] = None) -> Any:
        raise NotImplementedError  # FILL IN — like request without agree

    async def cfp(self, *, capability_filter: str, task: Any, bid_window_ms: int = 500,
                  scorer: Optional[BidScorer] = None) -> Award:
        raise NotImplementedError  # FILL IN — broadcast cfp, wait window, engine.award, send accept/reject

    async def subscribe(self, *, blackboard_key: Optional[str] = None, capability_filter: Optional[str] = None,
                        handler: Optional[Handler] = None) -> str:
        raise NotImplementedError  # FILL IN — blackboard key ⇒ Blackboard.subscribe; else a Subscribe conversation

    async def cancel(self, conversation_id: str, *, reason: str = "") -> None:
        raise NotImplementedError  # FILL IN — engine.close(CANCELLED) + fail the pending future

    def register_handler(self, content_type: str, handler: Handler, *, needs_decision: bool = False) -> None:
        self.dispatcher.handlers.register(content_type, handler, needs_decision=needs_decision)

    async def find_and_mount(self, query: str, *, limit: int = 5) -> list[str]:
        """registry.find_capability(query, caller=self.agent_name) → squawk_bridge.mount_capabilities ([] w/o satellite)."""
        if self.registry is None:
            return []
        matches = self.registry.find_capability(query, caller=self.agent_name, limit=limit)
        return await squawk_bridge.mount_capabilities(self.tool_manager, matches)

    @property
    def metrics(self) -> dict[str, int]:
        return dict(self._metrics)
```
**Why**: Public methods are spec M11 verbatim; `find_and_mount` is complete because it is pure composition.

### FILL IN checklist
- [ ] start/stop/_on_message
- [ ] send
- [ ] request/query/cfp/subscribe/cancel
- [ ] tests

---

## Acceptance Criteria

- [ ] Request between two in-process endpoints returns the serving tool's object itself (identity, AC-18)
- [ ] Refuse/failure/timeout raise `RoostFailure` with the typed code
- [ ] Every message produces one audit entry per side
- [ ] RUN_TOOL goes through `ToolManager.execute_tool` with `permission_context=resolve_authority(msg)`
- [ ] `find_and_mount` returns `[]` without the satellite
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/endpoint.py packages/ai-parrot/tests/roost/test_endpoint.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_endpoint.py -q`

---

## Test Specification

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint, RoostFailure
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress
from parrot.roost.performatives import CarrierKind
from parrot.roost.protocols import ProtocolEngine


def make_endpoint(name, carrier, cfg=None, tool_result=None):
    tm = MagicMock(); tm.execute_tool = AsyncMock(return_value=tool_result)
    eng = ProtocolEngine()
    disp = GatingDispatcher(self_name=name, config=cfg, engine=eng, handlers=HandlerRegistry(), grant=GrantPolicy())
    return RoostEndpoint(agent_name=name, config=cfg, engine=eng, dispatcher=disp,
                         carriers={CarrierKind.IN_PROCESS: carrier}, tool_manager=tm)


async def test_request_returns_native_object():
    carrier, result = InProcessCarrier(), {"salary": 100}
    hr = make_endpoint("hr", carrier, RoostAgentConfig(capabilities=["hr.people.salary"], backing="deterministic"),
                       tool_result=result)
    a = make_endpoint("a", carrier)
    await hr.start(); await a.start()
    out = await a.request("hr.people.salary", {"employee_id": "E-17"}, receiver=AgentAddress(name="hr"), timeout=2)
    assert out is result
# FILL IN: refuse ⇒ RoostFailure, addressed inform wakes once, broadcast stored, audit per side, find_and_mount []
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4725 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Delivered by engine; merge-tier green.
Seat: gpt-5.6-terra (codex) · Attempts: 1

**Deviations from spec**: none
