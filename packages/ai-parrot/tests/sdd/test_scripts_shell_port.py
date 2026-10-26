# packages/ai-parrot/tests/sdd/test_scripts_shell_port.py
"""FEAT-633: Python ports of close_task.sh / heal_orphans.sh keep CLI + behaviour identical."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for sub in ("active", "completed", "index"):
        (root / "sdd" / "tasks" / sub).mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "sdd/tasks/active/TASK-9001-demo.md").write_text("# TASK-9001\n", encoding="utf-8")
    index = {"feature": "demo", "tasks": [{"id": "TASK-9001", "status": "in-progress", "completed_at": None,
                                           "file": "sdd/tasks/active/TASK-9001-demo.md"}]}
    (root / "sdd/tasks/index/demo.json").write_text(json.dumps(index), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), env.get("PYTHONPATH", "")])
    return env


def _module(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", f"parrot.sdd.scripts.{name}", *args],
                          cwd=cwd, env=_env(), capture_output=True, text=True)


def _wrapper(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(REPO_ROOT / "scripts" / "sdd" / f"{name}.sh"), *args],
                          cwd=cwd, env={**_env(), "PYTHON": sys.executable}, capture_output=True, text=True)


@pytest.mark.parametrize("runner", [_module, _wrapper])
def test_close_moves_marks_done_and_stages(repo: Path, runner) -> None:
    proc = runner("close_task", repo, "TASK-9001", "demo", "verified")
    assert proc.returncode == 0, proc.stderr
    assert "✅ TASK-9001 closed (verification=verified). active/ is clean." in proc.stdout
    assert (repo / "sdd/tasks/completed/TASK-9001-demo.md").is_file()
    data = json.loads((repo / "sdd/tasks/index/demo.json").read_text(encoding="utf-8"))
    task = data["tasks"][0]
    assert (task["status"], task["verification"], task["file"]) == ("done", "verified", "sdd/tasks/completed/TASK-9001-demo.md")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", task["completed_at"])
    assert data["completed_at"] == task["completed_at"]
    assert "sdd/tasks/index/demo.json" in _git(repo, "diff", "--cached", "--name-only")


def test_close_exit_codes(repo: Path, tmp_path: Path) -> None:
    assert _module("close_task", repo).returncode == 1
    assert _module("close_task", repo, "TASK-404", "demo").returncode == 2
    outside = tmp_path / "plain"
    outside.mkdir()
    assert _module("close_task", outside, "TASK-9001", "demo").returncode == 128
    assert _module("close_task", repo, "TASK-9001", "demo").returncode == 0
    second = _module("close_task", repo, "TASK-9001", "demo")
    assert second.returncode == 0 and "already in completed/" in second.stdout


def test_close_invalid_index_exits_5(repo: Path) -> None:
    (repo / "sdd/tasks/index/demo.json").write_text('{"tasks": null}', encoding="utf-8")
    assert _module("close_task", repo, "TASK-9001", "demo").returncode == 5


@pytest.mark.parametrize("runner", [_module, _wrapper])
def test_heal_orphans_dry_run_then_reap(repo: Path, runner) -> None:
    index_path = repo / "sdd/tasks/index/demo.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    data["tasks"][0]["status"] = "done"
    index_path.write_text(json.dumps(data), encoding="utf-8")
    (repo / "sdd/tasks/completed/TASK-9001-demo.md").write_text("# twin\n", encoding="utf-8")
    active = repo / "sdd/tasks/active/TASK-9001-demo.md"
    rel = "sdd/tasks/active/TASK-9001-demo.md"

    dry = runner("heal_orphans", repo, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert f"would reap: {rel}" in dry.stdout
    assert "── heal_orphans: 1 orphan(s) would be reaped, 0 kept for review." in dry.stdout
    assert active.is_file()

    # --dry-run is honoured only as the FIRST argument: "demo --dry-run" really reaps.
    real = runner("heal_orphans", repo, "demo", "--dry-run")
    assert real.returncode == 0, real.stderr
    assert f"reaped orphan: {rel}" in real.stdout
    assert "── heal_orphans: 1 orphan(s) reaped, 0 kept for review." in real.stdout
    assert not active.exists()


def test_heal_orphans_no_twin_kept(repo: Path) -> None:
    index_path = repo / "sdd/tasks/index/demo.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    data["tasks"][0]["status"] = "done"
    index_path.write_text(json.dumps(data), encoding="utf-8")
    proc = _module("heal_orphans", repo)
    assert "⚠️  TASK-9001: done but NO completed/ twin — leaving active file (manual review)." in proc.stdout
    assert "0 orphan(s) reaped, 1 kept for review." in proc.stdout
    assert (repo / "sdd/tasks/active/TASK-9001-demo.md").is_file()


def test_close_removes_orphan_active_copy(repo: Path) -> None:
    (repo / "sdd/tasks/completed/TASK-9001-demo.md").write_text("# twin\n", encoding="utf-8")
    proc = _module("close_task", repo, "TASK-9001", "demo")
    assert proc.returncode == 0, proc.stderr
    assert "✓ TASK-9001: removed orphan active copy (twin already in completed/)." in proc.stdout
    assert not (repo / "sdd/tasks/active/TASK-9001-demo.md").exists()


def test_ports_do_not_shell_out_to_jq_or_bash() -> None:
    for name in ("close_task", "heal_orphans"):
        text = (SRC / "parrot" / "sdd" / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert '"jq"' not in text and '"bash"' not in text
