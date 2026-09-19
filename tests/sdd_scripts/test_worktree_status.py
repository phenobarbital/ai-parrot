"""Unit tests for scripts.sdd.worktree_status — FEAT-582."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.sdd.worktree_status import (
    WorktreeHealth,
    WorktreeReport,
    WorktreeTaskStatus,
    _check_health,
    _git,
    _load_dev_indexes,
    _parse_branch,
    _parse_porcelain,
    _read_worktree_index,
    discover_worktree_reports,
    main,
    reconcile_feature,
    reconcile_reports,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_porcelain_output():
    return (
        "worktree /repo\n"
        "HEAD abc123\n"
        "branch refs/heads/dev\n"
        "\n"
        "worktree /repo/.claude/worktrees/feat-FEAT-550-token-budget-bedrock\n"
        "HEAD def456\n"
        "branch refs/heads/feat-FEAT-550-token-budget-bedrock\n"
        "\n"
        "worktree /repo/.claude/worktrees/hotfix-PAR-123-fix-foo\n"
        "HEAD ghi789\n"
        "branch refs/heads/hotfix-PAR-123-fix-foo\n"
        "\n"
    )


@pytest.fixture
def sample_index():
    return {
        "feature": "token-budget-bedrock",
        "feature_id": "FEAT-550",
        "base_branch": "dev",
        "tasks": [
            {"id": "TASK-3132", "status": "done", "completed_at": "2026-09-10T23:54:36+00:00"},
            {"id": "TASK-3133", "status": "in-progress", "completed_at": None},
        ],
    }


@pytest.fixture
def all_done_index():
    return {
        "feature": "token-budget-bedrock",
        "feature_id": "FEAT-550",
        "base_branch": "dev",
        "tasks": [
            {"id": "TASK-3132", "status": "done", "completed_at": "2026-09-10"},
            {"id": "TASK-3133", "status": "done", "completed_at": "2026-09-11"},
        ],
    }


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _discover_with_fake_worktree(
    tmp_path: Path,
    index_data: dict,
    *,
    status_out: str = "",
    log_out: str = "",
):
    """Build a single fake SDD worktree under tmp_path and run discover_worktree_reports
    against it with every subprocess/filesystem boundary mocked out."""
    worktree_root = tmp_path / ".claude" / "worktrees"
    wt_path = worktree_root / "feat-FEAT-550-token-budget-bedrock"
    idx_dir = wt_path / "sdd" / "tasks" / "index"
    idx_dir.mkdir(parents=True)
    (idx_dir / "token-budget-bedrock.json").write_text(json.dumps(index_data))

    porcelain_output = (
        f"worktree {tmp_path}\n"
        "HEAD abc123\n"
        "branch refs/heads/dev\n"
        "\n"
        f"worktree {wt_path}\n"
        "HEAD def456\n"
        "branch refs/heads/feat-FEAT-550-token-budget-bedrock\n"
        "\n"
    )

    def fake_git(*args, cwd):
        if args[:2] == ("worktree", "list"):
            return _completed(porcelain_output)
        if args[:2] == ("status", "--porcelain"):
            return _completed(status_out)
        if args and args[0] == "log":
            return _completed(log_out)
        return _completed("")

    with (
        patch("scripts.sdd.worktree_status._git", side_effect=fake_git),
        patch("scripts.sdd.worktree_status.WORKTREE_ROOT", str(worktree_root)),
        patch("scripts.sdd.worktree_status._live_process_count", return_value=0),
    ):
        reports = discover_worktree_reports(tmp_path)

    return [r for r in reports if r.feature_id == "FEAT-550"]


# ---------------------------------------------------------------------------
# TestParseBranch
# ---------------------------------------------------------------------------


class TestParseBranch:
    def test_feature_branch(self):
        result = _parse_branch("feat-FEAT-550-token-budget-bedrock")
        assert result == ("token-budget-bedrock", "FEAT-550", "feature")

    def test_hotfix_branch(self):
        result = _parse_branch("hotfix-PAR-123-fix-foo")
        assert result == ("fix-foo", "PAR-123", "hotfix")

    def test_legacy_feature_branch(self):
        """Legacy format: feat-<NNN>-<slug> without FEAT- prefix."""
        result = _parse_branch("feat-465-fix-weak-sha1")
        assert result == ("fix-weak-sha1", "FEAT-465", "feature")

    def test_non_sdd_branch(self):
        assert _parse_branch("chore-ruff-config") is None

    def test_dev_branch(self):
        assert _parse_branch("dev") is None

    def test_main_branch(self):
        assert _parse_branch("main") is None

    def test_task_sub_worktree(self):
        """sdd-coder sub-worktrees must NOT be parsed as features."""
        assert _parse_branch("TASK-3351-a1-some-slug") is None

    def test_pool_sub_worktree_real_pattern(self):
        """FEAT-549 pool sub-worktree branches (feat-FEAT-<N>-<slug>--TASK-<N>-a<N>-<hash>)
        must NOT be misparsed as a top-level feature worktree with a garbage slug."""
        branch = "feat-FEAT-571-memory-dynamics--TASK-3382-a1-7f3a91c25d844e6b9a103c6e2b8f4d15"
        assert _parse_branch(branch) is None


# ---------------------------------------------------------------------------
# TestParsePorcelain
# ---------------------------------------------------------------------------


class TestParsePorcelain:
    def test_parses_worktrees(self, sample_porcelain_output):
        result = _parse_porcelain(sample_porcelain_output)
        assert len(result) == 3
        paths = [str(p) for p, _ in result]
        assert "/repo" in paths

    def test_detached_head(self):
        output = "worktree /repo/.claude/worktrees/detached\nHEAD abc123\ndetached\n\n"
        result = _parse_porcelain(output)
        assert len(result) == 1
        assert result[0][1] is None  # no branch


# ---------------------------------------------------------------------------
# TestReadWorktreeIndex
# ---------------------------------------------------------------------------


class TestReadWorktreeIndex:
    def test_valid_index(self, tmp_path, sample_index):
        idx_dir = tmp_path / "sdd" / "tasks" / "index"
        idx_dir.mkdir(parents=True)
        (idx_dir / "token-budget-bedrock.json").write_text(json.dumps(sample_index))
        tasks, base = _read_worktree_index(tmp_path, "token-budget-bedrock")
        assert len(tasks) == 2
        assert tasks[0].id == "TASK-3132"
        assert base == "dev"

    def test_missing_index(self, tmp_path):
        tasks, base = _read_worktree_index(tmp_path, "nonexistent")
        assert tasks == []
        assert base == "dev"

    def test_malformed_json(self, tmp_path):
        idx_dir = tmp_path / "sdd" / "tasks" / "index"
        idx_dir.mkdir(parents=True)
        (idx_dir / "bad.json").write_text("{invalid json")
        tasks, base = _read_worktree_index(tmp_path, "bad")
        assert tasks == []

    def test_task_with_invalid_status_is_skipped_not_raised(self, tmp_path):
        """A task entry whose status is outside the Literal enum must be
        skipped (pydantic ValidationError), never propagate and crash the
        whole discovery run (AC9: malformed data must be handled gracefully)."""
        idx_dir = tmp_path / "sdd" / "tasks" / "index"
        idx_dir.mkdir(parents=True)
        index_data = {
            "feature": "bad-status",
            "feature_id": "FEAT-999",
            "base_branch": "dev",
            "tasks": [
                {"id": "TASK-1", "status": "blocked", "completed_at": None},
                {"id": "TASK-2", "status": "done", "completed_at": "2026-01-01"},
            ],
        }
        (idx_dir / "bad-status.json").write_text(json.dumps(index_data))
        tasks, base = _read_worktree_index(tmp_path, "bad-status")
        assert base == "dev"
        assert len(tasks) == 1
        assert tasks[0].id == "TASK-2"


# ---------------------------------------------------------------------------
# TestHealth
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_clean(self):
        """Clean worktree returns all zeros."""
        clean_status = _completed("")
        clean_log = _completed("")
        with (
            patch("scripts.sdd.worktree_status._git", side_effect=[clean_status, clean_log]),
            patch("scripts.sdd.worktree_status._live_process_count", return_value=0),
        ):
            health = _check_health(Path("/fake/wt"), "dev")
        assert health.dirty_count == 0
        assert health.unpushed_count == 0
        assert health.live_process_count == 0

    def test_health_dirty(self):
        """Dirty worktree returns non-zero dirty_count."""
        dirty_status = _completed(" M file1.py\n?? file2.py\n")
        clean_log = _completed("")
        with (
            patch("scripts.sdd.worktree_status._git", side_effect=[dirty_status, clean_log]),
            patch("scripts.sdd.worktree_status._live_process_count", return_value=0),
        ):
            health = _check_health(Path("/fake/wt"), "dev")
        assert health.dirty_count == 2
        assert health.unpushed_count == 0

    def test_health_unpushed(self):
        """Worktree with unpushed commits returns non-zero unpushed_count."""
        clean_status = _completed("")
        unpushed_log = _completed("abc1234 commit one\ndef5678 commit two\n")
        with (
            patch("scripts.sdd.worktree_status._git", side_effect=[clean_status, unpushed_log]),
            patch("scripts.sdd.worktree_status._live_process_count", return_value=0),
        ):
            health = _check_health(Path("/fake/wt"), "dev")
        assert health.dirty_count == 0
        assert health.unpushed_count == 2

    def test_git_missing_worktree_directory_does_not_raise(self, tmp_path):
        """A registered-but-deleted worktree directory (rm -rf'd without
        `git worktree remove`/`prune`) must not crash the whole scan (AC9)."""
        missing = tmp_path / "does-not-exist"
        result = _git("status", "--porcelain", cwd=missing)
        assert result.returncode != 0

        health = _check_health(missing, "dev")
        assert health.dirty_count == 0
        assert health.unpushed_count == 0


# ---------------------------------------------------------------------------
# TestReadyForDone
# ---------------------------------------------------------------------------


class TestReadyForDone:
    def test_ready_when_all_done_and_clean(self, tmp_path, all_done_index):
        """All tasks done + clean + pushed = ready_for_done=True."""
        reports = _discover_with_fake_worktree(tmp_path, all_done_index, status_out="", log_out="")
        assert len(reports) == 1
        assert reports[0].ready_for_done is True

    def test_not_ready_when_dirty(self, tmp_path, all_done_index):
        """All done but dirty = not ready."""
        reports = _discover_with_fake_worktree(
            tmp_path, all_done_index, status_out=" M scripts/sdd/worktree_status.py\n", log_out=""
        )
        assert len(reports) == 1
        assert reports[0].health.dirty_count > 0
        assert reports[0].ready_for_done is False

    def test_not_ready_when_unpushed(self, tmp_path, all_done_index):
        """All done but unpushed = not ready."""
        reports = _discover_with_fake_worktree(
            tmp_path, all_done_index, status_out="", log_out="abc1234 unpushed commit\n"
        )
        assert len(reports) == 1
        assert reports[0].health.unpushed_count > 0
        assert reports[0].ready_for_done is False

    def test_not_ready_when_tasks_pending(self, tmp_path, sample_index):
        """Some tasks pending/in-progress = not ready."""
        reports = _discover_with_fake_worktree(tmp_path, sample_index, status_out="", log_out="")
        assert len(reports) == 1
        assert reports[0].ready_for_done is False


# ---------------------------------------------------------------------------
# TestDiscover
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_end_to_end(self, tmp_path, sample_index):
        """Mocked git + filesystem produces correct reports."""
        reports = _discover_with_fake_worktree(tmp_path, sample_index, status_out="", log_out="")
        assert len(reports) == 1
        report = reports[0]
        assert report.feature_slug == "token-budget-bedrock"
        assert report.feature_id == "FEAT-550"
        assert report.flow_type == "feature"
        assert report.branch == "feat-FEAT-550-token-budget-bedrock"
        assert report.base_branch == "dev"
        assert report.index_found is True
        assert len(report.tasks) == 2
        assert report.tasks[0].id == "TASK-3132"
        assert report.tasks[0].status == "done"
        assert report.health.dirty_count == 0
        assert report.health.unpushed_count == 0


# ---------------------------------------------------------------------------
# TestCli
# ---------------------------------------------------------------------------


class TestCli:
    def test_json_output(self, capsys, monkeypatch):
        """--json emits valid JSON matching WorktreeReport schema."""
        monkeypatch.setattr(sys, "argv", ["worktree_status.py", "--json"])
        fake_report = WorktreeReport(
            feature_slug="token-budget-bedrock",
            feature_id="FEAT-550",
            flow_type="feature",
            worktree_path="/repo/.claude/worktrees/feat-FEAT-550-token-budget-bedrock",
            branch="feat-FEAT-550-token-budget-bedrock",
            base_branch="dev",
            health=WorktreeHealth(dirty_count=0, unpushed_count=0, live_process_count=0),
            tasks=[WorktreeTaskStatus(id="TASK-3132", status="done", completed_at="2026-09-10")],
            index_found=True,
            ready_for_done=False,
        )
        toplevel = _completed("/repo\n")

        with (
            patch("scripts.sdd.worktree_status._git", return_value=toplevel),
            patch("scripts.sdd.worktree_status.discover_worktree_reports", return_value=[fake_report]),
        ):
            exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["feature_id"] == "FEAT-550"
        assert data[0]["feature_slug"] == "token-budget-bedrock"
        assert data[0]["ready_for_done"] is False
        assert data[0]["index_found"] is True
        assert "health" in data[0]
        assert "tasks" in data[0]
        assert data[0]["tasks"][0]["id"] == "TASK-3132"

    def test_not_a_git_repo(self, capsys, monkeypatch):
        """When repo-root resolution fails, main() returns 1 and prints an error."""
        monkeypatch.setattr(sys, "argv", ["worktree_status.py"])
        failed = _completed("", returncode=128)

        with patch("scripts.sdd.worktree_status._git", return_value=failed):
            exit_code = main()

        assert exit_code == 1


# ---------------------------------------------------------------------------
# Reconciliation — the worktree may only advance a task, never roll it back
# ---------------------------------------------------------------------------


def _dev_index(statuses, **header):
    """Build a per-spec index dict with tasks TASK-1..N at the given statuses."""
    index = {
        "feature": "token-budget-bedrock",
        "feature_id": "FEAT-550",
        "spec": "sdd/specs/token-budget-bedrock.spec.md",
        "completed_at": None,
        "tasks": [{"id": f"TASK-{i + 1}", "status": s} for i, s in enumerate(statuses)],
    }
    index.update(header)
    return index


def _wt_report(statuses, *, index_found=True, ids=None, slug="token-budget-bedrock"):
    """Build a WorktreeReport whose index carries the given task statuses."""
    ids = ids or [f"TASK-{i + 1}" for i in range(len(statuses))]
    return WorktreeReport(
        feature_slug=slug,
        feature_id="FEAT-550",
        flow_type="feature",
        worktree_path=f"/repo/.claude/worktrees/feat-FEAT-550-{slug}",
        branch=f"feat-FEAT-550-{slug}",
        base_branch="dev",
        tasks=[WorktreeTaskStatus(id=i, status=s) for i, s in zip(ids, statuses, strict=True)],
        index_found=index_found,
    )


class TestReconcileFeature:
    def test_no_worktree_keeps_dev(self):
        """Without a worktree the dev index passes through untouched."""
        feature = reconcile_feature(_dev_index(["done", "pending"]), None)
        assert [t.status for t in feature.tasks] == ["done", "pending"]
        assert all(t.source == "dev" for t in feature.tasks)
        assert feature.worktree_ahead is False
        assert feature.worktree_stale is False

    def test_worktree_ahead_wins(self):
        """Work started in the worktree surfaces even though dev is untouched."""
        feature = reconcile_feature(
            _dev_index(["pending", "pending", "pending"]),
            _wt_report(["done", "in-progress", "pending"]),
        )
        assert [t.status for t in feature.tasks] == ["done", "in-progress", "pending"]
        assert [t.source for t in feature.tasks] == ["worktree", "worktree", "dev"]
        assert feature.worktree_ahead is True
        assert feature.worktree_stale is False

    def test_stale_worktree_never_reopens_a_finished_feature(self):
        """FEAT-561 regression: a leftover worktree must not un-done dev's tasks."""
        feature = reconcile_feature(
            _dev_index(["done", "done"], completed_at="2026-09-16T00:00:00+00:00"),
            _wt_report(["pending", "pending"]),
        )
        assert [t.status for t in feature.tasks] == ["done", "done"]
        assert all(t.source == "dev" for t in feature.tasks)
        assert feature.worktree_ahead is False
        assert feature.worktree_stale is True
        assert feature.dev_closed is True

    def test_pre_branch_snapshot_does_not_undo_in_progress(self):
        """A worktree branched before /sdd-start stamps must not show 'pending'."""
        feature = reconcile_feature(
            _dev_index(["in-progress", "in-progress"]),
            _wt_report(["pending", "pending"]),
        )
        assert [t.status for t in feature.tasks] == ["in-progress", "in-progress"]
        assert feature.worktree_stale is True

    def test_terminal_states_tie_keeps_dev(self):
        """done and done-with-issues share a rank — dev's record wins the tie."""
        feature = reconcile_feature(
            _dev_index(["done-with-issues", "done"]),
            _wt_report(["done", "done-with-issues"]),
        )
        assert [t.status for t in feature.tasks] == ["done-with-issues", "done"]
        assert feature.worktree_ahead is False

    def test_index_not_found_is_ignored(self):
        """index_found=False means the worktree has nothing to contribute."""
        feature = reconcile_feature(
            _dev_index(["in-progress"]),
            _wt_report(["pending"], index_found=False),
        )
        assert [t.status for t in feature.tasks] == ["in-progress"]
        assert feature.worktree_stale is False

    def test_worktree_only_tasks_are_appended(self):
        """Tasks generated inside the worktree still show on the board."""
        feature = reconcile_feature(
            _dev_index(["pending"]),
            _wt_report(["done", "done"], ids=["TASK-1", "TASK-99"]),
        )
        assert {t.id: t.status for t in feature.tasks} == {"TASK-1": "done", "TASK-99": "done"}
        assert feature.worktree_ahead is True

    def test_worktree_only_feature(self):
        """A feature with no dev index at all is reported from the worktree."""
        feature = reconcile_feature(None, _wt_report(["done", "pending"]))
        assert feature.worktree_only is True
        assert feature.feature_id == "FEAT-550"
        assert [t.status for t in feature.tasks] == ["done", "pending"]


class TestReconcileReports:
    def test_pairs_indexes_with_worktrees(self, tmp_path):
        """Dev indexes pair by feature_id; unmatched worktrees are appended."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "token-budget-bedrock.json").write_text(json.dumps(_dev_index(["pending", "pending"])))
        (index_dir / "_orphans.json").write_text(json.dumps({"tasks": [{"id": "TASK-9", "status": "pending"}]}))

        other = _wt_report(["done"], slug="other-feature")
        other.feature_id = "FEAT-999"

        features = reconcile_reports(tmp_path, [_wt_report(["done", "in-progress"]), other])

        by_id = {f.feature_id: f for f in features}
        assert set(by_id) == {"FEAT-550", "FEAT-999"}
        assert by_id["FEAT-550"].worktree_ahead is True
        assert [t.status for t in by_id["FEAT-550"].tasks] == ["done", "in-progress"]
        assert by_id["FEAT-999"].worktree_only is True

    def test_orphans_and_malformed_indexes_are_skipped(self, tmp_path):
        """_orphans.json is excluded and unreadable JSON never raises."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "_orphans.json").write_text(json.dumps({"tasks": []}))
        (index_dir / "broken.json").write_text("{not json")

        assert _load_dev_indexes(tmp_path) == []
        assert reconcile_reports(tmp_path, []) == []

    def test_missing_index_dir(self, tmp_path):
        """A checkout without sdd/tasks/index yields no features."""
        assert _load_dev_indexes(tmp_path) == []


class TestReconcileCli:
    def test_reconcile_json_output(self, capsys, monkeypatch, tmp_path):
        """--reconcile --json emits ReconciledFeature objects with provenance."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "token-budget-bedrock.json").write_text(json.dumps(_dev_index(["pending", "done"])))

        monkeypatch.setattr(sys, "argv", ["worktree_status.py", "--reconcile", "--json"])
        toplevel = _completed(f"{tmp_path}\n")

        with (
            patch("scripts.sdd.worktree_status._git", return_value=toplevel),
            patch(
                "scripts.sdd.worktree_status.discover_worktree_reports",
                return_value=[_wt_report(["done", "pending"])],
            ),
        ):
            exit_code = main()

        assert exit_code == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1
        assert data[0]["worktree_ahead"] is True
        assert [t["status"] for t in data[0]["tasks"]] == ["done", "done"]
        assert [t["source"] for t in data[0]["tasks"]] == ["worktree", "dev"]
