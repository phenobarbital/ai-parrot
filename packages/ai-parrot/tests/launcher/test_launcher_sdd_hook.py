"""Launcher fast path for ``parrot sdd run worktree_environment --hook`` (FEAT-633 C16)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRUB = ("PARROT_LAUNCHER_RESOLVED", "PARROT_VENV", "PARROT_PROJECT", "CLAUDE_PROJECT_DIR", "VIRTUAL_ENV", "PARROT_HOME")
HOOK_ARGV = ["sdd", "run", "worktree_environment", "--hook"]
PROBE = (
    "import sys, atexit; from parrot.launcher import main_parrot; sys.argv[0] = 'parrot'\n"
    "atexit.register(lambda: sys.stderr.write('MODS=' + ','.join(m for m in ('click', 'parrot.cli') if m in sys.modules) + '\\n'))\n"
    "sys.exit(main_parrot())"
)


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k not in SCRUB}
    return {**base, "PARROT_HOME": str(tmp_path / "nohome"), **extra}


def _payloads(tmp_path: Path) -> dict[str, dict]:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return {
        "allow": {"cwd": str(repo), "tool_name": "Read", "tool_input": {"file_path": "x"}},
        "deny": {},
        "rewrite": {"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest"}},
    }


def _run(cmd: list[str], payload: dict, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, env=env,
                          cwd=cwd, timeout=60, check=False)


def _mods(stderr: str) -> str:
    return next(line for line in stderr.splitlines() if line.startswith("MODS=")).removeprefix("MODS=")


def test_fast_path_never_imports_click(tmp_path: Path) -> None:
    res = _run([sys.executable, "-c", PROBE, *HOOK_ARGV], _payloads(tmp_path)["allow"], _env(tmp_path), tmp_path)
    assert _mods(res.stderr) == "", res.stderr
    assert res.stdout.strip(), res.stderr


@pytest.mark.parametrize("kind", ["allow", "deny", "rewrite"])
def test_fast_path_matches_module_behaviour(tmp_path: Path, kind: str) -> None:
    payload = _payloads(tmp_path)[kind]
    env = _env(tmp_path)
    fast = _run([sys.executable, "-c", PROBE, *HOOK_ARGV], payload, env, tmp_path)
    ref = _run([sys.executable, "-m", "parrot.sdd.scripts.worktree_environment", "--hook"], payload, env, tmp_path)
    assert fast.returncode == ref.returncode
    assert json.loads(fast.stdout) == json.loads(ref.stdout)


@pytest.mark.skipif(os.name == "nt", reason="POSIX execv path")
def test_fast_path_survives_reexec(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "venv").symlink_to(sys.prefix, target_is_directory=True)
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".venv" / "bin").mkdir(parents=True)
    (proj / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    stub = proj / ".venv" / "bin" / "parrot"
    stub.write_text(f"#!{sys.executable}\nimport sys\n{PROBE.replace('sys.argv[0]', 'sys.argv[0]')}\n", encoding="utf-8")
    stub.chmod(0o755)
    payload = _payloads(tmp_path)["allow"]
    env = _env(tmp_path, PARROT_HOME=str(home))
    res = _run([sys.executable, "-c", PROBE, *HOOK_ARGV], payload, env, proj)
    assert _mods(res.stderr) == "", res.stderr
    assert json.loads(res.stdout)
