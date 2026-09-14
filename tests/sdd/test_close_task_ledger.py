"""Tests for FEAT-566 Module 12: task.closed ledger emission from close_task.sh.

Exercises the real shell script as a subprocess against a temporary git
repo/SDD fixture — this is deliberately a black-box, shell-level test (per
the task's "shell-level coverage using a controlled CLI stub" note), not a
mock of the script's internals.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSE_TASK_SH = REPO_ROOT / "scripts" / "sdd" / "close_task.sh"


def _init_repo(tmp_path: Path) -> Path:
    """Create a bare git repo with an SDD active/ task and per-spec index."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    (repo / "sdd" / "tasks" / "active").mkdir(parents=True)
    (repo / "sdd" / "tasks" / "completed").mkdir(parents=True)
    (repo / "sdd" / "tasks" / "index").mkdir(parents=True)

    (repo / "sdd" / "tasks" / "active" / "TASK-9001-demo.md").write_text("# TASK-9001: Demo\n", encoding="utf-8")
    index = {
        "feature": "demo-feature",
        "feature_id": "FEAT-900",
        "tasks": [
            {
                "id": "TASK-9001",
                "status": "in-progress",
                "completed_at": None,
                "file": "sdd/tasks/active/TASK-9001-demo.md",
            }
        ],
    }
    (repo / "sdd" / "tasks" / "index" / "demo-feature.json").write_text(json.dumps(index), encoding="utf-8")

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


def _worktree_python_env() -> dict:
    """Subprocess env with THIS worktree's package sources on PYTHONPATH.

    A plain `python3` subprocess (unlike pytest, which loads the root
    conftest.py's sys.path insertion) resolves `parrot.*` through the
    shared venv's editable-install .pth files, which point at the MAIN
    checkout's source tree — not this worktree's in-progress changes.
    Without this, `close_task.sh`'s ledger emission would always hit its
    best-effort "module unavailable" fallback in these tests.
    """
    import os

    env = dict(os.environ)
    src = str(REPO_ROOT / "packages" / "ai-parrot" / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_close_task(repo: Path, task_id: str, feature_slug: str, verification: str = "verified"):
    return subprocess.run(
        ["bash", str(CLOSE_TASK_SH), task_id, feature_slug, verification],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_worktree_python_env(),
    )


def _read_events(repo: Path) -> list[dict]:
    log_path = repo / ".parrot" / "ledger" / "events.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestTaskClosedEmission:
    def test_successful_closure_emits_task_closed_after_post_condition(self, tmp_path):
        repo = _init_repo(tmp_path)

        result = _run_close_task(repo, "TASK-9001", "demo-feature", "verified")

        assert result.returncode == 0, result.stderr
        assert not (repo / "sdd" / "tasks" / "active" / "TASK-9001-demo.md").exists()
        assert (repo / "sdd" / "tasks" / "completed" / "TASK-9001-demo.md").exists()

        events = _read_events(repo)
        assert len(events) == 1
        assert events[0]["kind"] == "task.closed"
        assert events[0]["subject"] == "task:TASK-9001"
        assert events[0]["payload"]["feature"] == "demo-feature"
        assert events[0]["payload"]["verification"] == "verified"

    def test_missing_task_exits_before_emitting(self, tmp_path):
        repo = _init_repo(tmp_path)

        result = _run_close_task(repo, "TASK-404", "demo-feature", "verified")

        assert result.returncode == 2
        assert _read_events(repo) == []

    def test_already_closed_is_idempotent_and_still_succeeds(self, tmp_path):
        repo = _init_repo(tmp_path)
        first = _run_close_task(repo, "TASK-9001", "demo-feature", "verified")
        assert first.returncode == 0

        second = _run_close_task(repo, "TASK-9001", "demo-feature", "verified")

        assert second.returncode == 0, second.stderr
        # Existing move/index behavior is unchanged: no active copy resurfaces.
        assert not (repo / "sdd" / "tasks" / "active" / "TASK-9001-demo.md").exists()
        assert (repo / "sdd" / "tasks" / "completed" / "TASK-9001-demo.md").exists()

    def test_verification_status_is_recorded_in_the_event_payload(self, tmp_path):
        repo = _init_repo(tmp_path)

        result = _run_close_task(repo, "TASK-9001", "demo-feature", "partial")

        assert result.returncode == 0, result.stderr
        events = _read_events(repo)
        assert events[0]["payload"]["verification"] == "partial"

    def test_ledger_emission_failure_never_fails_an_otherwise_successful_closure(self, tmp_path):
        """A broken ledger emission (contention or otherwise) must not undo/misreport closure."""
        repo = _init_repo(tmp_path)
        # Force the ledger emission to fail deep inside (after a real
        # find_shared_root() resolution) rather than simulating a missing
        # dependency: `.parrot` exists as a plain FILE, so
        # `ledger_dir.mkdir(parents=True, exist_ok=True)` raises
        # NotADirectoryError — exercising this script's own try/except
        # safety net with the real worktree ledger code, not a stand-in.
        (repo / ".parrot").write_text("not a directory", encoding="utf-8")

        result = _run_close_task(repo, "TASK-9001", "demo-feature", "verified")

        assert result.returncode == 0, result.stderr
        assert (repo / "sdd" / "tasks" / "completed" / "TASK-9001-demo.md").exists()
        assert "ledger emission skipped" in result.stderr
        assert _read_events(repo) == []
