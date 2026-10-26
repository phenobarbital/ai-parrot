"""`parrot self doctor` checks (FEAT-633, TASK-4080)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from parrot.self_ import doctor


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PARROT_HOME + fake HOME so the Google user-global config is a tmp file."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_doctor_flags_broken_host_config(isolated_home: Path, tmp_path: Path) -> None:
    """Spec §4 — a config pointing at a missing binary is reported."""
    repo = tmp_path / "repo"
    repo.mkdir()
    missing = tmp_path / "gone" / "wikitoolkit"
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": str(missing), "args": ["mcp"]}}}), encoding="utf-8"
    )
    checks = doctor._check_host_configs(repo)
    assert any(not c.ok and str(missing) in c.detail for c in checks)


def test_remote_http_entry_is_not_flagged(isolated_home: Path, tmp_path: Path) -> None:
    """A remote MCP entry has no `command` (claude_code/assets.py:128-134) — never a broken-command finding."""
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = {"type": "http", "url": "https://wiki.example/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"wikitoolkit": remote}}), encoding="utf-8")
    assert all(c.ok for c in doctor._check_host_configs(repo))


def test_gemini_cross_repo_collision(isolated_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = isolated_home / ".gemini" / "config" / "mcp_config.json"
    cfg.parent.mkdir(parents=True)
    other = tmp_path / "other-repo"
    exe = tmp_path / "bin-wikitoolkit"
    exe.write_text("")
    cfg.write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": str(exe), "args": ["mcp"], "cwd": str(other)}}}),
        encoding="utf-8",
    )
    checks = doctor._check_host_configs(repo)
    assert any(not c.ok and "--portable" in c.fix for c in checks)


def test_gemini_repo_local_config_checked(isolated_home: Path, tmp_path: Path) -> None:
    """Rev 0.5 C24 — the repo-local Gemini file is command-checked too."""
    repo = tmp_path / "repo"
    local = repo / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    local.parent.mkdir(parents=True)
    missing = tmp_path / "gone" / "parrot"
    local.write_text(
        json.dumps({"mcpServers": {"parrot-memory": {"command": str(missing), "args": ["mcp-local", "memory"]}}}),
        encoding="utf-8",
    )
    checks = doctor._check_host_configs(repo)
    assert any(not c.ok and str(missing) in c.detail for c in checks)
    exe = tmp_path / "parrot-bin"
    exe.write_text("")
    local.write_text(
        json.dumps({"mcpServers": {"parrot-memory": {"command": str(exe), "cwd": str(tmp_path / "other-repo")}}}),
        encoding="utf-8",
    )
    assert not any("--portable" in c.fix for c in doctor._check_host_configs(repo))


def test_tools_wiki_check(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    python = doctor.script_path(doctor.managed_venv(), "python")
    assert doctor._check_tools_wiki().ok is False  # no interpreter
    python.parent.mkdir(parents=True)
    python.write_text("")
    real = subprocess.CompletedProcess
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: real(a[0], 1, "", "ModuleNotFoundError: x\n"))
    check = doctor._check_tools_wiki()
    assert check.name == "parrot_tools.wiki" and not check.ok and check.fix == "parrot self update"
    assert "ModuleNotFoundError" in check.detail
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: real(a[0], 0, "", ""))
    assert doctor._check_tools_wiki().ok


def test_python_check_reads_pyvenv_cfg(isolated_home: Path) -> None:
    cfg = doctor.managed_venv() / "pyvenv.cfg"
    assert not doctor._check_python().ok  # missing file
    cfg.parent.mkdir(parents=True)
    for value, expected in (("3.11.9", False), ("3.12.3", True), ("3.12", True), ("3.120", False)):
        cfg.write_text(f"home = /x\nversion_info = {value}\n", encoding="utf-8")
        assert doctor._check_python().ok is expected, value


def test_path_check(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home_bin = isolated_home / "parrot-home" / "bin"
    home_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", f"/usr/bin{os.pathsep}{home_bin}")
    assert doctor._check_path().ok
    monkeypatch.setenv("PATH", "/usr/bin")
    check = doctor._check_path()
    assert not check.ok and str(home_bin) in check.fix


def test_toolkit_missing_env_and_dist(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.mcp.toolkit_seed import seed_toolkit_sections

    repo = tmp_path / "repo"
    repo.mkdir()
    seed_toolkit_sections(repo, ["querysource"])
    monkeypatch.delenv("PG_USER", raising=False)
    monkeypatch.delenv("PG_PWD", raising=False)
    monkeypatch.setattr("parrot.mcp.toolkit_install.dist_available", lambda *_a, **_k: False)
    checks = [c for c in doctor._check_toolkits(repo) if "querysource" in c.name]
    assert len(checks) == 2 and all(not c.ok and "parrot self add querysource" in c.fix for c in checks)
    assert any("env/.env" in c.detail for c in checks)


def test_run_doctor_never_raises_on_empty_home(isolated_home: Path, tmp_path: Path) -> None:
    checks = doctor.run_doctor(tmp_path)
    assert all(isinstance(c, doctor.DoctorCheck) for c in checks)
