"""Tests for the E2E exploration agents' PreToolUse write guard."""
import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "e2e-exploration-write-guard.sh"
EXPL = "sdd/state/FEAT-1/e2e/exploration"


def _run(project: Path, stdin: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(["bash", str(HOOK)], input=stdin, text=True, capture_output=True, env=env, timeout=30)


def _payload(path: str, key: str = "file_path") -> str:
    return json.dumps({"tool_name": "Write", "tool_input": {key: path}})


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / EXPL).mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_allowed_absolute_and_relative(project: Path) -> None:
    assert _run(project, _payload(str(project / EXPL / "run-1" / "e2e-exploration.json"))).returncode == 0
    assert _run(project, _payload(f"{EXPL}/run-1/candidates/test_x.py")).returncode == 0


def test_notebook_path_key_is_checked(project: Path) -> None:
    assert _run(project, _payload("tests/n.ipynb", "notebook_path")).returncode == 2
    assert _run(project, _payload(f"{EXPL}/r/n.ipynb", "notebook_path")).returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_x.py",
        f"{EXPL}/../../../../tests/x.py",
        "/etc/passwd",
        "sdd/state/FEAT-1/e2e/other/x.json",
        "sdd/state/notfeat/e2e/exploration/x.json",
        EXPL,  # the directory itself, not a file inside it
    ],
)
def test_denied(project: Path, path: str) -> None:
    result = _run(project, _payload(path))
    assert result.returncode == 2
    assert "BLOCKED" in result.stderr


def test_symlink_escape_blocked(project: Path) -> None:
    (project / EXPL / "link").symlink_to(project / "tests")
    assert _run(project, _payload(f"{EXPL}/link/x.py")).returncode == 2


@pytest.mark.parametrize("stdin", ["", "not json", "{}", json.dumps({"tool_input": {}}), _payload("")])
def test_bad_input_fails_closed(project: Path, stdin: str) -> None:
    assert _run(project, stdin).returncode == 2
