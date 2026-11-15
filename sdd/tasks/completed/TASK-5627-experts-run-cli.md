# TASK-5627: `parrot experts run` — compile a scope, run, pause at gates, resume

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-5625, TASK-5615
**Assigned-to**: unassigned

---

## Context

Spec §2 User-Facing Behavior, AC9. Operator entry point; with no Redis it uses the SQLite gate store.

---

## Scope

- Create `parrot/experts/cli.py` exposing click group `experts` with `scopes` (list), `run --scope --input [--tenant]`, `gates` (list pending), `approve|reject <gate_id> [--comment]`, `resume --run-id`.
- Register `"experts": "parrot.experts.cli"` in the lazy command map (the module attribute must be named `experts`, see LazyGroup getattr at cli/__init__.py:99-100).
- Persist run checkpoints using AgentsFlow's checkpoint support (`from_definition(..., checkpoint=...)`, flow.py:607) — read it first.
- CliRunner tests with fake experts.

**NOT in scope**: Integration test of the full pipeline (TASK-5631).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/cli.py` | CREATE | CLI |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | lazy command |
| `packages/ai-parrot/tests/experts/test_experts_cli.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
import click
from parrot.experts.grid.loader import load_scopes  # TASK-5625
from parrot.experts.grid.compiler import compile_scope  # TASK-5625
from parrot.bots.flows.core.gates.stores import resolve_gate_store  # TASK-5615
from parrot.bots.flows.core.gates import GateHost  # TASK-5613
```

### Existing Signatures to Use
```python
# cli/__init__.py:170 cli._lazy_commands = {...}; last entry :214 "finance": "parrot.semantic.accounting.cli",
# cli/__init__.py:99-100 attr_name = cmd_name.replace("-", "_"); getattr(mod, attr_name) or getattr(mod, cmd_name)
# flow.py:607 AgentsFlow.from_definition(definition, *, agent_registry=None, node_factories=None, checkpoint=None, ...)
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
      "path": "packages/ai-parrot/src/parrot/experts/cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_experts_cli.py",
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
1. Read flow.py checkpoint handling.
2. Write cli.py; register.
3. Tests.

### Blocks

```python
# packages/ai-parrot/src/parrot/cli/__init__.py (MODIFY) — AFTER `    "finance": "parrot.semantic.accounting.cli",` (verified: cli/__init__.py:214; occurrences: 1)
    # FEAT-890 — expert scopes and gates.
    "experts": "parrot.experts.cli",
```
```python
# packages/ai-parrot/src/parrot/experts/cli.py  (CREATE)
"""`parrot experts` CLI (FEAT-890)."""
from __future__ import annotations
import click

@click.group(name="experts")
def experts() -> None:
    """Run expert scopes and resolve their gates."""

# FILL IN: scopes / run / gates / approve / reject / resume commands (async bodies via asyncio.run)
```

### FILL IN checklist
- [ ] checkpoint wiring
- [ ] registry construction for CLI (reuse load_experts bootstrap — grep `load_experts`)
- [ ] tests

---

## Acceptance Criteria

- [ ] `parrot experts --help` lists the commands.
- [ ] run pauses at a gate and resume continues after approve (fake experts).

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_experts_cli.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5627 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5627
- Feature: expert-stages-and-delegation
- Implementation SHA: a3f3dd4e7fd06d749643547a0699ea9965993d02
- Closed at (UTC): 2026-11-13T22:46:03+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: opus · Backend: native · Model: opus · Attempts: 1 · Duration: n/a · Tokens: n/a |
