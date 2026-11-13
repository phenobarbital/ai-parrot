# TASK-5631: Integration tests — security-patch pipeline pause/resume and dev-loop in-flight gate

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5627, TASK-5618
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, AC6, AC9.

---

## Scope

- `test_security_patch_pipeline_pause_resume`: bundled scope with fake LLM experts, SQLite store in tmp_path; run → paused at gate → new process objects (simulated restart) → approve → cve-remediation runs.
- `test_devloop_inflight_gate_survives_upgrade`: load a recorded legacy envelope fixture (TASK-5616) into the store/session, resolve via the runner.

**NOT in scope**: Real LLM calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/experts/test_integration_stages.py` | CREATE | pipeline test |
| `packages/ai-parrot/tests/flows/dev_loop/test_gate_upgrade_inflight.py` | CREATE | upgrade test |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
# imports from TASK-5613/5615/5616/5625/5627 public APIs only
```

### Existing Signatures to Use
```python
# none — this task only creates new modules
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
      "path": "packages/ai-parrot/tests/experts/test_integration_stages.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_gate_upgrade_inflight.py",
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
1. Read tests/experts/conftest.py fakes.
2. Write tests.

### Blocks

```python
# both files: pytest-asyncio tests; FILL IN bodies — no real_llm marker; use fakes from tests/experts/conftest.py
```

### FILL IN checklist
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Both integration tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_integration_stages.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_gate_upgrade_inflight.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5631 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
