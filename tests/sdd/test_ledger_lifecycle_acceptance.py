"""FEAT-566 final acceptance gate: end-to-end SDD ledger lifecycle.

Exercises the real `wikitoolkit ledger` CLI (Module 9) end to end — open,
ready, claim, acknowledge, blockers, export — plus `close_task.sh`'s
`task.closed` emission (Module 12), against a real temporary `LedgerService`
(no mocked service methods, unlike test_cli_ledger.py's unit-level coverage).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSE_TASK_SH = REPO_ROOT / "scripts" / "sdd" / "close_task.sh"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def real_service(tmp_path, monkeypatch):
    """Patch LedgerService.from_root (as the CLI calls it) to a real, temp-rooted service."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    service = LedgerService(LedgerIndex(store, log), store, log, tmp_path)

    monkeypatch.setattr(LedgerService, "from_root", classmethod(lambda cls, root=None: service))
    return service


def _init_repo_with_task(tmp_path: Path) -> Path:
    """A git repo with one in-progress SDD task, ready for close_task.sh."""
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

    A bare `python3` subprocess resolves `parrot.*` through the shared
    venv's editable install of the MAIN checkout, not this worktree's
    in-progress source — see TASK-3239's Completion Note for the full
    explanation.
    """
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "packages" / "ai-parrot" / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


class TestLedgerLifecycleAcceptance:
    def test_open_ready_claim_lifecycle_via_cli(self, runner, real_service):
        """A `ledger open`ed issue is surfaced by `ledger ready`, then claimable."""
        opened = runner.invoke(
            wiki,
            ["ledger", "open", "--title", "Leak", "--body", "b", "--discovered-from", "task:TASK-1"],
        )
        assert opened.exit_code == 0, opened.output
        issue_id = opened.output.split()[-1]

        ready = runner.invoke(wiki, ["ledger", "ready"])
        assert issue_id in ready.output

        claim = runner.invoke(wiki, ["ledger", "claim", issue_id])
        assert claim.exit_code == 0, claim.output

        second_claim = runner.invoke(wiki, ["ledger", "claim", issue_id])
        assert second_claim.exit_code != 0

    def test_merge_blockers_scoped_to_current_feature_and_resolved_by_human_acknowledgement(
        self, runner, real_service, tmp_path
    ):
        """Merge blocks only current-feature open/unacknowledged criticals."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "feature-a.json").write_text(
            json.dumps({"feature_id": "FEAT-100", "tasks": [{"id": "TASK-100"}]}), encoding="utf-8"
        )
        (index_dir / "feature-b.json").write_text(
            json.dumps({"feature_id": "FEAT-200", "tasks": [{"id": "TASK-200"}]}), encoding="utf-8"
        )
        opened = runner.invoke(
            wiki,
            [
                "ledger",
                "open",
                "--title",
                "Own critical",
                "--body",
                "b",
                "--severity",
                "critical",
                "--discovered-from",
                "task:TASK-100",
            ],
        )
        assert opened.exit_code == 0, opened.output
        issue_id = opened.output.split()[-1]
        runner.invoke(
            wiki,
            [
                "ledger",
                "open",
                "--title",
                "Other feature critical",
                "--body",
                "b",
                "--severity",
                "critical",
                "--discovered-from",
                "task:TASK-200",
            ],
        )

        blockers_before = runner.invoke(wiki, ["ledger", "blockers", "FEAT-100"])
        assert blockers_before.exit_code == 1  # blocking issues present
        assert "Own critical" in blockers_before.output
        assert "Other feature critical" not in blockers_before.output

        non_human = runner.invoke(
            wiki, ["ledger", "acknowledge", issue_id, "--reason", "known", "--actor", "agent:sdd"]
        )
        assert non_human.exit_code != 0

        human = runner.invoke(wiki, ["ledger", "acknowledge", issue_id, "--reason", "known", "--actor", "human:jesus"])
        assert human.exit_code == 0, human.output

        blockers_after = runner.invoke(wiki, ["ledger", "blockers", "FEAT-100"])
        assert blockers_after.exit_code == 0
        assert "No blocking issues" in blockers_after.output

    def test_export_snapshot_is_deterministic_via_cli(self, runner, real_service, tmp_path):
        """Snapshot is deterministic: re-exporting unchanged state reports "unchanged"."""
        runner.invoke(
            wiki, ["ledger", "open", "--title", "Snapshot me", "--body", "b", "--discovered-from", "task:TASK-1"]
        )
        dest = tmp_path / "sdd" / "ledger" / "issues.jsonl"

        first = runner.invoke(wiki, ["ledger", "export", "--dest", str(dest)])
        content_first = dest.read_text(encoding="utf-8")
        second = runner.invoke(wiki, ["ledger", "export", "--dest", str(dest)])
        content_second = dest.read_text(encoding="utf-8")

        assert "(changed)" in first.output
        assert "(unchanged)" in second.output
        assert content_first == content_second

    def test_close_task_emits_durable_task_closed_event(self, tmp_path):
        """close_task.sh's task.closed emission is durable (Module 12 lifecycle boundary)."""
        repo = _init_repo_with_task(tmp_path)

        result = subprocess.run(
            ["bash", str(CLOSE_TASK_SH), "TASK-9001", "demo-feature", "verified"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_worktree_python_env(),
        )

        assert result.returncode == 0, result.stderr
        events_path = repo / ".parrot" / "ledger" / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        closed = [e for e in events if e["kind"] == "task.closed"]
        assert len(closed) == 1
        assert closed[0]["subject"] == "task:TASK-9001"
        assert closed[0]["payload"]["verification"] == "verified"


class TestLifecycleRegressionGate:
    def test_focused_acceptance_suites_pass_and_evidence_is_saved(self):
        """Focused acceptance commands pass with evidence retained (spec Test Specification)."""
        log_path = REPO_ROOT / "artifacts" / "logs" / "feat-566-lifecycle.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        targets = [
            "tests/sdd/test_close_task_ledger.py",
            "tests/sdd/test_ledger_workflow_twins.py",
            "tests/knowledge/wiki/test_cli_ledger.py",
        ]
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *targets, "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )

        log_path.write_text(
            "FEAT-566 end-to-end SDD ledger lifecycle acceptance gate\n"
            f"command: pytest {' '.join(targets)} -q\n"
            f"exit_code: {result.returncode}\n\n"
            "--- stdout (tail) ---\n"
            + "\n".join(result.stdout.splitlines()[-40:])
            + "\n\n--- stderr (tail) ---\n"
            + "\n".join(result.stderr.splitlines()[-20:])
            + "\n",
            encoding="utf-8",
        )

        assert result.returncode == 0, result.stdout[-4000:]
