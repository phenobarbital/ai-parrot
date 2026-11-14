# TASK-5630: "Consult experts" step in /sdd-proposal and /sdd-spec (+ twins)

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-5629
**Assigned-to**: unassigned

---

## Context

Spec §2.6 / Module 9, AC14. Twins must stay in sync (memory: edit both suites; `.claude/` and `.agents/` may need `git add -f`).

---

## Scope

- Add an optional, non-blocking "Consult experts" step to `.claude/commands/sdd-proposal.md` and `.claude/commands/sdd-spec.md` (before drafting the design sections): run consult, list findings, triage each CONFIRM/REJECT/ESCALATE, fold CONFIRMed findings with a reference to the contribution file, ESCALATE → §8 question.
- `/sdd-spec` §6: promote `sdd/state/.contributions/<slug>/` to `sdd/state/<FEAT-ID>/contributions/` like design research.
- Mirror into `.agent/workflows/sdd-{proposal,spec}.md` and `.agents/skills/sdd-{proposal,spec}/SKILL.md`.

**NOT in scope**: Code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-proposal.md` | MODIFY | step |
| `.claude/commands/sdd-spec.md` | MODIFY | step + promotion |
| `.agent/workflows/sdd-proposal.md` | MODIFY | twin |
| `.agent/workflows/sdd-spec.md` | MODIFY | twin |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | twin |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | twin |
| `packages/ai-parrot/tests/sdd/test_consult_step_twins.py` | CREATE | asserts the step and the experts_cli.py commands appear in all six files |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-proposal.md` | MODIFY | packaged mirror, required by check_asset_sync |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-spec.md` | MODIFY | packaged mirror, required by check_asset_sync |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-proposal.md` | MODIFY | packaged mirror, required by check_asset_sync |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-spec.md` | MODIFY | packaged mirror, required by check_asset_sync |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-proposal/SKILL.md` | MODIFY | packaged mirror, required by check_asset_sync |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-spec/SKILL.md` | MODIFY | packaged mirror, required by check_asset_sync |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
# none beyond the standard library and pydantic
```

### Existing Signatures to Use
```python
# .claude/commands/sdd-spec.md:433 "Identify delegation-eligible modules" — unrelated (sdd-coder), do not conflate
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- Check whether a twin-sync test exists (grep tests for `sdd-spec.md`) and keep it green; if the installer ships these files from `parrot/sdd/_assets`, update that copy too (grep `_assets` for sdd-spec).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/sdd-proposal.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-proposal.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-proposal/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-spec/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_consult_step_twins.py",
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
1. Locate anchors; write the step once, copy to twins.
2. Run any twin-sync tests.

### Blocks

```markdown
<!-- each command file (MODIFY) — insert a new subsection; anchor chosen at task time: run grep -n '^### ' on the file and insert before the step that drafts §2 (spec) / the synthesis (proposal). FILL IN: exact anchor + occurrence count. -->
### Consult experts (optional, advisory — FEAT-890)
Run `parrot sdd experts consult --doc <doc> [--feature <FEAT-ID>]`. ...
```

### FILL IN checklist
- [ ] anchors
- [ ] _assets copies if they exist

---

## Acceptance Criteria

- [ ] AC14.
- [ ] Twin parity and asset-sync tests pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_consult_step_twins.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5630 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5630
- Feature: expert-stages-and-delegation
- Implementation SHA: 744cc734f6f7f05901b68976ed3712616f52233e
- Closed at (UTC): 2026-11-13T23:44:12+00:00
- Fix commits: 206721ae905964195ca15d3b950d1f11af148429, 2a3094e275708e9b7181bc4707496e513dd70bda

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 2 |
| seat_summary | Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 473.6s · Tokens: 3.09M in / 15.0k out (adopted by cherry-pick after fidelity_violation) |
