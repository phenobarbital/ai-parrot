# TASK-4748: M12a — core telemetry seam: `CapabilityCallRecord`, `CapabilityCallEvent`, `AbstractLogger.record_capability`

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12 (core seam; S11, D13, AC14): deterministic capability calls must not be forced into `UsageRecord`'s provider/model/token shape with fabricated values. Core gains a sibling `CapabilityCallRecord`, a `CapabilityCallEvent(LifecycleEvent)` (so FEAT-710's fan-out forwards it to the bus), and a default no-op `AbstractLogger.record_capability` so every existing recorder keeps working. The satellite emitter and received ledger are TASK-4749.

---

## Scope

- Add `CapabilityCallRecord` to `observability/recorders/models.py`; export it from `recorders/__init__.py`.
- Add `async def record_capability(self, record) -> None` (no-op) to `AbstractLogger` in `recorders/base.py`.
- Create `core/events/lifecycle/events/capability.py` with `CapabilityCallEvent`; export it from `events/__init__.py`.
- Tests: `packages/ai-parrot/tests/unit/observability/test_capability_call_record.py`.

**NOT in scope**: `ServedTelemetry`, `ReceivedLedger` (TASK-4749), any recorder implementing `record_capability` (opt-in later).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/models.py` | MODIFY | add `CapabilityCallRecord` |
| `packages/ai-parrot/src/parrot/observability/recorders/base.py` | MODIFY | add `record_capability` no-op |
| `packages/ai-parrot/src/parrot/observability/recorders/__init__.py` | MODIFY | export |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py` | CREATE | `CapabilityCallEvent` |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py` | MODIFY | export |
| `packages/ai-parrot/tests/unit/observability/test_capability_call_record.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.recorders.models import UsageRecord   # verified: packages/ai-parrot/src/parrot/observability/recorders/models.py:22
from parrot.observability.recorders.base import AbstractLogger   # verified: recorders/base.py:16
from navigator_eventbus.lifecycle.base import LifecycleEvent   # verified: core/events/lifecycle/events/client.py:14 (same import the sibling events use)
from parrot.core.events.lifecycle.events import AfterClientCallEvent   # verified: events/__init__.py:26 (export pattern)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/recorders/models.py
from datetime import datetime, timezone; from typing import Literal, Optional; from pydantic import BaseModel, Field, computed_field   # lines 15-19
class UsageRecord(BaseModel):   # line 22 — the sibling; do NOT extend it
# packages/ai-parrot/src/parrot/observability/recorders/base.py
class AbstractLogger(ABC):      # line 16
    name: str = "abstract"
    @abstractmethod
    async def record(self, record: UsageRecord) -> None   # line 31
    async def aclose(self) -> None                        # line 39 (no-op default — same idiom for record_capability)
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):   # line 45 — frozen dataclass pattern
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py — imports block :13-48, __all__ at :51
```

### Does NOT Exist
- ~~`UsageRecord.cap_id`~~ — never add protocol fields to `UsageRecord` (S11).
- ~~`AbstractLogger.record_capability` as abstract~~ — it MUST be a concrete no-op or every recorder breaks.
- ~~`parrot.core.events.lifecycle.events.capability`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_capability_call_record.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/models.py#UsageRecord",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/base.py#AbstractLogger",
    "sym:packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py#AfterClientCallEvent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `CapabilityCallRecord` carries NO user_id/session_id (observability PII contract, models.py docstring) — only agent names, cap_id, cost, trace ids.
- The event is a frozen dataclass like its siblings; its single field `record: CapabilityCallRecord`.
- Keep `__all__` lists sorted as they are (append in the right group with a `# FEAT-746` comment).

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py:45-83` — sibling event.

---

## Implementation Blueprint

### Steps (in order)
1. Model — *why*: both the event and the recorder hook reference it.
2. Recorder hook — *why*: no-op keeps every backend compatible.
3. Event + exports; tests.

### `packages/ai-parrot/src/parrot/observability/recorders/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class UsageRecord(BaseModel):' packages/ai-parrot/src/parrot/observability/recorders/models.py)
# APPEND at end of file (after UsageRecord, models.py:22-91) — FEAT-746 M12 (S11): a sibling, never fields on UsageRecord
class CapabilityCallRecord(BaseModel):
    """One Squawk capability call, served or received. No provider/model/PII fields; tokens only for llm_backed."""

    side: Literal["served", "received"]
    agent: str
    peer_agent: str
    cap_id: str
    category: str
    backing: Literal["deterministic", "llm_backed"]
    status: str
    duration_ms: float = 0.0
    rows: Optional[int] = None
    bytes: Optional[int] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Optional[float] = None
    policy_applied: tuple[str, ...] = ()
    trace_id: str
    correlation_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

### `packages/ai-parrot/src/parrot/observability/recorders/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def record(self, record: UsageRecord) -> None:' packages/ai-parrot/src/parrot/observability/recorders/base.py)
# 1) change the import at base.py:13 to:  from parrot.observability.recorders.models import CapabilityCallRecord, UsageRecord
# 2) AFTER — insert below the `record` method body (ends at `        raise NotImplementedError`, base.py:37), before `async def aclose`:
    async def record_capability(self, record: CapabilityCallRecord) -> None:
        """Record one capability call (FEAT-746). Default is a no-op; backends opt in."""
        return None
```

### `packages/ai-parrot/src/parrot/observability/recorders/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__all__ = \[' packages/ai-parrot/src/parrot/observability/recorders/__init__.py)
# change line 21 to: from parrot.observability.recorders.models import CapabilityCallRecord, UsageRecord
# and add "CapabilityCallRecord", to __all__ (sorted position, after "AbstractLogger")
```

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/capability.py` (CREATE)
```python
"""Capability-call lifecycle event (FEAT-746 M12): emitted on both sides of a Squawk call under the caller's trace_id."""
from dataclasses import dataclass

from navigator_eventbus.lifecycle.base import LifecycleEvent

from parrot.observability.recorders.models import CapabilityCallRecord


@dataclass(frozen=True)
class CapabilityCallEvent(LifecycleEvent):
    """Carries one CapabilityCallRecord; forwarded to the bus by the FEAT-710 fan-out when subscribed with forward_to_bus=True."""

    record: CapabilityCallRecord = None  # type: ignore[assignment]  # dataclass default required by LifecycleEvent's own defaults; always set by emitters
```

### `packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__all__ = \[' packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py)
# BEFORE `__all__ = [` (events/__init__.py:51) add the import:
from parrot.core.events.lifecycle.events.capability import CapabilityCallEvent  # FEAT-746
# and inside __all__ append a group:    # FEAT-746: capability-call domain
#                                        "CapabilityCallEvent",
```
**Why**: FEAT-710 fan-out subscribes typed events from this package; a new domain follows the same export shape. Check whether `LifecycleEvent` fields have defaults (it is a dataclass) — if none, drop the `= None` default on `record`.

### FILL IN checklist
- [ ] `capability.py::CapabilityCallEvent.record` default — keep or drop depending on `LifecycleEvent`'s dataclass fields (inspect `navigator_eventbus.lifecycle.base`)

---

## Acceptance Criteria

- [ ] `from parrot.observability.recorders import CapabilityCallRecord` and `from parrot.core.events.lifecycle.events import CapabilityCallEvent` work
- [ ] A minimal `AbstractLogger` subclass implementing only `record` instantiates and `await record_capability(...)` returns None
- [ ] `CapabilityCallRecord` has no `provider`/`model`/`user_id` fields (AC14)
- [ ] Existing `pytest packages/ai-parrot/tests/unit/observability/test_config.py -q` still passes; new test passes; ruff clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_capability_call_record.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_config.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_capability_call_record.py
import pytest
from parrot.core.events.lifecycle.events import CapabilityCallEvent
from parrot.observability.recorders import AbstractLogger, CapabilityCallRecord

class _Rec(AbstractLogger):
    async def record(self, record): pass

def _rec():
    return CapabilityCallRecord(side="served", agent="hr", peer_agent="ext", cap_id="hr.reports.x", category="hr.reports", backing="deterministic", status="OK", trace_id="t"*32)

async def test_default_hook_is_noop():
    assert await _Rec().record_capability(_rec()) is None

def test_no_provider_fields():
    assert not {"provider", "model", "user_id"} & set(CapabilityCallRecord.model_fields)
    assert CapabilityCallEvent(record=_rec()).record.cap_id == "hr.reports.x"
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M12, §9 S11
3. **Check dependencies** — none
4. **Verify the Codebase Contract** (re-grep the four anchors)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4748 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (review and close of a delivery merged by an earlier run)
**Date**: 2026-10-27
**Notes**: Reviewed: CapabilityCallRecord, CapabilityCallEvent, AbstractLogger.record_capability no-op, exports. Tests: test_capability_call_record.py passes; observability unit suite shows only the pre-existing baseline failure test_attributes.py::test_every_shipped_client_name_is_mapped. Engine merge-tier validation could not run in the sandbox (parrot.conf mkdir of ONTOLOGY_DIR on the read-only primary checkout, exit 4); tests were run by hand with ONTOLOGY_DIR set to a scratch dir. finalize_task not used (no review EvidenceRef artifact exists); closed via close_task.sh. Per-attempt seat/model attribution is not recorded here: the attempt_uid of this pre-existing delivery was not available, so coder_record_review/coder_record_feedback were NOT recorded.

**Deviations from spec**: none in the file set.
