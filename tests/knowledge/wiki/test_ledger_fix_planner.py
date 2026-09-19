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
