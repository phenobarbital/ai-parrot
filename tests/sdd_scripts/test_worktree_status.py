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
    _parse_branch,
    _parse_porcelain,
    _read_worktree_index,
    discover_worktree_reports,
    main,
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
