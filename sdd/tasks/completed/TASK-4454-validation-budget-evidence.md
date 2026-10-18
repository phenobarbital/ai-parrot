# TASK-4454: Measure the merge < 2 min / feature < 5 min budgets and document the flow

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4443, TASK-4450, TASK-4451, TASK-4453
**Assigned-to**: unassigned

---

## Context

Spec §5 AC "Replaying the FEAT-698 plans with a representative contract yields a merge-tier run < 2 min and
a feature-tier run < 5 min (evidence in `artifacts/logs/`)", and the template's "Documentation updated in
`docs/`". The baseline numbers come from the brainstorm: merge tier 2,990 tests/merge, feature tier 2,562,
FEAT-698 closeout 11,272 executions / 1,339 s.

---

## Scope

- Replay with the FEAT-699 selector, in a scratch worktree of the FEAT-698 tip `d7e03cb93` against its fork
  point `49806c49f` (`git worktree add --detach` under `.claude/worktrees/`, removed afterwards):
  1. write a temporary per-spec index for FEAT-698 with a representative `test_contract` (the FEAT-698 tasks'
     own validation test files — read them from `sdd/tasks/completed/` for FEAT-698) using
     `scripts/sdd/cache_test_contract.py`-compatible JSON (or `contract_to_header`);
  2. `python -m scripts.sdd.select_tests --tier merge --base 49806c49f --index <tmp idx> --json` and
     `--tier feature` — record collected test counts (`pytest --co -q` over each planned argv) and wall time of
     a `--run` for each tier (`/usr/bin/time -f %e`), plus a second merge `--run` to show the cache hit;
  3. same replay with the contract REMOVED (fallback mode) for comparison.
- Write raw evidence to `artifacts/logs/feat-699-budget.md` (git-ignored — `git add -f`) and a curated,
  tracked doc `docs/sdd/test-selection-validation-contract.md`: how the contract is authored/cached, the two
  modes, cache + baseline semantics, the nightly net, and a "Measured" table (before vs after, both tiers).
- Doc test `tests/sdd_scripts/test_feat699_budget_doc.py`: the doc exists, has the Measured table with a
  merge row < 120 s and a feature row < 300 s (parse the seconds column), and names the commits measured.
- If a budget is MISSED: do not tune numbers — record the real figures, mark the task `done-with-issues`,
  and open a ledger issue (`wikitoolkit ledger open --kind tech_debt --discovered-from spec:FEAT-699 ...`)
  describing the gap; the doc test then asserts the doc honestly reports "budget missed".

**NOT in scope**: any selector change (feed findings back as ledger issues).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/sdd/test-selection-validation-contract.md` | CREATE | User-facing doc + Measured table |
| `artifacts/logs/feat-699-budget.md` | CREATE | Raw evidence (`git add -f`) |
| `tests/sdd_scripts/test_feat699_budget_doc.py` | CREATE | Doc/budget contract test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `scripts/sdd/select_tests.py` flags after TASK-4450: `--tier --base --index --json --run --fresh/--use-cache --no-ledger`.
- FEAT-698 commits (from the brainstorm, re-verify with `git cat-file -t`): tip `d7e03cb93`, fork point `49806c49f`.
- FEAT-698 completed tasks: `sdd/tasks/completed/` files whose header says `FEAT-698` (grep `**Feature**: FEAT-698`).
- Worktree test caveat: run pytest with `PYTHONPATH=<scratch>/packages/ai-parrot/src` and copy
  `packages/ai-parrot/src/parrot/utils/*.so` from the main checkout into the scratch worktree.

### Does NOT Exist
- ~~`docs/sdd/test-selection-validation-contract.md`~~ — created here
- ~~a replay script~~ — this is a one-off measurement; do NOT add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/sdd/test-selection-validation-contract.md", "action": "CREATE"},
    {"path": "artifacts/logs/feat-699-budget.md", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_feat699_budget_doc.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create the scratch worktree + temp index — *why*: measure the real FEAT-698 diff, not a toy.
2. Run the six measurements (merge/feature × contract/fallback, + cached second merge) — *why*: §5 AC.
3. Write raw log, curated doc, doc test; remove the scratch worktree (`git worktree remove`, never `--force` on a dirty tree you did not create).

### `docs/sdd/test-selection-validation-contract.md` (CREATE)
```markdown
# Test selection in the SDD flow — the Validation Contract (FEAT-699)

## Authoring
<!-- FILL IN: spec §4 subsection format, `none — fallback`, real_llm rule, /sdd-task caching command -->

## How plans are built
<!-- FILL IN: contract vs fallback table (task/merge/feature), file-level mirror, no suite escalation -->

## Green cache and baseline verdict
<!-- FILL IN: cached targets, invalidation inputs, new red / baseline red / unknown, feature tier fresh -->

## Safety net
<!-- FILL IN: .github/workflows/nightly-tests.yml -->

## Measured (FEAT-698 replay, commits d7e03cb93 vs 49806c49f)

| Tier | Mode | Tests collected | Wall time (s) |
|---|---|---:|---:|
| merge | before (FEAT-563 heuristics) | 2990 | 87 |
| feature | before (FEAT-563 heuristics) | 2562 | — |
<!-- FILL IN: measured rows: merge/contract, merge/contract (cached 2nd run), feature/contract, merge/fallback, feature/fallback -->
```

### FILL IN checklist
- [ ] measurements + raw log
- [ ] doc sections + Measured rows (real numbers only)
- [ ] doc test (seconds parse; budgets or honest "budget missed")
- [ ] scratch worktree removed

---

## Acceptance Criteria

- [ ] Measured merge-tier (contract mode) < 120 s and feature-tier < 300 s — OR the doc reports the miss and a ledger issue exists.
- [ ] Doc test passes; raw evidence committed with `git add -f`.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_feat699_budget_doc.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_feat699_budget_doc.py
def test_measured_budgets_reported():
    # FILL IN: parse the Measured table; merge/contract row seconds < 120 and feature/contract < 300,
    #          unless the doc contains "budget missed"
    ...
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4454 tests-optimization-sdd-flow verified`
(or `partial` when a budget is missed — see Scope).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
