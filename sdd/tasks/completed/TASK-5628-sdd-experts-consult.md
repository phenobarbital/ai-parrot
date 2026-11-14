# TASK-5628: Contribution models and `parrot sdd experts consult`

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-5625
**Assigned-to**: unassigned

---

## Context

Spec §2.6 / Module 8, AC13. Advisory only; never blocks.

---

## Scope

- Create `parrot/sdd/experts_cli.py` with click group `experts` (registered on the `sdd` group) and command `consult --doc <path> [--feature FEAT-NNN]`.
- Models `Finding`, `Contribution` (spec §2 Data Models) in `parrot/experts/contributions.py`.
- Match: read the doc frontmatter `projects`/`tags` (`parrot sdd docs taxonomy` logic — reuse its function), pick scopes whose `match` intersects, run their stages, ask experts for findings as JSON matching `Finding`; write `sdd/state/<FEAT>/contributions/<slug>.json`, or `sdd/state/.contributions/<doc-slug>/` without a feature id.
- Digest of the doc stored; existing contribution with another digest → `stale: true`.
- No match → print one line, exit 0.
- Tests with fake experts.

**NOT in scope**: triage/promote (TASK-5629); command steps (TASK-5630).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/contributions.py` | CREATE | models + io |
| `packages/ai-parrot/src/parrot/sdd/experts_cli.py` | CREATE | consult command |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | register group |
| `packages/ai-parrot/tests/sdd/test_experts_consult.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
import click
from parrot.experts.grid.loader import load_scopes  # TASK-5625
from parrot.experts.grid.compiler import compile_scope  # TASK-5625
```

### Existing Signatures to Use
```python
# sdd/cli.py:71 @click.group(name="sdd") def sdd(); :400 sdd.add_command(_launch)
# taxonomy reader: grep `def ` in the module behind `parrot sdd docs taxonomy` before reusing
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
      "path": "packages/ai-parrot/src/parrot/experts/contributions.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/experts_cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_experts_consult.py",
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
1. Find the taxonomy helper.
2. Write models + CLI.
3. Tests (CliRunner, tmp repo).

### Blocks

```python
# packages/ai-parrot/src/parrot/sdd/cli.py (MODIFY) — AFTER `sdd.add_command(_launch)` (verified: sdd/cli.py:400; occurrences: 1)
from parrot.sdd.experts_cli import experts as _experts  # noqa: E402
sdd.add_command(_experts)
```
```python
# packages/ai-parrot/src/parrot/experts/contributions.py  (CREATE) — Finding / Contribution per spec §2 Data Models, plus
def contribution_dir(repo_root: "Path", *, feature_id: str | None, doc_slug: str) -> "Path": ...  # FILL IN
def load_contribution(path: "Path") -> "Contribution": ...
def save_contribution(path: "Path", c: "Contribution") -> None: ...
```
**Why**: models live in parrot.experts so triage/promote and the stage node can share them without importing the CLI.

### FILL IN checklist
- [ ] finding-extraction prompt + JSON parse with fallback
- [ ] matching
- [ ] tests

---

## Acceptance Criteria

- [ ] AC13.

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_experts_consult.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5628 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5628
- Feature: expert-stages-and-delegation
- Implementation SHA: a3f3dd4e7fd06d749643547a0699ea9965993d02
- Closed at (UTC): 2026-11-13T22:46:06+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
