"""C34 — ``parrot sdd install`` registers the sdd-coder and bounded-source MCP toolkits."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.flows.dev_loop.sdd_coder import roster as roster_mod
from parrot.sdd.cli import sdd as sdd_cli
from parrot.sdd.installer import (
    install_sdd_integration,
    load_receipt,
    sdd_status,
    uninstall_sdd_integration,
)
from parrot.self_.doctor import run_doctor

CONFIG = Path(".parrot/mcp-toolkits.yaml")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    return tmp_path


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe with no credentials and no CLIs unless a test injects them."""
    real = roster_mod.RosterProbe

    def factory(**kw):
        kw.setdefault("config_getter", lambda *a, **k: None)
        kw.setdefault("which", lambda *_: None)
        return real(**kw)

    monkeypatch.setattr(roster_mod, "RosterProbe", factory)


def _servers(root: Path) -> set[str]:
    return set(json.loads((root / ".mcp.json").read_text())["mcpServers"])


def test_install_registers_both_toolkits(repo: Path) -> None:
    actions = install_sdd_integration(repo)
    assert {"parrot-sdd-coder", "parrot-bounded-source"} <= _servers(repo)
    text = (repo / CONFIG).read_text()
    assert "sdd-coder:" in text and "bounded-source:" in text
    assert load_receipt(repo)["toolkits"] == ["bounded-source", "sdd-coder"]
    assert not [a for a in actions if a.startswith("warning:") and "toolkit" in a]


def test_reinstall_is_byte_identical(repo: Path) -> None:
    install_sdd_integration(repo)
    before = {p: (repo / p).read_bytes() for p in (CONFIG, Path(".mcp.json"))}
    actions = install_sdd_integration(repo)
    assert {p: (repo / p).read_bytes() for p in before} == before
    assert any("already installed" in a and not a.startswith("warning:") for a in actions)
    assert load_receipt(repo)["toolkits"] == ["bounded-source", "sdd-coder"]


def test_preexisting_toolkit_is_not_recorded_or_removed(repo: Path) -> None:
    from parrot.mcp.hosts import HostKind
    from parrot.mcp.toolkit_install import install_toolkits

    install_toolkits(repo, ["bounded-source"], [HostKind.CLAUDE])
    install_sdd_integration(repo)
    assert load_receipt(repo)["toolkits"] == ["sdd-coder"]
    uninstall_sdd_integration(repo)
    assert "bounded-source:" in (repo / CONFIG).read_text()
    assert "sdd-coder:" not in (repo / CONFIG).read_text()
    assert "parrot-bounded-source" in _servers(repo)
    assert "parrot-sdd-coder" not in _servers(repo)


def test_roster_note_and_strong_seat_warning(repo: Path) -> None:
    actions = install_sdd_integration(repo)
    note = next(a for a in actions if a.startswith("note: sdd-coder seats available:"))
    assert "haiku" in note and "opus" in note and "unavailable:" in note
    assert any(a.startswith("warning:") and "no retry seat" in a for a in actions)


def test_strong_seats_with_credentials_do_not_warn(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = roster_mod.RosterProbe

    def factory(**kw):
        kw["config_getter"] = lambda *a, **k: "x"
        kw["which"] = lambda name: f"/bin/{name}"
        return real(**kw)

    monkeypatch.setattr(roster_mod, "RosterProbe", factory)
    actions = install_sdd_integration(repo)
    assert not any("no retry seat" in a for a in actions)


def test_no_sdd_coder_opt_out(repo: Path) -> None:
    install_sdd_integration(repo, sdd_coder=False)
    assert not (repo / CONFIG).exists()
    assert not (repo / ".mcp.json").exists()
    assert "toolkits" not in load_receipt(repo)


def test_cli_flag_and_dry_run(repo: Path) -> None:
    runner = CliRunner()
    out = runner.invoke(sdd_cli, ["install", "--path", str(repo), "--dry-run"])
    assert out.exit_code == 0, out.output
    assert "plan: toolkits sdd-coder, bounded-source" in out.output
    assert not (repo / CONFIG).exists()
    off = runner.invoke(sdd_cli, ["install", "--path", str(repo), "--dry-run", "--no-sdd-coder"])
    assert "plan: toolkits" not in off.output


def test_fresh_repo_end_to_end_portable(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host then SDD installation emits portable host config, hooks, and doctor form checks."""
    managed_bin = repo / "parrot-home" / "bin"
    managed_bin.mkdir(parents=True)
    launcher = managed_bin / "parrot"
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    monkeypatch.setenv("PARROT_HOME", str(repo / "parrot-home"))
    monkeypatch.setenv("PATH", f"{managed_bin}{os.pathsep}{os.environ['PATH']}")

    actions = install_sdd_integration(repo, hosts=("claude",), portable=None)
    servers = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    for name in ("parrot-sdd-coder", "parrot-bounded-source"):
        assert servers[name]["command"] == "parrot"
        assert servers[name]["args"][-1] == ".parrot/mcp-toolkits.yaml"
        assert "cwd" not in servers[name]
    settings = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
    assert "parrot" in str(settings)
    assert not any(action.startswith("note: host config baked") for action in actions)
    forms = [check for check in run_doctor(repo) if check.name.endswith(" form")]
    assert any(check.name == "host config: claude .mcp.json form" and check.detail == "portable" for check in forms)


def test_fresh_repo_end_to_end_baked_with_note(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a launcher, SDD reports each baked fallback once and doctor stays informational."""
    empty_bin = repo / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", f"{empty_bin}{os.pathsep}{os.defpath}")

    actions = install_sdd_integration(repo, hosts=("claude",), portable=None)
    host_notes = [action for action in actions if action.startswith("note: host config baked to absolute paths")]
    guard_notes = [action for action in actions if action.startswith("note: guard hook baked")]
    assert len(host_notes) == 1
    assert len(guard_notes) == 1
    forms = [check for check in run_doctor(repo) if check.name.endswith(" form")]
    form = next(check for check in forms if check.name == "host config: claude .mcp.json form")
    assert form.informational and form.detail == "baked absolute paths"


@pytest.mark.parametrize("portable", [None, True, False])
def test_sdd_install_portable_reaches_toolkits(
    repo: Path, monkeypatch: pytest.MonkeyPatch, portable: bool | None
) -> None:
    """Selected hosts receive the explicit form, including False, and retain owned toolkit receipts."""
    monkeypatch.setattr("parrot.mcp.portability.managed_launcher_on_path", lambda: True)
    args = ["install", "--path", str(repo), "--host", "claude", "--host", "codex"]
    if portable is True:
        args.append("--portable")
    elif portable is False:
        args.append("--no-portable")
    result = CliRunner().invoke(sdd_cli, args)
    assert result.exit_code == 0, result.output

    claude = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    codex = (repo / ".codex/config.toml").read_text(encoding="utf-8")
    for name in ("sdd-coder", "bounded-source"):
        entry = claude[f"parrot-{name}"]
        if portable is False:
            assert entry["args"][-1] == str(repo / ".parrot/mcp-toolkits.yaml")
            assert entry["cwd"] == str(repo)
            assert str(repo / ".parrot/mcp-toolkits.yaml") in codex
        else:
            assert entry["command"] == "parrot" and entry["args"][-1] == ".parrot/mcp-toolkits.yaml"
            assert "cwd" not in entry and 'command = "parrot"' in codex
    assert load_receipt(repo)["toolkits"] == ["bounded-source", "sdd-coder"]


def test_malformed_toolkit_config_is_a_warning(repo: Path) -> None:
    (repo / CONFIG).parent.mkdir(parents=True)
    (repo / CONFIG).write_text("toolkits: [unclosed\n")
    actions = install_sdd_integration(repo)
    assert any(a.startswith("warning: MCP toolkits not registered") for a in actions)
    assert (repo / "sdd/.sdd-installed.json").is_file()


def test_status_reports_toolkits(repo: Path) -> None:
    assert sdd_status(repo)["toolkits"] == {"sdd-coder": "not_installed", "bounded-source": "not_installed"}
    install_sdd_integration(repo)
    assert sdd_status(repo)["toolkits"] == {"sdd-coder": "enabled", "bounded-source": "enabled"}
