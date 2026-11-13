# TASK-5632: Documentation — expert stages/grid, generic gate host, SDD expert consult

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M
**Depends-on**: TASK-5613, TASK-5615, TASK-5624, TASK-5625, TASK-5627, TASK-5629
**Assigned-to**: unassigned

---

## Context

Spec §10 (docs policy required), AC17.

---

## Scope

- Create `wiki/experts/expert-stages-and-scope-grid.md`, `wiki/flows/generic-gate-host.md`, `wiki/sdd-tooling/sdd/expert-consult.md` from `sdd/templates/techwiki-page.md`.
- Register them in `wiki/_index.yaml` if the index requires it (check how other pages are listed).

**NOT in scope**: Code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/experts/expert-stages-and-scope-grid.md` | CREATE | page |
| `wiki/flows/generic-gate-host.md` | CREATE | page |
| `wiki/sdd-tooling/sdd/expert-consult.md` | CREATE | page |
| `wiki/_index.yaml` | MODIFY | index entries if required |
| `packages/ai-parrot/tests/experts/test_expert_stages_docs.py` | CREATE | pages exist and name the public symbols they document |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
# none beyond the standard library and pydantic
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
      "path": "wiki/experts/expert-stages-and-scope-grid.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/flows/generic-gate-host.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/sdd-tooling/sdd/expert-consult.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/_index.yaml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_expert_stages_docs.py",
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
1. Read the template and one existing page.
2. Write pages.
3. Run the techwiki check.

### Blocks

```markdown
<!-- each page from sdd/templates/techwiki-page.md — FILL IN content from the implemented code, not from the spec -->
```

### FILL IN checklist
- [ ] page content

---

## Acceptance Criteria

- [ ] AC17: also run (acceptance, not a registered runner) `parrot sdd techwiki check --spec sdd/specs/expert-stages-and-delegation.spec.md --root .`.

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_expert_stages_docs.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5632 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
