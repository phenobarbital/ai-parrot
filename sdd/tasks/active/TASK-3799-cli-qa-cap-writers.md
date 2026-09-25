# TASK-3799: CLI + QA writers record cap escalations

**Feature**: FEAT-604 — Merge-Tier Validation Cost
**Spec**: `sdd/specs/merge-tier-validation-cost.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3797, TASK-3798
**Assigned-to**: unassigned

---

## Context

Spec §2 Integration Points: `scripts/sdd/select_tests.py --run` and
`nodes/qa.py::_record_green_escalations` are the two EXISTING ledger writers;
both currently attribute only core escalations (`reason == "core"`). With
TASK-3797/3798 landed, a cap escalation carries everything a writer needs on
the plan (`cap_hits`, `cap_impacted`). This task extends both writers so the
green/red attribution contract stays single-sourced across all three runner
paths (the third, the supervisor, is TASK-3800 and mirrors this one).

---

## Scope

- `scripts/sdd/select_tests.py --run`: treat `reason == "escalated"` targets
  as ledger-relevant too; green → `record_green_escalation` with the dist's
  `core_files` (if any core hit) plus `impact_files=plan.cap_hits.get(dist, ())`
  and `impacted_hashes={dist: plan.cap_impacted[dist]}` when present; red →
  `record_red_run` (unchanged call, now for both kinds).
- `nodes/qa.py::_record_green_escalations`: same extension; the criterion
  name marker distinguishes kinds (`" (core escalation)"` exists today —
  derive cap coverage from the plan, not from parsing new name markers, to
  keep the change minimal: for each green escalated criterion's dist, pass
  whatever the plan carries for that dist).
- `nodes/qa.py::_derive_feature_criteria` (`qa.py:607-614`): mark escalated
  invocations too so red cap runs re-arm — extend the `core` predicate to
  `t.reason in ("core", "escalated")` for the marker only if needed by the
  recorder; keep the label string `" (core escalation)"` VERBATIM (other code
  greps it) and do not invent a second marker unless the recorder cannot
  otherwise identify the dist.
- Extend the two existing test files.

**NOT in scope**: `background.py` (TASK-3800); any `test_scope/` module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/select_tests.py` | MODIFY | `--run` records cap escalations green/red |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | QA-path recorder covers cap escalations |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | cap-recording tests for the CLI |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py` | MODIFY | cap-recording tests for the QA path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/sdd/select_tests.py imports the kernel as `kernel` (path-dependent import);
# ledger calls are kernel.context.record_green_escalation / record_red_run (verified: select_tests.py:97,102)
from parrot.flows.dev_loop.test_scope.context import record_green_escalation  # verified: qa.py imports it already (qa.py:633 call site)
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py:88-103 (verbatim core of --run)
    exit_code = 0
    for invocation in plan.invocations:
        result = subprocess.run(list(invocation.argv), cwd=worktree)
        is_core_escalation = any(target.reason == "core" for target in invocation.targets)   # line 91
        if result.returncode != 0:
            exit_code = 1
            if is_core_escalation:
                kernel.context.record_red_run(worktree, [invocation.distribution])           # line 97
            continue
        if is_core_escalation:
            core_files = [hit.path for hit in plan.core_hits if invocation.distribution in hit.distributions]
            if core_files:
                kernel.context.record_green_escalation(worktree, [invocation.distribution], core_files)  # line 102

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
async def _record_green_escalations(self, shared, research, report) -> None:   # line 618
#   reads plan = shared.get("test_scope_plan"); early-returns when `plan is None or not plan.core_hits`
#   criterion name shape: f"pytest[{inv.distribution}]" + (" (core escalation)" if core else "")  # line 611
#   green record call: await asyncio.to_thread(record_green_escalation, Path(...), [dist], core_files)  # line 633
#   never raises: broad except → self.logger.warning                          # lines 634-635

# after TASK-3797/3798:
record_green_escalation(worktree, hit_dists, core_files, impact_files=(), impacted_hashes={})
plan.cap_hits: dict[str, tuple[str, ...]];  plan.cap_impacted: dict[str, str]
```

### Does NOT Exist
- ~~a `record_red_run` variant with impact arguments~~ — re-arm just drops the
  entry; one signature covers both kinds (TASK-3797 keeps it unchanged).
- ~~`plan.cap_hits` on a task-tier plan with content~~ — cap data exists only
  for merge-tier selections; both writers must tolerate empty maps.
- ~~a criterion-name marker `" (cap escalation)"`~~ — does not exist today;
  only add one if the recorder genuinely cannot resolve the dist without it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/select_tests.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_select_tests.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._record_green_escalations",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_green_escalation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#record_red_run"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Mirror `select_tests.py:88-102` — it "already encodes the R14/AC9c re-arm
  rule" (spec §7); do not invent a second contract.
- Ledger recording must NEVER fail the run: the QA path's broad
  except/`logger.warning` stays; the CLI path's calls are best-effort in the
  same way the existing ones are.
- `plan.core_hits` empty no longer means "nothing to record" on the QA path —
  the early return must also consider `plan.cap_hits`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the CLI writer — *why*: it is the reference contract the other two
   paths mirror; changing it first keeps them literal copies.
2. Extend the QA recorder + its early return — *why*: same dedupe on the
   dev-loop path (spec Integration Points row `nodes/qa.py:618`).
3. Extend both test files with a green-cap and a red-cap case each.

### `scripts/sdd/select_tests.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'is_core_escalation = any(target.reason == "core" for target in invocation.targets)' scripts/sdd/select_tests.py)
# REPLACE — anchor `is_core_escalation = ...` (verified: select_tests.py:91) and the two
# blocks using it:
        is_core_escalation = any(target.reason == "core" for target in invocation.targets)
        is_cap_escalation = any(target.reason == "escalated" for target in invocation.targets)
        if result.returncode != 0:
            exit_code = 1
            if is_core_escalation or is_cap_escalation:
                kernel.context.record_red_run(worktree, [invocation.distribution])
            continue
        if is_core_escalation or is_cap_escalation:
            dist = invocation.distribution
            core_files = [hit.path for hit in plan.core_hits if dist in hit.distributions]
            impact_files = list(plan.cap_hits.get(dist, ()))
            impacted_hashes = {dist: plan.cap_impacted[dist]} if dist in plan.cap_impacted else {}
            if core_files or impact_files:
                kernel.context.record_green_escalation(
                    worktree, [dist], core_files, impact_files=impact_files, impacted_hashes=impacted_hashes
                )
```
**Why**: keeps one attribution contract; a dist escalated by both kinds writes
one entry carrying both key sets, which is exactly what
`pending_escalations`'s dual check (TASK-3797) reads back.

### `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'async def _record_green_escalations(' …/nodes/qa.py)
# MODIFY the body — anchor `async def _record_green_escalations(` (verified: qa.py:618):
#   1. early return becomes: `if plan is None or (not plan.core_hits and not getattr(plan, "cap_hits", {})):`
#      (getattr guard keeps the node tolerant of a stale plan object in `shared`).
#   2. inside the loop, after resolving `dist`:
#        core_files = [hit.path for hit in plan.core_hits if dist in hit.distributions]
#        impact_files = list(getattr(plan, "cap_hits", {}).get(dist, ()))
#        impacted_hashes = ({dist: plan.cap_impacted[dist]} if dist in getattr(plan, "cap_impacted", {}) else {})
#        if not core_files and not impact_files: continue
#        await asyncio.to_thread(record_green_escalation, Path(research.worktree_path), [dist],
#                                core_files, impact_files, impacted_hashes)
# FILL IN: whether the criterion-name filter needs to also accept a cap marker — bounded by
# scope note: keep " (core escalation)" verbatim; derive cap coverage from the plan; only
# extend _derive_feature_criteria's marker if the recorder cannot resolve cap dists otherwise.
```
**Why**: the QA path must not silently diverge from the CLI contract; the
`getattr` guards keep `never raises` true even against an old cached plan.

### Test files (MODIFY — append)
```python
# tests/sdd_scripts/test_select_tests.py — append:
def test_run_records_green_cap_escalation(tmp_path):
    """--run on a green cap-escalated invocation writes impact_blobs + impacted_hash."""
    # FILL IN: reuse this file's existing plan/subprocess stubbing pattern; assert via read_ledger.

def test_run_rearms_red_cap_escalation(tmp_path):
    """--run on a red cap-escalated invocation drops the entry (record_red_run)."""

# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py — append:
def test_qa_records_cap_escalation_from_plan(tmp_path):
    """A green escalated criterion with plan.cap_hits writes the cap record; core-only plans unchanged."""
```
**Why**: spec §4 rows for the two writer paths; each file already stubs its
runner — follow the local pattern, never spawn real suites.

### FILL IN checklist
- [ ] `qa.py` — criterion→dist resolution for cap escalations without breaking the `" (core escalation)"` grep contract
- [ ] both test bodies — reuse each file's existing fixtures/stubs

---

## Acceptance Criteria

- [ ] `--run` records green cap escalations (impact blobs + hash) and re-arms red ones
- [ ] QA path records cap escalations; still never raises
- [ ] A dist escalated by both kinds writes ONE entry with both key sets
- [ ] Task-tier / cap-less plans behave byte-identically to before
- [ ] `pytest tests/sdd_scripts/test_select_tests.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py -q` passes
- [ ] `ruff check` and `black -l 120 --check` clean on touched files

---

## Validation Commands

- `pytest tests/sdd_scripts/test_select_tests.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py -q`

---

## Test Specification

See the test MODIFY blocks above — three tests with docstrings; bodies FILL IN.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3797 and TASK-3798 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code; if anything drifted, update the contract FIRST
4. **Update status** in the per-spec index → `"in-progress"`
5. **Implement** from the Implementation Blueprint; never change a fixed signature or path
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
