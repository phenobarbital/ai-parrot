"""`parrot self doctor` checks (FEAT-633, TASK-4080)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from parrot.self_ import doctor
from parrot.self_.uv import UvResolution


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PARROT_HOME + fake HOME so the Google user-global config is a tmp file."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_uv_check_uses_recorded_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A compatible recorded system uv satisfies the runtime doctor check."""
    recorded = tmp_path / "uv"
    monkeypatch.setattr(
        doctor,
        "resolve_uv",
        lambda: UvResolution(path=recorded, version="0.11.30", source="recorded"),
    )
    check = doctor._check_uv()
    assert check.ok and "recorded" in check.detail and "0.11.30" in check.detail


def test_uv_check_reports_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unresolved uv supplies the installer recovery instruction."""
    monkeypatch.setattr(
        doctor,
        "resolve_uv",
        lambda: (_ for _ in ()).throw(FileNotFoundError("no compatible uv")),
    )
    check = doctor._check_uv()
    assert not check.ok and check.detail == "no compatible uv" and check.fix == "re-run install-parrot --global"


def test_uv_layout_check_is_informational(isolated_home: Path) -> None:
    """Legacy bin uv is informational because doctor remains read-only."""
    home = isolated_home / "parrot-home"
    path = home / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    check = doctor._check_uv_layout()
    assert not check.ok and check.informational and str(path) in check.detail
    path.unlink()
    clean = doctor._check_uv_layout()
    assert clean.ok and clean.informational


def test_runtime_only_includes_uv_layout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Runtime-only doctor output includes the legacy layout diagnostic."""
    monkeypatch.setattr(doctor, "_check_uv", lambda: doctor.DoctorCheck(name="uv", ok=True))
    monkeypatch.setattr(doctor, "_check_uv_layout", lambda: doctor.DoctorCheck(name="uv layout", ok=True))
    monkeypatch.setattr(doctor, "_check_python", lambda: doctor.DoctorCheck(name="python", ok=True))
    monkeypatch.setattr(doctor, "_check_entrypoints", lambda: doctor.DoctorCheck(name="entrypoints", ok=True))
    monkeypatch.setattr(doctor, "_check_path", lambda: doctor.DoctorCheck(name="PATH", ok=True))
    monkeypatch.setattr(doctor, "_check_tools_wiki", lambda: doctor.DoctorCheck(name="tools", ok=True))
    monkeypatch.setattr(doctor, "_check_runtime_lockstep", lambda: doctor.DoctorCheck(name="lockstep", ok=True))
    assert "uv layout" in [check.name for check in doctor.run_doctor(tmp_path, scope="runtime-only")]


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


def test_doctor_host_config_form(isolated_home: Path, tmp_path: Path) -> None:
    """Each present config gets its own informational form without altering failure status."""
    from parrot.knowledge.wiki.codex import assets as codex_assets
    from parrot.knowledge.wiki.google.installer import toolkit_config_paths

    repo = tmp_path / "repo"
    repo.mkdir()
    assert not doctor._check_host_config_forms(repo)

    claude = repo / ".mcp.json"
    codex = repo / ".codex" / "config.toml"
    google, google_local = toolkit_config_paths(repo)
    codex.parent.mkdir(parents=True)
    google.parent.mkdir(parents=True)
    google_local.parent.mkdir(parents=True)

    claude.write_text(json.dumps({"mcpServers": {"foreign": {"command": "foreign"}}}), encoding="utf-8")
    codex.write_text("title = 'foreign'\n", encoding="utf-8")
    google.write_text(json.dumps({"mcpServers": {"foreign": {"command": "foreign"}}}), encoding="utf-8")
    google_local.write_text(json.dumps({"mcpServers": {"foreign": {"command": "foreign"}}}), encoding="utf-8")
    forms = doctor._check_host_config_forms(repo)
    assert len(forms) == 4
    assert {check.detail for check in forms} == {"no managed entries"}
    assert not doctor.failed(forms)

    claude.write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}}}),
        encoding="utf-8",
    )
    codex.write_text(
        "\n".join(
            (
                codex_assets.MCP_BEGIN,
                f"[{codex_assets.MCP_TABLE}]",
                'command = "/opt/parrot/bin/wikitoolkit"',
                'args = ["mcp"]',
                codex_assets.MCP_END,
                "",
            )
        ),
        encoding="utf-8",
    )
    google.write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}}}),
        encoding="utf-8",
    )
    google_local.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "wikitoolkit": {
                        "command": "/opt/parrot/bin/wikitoolkit",
                        "args": ["mcp"],
                        "cwd": str(repo),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    forms = {check.name: check for check in doctor._check_host_config_forms(repo)}
    assert forms["host config: claude .mcp.json form"].detail == "portable"
    assert forms["host config: codex config.toml form"].detail == "baked absolute paths"
    assert forms["host config: google mcp_config.json (user-global) form"].detail == "portable"
    assert forms["host config: google mcp_config.json (repo-local) form"].detail == "baked absolute paths"
    assert all(check.informational and check.ok for check in forms.values())
    assert all("--portable" in check.fix for check in forms.values() if check.detail == "baked absolute paths")

    claude.write_text("{", encoding="utf-8")
    checks = doctor._check_host_configs(repo)
    assert any(check.name == "host config: claude .mcp.json" and not check.ok for check in checks)
    malformed_form = next(check for check in checks if check.name == "host config: claude .mcp.json form")
    assert malformed_form.detail == "no managed entries" and malformed_form.informational


def test_doctor_google_form_uses_repo_root(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Google form helper receives the repo root and the file to inspect — never a config as ``root``."""
    from parrot.knowledge.wiki.google import installer as google_installer
    from parrot.knowledge.wiki.google.installer import toolkit_config_paths

    repo = tmp_path / "repo"
    repo.mkdir()
    google, google_local = toolkit_config_paths(repo)
    google.parent.mkdir(parents=True)
    google_local.parent.mkdir(parents=True)
    managed = json.dumps({"mcpServers": {"wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}}})
    google.write_text(managed, encoding="utf-8")
    google_local.write_text(managed, encoding="utf-8")

    seen: list[tuple[Path, Path]] = []
    real = google_installer.portable_mode_of_config

    def _spy(path: Path, root: Path) -> bool | None:
        seen.append((path, root))
        return real(path, root)

    monkeypatch.setattr(google_installer, "portable_mode_of_config", _spy)
    doctor._check_host_config_forms(repo)
    assert seen == [(google, repo), (google_local, repo)]
    assert all(root.is_dir() for _, root in seen)


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


@pytest.mark.parametrize(
    "key, entry",
    [
        ("bookstore", {"command": ".venv/bin/python3", "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"]}),
        ("my-wiki", {"command": "/opt/x/.venv/bin/wikitoolkit", "args": ["mcp"]}),
        ("books", {"command": "python3", "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"]}),
    ],
)
def test_gemini_cross_repo_collision_matches_parrot_entries(
    isolated_home: Path, tmp_path: Path, key: str, entry: dict
) -> None:
    """TASK-5115 (issue:a7deda11b8c3): bookstore and command-matched parrot entries are collision candidates."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = isolated_home / ".gemini" / "config" / "mcp_config.json"
    cfg.parent.mkdir(parents=True)
    other = tmp_path / "other-repo"
    cfg.write_text(json.dumps({"mcpServers": {key: {**entry, "cwd": str(other)}}}), encoding="utf-8")
    collision = [c for c in doctor._check_host_configs(repo) if c.name == "host config: google cross-repo collision"]
    assert collision and f"{key} -> {other.resolve()}" in collision[0].detail


def test_gemini_foreign_non_parrot_entry_is_not_a_collision(isolated_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = isolated_home / ".gemini" / "config" / "mcp_config.json"
    cfg.parent.mkdir(parents=True)
    entry = {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"], "cwd": str(tmp_path / "x")}
    cfg.write_text(json.dumps({"mcpServers": {"filesystem": entry}}), encoding="utf-8")
    assert not [c for c in doctor._check_host_configs(repo) if "collision" in c.name]


@pytest.mark.parametrize(
    "stdout, ok, informational, fix",
    [
        ("1.4.0\n1.4.0\n", True, False, ""),
        ("1.5.0\n1.4.0\n", False, False, "parrot self update --version 1.4.0"),
        ("1.5.0\n\n", True, True, ""),  # ai-parrot-tools absent: parrot_tools.wiki already reports it
    ],
)
def test_runtime_lockstep_check(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, ok: bool, informational: bool, fix: str
) -> None:
    """TASK-5117 (issue:66700eac9b2f): doctor compares ai-parrot and ai-parrot-tools in the managed venv."""
    assert doctor._check_runtime_lockstep().informational  # no interpreter yet
    python = doctor.script_path(doctor.managed_venv(), "python")
    python.parent.mkdir(parents=True)
    python.write_text("")
    real = subprocess.CompletedProcess
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: real(a[0], 0, stdout, ""))
    check = doctor._check_runtime_lockstep()
    assert (check.ok, check.informational, check.fix) == (ok, informational, fix)
    assert (check in doctor.failed([check])) is (not ok and not informational)
