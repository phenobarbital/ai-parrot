# TASK-5618: dev-loop runner, commands and streaming on the generic gate host

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5617, TASK-5615
**Assigned-to**: unassigned

---

## Context

Spec §2.2 / Module 3. The runner exposes `resolve_gate` and the HTTP handler; gate state for paused runs must be recoverable through a GateStore (Redis in production) so `GateHost.recover()` applies elapsed expiries on startup.

---

## Scope

- Runner: hold a `GateHost` over `resolve_gate_store(redis_client=<runner redis>)`; call `recover()` when a host is (re)attached; route `resolve_gate` through it before delegating to SessionHost.
- commands.py: `resolve_gate_handler` unchanged externally; map GateError codes to HTTP 404/409.
- streaming.py: no format change; only wire the store if the multiplexer owns the Redis client.

**NOT in scope**: integrations (TASK-5619).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | GateHost + recover |
| `packages/ai-parrot/src/parrot/flows/dev_loop/commands.py` | MODIFY | error mapping |
| `packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py` | MODIFY | expose redis client to the store if needed |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_gate_store.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.bots.flows.core.gates import GateHost, GateError, GateErrorCode  # TASK-5612/5613
from parrot.bots.flows.core.gates.stores import resolve_gate_store  # TASK-5615
```

### Existing Signatures to Use
```python
async def resolve_gate(self, run_id: str, gate_id: str, resolution: str, resolved_by: str, comment: str = "", origin: Optional[ActionOrigin] = None, answers: Optional[Dict[str, str]] = None) -> ActionEnvelope  # runner.py:1005
async def resolve_gate_handler(request: web.Request) -> web.Response  # commands.py:77
self._actions_key = f"flow:{run_id}:actions"  # streaming.py:106
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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/runner.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_runner_gate_store.py",
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
1. Read runner.py around 900–1100 and commands.py:60–120.
2. Wire GateHost; add tests with a fake store.
3. Run existing runner/commands tests.

### Blocks

```python
# runner.py (MODIFY) — edit inside `    async def resolve_gate(` (verified: runner.py:1005; occurrences: 1)
#   FILL IN: GateHost.resolve(...) then existing SessionHost path; keep return type ActionEnvelope
# commands.py (MODIFY) — edit inside `async def resolve_gate_handler(request: web.Request) -> web.Response:` (verified: commands.py:77; occurrences: 1)
#   FILL IN: except GateError: NOT_FOUND → 404, NOT_PENDING → 409
# streaming.py (MODIFY) — anchor `        self._actions_key = f"flow:{run_id}:actions"` (verified: streaming.py:106; occurrences: 1)
#   FILL IN: only if the runner cannot reach the redis client otherwise; else leave untouched and drop this row
```
**Why**: recover-on-attach implements "gate expires while the process is down" (spec §7).

### FILL IN checklist
- [ ] where the runner keeps its redis client
- [ ] recover hook location
- [ ] HTTP mapping

---

## Acceptance Criteria

- [ ] Existing `test_runner.py`, `test_runner_host.py`, `test_commands.py` pass.
- [ ] Paused-run expiry applied on recover (new test).

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_runner_gate_store.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_runner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_runner_host.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_commands.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5618 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
