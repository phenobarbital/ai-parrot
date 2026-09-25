# TASK-3801: xdist safety evidence — measure, populate XDIST_SAFE_DISTRIBUTIONS

**Feature**: FEAT-604 — Merge-Tier Validation Cost
**Spec**: `sdd/specs/merge-tier-validation-cost.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h wall clock; ~2h measurement budget by decision)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `XDIST_SAFE_DISTRIBUTIONS` (`policy.py:740`) is an empty
`frozenset()` because the FEAT-563 S3 spike (`artifacts/logs/feat-563-s3-xdist.md`)
could not complete a single serial `ai-parrot` pass (≈2.3h extrapolated) inside
its budget and fail-safed to excluding everything. Every escalated suite
therefore runs single-process. This task re-runs the comparison as a bounded,
RESUMABLE per-distribution job under the budget and scope fixed by resolved
Open Question 2 (spec §3 M3 + §8).

**This is an orchestrator-run measurement task, NOT delegation-eligible**
(spec §3 delegation table: the pass/fail criterion is a measurement
judgement). Its wall-clock runs must not share the machine with other tasks'
test runs — it is `parallel: false` (exclusive) in the index.

---

## Scope

- Protocol per distribution (spec M3): 1 serial baseline + 2 `-n auto` runs,
  comparing **per-test outcomes** (junitxml nodeids + status), not summary
  counts. A distribution enters the safe set ONLY when both xdist runs agree
  with serial.
- Budget & scope (resolved OQ2): **~2h total**, smallest distributions first,
  covering every distribution EXCEPT the three pre-excluded on cited
  evidence — `ai-parrot` (≈2.3h/serial pass, S3 log), `ai-parrot-integrations`
  (deterministic hang, ledger `1dbb2aac09ba`), `ai-parrot-server` (contention
  flakiness, ledger `e21ec87c6aba`). Record those three as excluded WITH the
  citations; do not re-measure them.
- Resumable: write per-distribution results to the evidence file as they
  complete, so a rerun skips finished distributions (the S3 spike's failure
  mode was all-or-nothing).
- Populate `XDIST_SAFE_DISTRIBUTIONS` with exactly the distributions that
  passed twice; every excluded distribution gets a recorded reason (and wall
  time when measured).
- Evidence file: `artifacts/logs/feat-604-xdist.md` (git-ignored path —
  `git add -f` when committing).

**NOT in scope**: parallelising across distributions in the supervisor (spec
Non-Goal); changing `planner.py` (the `-n auto` wiring exists and is tested:
`test_planner.py::test_xdist_only_for_allowlisted_dist`); fixing the two
ledger-cited defects.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | populate `XDIST_SAFE_DISTRIBUTIONS` from evidence |
| `artifacts/logs/feat-604-xdist.md` | CREATE | per-distribution evidence table (git add -f) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.policy import XDIST_SAFE_DISTRIBUTIONS, ScopePolicy  # verified: policy.py:740,751
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset(   # line 740 — EMPTY, with the S3 negative-result comment
@dataclass(frozen=True)
class ScopePolicy:                                      # line 751
    xdist_safe: frozenset[str] = XDIST_SAFE_DISTRIBUTIONS  # line 758

# the planner consumes it (already wired + tested — do not touch):
# planner.py:40  xdist = ("-n", "auto") if distribution in policy.xdist_safe else ()
# test_planner.py:36  test_xdist_only_for_allowlisted_dist

# measurement command shape MUST equal the planner's (S3 lesson, feat-563-s3-xdist.md):
# pytest -q --tb=short -p no:cacheprovider -o log_cli=false -m "not e2e and not real_llm and not integration" --confcutdir=<worktree>
# AGENT_FLAGS / AGENT_MARKER_EXPRESSION are defined in policy.py — read them, don't retype.
```

### Does NOT Exist
- ~~`ScopePolicy.xdist_cap` / per-distribution worker counts~~ — `-n auto` is
  the only xdist form (`planner.py:40`).
- ~~a committed measurement harness~~ — the runner script is scratch tooling;
  only the evidence file and the policy constant are deliverables. If you
  write a helper script, keep it out of the repo (scratchpad), or the diff
  fails the fidelity gate.
- ~~distribution names with a `packages/` prefix~~ — distribution ids are the
  short names (`ai-parrot-tools`, `parrot-formdesigner`, `root`, …) as
  `mirror.distribution_of` yields them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "MODIFY"},
    {"path": "artifacts/logs/feat-604-xdist.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py#ScopePolicy"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Two independent comparisons minimum; per-test outcome equality** — one
  lucky agreement converts a flaky suite into a silently flaky gate (spec §7).
- **Pre-existing red is not disagreement**: a test that fails identically in
  serial and both xdist runs COUNTS AS AGREEMENT (deterministic outcome
  equality), so suites with known stable failures are still measurable.
- Use an **absolute** `--junitxml` path — navconfig's import-time `os.chdir`
  made a relative one resolve against the main checkout in S3 (recorded in
  `feat-563-s3-xdist.md`).
- Suites needing `--continue-on-collection-errors` (e.g. ai-parrot-tools' 5
  pre-existing collection errors, per S3) get it in ALL THREE runs, so the
  compared universe is identical.
- Per-distribution wall-time cap: stop a distribution that exceeds ~3× its
  expected serial time (test-file count is the proxy; see the size table in
  spec §3 M3) and record it as excluded-with-wall-time. Wrap every run in
  `timeout -s KILL` (known post-summary hang: leaked non-daemon threads).
- Smallest-first order maximizes safe-set entries within the budget.

---

## Implementation Blueprint

### Steps (in order)
1. Write the evidence file skeleton FIRST with the three pre-excluded rows —
   *why*: the exclusions are decided (resolved OQ2), not measured; recording
   them up front makes the empty-set-so-far state honest if the budget dies early.
2. Enumerate remaining distributions smallest-first (test-file count) — *why*:
   budget discipline (resolved OQ2).
3. Per distribution: serial + 2× `-n auto`, junitxml to absolute scratch
   paths, diff nodeid→status maps, append the row (resumability = skip dists
   already in the table).
4. Populate `XDIST_SAFE_DISTRIBUTIONS` and replace the S3 comment.
5. `git add -f artifacts/logs/feat-604-xdist.md`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset(' …/test_scope/policy.py)
# REPLACE the constant + its interior comment — anchor `XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset(`
# (verified: policy.py:740):
# Measured safe under `-n auto` (same per-test outcome as serial, twice) — evidence:
# artifacts/logs/feat-604-xdist.md (FEAT-604 M3; supersedes the FEAT-563 S3 negative result).
# A distribution is added ONLY with a two-run comparison of its own; excluded distributions
# are listed in the evidence file with a recorded reason (and wall time when measured).
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        # FILL IN: exactly the distributions whose two xdist runs matched serial per-test —
        # bounded by AC "contains only distributions with a recorded two-run comparison".
    }
)
```
**Why**: the constant IS the deliverable; the comment must point at the new
evidence file so the set never again "looks accidental" (spec Goal 3).

### `artifacts/logs/feat-604-xdist.md` (CREATE)
```markdown
# FEAT-604 M3 — xdist safety per distribution

Date: <run date> · host cores: <N> · pytest <ver> · xdist <ver>
flags: <the planner-equal command line, verbatim>
Budget: ~2h (resolved spec §8 OQ2); smallest-first; resumable per distribution.

## Pre-excluded (decided, not measured — resolved OQ2)

| distribution | reason |
|---|---|
| ai-parrot | ≈2.3h per serial pass (artifacts/logs/feat-563-s3-xdist.md); stays serial — M1/M2 dedupe buys down its cost |
| ai-parrot-integrations | deterministic hang in test_handle_web_app_data_routes_to_strategy (ledger 1dbb2aac09ba) |
| ai-parrot-server | ~18 intermittent contention failures when run together (ledger e21ec87c6aba) |

## Measured

| distribution | tests | serial (s) | -n auto run1 (s) | run2 (s) | workers | disagreements | verdict |
|---|---|---|---|---|---|---|---|
<!-- FILL IN: one row per measured distribution, appended as each completes (resumability) -->

## Disagreements (first 30 per unsafe distribution)
<!-- FILL IN: nodeid + serial/xdist outcomes, or "None recorded" -->

## Decision
<!-- FILL IN: the final frozenset literal, matching policy.py exactly -->
```
**Why**: same table shape as the S3 record so the two artifacts are directly
comparable; the pre-excluded section carries the OQ2 citations verbatim.

### FILL IN checklist
- [ ] evidence rows + safe-set contents — bounded by "passes twice, per-test equality"
- [ ] `policy.py` set members — must equal the evidence file's Decision section

---

## Acceptance Criteria

- [ ] `XDIST_SAFE_DISTRIBUTIONS` contains ONLY distributions with a recorded two-run comparison in `artifacts/logs/feat-604-xdist.md`
- [ ] Every excluded distribution has a recorded reason; the three pre-excluded carry their citations; measured-but-failed ones carry wall time
- [ ] The measured command shape equals the planner's (AGENT_FLAGS + marker expression + --confcutdir)
- [ ] Evidence file appended per distribution (resumable), committed with `git add -f`
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q` passes (xdist flag wiring unchanged, allowlist honored)
- [ ] `ruff check` and `black -l 120 --check` clean on `policy.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py -q`

---

## Test Specification

No new test file: the deliverable is measured evidence + a data change.
`test_planner.py::test_xdist_only_for_allowlisted_dist` already pins the
consumption behaviour; the Validation Commands above prove nothing regressed.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context — §3 M3, §7 gotchas, §8 OQ2
2. **Check dependencies** — none, but this task is EXCLUSIVE: never run it while another task's suites run on this machine (timings become meaningless)
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in the per-spec index → `"in-progress"`
5. **Measure**, appending evidence per distribution; then edit `policy.py`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (include total wall time spent vs the ~2h budget)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
