# TASK-5619: ai-parrot-integrations devloop service/bridge on the generic gate host

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-5618
**Assigned-to**: unassigned

---

## Context

Spec §2.2 / Module 3. The Slack/agentd devloop bridge resolves gates through the runner; it must surface GateError cleanly.

---

## Scope

- Update `service.py` and `bridge.py` `resolve_gate` paths to catch `GateError` and report NOT_FOUND / NOT_PENDING to the user-facing channel.
- Keep e2e tests green.

**NOT in scope**: Any runner change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py` | MODIFY | GateError handling |
| `packages/ai-parrot-integrations/src/parrot/integrations/devloop/bridge.py` | MODIFY | GateError handling |
| `packages/ai-parrot-integrations/tests/integrations/devloop/test_gate_errors.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.bots.flows.core.gates import GateError, GateErrorCode  # TASK-5612
```

### Existing Signatures to Use
```python
# integrations/devloop/service.py:242 async def resolve_gate(  (calls self._channel(record).resolve_gate at :247)
# integrations/devloop/bridge.py:20 and :78 async def resolve_gate(
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
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/devloop/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/devloop/bridge.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/devloop/test_gate_errors.py",
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
1. Read both files.
2. Add handling + tests.
3. Run devloop tests.

### Blocks

```python
# service.py (MODIFY) — anchor `    async def resolve_gate(` (verified: service.py:242; occurrences: 1)
# bridge.py (MODIFY) — anchor `    async def resolve_gate(` occurrences: 2 (bridge.py:20 protocol, :78 impl)
#   FILL IN: disambiguate — attach to the implementation at :78 (quote its class line) — error handling only there
```
**Why**: the protocol method at :20 has no body to change.

### FILL IN checklist
- [ ] message wording
- [ ] tests

---

## Acceptance Criteria

- [ ] `test_bridge.py`, `test_e2e_service.py` pass; new tests pass.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_gate_errors.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_bridge.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/devloop/test_e2e_service.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5619 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5619
- Feature: expert-stages-and-delegation
- Implementation SHA: da506d454408f72be2a2e0fd492868cb840c8e6c
- Closed at (UTC): 2026-11-13T23:30:50+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
