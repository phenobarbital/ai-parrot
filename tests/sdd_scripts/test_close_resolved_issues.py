"""Tests for ``scripts.sdd.close_resolved_issues`` — the /sdd-done ledger close step."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.close_resolved_issues import close_resolved_issues, collect_links

ISSUE_A = "issue:aaaaaaaaaaaa"
ISSUE_B = "issue:bbbbbbbbbbbb"
ISSUE_SPEC = "issue:cccccccccccc"
ISSUE_BODY = "issue:dddddddddddd"
INDEX = "sdd/tasks/index/demo.json"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    _write(
        tmp_path / "sdd/specs/demo.spec.md",
        f'---\nid: FEAT-900\nsource: "ledger {ISSUE_SPEC} via /sdd-fix"\n---\n\n# Spec\n\nRelated: {ISSUE_BODY}\n',
    )
    _write(
        tmp_path / "sdd/tasks/completed/TASK-10-one.md",
        f"# TASK-10\n\n**Discovered-from**: `{ISSUE_A}` (ledger, severity major)\n",
    )
    _write(tmp_path / "sdd/tasks/completed/TASK-11-two.md", f"# TASK-11\n\ndiscovered_from: {ISSUE_B}, {ISSUE_A}\n")
    _write(tmp_path / "sdd/tasks/active/TASK-12-three.md", "# TASK-12\n\nNo link.\n")
    index = {
        "feature": "demo",
        "feature_id": "FEAT-900",
        "spec": "sdd/specs/demo.spec.md",
        "tasks": [
            {"id": "TASK-10", "status": "done", "verification": "verified"},
            {"id": "TASK-11", "status": "done", "verification": "verified"},
            {"id": "TASK-12", "status": "done", "verification": "partial"},
        ],
    }
    _write(tmp_path / INDEX, json.dumps(index))
    return tmp_path


class FakeLedger:
    """Records ledger calls; ``show`` answers from a dict of issues."""

    def __init__(self, issues: dict[str, dict], close_rc: int = 0, close_err: str = "") -> None:
        self.issues = issues
        self.close_rc = close_rc
        self.close_err = close_err
        self.closed: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        if args[0] == "show":
            issue = self.issues.get(args[1])
            if issue is None:
                return subprocess.CompletedProcess(args, 1, "", "not found")
            # Mimic the navconfig banner printed before the JSON.
            return subprocess.CompletedProcess(args, 0, "banner line\n" + json.dumps({"issue": issue}), "")
        self.closed.append(args)
        return subprocess.CompletedProcess(args, self.close_rc, "", self.close_err)


def _issue(status: str, *paths: str) -> dict:
    return {"status": status, "about": [f"sym:{p}#Thing" for p in paths]}


def test_collect_links_reads_tasks_and_spec_frontmatter_only(worktree: Path) -> None:
    links = collect_links(worktree, json.loads((worktree / INDEX).read_text()))
    assert links[ISSUE_A] == {"TASK-10", "TASK-11"}
    assert links[ISSUE_B] == {"TASK-11"}
    assert links[ISSUE_SPEC] == {"TASK-10", "TASK-11", "TASK-12"}
    assert ISSUE_BODY not in links


def test_closes_only_when_both_keys_hold(worktree: Path) -> None:
    ledger = FakeLedger(
        {
            ISSUE_A: _issue("claimed", "pkg/a.py"),
            ISSUE_B: _issue("open", "pkg/untouched.py"),
            ISSUE_SPEC: _issue("open", "pkg/a.py"),
        }
    )
    report = close_resolved_issues(
        worktree=worktree, index_path=Path(INDEX), base="origin/dev", changed_files={"pkg/a.py"}, ledger=ledger
    )
    by_id = {o.issue_id: o for o in report.issues}
    assert by_id[ISSUE_A].outcome == "closed"
    assert by_id[ISSUE_A].resolved_by == "task:TASK-10"
    assert by_id[ISSUE_B].outcome == "skipped" and "files" in by_id[ISSUE_B].detail
    # Spec-linked issue covers TASK-12, which is only "partial".
    assert by_id[ISSUE_SPEC].outcome == "skipped" and "TASK-12" in by_id[ISSUE_SPEC].detail
    assert [c[1] for c in ledger.closed] == [ISSUE_A]
    assert ledger.closed[0][-2:] == ["--resolved-by", "task:TASK-10"]


def test_already_closed_issue_is_left_alone(worktree: Path) -> None:
    ledger = FakeLedger({ISSUE_A: _issue("closed", "pkg/a.py")})
    report = close_resolved_issues(
        worktree=worktree, index_path=Path(INDEX), base="origin/dev", changed_files={"pkg/a.py"}, ledger=ledger
    )
    by_id = {o.issue_id: o for o in report.issues}
    assert by_id[ISSUE_A].detail == "already closed"
    assert by_id[ISSUE_B].outcome == "error"  # unknown to the fake ledger
    assert ledger.closed == []


def test_dry_run_never_writes(worktree: Path) -> None:
    ledger = FakeLedger({ISSUE_A: _issue("open", "pkg/a.py")})
    report = close_resolved_issues(
        worktree=worktree,
        index_path=Path(INDEX),
        base="origin/dev",
        changed_files={"pkg/a.py"},
        ledger=ledger,
        dry_run=True,
    )
    assert {o.issue_id: o.outcome for o in report.issues}[ISSUE_A] == "would-close"
    assert ledger.closed == []


def test_read_only_ledger_is_reported_not_raised(worktree: Path) -> None:
    ledger = FakeLedger(
        {ISSUE_A: _issue("open", "pkg/a.py")}, close_rc=1, close_err="OSError: [Errno 30] Read-only file system"
    )
    report = close_resolved_issues(
        worktree=worktree, index_path=Path(INDEX), base="origin/dev", changed_files={"pkg/a.py"}, ledger=ledger
    )
    assert {o.issue_id: o.outcome for o in report.issues}[ISSUE_A] == "read-only"


def test_feature_without_links_is_a_no_op(tmp_path: Path) -> None:
    _write(tmp_path / INDEX, json.dumps({"feature_id": "FEAT-1", "tasks": [{"id": "TASK-1", "status": "done"}]}))
    ledger = FakeLedger({})
    report = close_resolved_issues(worktree=tmp_path, index_path=Path(INDEX), base="origin/dev", ledger=ledger)
    assert report.issues == []
