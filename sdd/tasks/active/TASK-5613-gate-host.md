# TASK-5613: GateHost — open, resolve, expire, recover, pre_review hook, human delivery

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-5612
**Assigned-to**: unassigned

---

## Context

Spec §2.1 / Module 1 second half. The host owns gate semantics: same expiry rules as dev-loop (`fail` → expired, `approve` → auto-resolve by `system:ttl-auto-approve`), downtime recovery, advisory pre_review, delivery via parrot/human.

---

## Scope

- Implement `GateHost` in `core/gates/host.py` with `open`, `resolve`, `recover`, `subscribe` (event listeners).
- Run the optional `pre_reviewer` callable before notification; store its verdict on the record; never change status from it.
- Notify humans through an optional `HumanInteractionManager` (`parrot.human`); no channel code.
- Unit tests with an in-memory fake GateStore.

**NOT in scope**: Concrete stores (TASK-5614/5615); dev-loop wiring (TASK-5617).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/host.py` | CREATE | GateHost |
| `packages/ai-parrot/src/parrot/bots/flows/core/gates/__init__.py` | MODIFY | export GateHost |
| `packages/ai-parrot/tests/flows/gates/test_gate_host.py` | CREATE | unit tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.human import HumanInteractionManager  # verified: parrot/human/__init__.py:32
from parrot.bots.flows.core.gates import GateSpec, GateRecord, GateStore, GateError, GateErrorCode, GateEvent, PreReviewVerdict  # TASK-5612
from parrot.bots.flows.core.gates.kinds import is_registered  # TASK-5612
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py — semantics to MIRROR, never import:
#   ApprovalGate.on_expiry: 'fail' emits GateExpired; 'approve' auto-resolves by 'system:ttl-auto-approve'  # :297
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`HumanInteractionManager.open_gate`~~ — read `parrot/human/manager.py:51` for the real request API before wiring; if no fitting method, keep notifier optional and log.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/host.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/core/gates/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/gates/test_gate_host.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Write host.py from the block.
2. Fill open/resolve/recover.
3. Export GateHost and AUTO_APPROVER in `__init__.py` — append to the import list and `__all__`.
4. Tests with an in-memory dict store: roundtrip, NOT_PENDING, both expiry policies, recover after simulated downtime, pre_review never resolves, pre_review error captured.

### Blocks

```python
# packages/ai-parrot/src/parrot/bots/flows/core/gates/host.py  (CREATE)
"""Generic gate host (FEAT-890 M1)."""
from __future__ import annotations
import logging, time, uuid
from typing import Awaitable, Callable, Literal, Mapping, TYPE_CHECKING
from .kinds import is_registered
from .models import GateError, GateErrorCode, GateEvent, GateRecord, GateSpec, GateStore, PreReviewVerdict
if TYPE_CHECKING:
    from parrot.human import HumanInteractionManager

AUTO_APPROVER = "system:ttl-auto-approve"
Listener = Callable[[GateEvent], Awaitable[None]]

class GateHost:
    """Open, resolve, expire and recover gates over a GateStore."""
    def __init__(self, store: GateStore, *, notifier: "HumanInteractionManager | None" = None,
                 pre_reviewer: Callable[[GateRecord], Awaitable[PreReviewVerdict]] | None = None) -> None:
        self.store = store
        self.notifier = notifier
        self.pre_reviewer = pre_reviewer
        self._listeners: list[Listener] = []
        self.logger = logging.getLogger(__name__)

    def subscribe(self, listener: Listener) -> None:
        """Register an async listener for GateEvent."""
        self._listeners.append(listener)

    async def open(self, spec: GateSpec, *, owner: str, payload_ref: str = "") -> GateRecord:
        """Persist a pending gate, run pre_review (advisory), then notify; raises GateError(UNKNOWN_KIND)."""
        if not is_registered(spec.kind):
            raise GateError(GateErrorCode.UNKNOWN_KIND, spec.kind)
        now = time.time()
        record = GateRecord(gate_id=uuid.uuid4().hex, kind=spec.kind, owner=owner, spec=spec, payload_ref=payload_ref,
                            opened_at=now, expires_at=(now + spec.ttl_seconds) if spec.ttl_seconds else None)
        # FILL IN: if spec.pre_review and self.pre_reviewer → verdict (catch errors into PreReviewVerdict.error); status stays pending — AC4
        # FILL IN: store.put, emit 'opened', notify via self.notifier when set — AC5
        return record

    async def resolve(self, gate_id: str, resolution: Literal["approved", "rejected"], *, resolved_by: str,
                      comment: str = "", answers: Mapping[str, str] | None = None) -> GateRecord:
        """Resolve a pending gate; GateError(NOT_FOUND|NOT_PENDING) otherwise."""
        # FILL IN: load, check pending, model_copy(update=...), put, emit 'resolved'

    async def recover(self, *, now: float | None = None) -> list[GateRecord]:
        """Apply on_expiry to pending gates whose expires_at elapsed (incl. while the process was down)."""
        # FILL IN: 'fail' → status expired + emit 'expired'; 'approve' → approved by AUTO_APPROVER + emit 'resolved'

    async def _emit(self, event: GateEvent) -> None:
        for listener in self._listeners:
            try:
                await listener(event)
            except Exception:  # listeners must not break gate state
                self.logger.exception("gate listener failed for %s", event.record.gate_id)
```
**Why**: expiry semantics are copied from dev-loop so the migration (TASK-5617) is behavior-preserving.

### FILL IN checklist
- [ ] pre_review invocation + error capture
- [ ] notifier call (inspect HumanInteractionManager API first)
- [ ] resolve body
- [ ] recover body
- [ ] tests

---

## Acceptance Criteria

- [ ] AC1, AC4, AC5 of the spec hold under unit tests.
- [ ] No dev-loop import.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/gates/test_gate_host.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5613 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
