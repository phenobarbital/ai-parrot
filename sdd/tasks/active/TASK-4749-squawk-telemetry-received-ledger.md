# TASK-4749: M12b — satellite telemetry: `ServedTelemetry` emitter and client `ReceivedLedger`

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4737, TASK-4740, TASK-4748
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (satellite slice; D13, AC14): `ServedTelemetry.emit(record)` publishes a `CapabilityCallEvent` on the lifecycle `EventRegistry` and calls `AbstractLogger.record_capability` on the configured recorder; the client-side `ReceivedLedger` keeps `ReceivedLedgerEntry` rows (remote agent, cap_id, contract hash, handle key, descriptor digest, cost, later affordance uses) with an optional async sink. Both sides share the caller's `trace_id`.

---

## Scope

- `parrot/squawk/telemetry.py`: `ServedTelemetry(*, registry=None, recorder=None)` with `async emit(record)`; `record_from_call(...)` helper building a `CapabilityCallRecord` from `(side, agent, peer, cap, status, cost, trace_id, correlation_id, policy_applied)`.
- `parrot/squawk/client/{__init__,received_ledger}.py`: `ReceivedLedgerEntry`, `ReceivedLedger(*, sink=None, max_entries=10_000)` with `append`, `note_follow_up(handle_key, tool_name)`, `recent(limit)`.
- Tests: `tests/test_telemetry.py`, `tests/client/{__init__,test_received_ledger}.py`.

**NOT in scope**: the dispatcher calling `emit` (M8), `CapabilityTool` recording receipts (M7), `invocation_context` binding (M8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-squawk/src/parrot/squawk/telemetry.py` | CREATE | `ServedTelemetry`, `record_from_call` |
| `packages/ai-parrot-squawk/src/parrot/squawk/client/__init__.py` | CREATE | exports |
| `packages/ai-parrot-squawk/src/parrot/squawk/client/received_ledger.py` | CREATE | `ReceivedLedgerEntry`, `ReceivedLedger` |
| `packages/ai-parrot-squawk/tests/test_telemetry.py` | CREATE | unit tests |
| `packages/ai-parrot-squawk/tests/client/__init__.py` | CREATE | tests package |
| `packages/ai-parrot-squawk/tests/client/test_received_ledger.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.recorders import AbstractLogger, CapabilityCallRecord   # TASK-4748 (recorders/__init__.py export)
from parrot.core.events.lifecycle import EventRegistry   # verified: packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:21 (navigator_eventbus.lifecycle.registry)
from parrot.core.events.lifecycle.events import CapabilityCallEvent   # TASK-4748
from parrot.interagent import CallCost, SquawkCapability   # TASK-4740
```

### Existing Signatures to Use
```python
# navigator_eventbus.lifecycle.registry.EventRegistry — publish/emit API: inspect with
#   python -c "from parrot.core.events.lifecycle import EventRegistry; help(EventRegistry)"  (record the method name — `emit`/`publish` — in the Completion Note)
# packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:22 — get_global_registry() is the default registry when none is injected
# TASK-4748 AbstractLogger.record_capability(record) -> None
```

### Does NOT Exist
- ~~`UsageRecordingSubscriber` handling capability events~~ — out of scope; `ServedTelemetry` calls the recorder directly.
- ~~`ReceivedLedger` persistence in WorkingMemory~~ — in-memory deque + optional sink only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/telemetry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/client/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/src/parrot/squawk/client/received_ledger.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/test_telemetry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/client/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-squawk/tests/client/test_received_ledger.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `emit` never raises into the call path: registry/recorder failures are logged with `self.logger.exception`.
- `record_from_call` sets `tokens_in/out` only when `cap.backing == "llm_backed"`; deterministic records keep 0 (AC14).
- `ReceivedLedger.note_follow_up` appends `tool_name` to the `follow_ups` of the latest entry with that `handle_key` (replace the frozen model via `model_copy`).

### References in Codebase
- `packages/ai-parrot/src/parrot/observability/fanout.py` — how typed events reach the bus (`forward_to_bus=True` subscriptions); not modified here.

---

## Implementation Blueprint

### Steps (in order)
1. `telemetry.py` — *why*: the served side's single emission point.
2. `received_ledger.py` + `client/__init__.py` — *why*: the client side's ledger (D13 level 2).
3. Tests with a fake recorder and a fake registry.

### `packages/ai-parrot-squawk/src/parrot/squawk/telemetry.py` (CREATE)
```python
"""Served-side telemetry: one CapabilityCallEvent + one recorder call per capability call (FEAT-746 M12, D13)."""
from __future__ import annotations

import logging
from typing import Literal

from parrot.core.events.lifecycle import EventRegistry, get_global_registry  # verified: core/events/lifecycle/__init__.py:21-22
from parrot.core.events.lifecycle.events import CapabilityCallEvent
from parrot.interagent import CallCost, SquawkCapability
from parrot.observability.recorders import AbstractLogger, CapabilityCallRecord


def record_from_call(*, side: Literal["served", "received"], agent: str, peer: str, cap: SquawkCapability, status: str, cost: CallCost,
                     trace_id: str, correlation_id: str | None = None, policy_applied: tuple[str, ...] = ()) -> CapabilityCallRecord:
    """Tokens only for llm_backed capabilities; never provider/model fields."""
    llm = cap.backing == "llm_backed"
    return CapabilityCallRecord(side=side, agent=agent, peer_agent=peer, cap_id=cap.cap_id, category=cap.category, backing=cap.backing,
                                status=status, duration_ms=float(cost.duration_ms), rows=cost.rows, bytes=cost.bytes,
                                tokens_in=cost.tokens_in if llm else 0, tokens_out=cost.tokens_out if llm else 0, cost_usd=cost.cost_usd,
                                policy_applied=policy_applied, trace_id=trace_id, correlation_id=correlation_id)


class ServedTelemetry:
    def __init__(self, *, registry: EventRegistry | None = None, recorder: AbstractLogger | None = None) -> None:
        self._registry = registry
        self._recorder = recorder
        self.logger = logging.getLogger(__name__)

    async def emit(self, record: CapabilityCallRecord) -> None:
        """Publish the event and record it; failures are logged, never raised into the call path."""
        try:
            registry = self._registry or get_global_registry()
            # FILL IN: await registry.<emit|publish>(CapabilityCallEvent(record=record)) — method name from the installed navigator_eventbus
        except Exception:  # noqa: BLE001
            self.logger.exception("ServedTelemetry: event publish failed")
        if self._recorder is not None:
            try:
                await self._recorder.record_capability(record)
            except Exception:  # noqa: BLE001
                self.logger.exception("ServedTelemetry: recorder failed")
```

### `packages/ai-parrot-squawk/src/parrot/squawk/client/received_ledger.py` (CREATE)
```python
"""Client-side received ledger (D13 level 2): what came back, from whom, under which contract, and what the LLM did with it."""
from __future__ import annotations

import logging
from collections import deque
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from parrot.interagent import CallCost


class ReceivedLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    remote_agent: str; cap_id: str; contract_hash: str
    handle_key: str | None = None; descriptor_digest: str | None = None
    cost: CallCost; trace_id: str; follow_ups: tuple[str, ...] = ()


class ReceivedLedger:
    def __init__(self, *, sink: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None:
        self._sink = sink
        self._recent: deque[ReceivedLedgerEntry] = deque(maxlen=max_entries)
        self.logger = logging.getLogger(__name__)

    async def append(self, entry: ReceivedLedgerEntry) -> None:
        self._recent.append(entry)
        if self._sink is not None:
            try:
                await self._sink(entry.model_dump_json())
            except Exception:  # noqa: BLE001 — receiving side is best-effort (the served ledger is the fail-closed one)
                self.logger.exception("ReceivedLedger: sink failed")

    def note_follow_up(self, handle_key: str, tool_name: str) -> None:
        """Record that a local affordance consumed the handle."""
        # FILL IN: find the latest entry with handle_key, replace it with model_copy(update={"follow_ups": (*e.follow_ups, tool_name)}) — bounded by: no-op when absent
        raise NotImplementedError

    def recent(self, *, limit: int = 100) -> list[ReceivedLedgerEntry]:
        return list(self._recent)[-limit:]
```

### FILL IN checklist
- [ ] `telemetry.py::ServedTelemetry.emit` registry method name; bounded by the installed `EventRegistry` API
- [ ] `received_ledger.py::note_follow_up`; bounded by "no-op when absent"

---

## Acceptance Criteria

- [ ] `record_from_call` yields `tokens_in=0` for deterministic even when `cost.tokens_in>0`; `side`/`trace_id` set
- [ ] `emit` with a raising recorder does not raise; with a fake registry the event is published once
- [ ] `ReceivedLedger.append`/`note_follow_up`/`recent` behave; raising sink is logged
- [ ] Tests pass; ruff clean

---

## Validation Commands

- `pytest packages/ai-parrot-squawk/tests/test_telemetry.py -q`
- `pytest packages/ai-parrot-squawk/tests/client/test_received_ledger.py -q`

---

## Test Specification

Fake recorder subclassing `AbstractLogger` with a list; fake registry object exposing the emit method name discovered in the contract step.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M12, AC14
3. **Check dependencies** — TASK-4737, TASK-4740, TASK-4748 `"done"`
4. **Verify the Codebase Contract** (inspect `EventRegistry`)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4749 inter-agent-protocol verified`
10. **Completion Note** — record the registry method used

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
