"""Subprocess state machine for parrot.launcher re-exec (spec §4 integration rows)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX execv path; Windows covered by the install matrix")
STUB = "#!{py}\nimport json, os, sys\nprint(json.dumps({{'venv': {name!r}, 'argv': sys.argv[1:], 'guard': os.environ.get('PARROT_LAUNCHER_RESOLVED')}}))\n"


def fake_venv(path: Path, name: str, *scripts: str) -> Path:
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for script in scripts:
        stub = path / "bin" / script
        stub.write_text(STUB.format(py=sys.executable, name=name), encoding="utf-8")
        stub.chmod(0o755)
    return path


@pytest.fixture
def fake_managed_home(tmp_path: Path) -> Path:
    """PARROT_HOME whose venv/ symlinks to the running interpreter's prefix ⇒ is_managed() is True."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "venv").symlink_to(sys.prefix, target_is_directory=True)
    return home


#: Resolution inputs inherited from the developer's shell/Claude session would hijack the matrix.
SCRUB = ("PARROT_LAUNCHER_RESOLVED", "PARROT_VENV", "PARROT_PROJECT", "CLAUDE_PROJECT_DIR", "VIRTUAL_ENV", "PARROT_HOME")


def run_wrapper(func: str, args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    code = f"import sys; from parrot.launcher import {func}; sys.argv[0] = 'x'; sys.exit({func}())"
    base = {k: v for k, v in os.environ.items() if k not in SCRUB}
    return subprocess.run([sys.executable, "-c", code, *args], cwd=cwd, env={**base, **env},
                          capture_output=True, text=True, timeout=120, check=False)


def test_managed_reexecs_into_project(fake_managed_home, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "wikitoolkit")
    env = {"PARROT_HOME": str(fake_managed_home)}
    res = run_wrapper("main_wikitoolkit", ["status", "--x"], cwd=proj, env=env)
    payload = json.loads(res.stdout)
    assert payload == {"venv": "project", "argv": ["status", "--x"], "guard": "1"}


def _home_env(home: Path, **extra: str) -> dict[str, str]:
    return {"PARROT_HOME": str(home), **extra}


def test_parrot_venv_wins(fake_managed_home, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "wikitoolkit")
    explicit = fake_venv(tmp_path / "explicit", "explicit", "wikitoolkit")
    res = run_wrapper("main_wikitoolkit", ["a"], cwd=proj, env=_home_env(fake_managed_home, PARROT_VENV=str(explicit)))
    assert json.loads(res.stdout)["venv"] == "explicit"


def test_project_missing_script_warns_then_virtual_env(fake_managed_home, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "other")
    ve = fake_venv(tmp_path / "ve", "virtualenv", "wikitoolkit")
    res = run_wrapper("main_wikitoolkit", [], cwd=proj, env=_home_env(fake_managed_home, VIRTUAL_ENV=str(ve)))
    assert json.loads(res.stdout)["venv"] == "virtualenv"
    assert res.stderr.count("has no 'wikitoolkit'") == 1


def test_linked_worktree_local_then_main(fake_managed_home, tmp_path):
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    fake_venv(main / ".venv", "main", "wikitoolkit")
    env = _home_env(fake_managed_home)
    assert json.loads(run_wrapper("main_wikitoolkit", [], cwd=wt, env=env).stdout)["venv"] == "main"
    fake_venv(wt / ".venv", "worktree", "wikitoolkit")
    assert json.loads(run_wrapper("main_wikitoolkit", [], cwd=wt, env=env).stdout)["venv"] == "worktree"


def test_leading_project_flag_is_stripped(fake_managed_home, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "wikitoolkit")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    res = run_wrapper("main_wikitoolkit", ["--project", str(proj), "status"], cwd=elsewhere, env=_home_env(fake_managed_home))
    assert json.loads(res.stdout) == {"venv": "project", "argv": ["status"], "guard": "1"}


def test_loop_guard_runs_in_place(fake_managed_home, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "bookstore")
    res = run_wrapper("main_bookstore", ["--help"], cwd=proj, env=_home_env(fake_managed_home, PARROT_LAUNCHER_RESOLVED="1"))
    assert res.returncode == 0 and '"venv"' not in res.stdout


def test_not_managed_runs_in_place(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    fake_venv(proj / ".venv", "project", "bookstore")
    res = run_wrapper("main_bookstore", ["--help"], cwd=proj, env=_home_env(tmp_path / "elsewhere-home"))
    assert res.returncode == 0 and '"venv"' not in res.stdout


def test_no_candidate_runs_in_place(fake_managed_home, tmp_path):
    cwd = tmp_path / "bare"
    cwd.mkdir()
    res = run_wrapper("main_bookstore", ["--help"], cwd=cwd, env=_home_env(fake_managed_home))
    assert res.returncode == 0 and '"venv"' not in res.stdout


def test_managed_to_project_reexec_stdio(fake_managed_home, tmp_path):
    """JSON-RPC initialize round-trip survives the re-exec; launcher writes nothing to stdout."""
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".venv" / "bin").mkdir(parents=True)
    (proj / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    stub = proj / ".venv" / "bin" / "wikitoolkit"
    stub.write_text(
        f"#!{sys.executable}\nimport json, sys\nreq = json.loads(sys.stdin.readline())\n"
        "sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': {'protocolVersion': '2025-06-18'}}) + '\\n')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    code = "import sys; from parrot.launcher import main_wikitoolkit; sys.exit(main_wikitoolkit())"
    base = {k: v for k, v in os.environ.items() if k not in SCRUB}
    res = subprocess.run(
        [sys.executable, "-c", code, "mcp"], cwd=proj, env={**base, "PARROT_HOME": str(fake_managed_home)},
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n",
        capture_output=True, text=True, timeout=120, check=False,
    )
    lines = res.stdout.splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["id"] == 1
