"""Tests for scripts/sdd/launch_worker.sh (issue:6756c929a450).

The launcher must start ``claude --agent sdd-worker`` without the ``user``
setting source, because a user-level PreToolUse hook can replace the
Bubblewrap wrapper the agent-file hook installs. Black-box: a fake ``claude``
first on PATH prints the argv it received, one argument per line.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCH_WORKER_SH = REPO_ROOT / "scripts" / "sdd" / "launch_worker.sh"


@pytest.fixture
def fake_claude_path(tmp_path: Path) -> str:
    """Return a PATH whose first entry holds a ``claude`` stub echoing its argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    stub.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _run(path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(LAUNCH_WORKER_SH), *args],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        check=False,
    )


def test_defaults_exclude_user_source(fake_claude_path: str) -> None:
    result = _run(fake_claude_path)
    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()
    assert argv[:2] == ["--agent", "sdd-worker"]
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert not any("user" in arg for arg in argv)


def test_forwards_extra_args_and_keeps_caller_model(fake_claude_path: str) -> None:
    result = _run(fake_claude_path, "--model", "opus", "--verbose")
    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()
    assert argv.count("--model") == 1
    assert argv[argv.index("--model") + 1] == "opus"
    assert "--verbose" in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"


def test_caller_sources_without_user_are_kept(fake_claude_path: str) -> None:
    result = _run(fake_claude_path, "--setting-sources=project")
    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()
    assert [arg for arg in argv if arg.startswith("--setting-sources")] == ["--setting-sources=project"]


@pytest.mark.parametrize(
    "args",
    [
        ("--setting-sources", "user,project"),
        ("--setting-sources=project,user",),
        ("--setting-sources", "user"),
    ],
)
def test_refuses_user_source(fake_claude_path: str, args: tuple[str, ...]) -> None:
    result = _run(fake_claude_path, *args)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "issue:6756c929a450" in result.stderr
