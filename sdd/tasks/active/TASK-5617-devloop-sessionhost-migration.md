# TASK-5617: dev-loop SessionHost delegates gates to GateHost (hard cut)

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-5613, TASK-5616
**Assigned-to**: unassigned

---

## Context

Spec §2.2 / Module 3, AC6. `SessionHost.open_gate/resolve_gate` keep their signatures (callers unchanged) but gate state transitions are computed by GateHost semantics; the emitted actions stay `GateOpened/GateResolved/GateExpired` so the Redis action log format is unchanged.

---

## Scope

- Make `SessionHost.open_gate` and `resolve_gate` build `GateSpec`/use `GateHost` (in-memory store scoped to the session, seeded from the session state via the adapter) and translate results back into the existing actions.
- Call `register_devloop_gate_kinds()` at module import of session_state (or SessionHost init).
- Remove any now-dead duplicate expiry logic; no shims.
- All existing dev-loop gate tests must stay green.

**NOT in scope**: runner/commands/streaming (TASK-5618); integrations (TASK-5619).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py` | MODIFY | SessionHost gate methods delegate to GateHost |
| `packages/ai-parrot/tests/flows/dev_loop/test_session_state_gate_host.py` | CREATE | delegation tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.bots.flows.core.gates import GateHost, GateSpec  # TASK-5612/5613
from parrot.flows.dev_loop.gate_adapter import DevLoopGateAdapter, register_devloop_gate_kinds  # TASK-5616
```

### Existing Signatures to Use
```python
class SessionHost:  # session_state.py:1346
    def resolve_gate(self, gate_id: str, resolution: Literal["approved","rejected"], resolved_by: str, comment: str = "", origin=None, answers=None)  # :1438
    def open_gate(self, *, kind: GateKind, node_id: NodeId, title: str, instructions: str = "", payload_ref: str = "", ttl_seconds=None, on_expiry="fail", questions=None) -> Tuple[str, ActionEnvelope]  # :1502
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~async SessionHost.open_gate~~ — both methods are SYNC today; GateHost is async. Decide: run the pure transition helpers synchronously (factor GateHost's transition logic into sync pure functions in TASK-5613's host if needed — coordinate by adding them in THIS task to host.py is NOT allowed (file owned by TASK-5613); instead compute transitions with GateRecord.model_copy here) — FILL IN.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_session_state_gate_host.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py#SessionHost"
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
1. Read SessionHost lines 1346–1600 fully before editing.
2. Run the existing gate tests first to get a baseline.
3. Delegate; re-run all listed tests.

### Blocks

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py  (MODIFY)
# AFTER — edit inside `    def open_gate(` (verified: session_state.py:1502)
# occurrences: 1 (verified: grep -c '    def open_gate(' session_state.py)
#   FILL IN: build GateSpec(kind=kind, title=title, instructions=instructions, questions=questions or [],
#            ttl_seconds=ttl_seconds, on_expiry=on_expiry); validate via the generic kind registry;
#            produce the same GateOpened action as before — signature unchanged (callers: runner, commands, integrations)
# AFTER — edit inside `    def resolve_gate(` (verified: session_state.py:1438)
# occurrences: 1
#   FILL IN: transition via GateRecord semantics (DevLoopGateAdapter.to_record → update → from_record); same GateResolved action
```
**Why**: keeping the public SessionHost signatures and the action format is what makes the hard cut safe for in-flight runs (AC6), while the generic host becomes the single source of gate semantics.

### FILL IN checklist
- [ ] sync/async boundary decision
- [ ] open_gate delegation
- [ ] resolve_gate delegation
- [ ] expiry path wherever SessionHost expires gates

---

## Acceptance Criteria

- [ ] Existing tests `test_session_state.py`, `test_gate_integration.py`, `test_open_questions_gate.py`, `test_plan_gate_override.py` pass unchanged.
- [ ] New delegation tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_session_state_gate_host.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_session_state.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_gate_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_open_questions_gate.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_plan_gate_override.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5617 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
