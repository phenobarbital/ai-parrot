# TASK-3389: `fix_planner.py` — models, constants, `files_for()` and connected-component `group_issues()`

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3388
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models / Purity boundary and §3 Module 1. Everything algorithmic in this
feature lives in ONE pure module, `parrot/knowledge/wiki/ledger/fix_planner.py`: no I/O,
no `async`, no store access, no clock except an injectable `generated_at`. That purity is
what lets the committed snapshot `sdd/ledger/issues.jsonl` serve as a golden fixture and
what makes two runs over the same input byte-identical (S2).

This task lays the first half of the module: the Pydantic contract (`FixIssue`,
`ParentFeature`, `FixGroup`, `FixPlan`), the named threshold constants, the ONLY grouping
contract `files_for()` (S1), and the transitive union-find `group_issues()`. TASK-3390 adds
`decide_lane`, `suggest_slug` and `plan_fix_batch` on top.

It depends on TASK-3388 because the planner imports `SEVERITY_ORDER` from `events.py` — a
NEW edge introduced by design research (spec Worktree Strategy: "M1 and M2 are no longer
concurrent").

---

## Scope

- CREATE `fix_planner.py` with: `PLANNER_VERSION`, `FAST_LANE_MAX_FILES`, `FAST_LANE_KINDS`,
  `FAST_LANE_SEVERITIES`, `ALWAYS_SDD_KINDS`, `CODE_PATH_EXCLUDE_PREFIXES`, `Lane`,
  `FixIssue`, `ParentFeature`, `FixGroup`, `FixPlan`, `files_for()`, `group_issues()`.
- `FixGroup.lane`, `lane_reason`, `suggested_slug` get **defaults** (`"sdd"`, `""`, `""`) so
  `group_issues()` can construct groups before `decide_lane`/`suggest_slug` run — a
  deliberate, documented refinement of the spec's Data Models (which show no defaults);
  `"sdd"` is the safe default per the asymmetric design.
- Deterministic `group_id`: `"fixgroup:" + sha1("|".join(sorted(issue_ids)))[:12]`.
- CREATE `tests/knowledge/wiki/test_ledger_fix_planner.py` with the `snapshot_issues`
  fixture and the `files_for` / `group_issues` tests.

**NOT in scope**: `decide_lane`, `suggest_slug`, `plan_fix_batch`, parent resolution, the
snapshot "7 groups" test (all TASK-3390); anything in `cli.py` (TASK-3392).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py` | CREATE | Pure planner — part 1 (models, constants, `files_for`, `group_issues`) |
| `tests/knowledge/wiki/test_ledger_fix_planner.py` | CREATE | Fixture + grouping/extraction tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity, SEVERITY_ORDER  # verified: events.py:21,22; SEVERITY_ORDER added by TASK-3388 below IssueStatus (:23)
from pydantic import BaseModel, Field                                                    # verified: events.py:5 (project-wide Pydantic v2)
from collections.abc import Mapping, Sequence                                            # stdlib
from typing import Any, Final, Literal, get_args                                         # stdlib
import hashlib                                                                           # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
IssueKind = Literal["bug", "tech_debt", "feature_gap", "vulnerability"]      # 21
IssueSeverity = Literal["critical", "major", "minor", "low"]                 # 22
SEVERITY_ORDER: Final[dict[IssueSeverity, int]] = {"critical": 0, "major": 1, "minor": 2, "low": 3}   # TASK-3388
class IssueOpenedPayload(BaseModel):
    about: list[str] = Field(default_factory=list, description="Target code symbols/files, e.g. sym:pkg/mod.py#Func")  # 32

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
def _issue_dict(issue_id, state) -> dict   # 78-93 — keys: issue_id, title, status, kind, severity, acknowledged,
                                           #   discovered_from, about, claimed_by, closed_by, closed_reason, resolved_by
# sdd/ledger/issues.jsonl — 15 rows, one JSON object per line, exactly the _issue_dict shape (sorted keys).
#   Real `about` ids look like:  sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py#DevelopmentNode._execute_pool
#   One row carries a NON-code anchor:  sym:sdd/specs/dev-loop-pool-exclusive-tasks.spec.md   (issue:27a665e3773c)
#   Hand-verified components over the snapshot: 7 groups; development.py ∪ task_scheduler.py is a 5-issue group.

# tests/sdd/test_ledger_workflow_twins.py:23 — the CWD gotcha pattern:
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]   # from tests/sdd/ → repo root
# For tests/knowledge/wiki/<file>.py the repo root is parents[3]  (wiki → knowledge → tests → root).
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.ledger.fix_planner`~~ — this task creates it. `ledger/` today has
  exactly: `__init__.py`, `coder_feedback.py`, `coder_reviews.py`, `coder_suspensions.py`,
  `events.py`, `index.py`, `log.py`, `sdd_ingest.py`, `sdd_meta.py`, `service.py`, `store.py`.
- ~~`decide_lane` / `suggest_slug` / `plan_fix_batch`~~ — TASK-3390. Do not stub them here.
- ~~any import of `LedgerService`, `LedgerStore`, `aiosqlite`, `Path.read_text` in the planner~~ — purity boundary; the planner receives `Sequence[Mapping]`.
- ~~`networkx`~~ — not a dependency; write the union-find by hand (a dict `parent: dict[str, str]`).
- ~~`IssueSeverity`/`IssueKind` as Enums~~ — Literals; validate membership with `get_args`.
- ~~`Path(__file__).resolve().parents[2]` from `tests/knowledge/wiki/`~~ — that is `tests/`, not the
  repo root; the spec's fixture snippet is off by one for this directory. Use `parents[3]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/test_ledger_fix_planner.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueKind",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueSeverity",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueOpenedPayload",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_issue_dict"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Pure**: no `async`, no file/DB/clock access. `ruff` will not catch a stray `Path.read_text` — you must.
- `files_for` is the ONLY grouping contract (S1). `LedgerService.get_context()` matches by
  bidirectional substring (`service.py:269`) — fine for priming, never for grouping.
- Spec/doc paths (`sdd/`, `docs/`) never create a grouping edge — otherwise two unrelated
  features sharing a spec reference would merge (§7).
- Grouping is **transitive** and load-bearing: `development.py` and `task_scheduler.py` merge
  into one 5-issue group via `issue:8f46e2c1eed1`. A per-file bucket is WRONG.
- Group order `(SEVERITY_ORDER[max_severity], -len(issues), group_id)`; issues inside a group
  `(SEVERITY_ORDER[severity], issue_id)`. Both sorts are what S2 determinism rests on.
- Google-style docstrings, strict type hints, `black -l 120`, `ruff check`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:170` — small Pydantic models in the same package (`WorktreePlan`), style to match.
- `tests/knowledge/wiki/test_ledger_service.py` — test module layout in this tree.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with constants and models — *why*: TASK-3390 and TASK-3392 import these names verbatim; they are the contract.
2. Implement `files_for` — *why*: it is the single grouping edge definition (S1); everything downstream keys on its output.
3. Implement `group_issues` as union-find over `(issue, file)` — *why*: transitivity is a spec requirement, not an optimisation.
4. Write the fixture and tests, including the real-snapshot spot-checks — *why*: the snapshot is the golden corpus the whole feature is validated against.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py` (CREATE)
```python
"""Pure fix planner for the SDD work ledger (FEAT-572 Module 1).

No I/O, no async, no store access, no clock except an injectable ``generated_at``:
every filesystem fact reaches this module as an argument. Ordering, grouping and
lane rules live here and ONLY here — the ``/sdd-fix`` twins execute
``wikitoolkit ledger plan-fix --json`` and never re-implement them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import SEVERITY_ORDER, IssueKind, IssueSeverity

PLANNER_VERSION: Final[str] = "1"  # S2 — bump on ANY change to the contract shape or the ordering/lane rules
FAST_LANE_MAX_FILES: Final[int] = 1
FAST_LANE_KINDS: Final[frozenset[str]] = frozenset({"tech_debt"})
FAST_LANE_SEVERITIES: Final[frozenset[str]] = frozenset({"minor", "low"})
ALWAYS_SDD_KINDS: Final[frozenset[str]] = frozenset({"vulnerability"})
CODE_PATH_EXCLUDE_PREFIXES: Final[tuple[str, ...]] = ("sdd/", "docs/")
_SYM_PREFIX: Final[str] = "sym:"

Lane = Literal["fast", "sdd"]


class FixIssue(BaseModel):
    """One ledger issue as the planner sees it (a projection of ``_issue_dict``)."""

    issue_id: str
    title: str
    kind: IssueKind
    severity: IssueSeverity
    discovered_from: str | None = None
    about: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class ParentFeature(BaseModel):
    """A feature that discovered issues in this group, and whether it is still open.

    ``completed_at`` is the per-spec index's stamp, NOT the spec's ``**Status**``.
    ``open`` is exactly ``completed_at is None`` AND the parent was present in the
    caller-supplied mapping — unknown is never treated as open.
    """

    feature_id: str
    completed_at: str | None = None
    open: bool = False


class FixGroup(BaseModel):
    """A connected component of issues sharing at least one code file."""

    group_id: str
    issues: list[FixIssue]
    files: list[str]
    max_severity: IssueSeverity
    lane: Lane = "sdd"  # filled by decide_lane (TASK-3390); "sdd" is the safe default
    lane_reason: str = ""
    suggested_slug: str = ""  # filled by suggest_slug (TASK-3390)
    parents: list[ParentFeature] = Field(default_factory=list)


class FixPlan(BaseModel):
    """The full, ordered plan the twins render and execute (S2: ``groups`` is deterministic)."""

    planner_version: str = PLANNER_VERSION
    generated_at: str
    total_open: int
    groups: list[FixGroup]
    filters: dict[str, str | None] = Field(default_factory=dict)


def files_for(about: Sequence[str]) -> list[str]:
    """Extract sorted, de-duplicated repo-relative code paths from ``about`` symbol ids.

    ``sym:<path>#<qualname>`` → ``<path>``; bare ``sym:<path>`` → ``<path>``. Ids without
    the ``sym:`` prefix are ignored; paths under ``CODE_PATH_EXCLUDE_PREFIXES`` are dropped
    (a spec or doc is context, never a grouping edge). This is the ONLY grouping contract
    (S1) — ``LedgerService.get_context()`` substring matching must never be used for it.
    """
    # FILL IN: strip prefix, split on the first "#", drop excluded prefixes, sorted(set(...)) — bounded by the three files_for tests


def group_issues(issues: Sequence[FixIssue]) -> list[FixGroup]:
    """Partition issues into connected components of the issue↔file graph.

    Two issues share a component when they share at least one file, directly or
    transitively. An issue with no files is its own singleton. Issues inside a group are
    sorted by ``(SEVERITY_ORDER, issue_id)``; groups by
    ``(SEVERITY_ORDER[max_severity], -len(issues), group_id)``. ``lane``/``lane_reason``/
    ``suggested_slug`` are left at their defaults for ``decide_lane``/``suggest_slug``.
    """
    parent: dict[str, str] = {}
    # FILL IN: union-find — nodes are issue_ids AND file paths; union(issue, file) for every file;
    #          collect components by root, build FixGroup with group_id = "fixgroup:" + sha1("|".join(sorted(ids)))[:12],
    #          files = sorted union of member files, max_severity = min(severity, key=SEVERITY_ORDER) —
    #          bounded by test_group_issues_merges_transitively / _singleton_when_no_files / _ordering_is_severity_then_size
```
**Why this shape**: model fields and names are fixed by spec §2 (TASK-3390/3392 import them);
the three defaulted `FixGroup` fields are the one documented refinement that lets grouping
run before lane decision. `_SYM_PREFIX` and the `frozenset[str]` constants are the "named
thresholds" the spec wants retuned by a one-line diff, never a prose edit.

### `tests/knowledge/wiki/test_ledger_fix_planner.py` (CREATE)
```python
"""Tests for the pure fix planner (FEAT-572 Module 1) against synthetic rows and the committed snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.fix_planner import FixIssue, files_for, group_issues

# tests/knowledge/wiki/ → knowledge → tests → repo root  (parents[3]); resolved from __file__, never CWD
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SNAPSHOT = _REPO_ROOT / "sdd" / "ledger" / "issues.jsonl"


@pytest.fixture
def snapshot_issues() -> list[dict]:
    """The committed ledger snapshot — a real, non-synthetic 15-issue corpus."""
    return [json.loads(line) for line in _SNAPSHOT.read_text(encoding="utf-8").splitlines() if line.strip()]


def _issue(issue_id: str, *files: str, severity: str = "minor", kind: str = "tech_debt") -> FixIssue:
    about = [f"sym:{f}#X" for f in files]
    return FixIssue(issue_id=issue_id, title=issue_id, kind=kind, severity=severity, about=about, files=files_for(about))


class TestFilesFor:
    def test_files_for_strips_sym_prefix_and_qualname(self):
        assert files_for(["sym:a/b.py#C.m"]) == ["a/b.py"]

    def test_files_for_drops_spec_and_doc_paths(self):
        # FILL IN: ["sym:sdd/specs/x.spec.md", "sym:docs/y.md", "sym:pkg/z.py"] → ["pkg/z.py"] — real case issue:27a665e3773c

    def test_files_for_ignores_non_sym_ids(self):
        # FILL IN: ["file:pkg/a.py", "pkg/a.py", "sym:pkg/b.py"] → ["pkg/b.py"], no exception


class TestGroupIssues:
    def test_group_issues_merges_transitively(self):
        groups = group_issues([_issue("issue:a", "f1.py"), _issue("issue:b", "f1.py", "f2.py"), _issue("issue:c", "f2.py")])
        assert len(groups) == 1 and sorted(i.issue_id for i in groups[0].issues) == ["issue:a", "issue:b", "issue:c"]

    def test_group_issues_singleton_when_no_files(self):
        # FILL IN: an issue with about=[] is its own group; two such issues are two groups

    def test_group_ordering_is_severity_then_size(self):
        # FILL IN: a 1-issue major group sorts before a 3-issue minor group; two minor groups sort larger-first,
        #          then by group_id — bounded by the group sort key in the docstring

    def test_group_id_is_deterministic_for_same_members(self):
        # FILL IN: group_issues(...) twice → identical group_id (S2)

    def test_snapshot_groups_into_seven_components(self, snapshot_issues):
        issues = [FixIssue(**{k: r[k] for k in ("issue_id", "title", "kind", "severity", "discovered_from", "about")}, files=files_for(r["about"])) for r in snapshot_issues]
        groups = group_issues(issues)
        assert len(groups) == 7
        # FILL IN: the largest group has 5 issues and its files include .../nodes/development.py and .../task_scheduler.py
```
**Why**: the synthetic tests pin each rule in isolation; the snapshot test pins the real-world
consequence (7 groups, one 5-issue transitive merge) that TASK-3390's plan test extends.

### FILL IN checklist
- [ ] `fix_planner.py::files_for` — body; bounded by `TestFilesFor` (3 tests)
- [ ] `fix_planner.py::group_issues` — union-find + FixGroup assembly; bounded by `TestGroupIssues`
- [ ] `test_ledger_fix_planner.py` — 6 test bodies marked FILL IN

---

## Acceptance Criteria

- [ ] `fix_planner.py` imports nothing I/O-shaped (`grep -E "aiosqlite|LedgerStore|LedgerService|open\(|read_text|datetime.now" fix_planner.py` is empty).
- [ ] `files_for` strips `sym:`/qualname, drops `sdd/` and `docs/` paths, ignores non-`sym:` ids, returns sorted unique paths.
- [ ] `group_issues` merges transitively, singletons for empty `about`, orders groups `(severity, -size, group_id)` and issues `(severity, issue_id)`.
- [ ] Over `sdd/ledger/issues.jsonl` grouping yields exactly 7 components.
- [ ] `group_id` is deterministic for the same member set.
- [ ] `FixGroup` is constructible without `lane`/`lane_reason`/`suggested_slug`.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_fix_planner.py -v`
- [ ] `ruff check` and `black --check -l 120` clean.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_fix_planner.py -q`

---

## Test Specification

```python
class TestFilesFor:      # 3 tests (see blueprint)
class TestGroupIssues:   # 5 tests incl. test_snapshot_groups_into_seven_components
```

---

## Agent Instructions

1. **Read the spec** (§2 Data Models + Purity boundary, §3 Module 1 `files_for` / `group_issues`, §7 gotchas "Grouping is transitive", "`about` is not purely code").
2. **Check dependencies** — TASK-3388 completed (`SEVERITY_ORDER` importable).
3. **Verify the Codebase Contract** — confirm `SEVERITY_ORDER` exists in `events.py`.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint; do not add `decide_lane`/`suggest_slug`/`plan_fix_batch`.
6. **Verify** the Validation Command (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3389-fix-planner-models-and-grouping.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (native sonnet coder, attempt_uid a95ed4e1b13c46fd985133cb8457f24c)
**Date**: 2026-09-19
**Notes**: Created `fix_planner.py` with `PLANNER_VERSION`, the four lane-threshold constants,
`Lane`, `FixIssue`, `ParentFeature`, `FixGroup`, `FixPlan`, `files_for()` and `group_issues()`
exactly per the blueprint (union-find over issue↔file edges). Created
`test_ledger_fix_planner.py` with `TestFilesFor` (3) + `TestGroupIssues` (5), 8/8 passing.

**Stale Codebase Contract flagged and resolved**: the task's "hand-verified 2026-09-18"
`sdd/ledger/issues.jsonl` facts (15 rows / 7 groups, six specific issue ids) no longer match
the live, committed snapshot — it has grown to 44 rows via unrelated `/sdd-codereview`
activity in other concurrent sessions, and none of the six referenced issue ids exist
anymore (independently re-verified by the orchestrator via grep). Rather than hardcode the
now-false numbers, the coder rewrote the one snapshot-dependent test
(`test_snapshot_groups_into_expected_components`) to assert structural invariants (total
issue count preserved, transitivity: issues sharing a file land in the same group, largest
group ≥2) instead of a literal "7 groups" count. The orchestrator verified this and applied
the same correction to the downstream TASK-3390 and TASK-3392 blueprints/acceptance criteria
(commit `6421c4a0e`) so their coders don't hit the same stale contract.

Validation: `pytest tests/knowledge/wiki/test_ledger_fix_planner.py -q` → 8 passed. `ruff check` + `black --check` clean.
Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 282.9s · Tokens: n/a (native, no usage telemetry)

**Deviations from spec**: none in the delivered code; the task's own snapshot-fact
documentation was corrected (see above) — the algorithm (`files_for`, `group_issues`) is an
unmodified, exact realization of the blueprint.
