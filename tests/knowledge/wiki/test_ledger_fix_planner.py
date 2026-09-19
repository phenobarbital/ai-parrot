"""Tests for the pure fix planner (FEAT-572 Module 1) against synthetic rows and the committed snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import SEVERITY_ORDER
from parrot.knowledge.wiki.ledger.fix_planner import (
    PLANNER_VERSION,
    FixGroup,
    FixIssue,
    FixPlan,
    ParentFeature,
    decide_lane,
    files_for,
    group_issues,
    plan_fix_batch,
    suggest_slug,
)

# tests/knowledge/wiki/ → knowledge → tests → repo root  (parents[3]); resolved from __file__, never CWD
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SNAPSHOT = _REPO_ROOT / "sdd" / "ledger" / "issues.jsonl"


@pytest.fixture
def snapshot_issues() -> list[dict]:
    """The committed ledger snapshot — a real, non-synthetic corpus."""
    return [json.loads(line) for line in _SNAPSHOT.read_text(encoding="utf-8").splitlines() if line.strip()]


def _issue(issue_id: str, *files: str, severity: str = "minor", kind: str = "tech_debt") -> FixIssue:
    about = [f"sym:{f}#X" for f in files]
    return FixIssue(
        issue_id=issue_id, title=issue_id, kind=kind, severity=severity, about=about, files=files_for(about)
    )


class TestFilesFor:
    def test_files_for_strips_sym_prefix_and_qualname(self):
        assert files_for(["sym:a/b.py#C.m"]) == ["a/b.py"]

    def test_files_for_drops_spec_and_doc_paths(self):
        assert files_for(["sym:sdd/specs/x.spec.md", "sym:docs/y.md", "sym:pkg/z.py"]) == ["pkg/z.py"]

    def test_files_for_ignores_non_sym_ids(self):
        assert files_for(["file:pkg/a.py", "pkg/a.py", "sym:pkg/b.py"]) == ["pkg/b.py"]


class TestGroupIssues:
    def test_group_issues_merges_transitively(self):
        groups = group_issues(
            [_issue("issue:a", "f1.py"), _issue("issue:b", "f1.py", "f2.py"), _issue("issue:c", "f2.py")]
        )
        assert len(groups) == 1 and sorted(i.issue_id for i in groups[0].issues) == ["issue:a", "issue:b", "issue:c"]

    def test_group_issues_singleton_when_no_files(self):
        groups = group_issues([_issue("issue:a"), _issue("issue:b")])
        assert len(groups) == 2
        assert {g.issues[0].issue_id for g in groups} == {"issue:a", "issue:b"}

    def test_group_ordering_is_severity_then_size(self):
        major_single = _issue("issue:major", "m1.py", severity="major")
        minor_group_a = [
            _issue("issue:a1", "a.py", severity="minor"),
            _issue("issue:a2", "a.py", severity="minor"),
            _issue("issue:a3", "a.py", severity="minor"),
        ]
        minor_group_b = [
            _issue("issue:b1", "b.py", severity="minor"),
            _issue("issue:b2", "b.py", severity="minor"),
        ]
        groups = group_issues([major_single, *minor_group_a, *minor_group_b])
        # major (severity 1) sorts before minor (severity 2) regardless of size
        assert groups[0].max_severity == "major"
        # among the two minor groups, the larger (3 issues) sorts before the smaller (2 issues)
        minor_groups = [g for g in groups if g.max_severity == "minor"]
        assert len(minor_groups[0].issues) == 3
        assert len(minor_groups[1].issues) == 2

    def test_group_id_is_deterministic_for_same_members(self):
        issues = [_issue("issue:a", "f1.py"), _issue("issue:b", "f1.py")]
        first = group_issues(issues)
        second = group_issues(issues)
        assert first[0].group_id == second[0].group_id

    def test_snapshot_groups_into_expected_components(self, snapshot_issues):
        # NOTE: the task's Codebase Contract records a hand-verified "7 groups / 15 issues"
        # snapshot with a 5-issue development.py/task_scheduler.py group (issue:8f46e2c1eed1).
        # The committed sdd/ledger/issues.jsonl in this worktree has since grown to 44 issues
        # via unrelated /sdd-codereview activity and neither issue:8f46e2c1eed1 nor
        # issue:27a665e3773c is present anymore, so it now resolves to a different component
        # count. This test is pinned to the snapshot actually committed in this worktree
        # (flagged to the orchestrator as a stale Codebase Contract fixture) rather than to
        # the now-inapplicable literal numbers.
        issues = [
            FixIssue(
                **{k: r[k] for k in ("issue_id", "title", "kind", "severity", "discovered_from", "about")},
                files=files_for(r["about"]),
            )
            for r in snapshot_issues
        ]
        groups = group_issues(issues)
        assert sum(len(g.issues) for g in groups) == len(issues)
        largest = max(groups, key=lambda g: len(g.issues))
        assert len(largest.issues) >= 2
        # transitivity spot-check: issues sharing a file end up in the same group
        by_file: dict[str, set[str]] = {}
        for issue in issues:
            for f in issue.files:
                by_file.setdefault(f, set()).add(issue.issue_id)
        group_of_issue = {i.issue_id: g.group_id for g in groups for i in g.issues}
        for members in by_file.values():
            assert len({group_of_issue[m] for m in members}) == 1


def _group(*issues: FixIssue) -> FixGroup:
    return group_issues(list(issues))[0]


class TestDecideLane:
    def test_decide_lane_major_goes_sdd(self):
        assert decide_lane(_group(_issue("issue:a", "p/a.py", severity="major")))[0] == "sdd"

    def test_decide_lane_vulnerability_always_sdd(self):
        group = _group(_issue("issue:a", "p/a.py", severity="minor", kind="vulnerability"))
        assert decide_lane(group)[0] == "sdd"

    def test_decide_lane_mixed_kind_group_goes_sdd(self):
        group = _group(
            _issue("issue:a", "shared.py", severity="minor", kind="tech_debt"),
            _issue("issue:b", "shared.py", severity="minor", kind="bug"),
        )
        assert decide_lane(group)[0] == "sdd"

    def test_decide_lane_fast_requires_single_file(self):
        two_files = _group(_issue("issue:a", "a.py", "b.py", severity="minor", kind="tech_debt"))
        assert decide_lane(two_files)[0] == "sdd"
        one_file = _group(_issue("issue:b", "a.py", severity="minor", kind="tech_debt"))
        assert decide_lane(one_file)[0] == "fast"

    def test_decide_lane_override_forces_lane(self):
        group = _group(_issue("issue:a", "a.py", severity="minor", kind="tech_debt"))
        assert decide_lane(group, override="sdd") == ("sdd", "forced by --lane")

    def test_decide_lane_override_cannot_force_critical_to_fast(self):
        with pytest.raises(ValueError):
            decide_lane(_group(_issue("issue:a", "p/a.py", severity="critical")), override="fast")

    def test_decide_lane_override_cannot_force_vulnerability_to_fast(self):
        group = _group(_issue("issue:a", "p/a.py", severity="minor", kind="vulnerability"))
        with pytest.raises(ValueError):
            decide_lane(group, override="fast")


class TestSuggestSlug:
    def test_suggest_slug_is_deterministic_for_same_input(self):
        issues = [_issue("issue:a", "pkg/mod.py", severity="minor", kind="tech_debt")]
        first = suggest_slug(_group(*issues))
        second = suggest_slug(_group(*issues))
        assert first == second

    def test_suggest_slug_uses_dominant_file_and_breaks_ties_by_path(self):
        dominant = [
            _issue(f"issue:dom{i}", "pkg/nodes/development.py", severity="minor", kind="tech_debt") for i in range(4)
        ]
        minority = [_issue("issue:min", "pkg/other.py", severity="minor", kind="tech_debt")]
        group = _group(*dominant, *minority)
        assert suggest_slug(group) == "nodes-development-tech-debt"

        # a.py and b.py are each referenced by 1 issue directly, plus 1 shared issue that
        # references both (and keeps them in the same connected component) → tied at count 2.
        tied = _group(
            _issue("issue:x", "pkg/a.py", severity="minor", kind="tech_debt"),
            _issue("issue:y", "pkg/b.py", severity="minor", kind="tech_debt"),
            _issue("issue:z", "pkg/a.py", "pkg/b.py", severity="minor", kind="tech_debt"),
        )
        assert suggest_slug(tied) == "pkg-a-tech-debt"

    def test_suggest_slug_falls_back_to_group_id_without_files(self):
        group = _group(_issue("issue:a", severity="minor", kind="tech_debt"))
        assert suggest_slug(group) == group.group_id.replace(":", "-")


class TestPlanFixBatch:
    def test_plan_fix_batch_skips_malformed_rows(self):
        rows = [
            {"title": "no id", "kind": "tech_debt", "severity": "minor", "about": []},
            {"issue_id": "issue:a", "title": "bad kind", "kind": "chore", "severity": "minor", "about": []},
            {"issue_id": "issue:b", "title": "bad severity", "kind": "tech_debt", "severity": "urgent", "about": []},
        ]
        plan = plan_fix_batch(rows, generated_at="x")
        assert plan.total_open == 0
        assert plan.groups == []

    def test_plan_fix_batch_filters_by_kind_and_severity(self):
        rows = [
            {
                "issue_id": "issue:a",
                "title": "tech debt",
                "kind": "tech_debt",
                "severity": "minor",
                "discovered_from": None,
                "about": ["sym:a.py"],
            },
            {
                "issue_id": "issue:b",
                "title": "a bug",
                "kind": "bug",
                "severity": "minor",
                "discovered_from": None,
                "about": ["sym:b.py"],
            },
        ]
        plan = plan_fix_batch(rows, kind="bug", generated_at="x")
        assert plan.filters == {"kind": "bug", "severity": None, "lane": None}
        assert len(plan.groups) == 1
        assert {i.issue_id for g in plan.groups for i in g.issues} == {"issue:b"}

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
        plan: FixPlan = plan_fix_batch(snapshot_issues, generated_at="x")

        well_formed = 0
        valid_kinds = {"bug", "tech_debt", "feature_gap", "vulnerability"}
        for row in snapshot_issues:
            if row.get("issue_id") and row.get("kind") in valid_kinds and row.get("severity") in SEVERITY_ORDER:
                well_formed += 1
        assert plan.total_open == well_formed

        orders = [SEVERITY_ORDER[g.max_severity] for g in plan.groups]
        assert orders == sorted(orders)

        for group in plan.groups:
            if any(issue.kind == "vulnerability" for issue in group.issues):
                assert group.lane == "sdd"
            if group.lane == "fast":
                assert len(group.files) == 1
                assert all(issue.kind == "tech_debt" for issue in group.issues)
                assert all(issue.severity in {"minor", "low"} for issue in group.issues)


class TestParents:
    def test_parents_open_flag_from_index_status(self):
        open_status = {"FEAT-551": None}
        open_parents = (
            plan_fix_batch(
                [
                    {
                        "issue_id": "issue:a",
                        "title": "t",
                        "kind": "tech_debt",
                        "severity": "minor",
                        "discovered_from": "spec:FEAT-551",
                        "about": ["sym:p/a.py"],
                    }
                ],
                parent_index_status=open_status,
                generated_at="x",
            )
            .groups[0]
            .parents
        )
        assert open_parents == [ParentFeature(feature_id="FEAT-551", completed_at=None, open=True)]

        closed_status = {"FEAT-551": "2026-01-01T00:00:00+00:00"}
        closed_parents = (
            plan_fix_batch(
                [
                    {
                        "issue_id": "issue:a",
                        "title": "t",
                        "kind": "tech_debt",
                        "severity": "minor",
                        "discovered_from": "spec:FEAT-551",
                        "about": ["sym:p/a.py"],
                    }
                ],
                parent_index_status=closed_status,
                generated_at="x",
            )
            .groups[0]
            .parents
        )
        assert closed_parents == [
            ParentFeature(feature_id="FEAT-551", completed_at="2026-01-01T00:00:00+00:00", open=False)
        ]

    def test_parent_absent_from_mapping_is_not_open(self):
        plan = plan_fix_batch(
            [
                {
                    "issue_id": "issue:a",
                    "title": "t",
                    "kind": "tech_debt",
                    "severity": "minor",
                    "discovered_from": "spec:FEAT-551",
                    "about": ["sym:p/a.py"],
                }
            ],
            parent_index_status={},
            generated_at="x",
        )
        assert plan.groups[0].parents == [ParentFeature(feature_id="FEAT-551", completed_at=None, open=False)]

    def test_parents_only_from_spec_prefixed_discovered_from(self):
        rows = [
            {
                "issue_id": "issue:a",
                "title": "t",
                "kind": "tech_debt",
                "severity": "minor",
                "discovered_from": "task:TASK-1",
                "about": ["sym:p/a.py"],
            },
            {
                "issue_id": "issue:b",
                "title": "t",
                "kind": "tech_debt",
                "severity": "minor",
                "discovered_from": "review:TASK-1",
                "about": ["sym:p/b.py"],
            },
            {
                "issue_id": "issue:c",
                "title": "t",
                "kind": "tech_debt",
                "severity": "minor",
                "discovered_from": "spec:codex-dispatch-stdin-isolation",
                "about": ["sym:p/c.py"],
            },
        ]
        plan = plan_fix_batch(rows, generated_at="x")
        for group in plan.groups:
            assert group.parents == []
