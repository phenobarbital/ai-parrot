# TASK-4983: UsageAttribution model, ContextVar binding and event snapshot

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first half), design review S1/S2. Every downstream module needs one
immutable attribution object that is **snapshotted onto the lifecycle event at construction**,
so a forwarded or cross-registry delivery can never attach a call to the wrong task. A
subscriber-side ContextVar read stays only as a fallback (done in TASK-4985).

---

## Scope

- Create `parrot/observability/attribution.py` with the frozen `UsageAttribution` model (§2 Data Models, exact field list).
- Add the `current_usage_attribution` ContextVar to `observability/context.py` beside `current_seat`.
- Extend `usage_attribution()` with an optional `attribution` kwarg. **`attribution=None` must leave the currently bound value untouched** (no set/reset).
- Add `attribution: Optional[UsageAttribution]` to `AfterClientCallEvent` **and** `ClientCallFailedEvent`, defaulted by a `default_factory` that reads `current_usage_attribution` at construction time.
- Write unit tests.

**NOT in scope**: `UsageRecord` fields and the subscriber read (TASK-4985); the cache counters on the event (TASK-4986); binding attribution in the engine (TASK-4992).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/attribution.py` | CREATE | `UsageAttribution` model |
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | ContextVar + `attribution` kwarg |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | `attribution` field on two events |
| `packages/ai-parrot/tests/observability/test_attribution_snapshot.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.context import current_run_id, current_seat   # context.py:156,158
from parrot.observability.context import usage_attribution              # context.py:162
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent  # re-exported (subscriber.py:18-21)
from parrot.core.events.lifecycle import TraceContext                   # used by claude.py:46
from navigator_eventbus.lifecycle.base import LifecycleEvent            # client.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/context.py:161-189 — imports ONLY stdlib (contextlib, contextvars, typing: lines 50-52)
@contextmanager
def usage_attribution(run_id: Optional[str], seat: Optional[str] = None) -> Iterator[None]:
    tok_run = current_run_id.set(run_id); tok_seat = current_seat.set(seat)
    try: yield
    finally: current_seat.reset(tok_seat); current_run_id.reset(tok_run)

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):   # :45 — last field line 80: `cost_usd: Optional[float] = None  # FEAT-710: computed once at the origin`
@dataclass(frozen=True)
class ClientCallFailedEvent(LifecycleEvent):  # :84 — last field line 112: `tenant: Optional[str] = None  # FEAT-710`
```

### Does NOT Exist
- ~~`parrot.observability.attribution`~~ — this task creates it
- ~~`parrot.observability.context.current_usage_attribution`~~ — this task creates it
- ~~`parrot.observability.context.current_feat_id`~~ — never create per-field ContextVars; one object only
- ~~`AfterClientCallEvent.attribution`~~ — no such field today

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/attribution.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/observability/context.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/observability/test_attribution_snapshot.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/context.py#usage_attribution",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#AfterClientCallEvent",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#ClientCallFailedEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `attribution.py` imports only pydantic and typing. `context.py` may import it, but `context.py` must stay free of any other parrot import, because `events/client.py` will import `context.py`.
- The event is a frozen **dataclass**. Use `field(default_factory=_snapshot_attribution)`, never a mutable default.
- `attempt_uid`/`execution_id` are never metric labels (AC-9). This task only adds data; it must not touch `subscribers/metrics.py`.

### References in Codebase
- `events/client.py:58-65` — the existing "snapshot ContextVars at construction" convention for `agent_name`/`user_id`/`session_id`.

---

## Implementation Blueprint

### Steps (in order)
1. Create `attribution.py`, because the ContextVar's type needs it.
2. Add the ContextVar and widen `usage_attribution()`. Setting attribution only when it is not `None` matters because `dispatchers/claude.py:1013` re-enters `usage_attribution(run_id, seat=node_id)` *inside* the engine's binding; resetting there would erase the task identity.
3. Add the event fields with a construction-time default factory, so the snapshot cannot drift after emit (S2).
4. Write the tests.

### `packages/ai-parrot/src/parrot/observability/attribution.py` (CREATE)
```python
"""UsageAttribution — immutable SDD identity for one dispatched unit of work (FEAT-783 M1)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class UsageAttribution(BaseModel):
    """Immutable SDD attribution for one dispatched unit of work.

    "Seat" is deliberately split into three fields: the codebase gives the word two
    incompatible meanings (roster label ``"a"`` vs accounting seat ``"development.w1"``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    feat_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_uid: Optional[str] = None
    execution_id: Optional[str] = None
    dispatch_kind: Optional[str] = None     # "in-process" | "cli" | "sdk"
    roster_seat: Optional[str] = None       # sdd-coder roster label: "a"/"b"/"c"
    accounting_seat: Optional[str] = None   # observability seat: "development.w1"
```

### `packages/ai-parrot/src/parrot/observability/context.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'current_seat: ContextVar\[Optional\[str\]\] = ContextVar("parrot_current_seat", default=None)' context.py)
# AFTER — insert below `current_seat: ContextVar[Optional[str]] = ContextVar("parrot_current_seat", default=None)` (verified: context.py:158)
current_usage_attribution: ContextVar[Optional["UsageAttribution"]] = ContextVar(
    "parrot_current_usage_attribution", default=None
)
```
```python
# occurrences: 1 (verified: grep -c 'def usage_attribution(' context.py) — REPLACE the function at context.py:161-189
@contextmanager
def usage_attribution(
    run_id: Optional[str],
    seat: Optional[str] = None,
    attribution: Optional["UsageAttribution"] = None,
) -> Iterator[None]:
    """Bind run/seat AND (optionally) the full SDD attribution; token-based, nesting-safe.

    ``attribution=None`` leaves the currently bound attribution untouched, because
    dispatchers re-enter this block with only run/seat inside the engine's binding.
    """
    tok_run = current_run_id.set(run_id)
    tok_seat = current_seat.set(seat)
    tok_attr = current_usage_attribution.set(attribution) if attribution is not None else None
    try:
        yield
    finally:
        if tok_attr is not None:
            current_usage_attribution.reset(tok_attr)
        current_seat.reset(tok_seat)
        current_run_id.reset(tok_run)
```
Add `from typing import TYPE_CHECKING` and, under `if TYPE_CHECKING:`, `from parrot.observability.attribution import UsageAttribution`. Keep the existing docstring's Args and Example, and add an `attribution` entry.

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` (MODIFY)
```python
# occurrences: 1 — change `from dataclasses import dataclass` (client.py:11) to:
from dataclasses import dataclass, field

from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import current_usage_attribution


def _snapshot_attribution() -> Optional[UsageAttribution]:
    """Read the bound SDD attribution at event construction (FEAT-783 S2)."""
    return current_usage_attribution.get()
```
```python
# occurrences: 1 (verified: grep -c 'cost_usd: Optional\[float\] = None  # FEAT-710: computed once at the origin' client.py)
# AFTER — insert below `    cost_usd: Optional[float] = None  # FEAT-710: computed once at the origin` (verified: client.py:80)
    attribution: Optional[UsageAttribution] = field(default_factory=_snapshot_attribution)  # FEAT-783
```
```python
# FILL IN: disambiguate — `tenant: Optional[str] = None  # FEAT-710` occurs 2x (client.py:79 and :112).
# Insert the SAME `attribution` line below the occurrence inside ClientCallFailedEvent (:112),
# i.e. the one followed by the blank lines and `@dataclass(frozen=True)\nclass ClientStreamChunkEvent`.
```
Also add an `attribution:` entry to both docstrings' Attributes lists.

**Why this shape**: the event already snapshots `agent_name`/`user_id`/`session_id` at construction. A default factory does the same for every emitter (in-process clients, `claude.py`, `codex.py`) with no change at their call sites.

### `packages/ai-parrot/tests/observability/test_attribution_snapshot.py` (CREATE)
```python
"""FEAT-783 TASK-4983 — UsageAttribution + event snapshot."""
import pytest
from pydantic import ValidationError

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import current_usage_attribution, usage_attribution


def test_attribution_is_frozen_and_rejects_extras() -> None:
    # FILL IN: assignment raises ValidationError; UsageAttribution(bogus=1) raises; UsageAttribution() is legal
    ...


def test_event_snapshots_attribution_at_construction() -> None:
    # FILL IN: build event inside usage_attribution(..., attribution=a); leave the block; event.attribution == a (AC-2)
    ...


def test_inner_block_without_attribution_keeps_outer() -> None:
    # FILL IN: outer binds a; inner usage_attribution("r", seat="s") -> current_usage_attribution.get() is a
    ...


def test_failed_event_carries_attribution_and_default_is_none() -> None:
    # FILL IN: ClientCallFailedEvent inside a binding has it; outside any binding attribution is None
    ...
```

### FILL IN checklist
- [ ] `client.py` — insert into ClientCallFailedEvent at the second `tenant` occurrence; bounded by S2
- [ ] Verify `python -c "import parrot.core.events.lifecycle.events"` has no import cycle; bounded by Key Constraints
- [ ] Four test bodies; bounded by AC-2

---

## Acceptance Criteria

- [ ] `UsageAttribution` is frozen, `extra="forbid"`, all fields optional.
- [ ] Events built inside a binding carry the attribution after the block exits (AC-2, forwarded-event case).
- [ ] A nested `usage_attribution(run_id, seat)` without `attribution` preserves the outer attribution.
- [ ] Existing `usage_attribution` tests still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/observability/test_attribution_snapshot.py -q`
- `pytest packages/ai-parrot/tests/observability/test_usage_attribution.py -q`
- `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_usage_event_fields.py -q`

## Test Specification
See the blueprint's test file; one test per acceptance bullet.

## Agent Instructions
Implement exactly the four files. Use `PYTHONPATH=packages/ai-parrot/src` in the worktree. Do not touch `subscriber.py` or `metrics.py`.

## Completion Note

- Task: TASK-4983
- Feature: unified-usage
- Implementation SHA: 0ea7fd310aa515f2e5c9bb3400d1b904008dbe57
- Closed at (UTC): 2026-10-31T00:30:02+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 2 · Duration: 127.9s · Tokens: n/a |
