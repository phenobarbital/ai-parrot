# TASK-5616: DevLoopGateAdapter and registration of the six legacy gate kinds

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5612
**Assigned-to**: unassigned

---

## Context

Spec §2.2 / Module 3. Persisted dev-loop runs hold `ApprovalGate` objects inside Redis-streamed actions; the adapter is what lets them survive the hard cut (AC6).

---

## Scope

- Create `flows/dev_loop/gate_adapter.py` with `register_devloop_gate_kinds()` (the six `GateKind` values) and `DevLoopGateAdapter.to_record(gate, *, owner)` / `.from_record(record, *, node_id) -> ApprovalGate`.
- Record fixtures: serialize a representative set of `GateOpened`/`GateResolved`/`GateExpired` actions with the CURRENT code into `tests/flows/dev_loop/fixtures/legacy_gate_envelopes.json` BEFORE any migration task changes `session_state.py`.
- Round-trip tests over the fixtures.

**NOT in scope**: Changing `SessionHost` (TASK-5617).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/gate_adapter.py` | CREATE | adapter |
| `packages/ai-parrot/tests/flows/dev_loop/fixtures/legacy_gate_envelopes.json` | CREATE | recorded envelopes |
| `packages/ai-parrot/tests/flows/dev_loop/test_gate_adapter.py` | CREATE | round-trip tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.session_state import ApprovalGate, GateKind, GateOpened, GateResolved, GateExpired, ActionEnvelope  # verified: session_state.py:297,174,655,660,674,815
from parrot.bots.flows.core.gates import GateRecord, GateSpec, register_gate_kind  # TASK-5612
```

### Existing Signatures to Use
```python
class ApprovalGate(_Frozen):  # session_state.py:297 — gate_id, kind, node_id, status, on_expiry, title, instructions, payload_ref, opened_at, expires_at, resolved_by, resolved_at, comment, questions, answers
GateKind = Literal[...]  # :174 — use typing.get_args(GateKind) to enumerate, never retype the list
class ActionEnvelope(_Frozen): channel, server_seq, action, origin, rejection_reason  # :815
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.


---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/gate_adapter.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/fixtures/legacy_gate_envelopes.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_gate_adapter.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py#ApprovalGate"
  ]
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. FIRST record the fixtures with the current code (commit them with the task).
2. Write the adapter.
3. Tests: for each fixture gate, from_record(to_record(g)) == g; unknown kind raises.

### Blocks

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/gate_adapter.py  (CREATE)
"""Bridge dev-loop ApprovalGate ⇄ generic GateRecord (FEAT-890 M3)."""
from __future__ import annotations
from typing import get_args
from parrot.bots.flows.core.gates import GateRecord, GateSpec, register_gate_kind
from .session_state import ApprovalGate, GateKind

def register_devloop_gate_kinds() -> None:
    """Register every dev-loop GateKind as a generic string kind (idempotent)."""
    for kind in get_args(GateKind):
        register_gate_kind(kind, description=f"dev-loop {kind}")

class DevLoopGateAdapter:
    """Lossless conversion for persisted dev-loop gates."""
    @staticmethod
    def to_record(gate: ApprovalGate, *, owner: str) -> GateRecord:
        """Map every ApprovalGate field; node_id goes into payload metadata — FILL IN where."""
        # FILL IN: ttl_seconds = expires_at - opened_at when set; unknown kind → GateError(UNKNOWN_KIND) with gate_id (spec §7)

    @staticmethod
    def from_record(record: GateRecord, *, node_id: str) -> ApprovalGate:
        """Inverse of to_record; ApprovalGate(record→...) must equal the original."""
        # FILL IN
```
**Why**: `get_args(GateKind)` keeps the adapter correct if dev-loop adds a kind; lossless round-trip is the AC6 evidence.

### FILL IN checklist
- [ ] field mapping (where node_id lives in GateRecord — payload_ref is taken; use owner=f'{run}:{node_id}' or extend nothing: decide and document)
- [ ] fixture recording script (test helper, not shipped)
- [ ] tests

---

## Acceptance Criteria

- [ ] Round-trip is lossless for every recorded fixture.
- [ ] Six kinds registered.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_gate_adapter.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5616 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
