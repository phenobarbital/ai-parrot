# TASK-4720: Carrier base and in-process carrier — asyncio queues, payloads by reference (M7)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4711
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 7**: the `Carrier` ABC every transport implements, and the in-process fast path.
Resolved U5: keep the full envelope, pass payloads by reference inside it — uniform audit, gating and protocol
state on every carrier, zero serialization in-process (AC-17). Creates `parrot/roost/carriers/__init__.py` with a
lazy export map so the shm (TASK-4721) and bus (TASK-4722) tasks never edit it.

---

## Scope

- Create `carriers/__init__.py` (lazy map: Carrier, CarrierError, Undeliverable, CarrierClosed, InProcessCarrier, SharedMemoryCarrier, ShmPayloadRef, EventBusCarrier, build_roost_bus).
- Create `carriers/base.py` and `carriers/inprocess.py`.
- Write `tests/roost/test_carriers_inprocess.py`.

**NOT in scope**: shm (TASK-4721); bus (TASK-4722); Matrix (TASK-4727)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/roost/carriers/__init__.py` | CREATE | Lazy export map |
| `packages/ai-parrot/src/parrot/roost/carriers/base.py` | CREATE | Carrier ABC + errors |
| `packages/ai-parrot/src/parrot/roost/carriers/inprocess.py` | CREATE | InProcessCarrier |
| `packages/ai-parrot/tests/roost/test_carriers_inprocess.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.roost.messages import AgentAddress, RoostMessage  # TASK-4711
from parrot.roost.performatives import CarrierKind            # TASK-4711
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
```

### Does NOT Exist
- ~~any existing agent-to-agent queue/bus carrier — 0 hits~~
- ~~copying or pickling `content` — forbidden (AC-17)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/roost/carriers/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/roost/carriers/base.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/roost/carriers/inprocess.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/roost/test_carriers_inprocess.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- One `asyncio.Queue` + one consumer task per subscribed address; `send` puts the SAME `RoostMessage` object on each receiver queue (no `model_copy`).
- Capability-filtered broadcast: deliver to every subscription whose `capabilities` contain a match for `fnmatch.fnmatchcase(cap, msg.capability_filter)`; zero recipients ⇒ `Undeliverable`.
- Addressed send to an unknown name ⇒ `Undeliverable(name)`; after `close()` ⇒ `CarrierClosed`.
- Consumer exceptions are logged and do not kill the consumer task.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- spec §3 Module 7 skeleton

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Write base + lazy `__init__`.
2. Write InProcessCarrier.
3. Tests: identity preserved, broadcast fan-out, undeliverable, close.

### `packages/ai-parrot/src/parrot/roost/carriers/base.py` (CREATE)
```python
"""Carrier contract (FEAT-747 M7). The protocol is identical on every carrier; only payload passing differs."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, ClassVar, Sequence

from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind


class CarrierError(Exception): ...
class Undeliverable(CarrierError): ...
class CarrierClosed(CarrierError): ...


Inbound = Callable[[RoostMessage], Awaitable[None]]


class Carrier(ABC):
    kind: ClassVar[CarrierKind]

    @abstractmethod
    async def send(self, msg: RoostMessage) -> None:
        """Deliver to every receiver (or every subscriber matching ``capability_filter``). Raises Undeliverable."""

    @abstractmethod
    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str: ...

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...
```
**Why**: Complete; the contract is the spec skeleton.

### `packages/ai-parrot/src/parrot/roost/carriers/inprocess.py` (CREATE)
```python
"""In-process carrier: one asyncio.Queue per address, payloads by reference (FEAT-747 M7, resolved U5)."""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import uuid
from typing import Sequence

from ..messages import AgentAddress, RoostMessage
from ..performatives import CarrierKind
from .base import Carrier, CarrierClosed, Inbound, Undeliverable


class InProcessCarrier(Carrier):
    """Shared by every RoostEndpoint in the process. Never copies ``content``."""

    kind = CarrierKind.IN_PROCESS

    def __init__(self, *, maxsize: int = 1024) -> None:
        self.logger = logging.getLogger(__name__)
        self._maxsize = maxsize
        self._subs: dict[str, tuple[AgentAddress, Inbound, tuple[str, ...], asyncio.Queue, asyncio.Task]] = {}
        self._closed = False

    async def send(self, msg: RoostMessage) -> None:
        raise NotImplementedError  # FILL IN — Key Constraints bullets 1-3

    async def subscribe(self, address: AgentAddress, inbound: Inbound, *, capabilities: Sequence[str] = ()) -> str:
        raise NotImplementedError  # FILL IN — create queue + consumer task (bullet 4)

    async def unsubscribe(self, subscription_id: str) -> bool:
        raise NotImplementedError  # FILL IN — cancel the consumer task

    async def close(self) -> None:
        raise NotImplementedError  # FILL IN

    def pending(self, name: str) -> int:
        """Queue depth for *name* (tests and the L-S1 metric)."""
        return sum(q.qsize() for addr, _, _, q, _ in self._subs.values() if addr.name == name)
```
**Why**: Same `RoostMessage` instance to every receiver is what makes L-S4 (same buffer address) hold.

### `packages/ai-parrot/src/parrot/roost/carriers/__init__.py` (CREATE)
```python
"""Roost carriers (FEAT-747). Lazy exports so optional carriers never import their dependencies eagerly."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "Carrier": "base", "CarrierError": "base", "Undeliverable": "base", "CarrierClosed": "base", "Inbound": "base",
    "InProcessCarrier": "inprocess", "SharedMemoryCarrier": "shm", "ShmPayloadRef": "shm",
    "EventBusCarrier": "bus", "build_roost_bus": "bus",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    mod = _EXPORTS.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{mod}"), name)
    globals()[name] = value
    return value
```
**Why**: Complete; names for TASK-4721/4722 are fixed here so those tasks never edit this file.

### FILL IN checklist
- [ ] `InProcessCarrier.send/subscribe/unsubscribe/close`
- [ ] tests

---

## Acceptance Criteria

- [ ] `received.content is sent.content` (identity, AC-17)
- [ ] Broadcast reaches only matching capability subscribers
- [ ] Unknown receiver ⇒ `Undeliverable`; after close ⇒ `CarrierClosed`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/roost/carriers/__init__.py packages/ai-parrot/src/parrot/roost/carriers/base.py packages/ai-parrot/src/parrot/roost/carriers/inprocess.py packages/ai-parrot/tests/roost/test_carriers_inprocess.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/roost/test_carriers_inprocess.py -q`

---

## Test Specification

```python
import asyncio

import pytest

from parrot.roost.carriers.base import Undeliverable
from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P


async def test_by_reference():
    c, got, payload = InProcessCarrier(), asyncio.Queue(), object()
    await c.subscribe(AgentAddress(name="b"), got.put)
    await c.send(RoostMessage(performative=P.INFORM, protocol=IP.INFORM, conversation_id="c",
                              sender=AgentAddress(name="a"), receivers=[AgentAddress(name="b")], content=payload))
    assert (await asyncio.wait_for(got.get(), 1)).content is payload
    await c.close()


async def test_unknown_receiver():
    c = InProcessCarrier()
    with pytest.raises(Undeliverable):
        await c.send(RoostMessage(performative=P.INFORM, protocol=IP.INFORM, conversation_id="c",
                                  sender=AgentAddress(name="a"), receivers=[AgentAddress(name="zz")]))
# FILL IN: capability broadcast fan-out, CarrierClosed after close()
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4720 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: Carrier ABC + InProcessCarrier; 5 tests green. Coder added an unspecified behaviour: broadcast excludes the sender — confirm at feature review.
Seat: sonnet (native) · Attempts: 1

**Deviations from spec**: sender-exclusion in broadcast (unspecified)
