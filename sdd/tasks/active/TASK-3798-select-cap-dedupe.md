# TASK-3798: select.py — cap escalations consult and feed the ledger

**Feature**: FEAT-604 — Merge-Tier Validation Cost
**Spec**: `sdd/specs/merge-tier-validation-cost.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3797
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, selection side. Today the cap branch (`select.py:177`)
escalates unconditionally: `len(paths) > policy.impact_cap` → whole suite,
every merge, with no record of what content it covered. With TASK-3797's
ledger machinery in place, this task makes `plan_tests` (a) attribute each
cap escalation to the changed files that drove it, (b) fingerprint the
impacted set (sha256 of the sorted paths — resolved Open Question 1), and
(c) route cap escalations through `pending_escalations` so a cap escalation
that went green for unchanged content is SKIPPED on the next selection, and
carried on the plan (`cap_hits`/`cap_impacted`) for the writers
(TASK-3799/TASK-3800) to record.

---

## Scope

- In `plan_tests`' merge-tier cap branch: collect cap candidates instead of
  escalating immediately; compute per-distribution driving changed files and
  the impacted-set sha256.
- Driving-file attribution: for each changed file with a source module,
  compute its own impacted set once (`impacted_tests(index, [path], ...)`);
  a changed file DRIVES distribution `d` when its impacted set intersects
  `by_dist[d]`.
- Call `pending_escalations(worktree, hits, cap_hits, cap_impacted)` ONCE for
  both kinds (replacing the core-only call at `select.py:191`); skipped cap
  distributions get NO suite target and NO per-test import targets, land in
  `skipped_escalations`, and add a note
  (`f"{dist}: cap escalation skipped — ledger blobs and impacted hash match"`).
- Pass `cap_hits`/`cap_impacted` through `build_plan` onto the `ScopePlan`.
- Plan-level tests appended to `test_cap_escalation_ledger.py`.

**NOT in scope**: `datatypes.py`/`context.py`/`planner.py` (TASK-3797),
CLI/QA/supervisor writers (TASK-3799/3800), `policy.py` (TASK-3801). Never
change `DEFAULT_IMPACT_CAP` or `CORE_PATHS` (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | cap branch: attribution + fingerprint + ledger consult |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` | MODIFY | plan-level tests (created by TASK-3797) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # verified: select.py:122 (plan_tests)
from parrot.flows.dev_loop.test_scope.impact import ImportIndex, impacted_tests, module_name_for  # verified: impact.py:112,234,25
from parrot.flows.dev_loop.test_scope.context import pending_escalations  # verified: context.py:134 (TASK-3797 adds cap params)
import hashlib  # stdlib — test_scope is stdlib-only
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
def plan_tests(*, worktree, changed_files, tier, declared=(), policy=None) -> ScopePlan:  # line 122
#   cap branch (verbatim, lines 171-186):
#     if index is not None and tier == "merge":
#         impacted = impacted_tests(index, list(changed_files), worktree=worktree, depth=policy.impact_depth)
#         by_dist: dict[str, list[str]] = {}
#         ...
#         for dist, paths in by_dist.items():
#             if len(paths) > policy.impact_cap:            # line 177
#                 escalated.append(dist)
#                 suite = _suite_for(dist, worktree)         # line 179
#                 ...
#             else:
#                 targets += [TestTarget(path=path, distribution=dist, reason="import") for path in paths]
#   core branch call to replace: to_run, ledger_skipped = pending_escalations(worktree, hits)  # line 191
#   plan constructor: return build_plan(targets, tier=..., escalated=..., core_hits=hits,
#                                       skipped_escalations=skipped, notes=notes)  # lines 207-216
def _suite_for(distribution: str, worktree: Path) -> str | None: ...  # line 66
def _dist(path: str) -> str: ...  # module-level helper used by the cap branch

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py
def impacted_tests(index, changed, *, worktree, depth) -> list[str]: ...  # line 234 (sorted)
def module_name_for(path: str) -> str | None: ...  # line 25 (None for non-source paths)

# after TASK-3797:
def pending_escalations(worktree, hits, cap_hits={}, cap_impacted={}) -> tuple[list[str], list[str]]
def build_plan(..., cap_hits=None, cap_impacted=None) -> ScopePlan
```

### Does NOT Exist
- ~~a per-file impact cache on `ImportIndex`~~ — compute the per-changed-file
  impacted sets locally in the cap branch (the index is already built; each
  call is a cheap BFS).
- ~~`ScopePlan.cap_hits` before TASK-3797 lands~~ — verify it exists before starting.
- ~~a `TestTarget` reason value `"cap"`~~ — cap suites keep `reason="escalated"`
  (`planner.py:17` priority map: declared|core|escalated|import|mirror).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#_suite_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#impacted_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#module_name_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#pending_escalations"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The fingerprint is `hashlib.sha256("\n".join(sorted(paths)).encode("utf-8")).hexdigest()`
  over the distribution's impacted-test paths — deterministic because
  `impacted_tests` returns sorted paths already.
- A skipped cap distribution contributes NOTHING to targets (neither suite nor
  the >cap import targets): the recorded green run is what covers it.
- A distribution escalated by BOTH cap and core must be skipped only when both
  checks pass — `pending_escalations` (TASK-3797) owns that rule; this task
  just supplies both inputs in one call.
- Order note: the core branch (`detect_core`, line 188) runs AFTER the cap
  branch; restructure so the single `pending_escalations` call happens after
  both candidate sets exist, then append suite targets only for `to_run`.
- Fail-open: any error computing attribution (e.g. `module_name_for` → None
  for every changed file) yields empty driving sets for that dist ⇒ it cannot
  be skipped ⇒ it runs. Never let attribution failure block escalation itself.

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3797's fields/signatures landed (`grep impacted_hash …/datatypes.py`)
   — *why*: this task's imports depend on them; drift means stop, not invent.
2. Restructure the cap branch to collect candidates — *why*: the skip decision
   needs core hits too, which are only known after `detect_core`.
3. Add attribution + fingerprint helpers — *why*: they define what "unchanged
   content" means for a cap skip (resolved Open Question 1).
4. Single `pending_escalations` call; emit targets/notes/skipped from its answer.
5. Pass `cap_hits`/`cap_impacted` to `build_plan`; extend tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'if len(paths) > policy.impact_cap:' …/test_scope/select.py)
# REPLACE the cap branch body — anchor `if len(paths) > policy.impact_cap:` (verified: select.py:177).
# The loop becomes a collection pass; suites are appended AFTER the ledger consult below.
        cap_candidates: dict[str, list[str]] = {}
        if index is not None and tier == "merge":
            impacted = impacted_tests(index, list(changed_files), worktree=worktree, depth=policy.impact_depth)
            by_dist: dict[str, list[str]] = {}
            for path in impacted:
                by_dist.setdefault(_dist(path), []).append(path)
            per_file_impact: dict[str, set[str]] = {
                p: set(impacted_tests(index, [p], worktree=worktree, depth=policy.impact_depth))
                for p in changed_files
                if module_name_for(p) is not None
            }
            for dist, paths in by_dist.items():
                if len(paths) > policy.impact_cap:
                    cap_candidates[dist] = paths
                    notes.append(
                        f"{dist}: {len(paths)} impacted tests exceed cap {policy.impact_cap}, escalated to suite"
                    )
                else:
                    targets += [TestTarget(path=path, distribution=dist, reason="import") for path in paths]
            cap_hits = {
                dist: tuple(sorted(p for p, tests in per_file_impact.items() if tests & set(paths)))
                for dist, paths in cap_candidates.items()
            }
            cap_impacted = {
                dist: hashlib.sha256("\n".join(sorted(paths)).encode("utf-8")).hexdigest()
                for dist, paths in cap_candidates.items()
            }
```
```python
# occurrences: 1 (verified: grep -cF 'to_run, ledger_skipped = pending_escalations(worktree, hits)' …/select.py)
# REPLACE — anchor `to_run, ledger_skipped = pending_escalations(worktree, hits)` (verified: select.py:191).
# Move the call OUT of the `if hits:` guard so cap-only selections still consult the ledger:
            to_run, ledger_skipped = pending_escalations(worktree, hits, cap_hits, cap_impacted)
            # FILL IN: for dist in to_run — append the suite target with reason "core" when the
            # dist has a core hit, else reason "escalated" (cap); keep the existing
            # missing-suite note; extend `escalated` for both kinds as today. For dists in
            # ledger_skipped that are cap candidates, add the skip note. `skipped = ledger_skipped`.
            # Bounded by: AC "second selection over unchanged content omits their invocations";
            # existing dedupe (planner._REASON_PRIORITY) resolves a dist that is both kinds.
```
```python
# occurrences: 1 (verified: grep -cF 'return build_plan(' …/test_scope/select.py)
# MODIFY the constructor call — anchor `return build_plan(` (verified: select.py:207): add
#     cap_hits=cap_hits,
#     cap_impacted=cap_impacted,
# (define both as {} before the tier != "task" block so task-tier plans carry empty maps).
```
**Why**: the collection-then-consult restructure is what lets one
`pending_escalations` call answer for both kinds (spec component diagram);
per-file impact sets give the exact "driving files" the spec's `cap_hits`
contract names. `hits`/`cap_hits` must both be defined (empty) on every path
reaching `build_plan`, including non-git and task-tier paths.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` (MODIFY)
```python
# AFTER — append at end of file (created by TASK-3797):

def test_plan_reports_cap_driving_files(tmp_path: Path) -> None:
    """ScopePlan.cap_hits names the changed files per cap-escalated distribution (spec §4)."""
    # FILL IN: temp repo with a low-cap ScopePolicy(impact_cap=0-ish) fixture so one changed
    # source file escalates its distribution; assert plan.cap_hits == {dist: (changed_file,)}
    # and plan.cap_impacted[dist] is a 64-char hex digest.


def test_second_selection_skips_unchanged_cap_suite(tmp_path: Path) -> None:
    """Green record + identical content ⇒ second plan_tests omits the suite invocation and
    reports the dist in skipped_escalations (AC: strictly fewer invocations)."""


def test_cap_skip_rearmed_by_impacted_set_change(tmp_path: Path) -> None:
    """Adding a NEW test file importing the changed module (driving blobs unchanged) changes
    the impacted set ⇒ impacted_hash mismatch ⇒ suite planned again (AC re-arm)."""
```
**Why**: these are the spec §4 plan-level rows (`test_plan_reports_cap_driving_files`,
`test_cap_escalation_skipped_when_blobs_match` at plan level, and the
impacted-set re-arm AC added by resolved Open Question 1).

### FILL IN checklist
- [ ] `select.py` — to_run/skipped target emission incl. both-kinds reason choice; bounded by planner reason priority (core > escalated)
- [ ] `select.py` — `cap_hits`/`cap_impacted`/`hits` defined empty on all early paths (task tier, non-git, no index)
- [ ] test bodies per docstrings — use a tiny `ScopePolicy(impact_cap=<small>)` override, never patch the defaults

---

## Acceptance Criteria

- [ ] `ScopePlan.cap_hits` names the driving changed files per cap-escalated distribution
- [ ] `ScopePlan.cap_impacted` carries the sha256 of each cap-escalated dist's sorted impacted set
- [ ] Second selection over identical content skips the cap-escalated suite (in `skipped_escalations`, no invocation)
- [ ] Any driving-file content change OR impacted-set change re-arms the distribution
- [ ] Task-tier and non-git selections are byte-identical to before (empty cap maps)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q` passes
- [ ] `ruff check` and `black -l 120 --check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

See the MODIFY block above — three plan-level tests with docstrings; bodies
are FILL IN. Reuse the real-git fixture from TASK-3797's file.

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3797 must be in `sdd/tasks/completed/`
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
