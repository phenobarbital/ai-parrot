"""Tests for the strict native launcher behind ``launch_worker.sh``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCH_WORKER_SH = REPO_ROOT / "scripts" / "sdd" / "launch_worker.sh"


def _write_executable(path: Path, content: str = "#!/bin/sh\nexit 0\n") -> None:
    """Write a small executable used as a host-prerequisite stub."""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def fake_claude_path(tmp_path: Path) -> str:
    """Return a PATH with Claude and native-sandbox prerequisite stubs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "claude",
        "#!/bin/sh\n"
        "printf 'BACKEND=%s\\n' \"$PARROT_SDD_SANDBOX_BACKEND\"\n"
        "printf 'DEGRADED=%s\\n' \"$PARROT_SDD_SANDBOX_DEGRADED\"\n"
        "printf 'CACHE=%s\\n' \"$PARROT_SDD_CACHE_DIR\"\n"
        "printf '%s\\n' \"$@\"\n",
    )
    _write_executable(bin_dir / "bwrap")
    _write_executable(bin_dir / "socat")
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


@pytest.fixture
def linked_cwd(tmp_path: Path) -> Path:
    """Create a fake linked worktree with valid common-Git metadata."""
    primary = tmp_path / "primary"
    git_dir = primary / ".git"
    admin_dir = git_dir / "worktrees" / "feature"
    linked = primary / ".claude" / "worktrees" / "feature"
    admin_dir.mkdir(parents=True)
    linked.mkdir(parents=True)
    (admin_dir / "commondir").write_text("../..\n", encoding="utf-8")
    (linked / ".git").write_text(f"gitdir: {admin_dir}\n", encoding="utf-8")
    return linked


def _run(path: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the launcher from ``cwd`` with a controlled executable path."""
    return subprocess.run(
        ["/bin/bash", str(LAUNCH_WORKER_SH), *args],
        cwd=cwd,
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> tuple[dict[str, str], list[str]]:
    """Split the Claude stub's environment markers from its argv."""
    lines = result.stdout.splitlines()
    environment = dict(line.split("=", 1) for line in lines[:3])
    return environment, lines[3:]


def test_defaults_exclude_user_source(fake_claude_path: str, linked_cwd: Path) -> None:
    result = _run(fake_claude_path, linked_cwd)
    assert result.returncode == 0, result.stderr
    _environment, argv = _output(result)
    assert argv[:2] == ["--agent", "sdd-worker"]
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "user" not in argv[argv.index("--setting-sources") + 1].split(",")


def test_forwards_extra_args_and_keeps_caller_model(fake_claude_path: str, linked_cwd: Path) -> None:
    result = _run(fake_claude_path, linked_cwd, "--model", "opus", "--verbose", "prompt with spaces")
    assert result.returncode == 0, result.stderr
    _environment, argv = _output(result)
    assert argv.count("--model") == 1
    assert argv[argv.index("--model") + 1] == "opus"
    assert "--verbose" in argv
    assert "prompt with spaces" in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"


def test_caller_sources_without_user_are_kept(fake_claude_path: str, linked_cwd: Path) -> None:
    result = _run(fake_claude_path, linked_cwd, "--setting-sources=project")
    assert result.returncode == 0, result.stderr
    _environment, argv = _output(result)
    assert [arg for arg in argv if arg.startswith("--setting-sources")] == ["--setting-sources=project"]


def test_settings_is_one_strict_json_argument(fake_claude_path: str, linked_cwd: Path) -> None:
    result = _run(fake_claude_path, linked_cwd)
    assert result.returncode == 0, result.stderr
    _environment, argv = _output(result)
    assert argv.count("--settings") == 1
    settings = json.loads(argv[argv.index("--settings") + 1])
    sandbox = settings["sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert sandbox["network"]["allowAllUnixSockets"] is False


def test_allow_domain_repeatable_and_normalized(fake_claude_path: str, linked_cwd: Path) -> None:
    result = _run(
        fake_claude_path,
        linked_cwd,
        "--sandbox-allow-domain",
        "API.Example.COM.",
        "--sandbox-allow-domain=cdn.example.com",
        "--sandbox-allow-domain",
        "api.example.com",
    )
    assert result.returncode == 0, result.stderr
    _environment, argv = _output(result)
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["sandbox"]["network"]["allowedDomains"] == ["api.example.com", "cdn.example.com"]
    assert not any(arg.startswith("--sandbox-allow-domain") for arg in argv)


@pytest.mark.parametrize(
    "args",
    [
        ["--settings", "{}"],
        ["--settings={}"],
        ["--add-dir", "/"],
        ["--add-dir=/"],
        ["--agent", "x"],
        ["--agent=x"],
        ["--setting-sources", "user,project"],
        ["--setting-sources=project,user"],
    ],
)
def test_policy_overrides_rejected(
    fake_claude_path: str,
    linked_cwd: Path,
    args: list[str],
) -> None:
    result = _run(fake_claude_path, linked_cwd, *args)
    assert result.returncode == 2
    assert result.stdout == ""
    assert args[0].split("=", 1)[0] in result.stderr


def test_primary_checkout_refused(fake_claude_path: str, tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    result = _run(fake_claude_path, primary)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "primary checkout" in result.stderr


@pytest.mark.parametrize("missing", ["claude", "bwrap", "socat"])
def test_missing_prerequisite_exits_1(tmp_path: Path, linked_cwd: Path, missing: str) -> None:
    bin_dir = tmp_path / f"missing-{missing}"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    (bin_dir / "dirname").symlink_to("/usr/bin/dirname")
    for executable in {"claude", "bwrap", "socat"} - {missing}:
        _write_executable(bin_dir / executable)
    result = _run(str(bin_dir), linked_cwd)
    assert result.returncode == 1
    assert result.stdout == ""
    assert missing in result.stderr


def test_required_mode_refuses_failing_bwrap_probe(fake_claude_path: str, linked_cwd: Path) -> None:
    bin_dir = Path(fake_claude_path.split(os.pathsep)[0])
    _write_executable(bin_dir / "bwrap", "#!/bin/sh\necho user namespaces denied >&2\nexit 1\n")

    result = _run(fake_claude_path, linked_cwd)

    assert result.returncode == 1
    assert "native sandbox unavailable (user namespaces denied); mode=required refuses to start" in result.stderr


def test_backend_env_set_for_child(fake_claude_path: str, linked_cwd: Path) -> None:
    result = _run(fake_claude_path, linked_cwd)
    assert result.returncode == 0, result.stderr
    environment, _argv = _output(result)
    assert environment["BACKEND"] == "claude-native"
    assert environment["DEGRADED"] == ""
    cache_dir = Path(environment["CACHE"])
    assert cache_dir.parent.name == "parrot-sdd-cache"
    assert cache_dir.is_dir()
    assert (cache_dir / "owner.pid").is_file()


def test_next_launch_removes_dead_owned_cache(fake_claude_path: str, linked_cwd: Path) -> None:
    first = _run(fake_claude_path, linked_cwd)
    assert first.returncode == 0, first.stderr
    first_environment, _first_argv = _output(first)
    first_cache = Path(first_environment["CACHE"])
    assert first_cache.is_dir()

    second = _run(fake_claude_path, linked_cwd)
    assert second.returncode == 0, second.stderr
    second_environment, _second_argv = _output(second)
    assert not first_cache.exists()
    assert Path(second_environment["CACHE"]).is_dir()


def test_pyproject_preferred_mode_degrades_after_failing_probe(
    fake_claude_path: str, linked_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (linked_cwd / "pyproject.toml").write_text("[tool.parrot.sdd]\nsandbox = 'preferred'\n", encoding="utf-8")
    bin_dir = Path(fake_claude_path.split(os.pathsep)[0])
    _write_executable(bin_dir / "bwrap", "#!/bin/sh\necho unavailable >&2\nexit 1\n")

    result = _run(fake_claude_path, linked_cwd)

    assert result.returncode == 0
    environment, argv = _output(result)
    assert environment["DEGRADED"] == "1"
    assert "sandbox" not in json.loads(argv[argv.index("--settings") + 1])
    assert "WARNING native sandbox unavailable (unavailable); mode=preferred launches DEGRADED" in result.stderr


def test_off_mode_skips_probe(fake_claude_path: str, linked_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARROT_SDD_SANDBOX_MODE", "off")
    bin_dir = Path(fake_claude_path.split(os.pathsep)[0])
    _write_executable(bin_dir / "bwrap", "#!/bin/sh\necho probe-called >&2\nexit 1\n")

    result = _run(fake_claude_path, linked_cwd)

    assert result.returncode == 0
    environment, argv = _output(result)
    assert environment["DEGRADED"] == "1"
    assert "sandbox" not in json.loads(argv[argv.index("--settings") + 1])
    assert "probe-called" not in result.stderr


def test_invalid_mode_exits_2(fake_claude_path: str, linked_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARROT_SDD_SANDBOX_MODE", "unsafe")

    result = _run(fake_claude_path, linked_cwd)

    assert result.returncode == 2
    assert "PARROT_SDD_SANDBOX_MODE" in result.stderr
