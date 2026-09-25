# TASK-3802: Measure the merge-tier cost reduction against the FEAT-601-shaped baseline

**Feature**: FEAT-604 — Merge-Tier Validation Cost
**Spec**: `sdd/specs/merge-tier-validation-cost.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3798, TASK-3800
**Assigned-to**: unassigned

---

## Context

Spec Goal 4 and AC8: "The cost reduction is measured against the same
FEAT-601-shaped baseline, not asserted." The spec's own problem statement is a
measurement (27 invocations, 26 full suites, `select_tests --tier merge` on
the FEAT-601 worktree, 2026-09-25, pre-#1494); this task closes the loop by
producing the after numbers on the same shape of worktree with M1/M2 landed,
and recording before/after in an evidence file the feature PR cites.

---

## Scope

- Reconstruct a FEAT-601-shaped selection: a worktree whose diff against the
  merge base touches the same breadth of files (if the original
  `feat-FEAT-601-training-agent` worktree still exists, use it; otherwise any
  branch whose merge-tier selection escalates ≥ 20 distributions is an
  acceptable stand-in — record which one was used).
- Run the merge-tier selection TWICE over unchanged content with a green
  first run recorded (either via `select_tests --run` on a cheap subset
  strategy is NOT acceptable — use the ledger-write path honestly: seed the
  ledger by running `--run` where feasible, or record green escalations via
  the public `record_green_escalation` API with the plan's own
  `cap_hits`/`cap_impacted`, which is exactly what the supervisor writes).
- Record: invocation count and escalated/skipped lists for run 1 vs run 2;
  AC8 requires run 2 to plan **strictly fewer** pytest invocations.
- Write `artifacts/logs/feat-604-merge-cost.md` with the before (from the
  spec's §1 baseline), run-1 and run-2 numbers, commands used, and worktree
  identity (`git add -f` — the path is git-ignored).

**NOT in scope**: any production code change. If run 2 does NOT plan strictly
fewer invocations, this task FAILS and files the defect — it does not patch
around it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/logs/feat-604-merge-cost.md` | CREATE | before/after measurement evidence (git add -f) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# CLI, not imports — the measurement uses the public entry points:
#   python -m scripts.sdd.select_tests --worktree <path> --tier merge [--json] [--run]
#   (baseline invocation shape: spec §1 problem statement, verified 2026-09-25)
from parrot.flows.dev_loop.test_scope.context import record_green_escalation, read_ledger  # verified: context.py:101,82
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # verified: select.py:122
```

### Existing Signatures to Use
```python
# after TASK-3797/3798/3800:
plan.invocations: tuple[PytestInvocation, ...]
plan.escalated / plan.skipped_escalations: tuple[str, ...]
plan.cap_hits: dict[str, tuple[str, ...]];  plan.cap_impacted: dict[str, str]
record_green_escalation(worktree, hit_dists, core_files, impact_files=(), impacted_hashes={})
# ledger location: <per-worktree git dir>/parrot-test-scope-escalations.json (context.py:16)
```

### Does NOT Exist
- ~~a `--baseline` or `--compare` flag on select_tests~~ — compare the two
  runs' output yourself (`--json` gives machine-readable plans).
- ~~AC8 satisfied by unit tests~~ — the integration test
  (`test_second_merge_validation_skips_unchanged_suites`, TASK-3800) proves
  the mechanism on a temp repo; THIS task proves it at monorepo scale.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/logs/feat-604-merge-cost.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_green_escalation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Run selections from the MAIN checkout against the target worktree
  (`--worktree <path>`), venv activated; the ledger lands in the target's
  per-worktree git dir, not the main checkout's.
- Seeding greens via the API is legitimate ONLY with the plan's own
  `cap_hits`/`cap_impacted`/`core_hits` values — never hand-crafted hashes;
  the point is to measure the skip path with real writer inputs.
- Record the numbers as text in the evidence file, and put the before/after
  pair in the feature PR description (AC8: "recorded in the PR").
- Do NOT actually execute the escalated suites to seed greens if wall time is
  prohibitive — the API-seeding path above exists precisely because AC8
  measures the SELECTION, not suite runtime.

---

## Implementation Blueprint

### Steps (in order)
1. Pick/build the worktree and record its identity + diff breadth — *why*:
   "FEAT-601-shaped" must be auditable, not vibes.
2. Run 1: `select_tests --tier merge --json` → save plan JSON; seed green
   records for its escalated distributions via `record_green_escalation`
   with the plan's own attribution values.
3. Run 2: same command, unchanged content → save plan JSON.
4. Diff the two plans; write the evidence file; `git add -f`.

### `artifacts/logs/feat-604-merge-cost.md` (CREATE)
```markdown
# FEAT-604 — merge-tier cost, before/after (AC8)

Baseline (spec §1, 2026-09-25, pre-#1494): 27 invocations, 26 full package suites,
ledger-skipped escalations: 0 (FEAT-601 worktree).

Worktree used: <path + branch + HEAD sha>
Diff breadth: <N changed files, M distributions impacted>
Command: python -m scripts.sdd.select_tests --worktree <path> --tier merge --json

| run | invocations | escalated | skipped_escalations |
|---|---|---|---|
| 1 (cold ledger) | FILL IN | FILL IN | FILL IN |
| 2 (unchanged content, green ledger) | FILL IN | FILL IN | FILL IN |

AC8 verdict: run 2 plans strictly fewer invocations: <yes/no — numbers>
Seeding method: <--run subset | record_green_escalation with plan-derived args>
```
**Why**: this file is the PR's citation for AC8; the table mirrors the spec's
own §1 measurement so before/after read side by side.

### FILL IN checklist
- [ ] worktree identity + both runs' numbers — bounded by AC8 "strictly fewer, recorded in the PR"

---

## Acceptance Criteria

- [ ] Second consecutive merge-tier selection over unchanged content plans STRICTLY fewer invocations than the first (AC8)
- [ ] Skipped distributions appear in `skipped_escalations` in run 2's plan output
- [ ] Evidence file committed (`git add -f`) and numbers copied into the feature PR description
- [ ] `pytest tests/sdd_scripts/test_select_tests.py -q` passes (CLI unbroken by the measurement session)

---

## Validation Commands

- `pytest tests/sdd_scripts/test_select_tests.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`

---

## Test Specification

No new test file: the deliverable is measured evidence. The Validation
Commands re-run the suites that pin the mechanisms this measurement exercises.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context — §1 baseline, Goal 4, AC8
2. **Check dependencies** — TASK-3798 and TASK-3800 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before running anything
4. **Update status** in the per-spec index → `"in-progress"`
5. **Measure** per the Steps; if run 2 is not strictly cheaper, STOP and file the defect (ledger issue), do not patch around it
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
