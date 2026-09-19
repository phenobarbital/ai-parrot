# TASK-3390: `fix_planner.py` — `decide_lane()`, `suggest_slug()`, `plan_fix_batch()` and parents

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3389
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (lane predicate, purity boundary), §3 Module 1 (`decide_lane`,
`suggest_slug`, `plan_fix_batch`), §8 resolved questions on `FixGroup.parents` and slug
naming, design research S2/S7. This completes the pure planner started in TASK-3389: the
per-group lane decision with its hard safety constraints, the deterministic slug, and the
top-level `plan_fix_batch()` that turns `ready_work()` rows into a `FixPlan`.

Two filesystem facts the planner needs — each parent's `completed_at` and slug uniqueness —
are deliberately **arguments / CLI concerns**: `parent_index_status` arrives as a mapping;
`suggested_slug` is derived but NOT de-duplicated here. Moving either into this module
breaks `test_plan_groups_are_byte_deterministic` (spec §7).

---

## Scope

- `decide_lane(group, *, override=None) -> tuple[Lane, str]` implementing the §2 predicate
  on the group's `max_severity`; `override="fast"` raises `ValueError` for `critical` or any
  `vulnerability` (S7).
- `suggest_slug(group) -> str`: dominant file (most issues; ties → sorted path), base
  `<parent-dir>-<stem>` kebab-cased, suffix `-tech-debt` when the dominant kind is
  `tech_debt`, else `-fixes`; no files → `group_id` kebab-cased.
- `plan_fix_batch(issues, *, kind, severity, lane_override, parent_index_status, generated_at) -> FixPlan`:
  skip malformed rows, apply filters before grouping, group, decide, slug, resolve parents
  from `discovered_from` matching `^spec:(FEAT-\d+)$` only, assemble `FixPlan`.
- Extend `tests/knowledge/wiki/test_ledger_fix_planner.py` with the lane/slug/plan/parents
  tests and a snapshot plan test asserting structural invariants over the live, committed
  `sdd/ledger/issues.jsonl` (see the STALE-DATA note below — the ledger grows continuously
  from unrelated `/sdd-codereview` activity across sessions, so hardcoded counts rot).

**NOT in scope**: slug de-duplication against `sdd/specs/` and reading `sdd/tasks/index/`
(TASK-3392 CLI + TASK-3391 service); the CLI itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py` | MODIFY | append `decide_lane`, `suggest_slug`, `_parents_for`, `plan_fix_batch` |
| `tests/knowledge/wiki/test_ledger_fix_planner.py` | MODIFY | add `TestDecideLane`, `TestSuggestSlug`, `TestPlanFixBatch`, `TestParents` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.fix_planner import (   # created by TASK-3389 — verify the file exists first
    ALWAYS_SDD_KINDS, CODE_PATH_EXCLUDE_PREFIXES, FAST_LANE_KINDS, FAST_LANE_MAX_FILES, FAST_LANE_SEVERITIES,
    PLANNER_VERSION, FixGroup, FixIssue, FixPlan, Lane, ParentFeature, files_for, group_issues,
)
from parrot.knowledge.wiki.ledger.events import SEVERITY_ORDER, IssueKind, IssueSeverity   # verified: events.py:21,22 (+TASK-3388)
from datetime import datetime, timezone                                                    # stdlib — ONLY for the generated_at default
from typing import get_args                                                                # stdlib
import re                                                                                  # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py  (TASK-3389)
PLANNER_VERSION = "1"; FAST_LANE_MAX_FILES = 1; FAST_LANE_KINDS = {"tech_debt"}; FAST_LANE_SEVERITIES = {"minor","low"}
ALWAYS_SDD_KINDS = {"vulnerability"}; CODE_PATH_EXCLUDE_PREFIXES = ("sdd/", "docs/"); Lane = Literal["fast","sdd"]
class FixIssue(BaseModel):  issue_id, title, kind: IssueKind, severity: IssueSeverity, discovered_from: str|None, about: list[str], files: list[str]
class ParentFeature(BaseModel): feature_id: str; completed_at: str|None = None; open: bool = False
class FixGroup(BaseModel):  group_id, issues, files, max_severity, lane: Lane = "sdd", lane_reason: str = "", suggested_slug: str = "", parents: list[ParentFeature] = []
class FixPlan(BaseModel):   planner_version = PLANNER_VERSION; generated_at: str; total_open: int; groups: list[FixGroup]; filters: dict[str, str|None] = {}
def files_for(about: Sequence[str]) -> list[str]
def group_issues(issues: Sequence[FixIssue]) -> list[FixGroup]     # groups sorted; lane/slug left at defaults

# tests/knowledge/wiki/test_ledger_fix_planner.py (TASK-3389) — reuse:
snapshot_issues fixture (list[dict] from sdd/ledger/issues.jsonl, resolved via Path(__file__).resolve().parents[3])
def _issue(issue_id, *files, severity="minor", kind="tech_debt") -> FixIssue

# STALE-DATA NOTE (updated 2026-09-19 by the sdd-worker orchestrator, confirmed by the
# TASK-3389 coder and independently re-verified before dispatching this task): the
# "hand-verified 2026-09-18" issue-id facts this contract used to list here
# (issue:bcd04b2170a0, issue:a9514c9232ad, issue:bd1c792a5afc, issue:bde3a98caed2,
# issue:0af9c12f991c, issue:c376867f96d8) NO LONGER EXIST in the committed
# sdd/ledger/issues.jsonl — the shared ledger has grown from 15 to 44+ rows via unrelated
# /sdd-codereview activity in other concurrent sessions since the spec was authored.
# Do NOT hardcode any specific issue_id, group count, or "7 groups" / "total_open == 15"
# assertion against the live snapshot — it will be false by the time you run it and it may
# drift again before this feature merges. Instead:
#   - For `TestSuggestSlug`'s dominant-file test, build synthetic FixIssue rows via `_issue()`
#     (same pattern as TestGroupIssues) — do NOT depend on the live snapshot's file contents.
#   - For the snapshot-backed `TestPlanFixBatch` test, assert STRUCTURAL INVARIANTS over
#     `snapshot_issues` instead of literal counts (mirror
#     `TestGroupIssues.test_snapshot_groups_into_expected_components` in the already-merged
#     TASK-3389 test file for the established pattern): e.g. `plan.total_open` equals the
#     number of well-formed rows in the fixture; `plan.groups` is sorted with `major`/`critical`
#     groups first (if any exist in the live data) via `SEVERITY_ORDER`; every group with any
#     `vulnerability` issue has `lane == "sdd"`; every group with `lane == "fast"` has exactly
#     one file, every issue `tech_debt`, and severity in `{"minor", "low"}` — properties that
#     hold regardless of how many rows the ledger currently contains.
```

### Does NOT Exist
- ~~`plan_fix_batch(service=...)` / any `LedgerService` parameter~~ — rows only; purity boundary.
- ~~slug de-duplication (`-2`, `-3`) in the planner~~ — CLI job (TASK-3392). `suggest_slug` is pure and therefore NOT unique.
- ~~reading `sdd/tasks/index/*.json` here~~ — `parent_index_status` is an argument (TASK-3391 produces it, TASK-3392 passes it).
- ~~`ParentFeature.open = True` for a parent absent from the mapping~~ — unknown is NOT open (spec §7 "Unknown parent ≠ open parent").
- ~~a parent from `task:TASK-…` / `review:TASK-…` / `spec:<slug>`~~ — only `spec:FEAT-<NNN>` yields a feature id.
- ~~`decide_lane` returning a bare `str`~~ — it returns `tuple[Lane, str]` (lane, human reason).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_fix_planner.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#FixGroup",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#FixIssue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#FixPlan",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#ParentFeature",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#files_for",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#group_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueKind",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueSeverity"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Predicate order (spec §2) — evaluate in exactly this order and return the first hit:
  1. `max_severity in ("critical", "major")` → sdd; 2. any issue kind in `ALWAYS_SDD_KINDS`
  → sdd; 3. `not group.files` → sdd; 4. severities ⊆ `FAST_LANE_SEVERITIES` and every kind in
  `FAST_LANE_KINDS` and `len(files) <= FAST_LANE_MAX_FILES` → fast; 5. otherwise sdd.
- `override` short-circuits **after** the S7 guard, never before it.
- Malformed rows are **skipped, never raised on**: missing `issue_id`, `kind` ∉
  `get_args(IssueKind)`, `severity` ∉ `SEVERITY_ORDER`. `total_open` counts rows that parsed
  (before `kind`/`severity` filters).
- `generated_at` defaults to `datetime.now(timezone.utc).isoformat()` — the ONE clock read,
  and only when the caller passes `None`.
- Tests that compare plans must exclude `generated_at` (S2) — pass a fixed `generated_at`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:178` — `plan_worktree` derives slugs/names deterministically; same spirit.

---

## Implementation Blueprint

### Steps (in order)
1. Append `decide_lane` — *why*: it is the only place lane rules live; S7 guard first, override second, heuristic third.
2. Append `suggest_slug` — *why*: the twins must never re-derive a name; determinism is a tested property.
3. Append `_parents_for` and `plan_fix_batch` — *why*: this is the function `ledger plan-fix` calls; its signature is fixed by spec §2.
4. Add the four test classes; run the file — *why*: the snapshot structural-invariant assertions (majors/vulnerability sort first, vulnerability → sdd, fast lane ⊆ single-file tech_debt) are acceptance criteria.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3389: grep -cF 'def group_issues(' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py)
# AFTER — append at END OF FILE (below group_issues). Add `import re` and `from datetime import datetime, timezone` to the imports.
_SPEC_PARENT_RE = re.compile(r"^spec:(FEAT-\d+)$")


def decide_lane(group: FixGroup, *, override: Lane | None = None) -> tuple[Lane, str]:
    """Return the lane for one group plus a one-line reason (spec §2 predicate on ``max_severity``).

    ``override`` short-circuits the heuristic ("forced by --lane") but is never a safety
    bypass (S7): ``override == "fast"`` raises ``ValueError`` when ``max_severity`` is
    ``critical`` or any issue is a ``vulnerability``.
    """
    kinds = {issue.kind for issue in group.issues}
    if override == "fast" and (group.max_severity == "critical" or kinds & ALWAYS_SDD_KINDS):
        raise ValueError(f"--lane fast refused for {group.group_id}: critical or vulnerability groups always take the SDD lane")
    if override is not None:
        return override, "forced by --lane"
    # FILL IN: rules 1-5 from Key Constraints, each returning (lane, reason) — bounded by TestDecideLane


def suggest_slug(group: FixGroup) -> str:
    """Deterministic kebab-case slug from the group's dominant file (pure; NOT unique — the CLI de-duplicates)."""
    if not group.files:
        return group.group_id.replace(":", "-")
    # FILL IN: count files across issues; dominant = max by (count, then reversed sort → ties pick the smallest path);
    #          base = f"{parent_dir_name}-{stem}".replace("_", "-"); dominant kind by count (ties → sorted kind name);
    #          suffix "-tech-debt" if kind == "tech_debt" else "-fixes" — bounded by TestSuggestSlug


def _parents_for(group: FixGroup, status: Mapping[str, str | None]) -> list[ParentFeature]:
    """Parents from ``spec:FEAT-<NNN>`` ``discovered_from`` only; absent from ``status`` ⇒ ``open=False``."""
    ids = sorted({m.group(1) for issue in group.issues if issue.discovered_from and (m := _SPEC_PARENT_RE.match(issue.discovered_from))})
    return [ParentFeature(feature_id=fid, completed_at=status.get(fid), open=(fid in status and status[fid] is None)) for fid in ids]


def plan_fix_batch(
    issues: Sequence[Mapping[str, Any]],
    *,
    kind: IssueKind | None = None,
    severity: IssueSeverity | None = None,
    lane_override: Lane | None = None,
    parent_index_status: Mapping[str, str | None] | None = None,
    generated_at: str | None = None,
) -> FixPlan:
    """Build the ordered, lane-labelled plan from ``ready_work()`` rows (see spec §3 M1 for the full contract)."""
    status = dict(parent_index_status or {})
    parsed: list[FixIssue] = []
    # FILL IN: for each row — skip if no issue_id / kind not in get_args(IssueKind) / severity not in SEVERITY_ORDER;
    #          else FixIssue(..., files=files_for(row.get("about") or [])) — bounded by test_plan_fix_batch_skips_malformed_rows
    selected = [i for i in parsed if (kind is None or i.kind == kind) and (severity is None or i.severity == severity)]
    groups = group_issues(selected)
    for group in groups:
        group.lane, group.lane_reason = decide_lane(group, override=lane_override)
        group.suggested_slug = suggest_slug(group)
        group.parents = _parents_for(group, status)
    return FixPlan(
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        total_open=len(parsed),
        groups=groups,
        filters={"kind": kind, "severity": severity, "lane": lane_override},
    )
```
**Why this shape**: signature and keyword names are fixed by spec §2 "New Public Interfaces"
(TASK-3392 calls them verbatim). The S7 guard precedes the override return so `--lane fast`
can never route a critical or vulnerability around review. `_parents_for` is the one place
`discovered_from` is interpreted, and its regex is what makes
`spec:codex-dispatch-stdin-isolation` yield no parent.

### `tests/knowledge/wiki/test_ledger_fix_planner.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3389: grep -cF 'class TestGroupIssues:' tests/knowledge/wiki/test_ledger_fix_planner.py)
# AFTER — append at END OF FILE. Extend the import to include decide_lane, suggest_slug, plan_fix_batch, FixPlan, PLANNER_VERSION.


def _group(*issues: FixIssue) -> FixGroup:
    return group_issues(list(issues))[0]


class TestDecideLane:
    def test_decide_lane_major_goes_sdd(self):
        assert decide_lane(_group(_issue("issue:a", "p/a.py", severity="major")))[0] == "sdd"

    def test_decide_lane_vulnerability_always_sdd(self):
        # FILL IN: synthetic minor vulnerability, single file, via _issue(..., kind="vulnerability") → "sdd"
        #          (do NOT depend on any specific live-snapshot issue_id — see STALE-DATA note above)
    def test_decide_lane_mixed_kind_group_goes_sdd(self):
        # FILL IN: minor tech_debt + minor bug sharing a file → "sdd"
    def test_decide_lane_fast_requires_single_file(self):
        # FILL IN: minor tech_debt with two files → "sdd"; with one file → "fast"
    def test_decide_lane_override_forces_lane(self):
        # FILL IN: fast-eligible group + override="sdd" → ("sdd", "forced by --lane")
    def test_decide_lane_override_cannot_force_critical_to_fast(self):
        with pytest.raises(ValueError):
            decide_lane(_group(_issue("issue:a", "p/a.py", severity="critical")), override="fast")
    def test_decide_lane_override_cannot_force_vulnerability_to_fast(self):
        # FILL IN: pytest.raises(ValueError) for a minor vulnerability with override="fast" (S7)


class TestSuggestSlug:
    def test_suggest_slug_is_deterministic_for_same_input(self):
        # FILL IN: same group built twice → identical slug
    def test_suggest_slug_uses_dominant_file_and_breaks_ties_by_path(self):
        # FILL IN: build SYNTHETIC issues via _issue() (do NOT depend on the live snapshot — see the
        #          STALE-DATA note in the Codebase Contract): 4 issues on "pkg/nodes/development.py"
        #          + 1 on "pkg/other.py", all kind="tech_debt" → dominant file is development.py →
        #          slug "nodes-development-tech-debt"; separately, two files tied 1-to-1 → the
        #          lexicographically smaller path wins
    def test_suggest_slug_falls_back_to_group_id_without_files(self):
        # FILL IN: about=[] → slug == group_id with ":" replaced by "-"


class TestPlanFixBatch:
    def test_plan_fix_batch_skips_malformed_rows(self):
        # FILL IN: rows without issue_id / with severity "urgent" / kind "chore" are dropped, no exception
    def test_plan_fix_batch_filters_by_kind_and_severity(self):
        # FILL IN: kind="bug" drops tech_debt rows BEFORE grouping; filters dict echoes the arguments
    def test_plan_groups_are_byte_deterministic(self, snapshot_issues):
        a = plan_fix_batch(snapshot_issues, generated_at="2026-01-01T00:00:00+00:00")
        b = plan_fix_batch(snapshot_issues, generated_at="2026-01-01T00:00:00+00:00")
        assert a.model_dump_json(exclude={"generated_at"}) == b.model_dump_json(exclude={"generated_at"})
    def test_plan_carries_planner_version(self, snapshot_issues):
        assert plan_fix_batch(snapshot_issues).planner_version == PLANNER_VERSION
    def test_plan_over_committed_snapshot_respects_lane_and_ordering_invariants(self, snapshot_issues):
        # NOTE: sdd/ledger/issues.jsonl grows continuously from unrelated /sdd-codereview
        # activity across sessions — do NOT hardcode a group count or total_open here (see
        # the Codebase Contract's STALE-DATA note). Assert properties that hold regardless
        # of how many rows the live snapshot currently has.
        plan = plan_fix_batch(snapshot_issues, generated_at="x")
        # FILL IN: plan.total_open == number of well-formed rows in snapshot_issues (same
        #          parsing rule as test_plan_fix_batch_skips_malformed_rows);
        #          groups are non-increasing in SEVERITY_ORDER[g.max_severity] (majors/criticals,
        #          if any, sort before minors/lows);
        #          every group with any issue.kind == "vulnerability" has lane == "sdd";
        #          every group with lane == "fast" has exactly one file, every issue.kind ==
        #          "tech_debt", and every issue.severity in {"minor", "low"} (mirror FAST_LANE_*)


class TestParents:
    def test_parents_open_flag_from_index_status(self):
        # FILL IN: discovered_from="spec:FEAT-551" with status {"FEAT-551": None} → open True; {"FEAT-551": "2026-..."} → open False
    def test_parent_absent_from_mapping_is_not_open(self):
        # FILL IN: status={} → parents == [ParentFeature(feature_id="FEAT-551", completed_at=None, open=False)]
    def test_parents_only_from_spec_prefixed_discovered_from(self):
        # FILL IN: "task:TASK-1", "review:TASK-1", "spec:codex-dispatch-stdin-isolation" → parents == []
```
**Why**: each test maps to a named row in spec §4; the snapshot tests are the acceptance
criteria for `plan-fix` before the CLI exists.

### FILL IN checklist
- [ ] `fix_planner.py::decide_lane` — rules 1-5; bounded by `TestDecideLane` + spec §2 predicate
- [ ] `fix_planner.py::suggest_slug` — dominant file/kind; bounded by `TestSuggestSlug`
- [ ] `fix_planner.py::plan_fix_batch` — row parsing/skipping; bounded by `test_plan_fix_batch_skips_malformed_rows`
- [ ] 14 test bodies marked FILL IN

---

## Acceptance Criteria

- [ ] `plan_fix_batch` over the live, committed `sdd/ledger/issues.jsonl` respects the lane/ordering
      invariants (majors/criticals sort first; vulnerability groups → sdd; fast-lane groups are
      single-file/tech_debt/minor-or-low only) and `total_open` equals the well-formed row count —
      see the Codebase Contract's STALE-DATA note; do not hardcode a literal group count.
- [ ] Two runs over identical input produce byte-identical `groups`; `planner_version` present (S2).
- [ ] `--lane fast` (override) raises `ValueError` for `critical` and for any `vulnerability` group (S7).
- [ ] `suggested_slug` is byte-identical across runs; no de-duplication happens in the planner.
- [ ] A parent absent from `parent_index_status` reports `open=False`; only `spec:FEAT-<NNN>` yields a parent.
- [ ] Malformed rows are skipped, never raised on.
- [ ] `plan_fix_batch` performs no filesystem access.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_fix_planner.py -v`
- [ ] `ruff check` and `black --check -l 120` clean.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_fix_planner.py -q`

---

## Test Specification

```python
class TestDecideLane:    # 7 tests
class TestSuggestSlug:   # 3 tests
class TestPlanFixBatch:  # 5 tests incl. test_plan_over_committed_snapshot_respects_lane_and_ordering_invariants
class TestParents:       # 3 tests
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview predicate, §3 Module 1 skeletons, §7 "purity boundary", "`discovered_from` only sometimes names a feature", §8 last three resolved questions).
2. **Check dependencies** — TASK-3389 completed; `fix_planner.py` and its test file exist.
3. **Verify the Codebase Contract** — confirm names in the TASK-3389 file match this contract.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint; the `plan_fix_batch` signature is not negotiable.
6. **Verify** the Validation Command (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3390-fix-planner-lanes-slug-and-plan.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (native sonnet coder, attempt_uid 5578890c60c94ef4a966cfa92433d40f)
**Date**: 2026-09-19
**Notes**: Appended `decide_lane` (5-rule predicate, S7 override guard), `suggest_slug`
(dominant-file/kind kebab-case, lexicographic tie-break), `_parents_for` (`spec:FEAT-<NNN>`-only
extraction), and `plan_fix_batch` to `fix_planner.py` per blueprint verbatim. Added
`TestDecideLane`(7) + `TestSuggestSlug`(3) + `TestPlanFixBatch`(5) + `TestParents`(3) = 19 new
tests (26 total in the file). Followed the orchestrator's STALE-DATA correction (commit
`6421c4a0e`) exactly: the snapshot-backed plan test asserts structural invariants only
(well-formed `total_open`, severity-ordered groups, vulnerability→sdd, fast-lane ⊆
single-file/tech_debt/minor-or-low), and the dominant-file slug test uses synthetic
`_issue()`-built rows, not the live snapshot.
Validation: `pytest tests/knowledge/wiki/test_ledger_fix_planner.py -q` → 26 passed. `ruff check` clean; `black` applied by the merge-time engine formatter.
Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 278.4s · Tokens: n/a (native, no usage telemetry)

**Deviations from spec**: none — implementation is an unmodified realization of the blueprint;
only the task's own stale snapshot-fact documentation was corrected beforehand by the orchestrator.
