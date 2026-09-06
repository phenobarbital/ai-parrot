"""Offline contracts for ``parrot google`` WikiToolkit integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.installer import (
    install_google_integration,
    integration_status,
    uninstall_google_integration,
)


@pytest.fixture
def mcp_config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "custom_mcp/mcp_config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mcp_config_path: Path) -> Path:
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / ".git").mkdir()
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "missing-library"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "global"))
    monkeypatch.setattr(assets, "default_mcp_config_path", lambda: mcp_config_path)
    return repo_path


def test_install_writes_mcp_skill_instructions_and_plugin(repo: Path, mcp_config_path: Path) -> None:
    actions = install_google_integration(repo, mcp_config_path=mcp_config_path)

    assert any("GEMINI.md" in a for a in actions)
    assert any("parrot-wiki" in a for a in actions)
    assert any("wikitoolkit MCP" in a for a in actions)

    # Check GEMINI.md
    assert assets.AGENTS_BEGIN in (repo / "GEMINI.md").read_text(encoding="utf-8")

    # Check skills
    assert (repo / assets.SKILL_PATH).read_text(encoding="utf-8") == assets.SKILL

    # Check mcp_config.json
    mcp_data = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    server = mcp_data["mcpServers"]["wikitoolkit"]
    assert server["args"] == ["mcp"]
    assert server["cwd"] == str(repo.resolve())

    # Check workspace plugin
    plugin_manifest = repo / assets.PLUGIN_DIR / "plugin.json"
    assert plugin_manifest.exists()
    plugin_mcp = repo / assets.PLUGIN_DIR / "mcp_config.json"
    assert plugin_mcp.exists()

    # Check .parrot/wiki.json and .gitignore
    assert (repo / ".parrot/wiki.json").exists()
    assert ".parrot/" in (repo / ".gitignore").read_text(encoding="utf-8")


def test_install_is_idempotent_and_preserves_unrelated_config(repo: Path, mcp_config_path: Path) -> None:
    mcp_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "foreign-server": {
                        "command": "foreign-cmd",
                        "args": ["--serve"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    install_google_integration(repo, mcp_config_path=mcp_config_path)
    first_mcp = mcp_config_path.read_bytes()
    gemini_md = (repo / "GEMINI.md").read_bytes()

    install_google_integration(repo, mcp_config_path=mcp_config_path)
    assert mcp_config_path.read_bytes() == first_mcp
    assert (repo / "GEMINI.md").read_bytes() == gemini_md

    parsed = json.loads(first_mcp.decode("utf-8"))
    assert "foreign-server" in parsed["mcpServers"]
    assert parsed["mcpServers"]["foreign-server"]["command"] == "foreign-cmd"
    assert "wikitoolkit" in parsed["mcpServers"]


def test_invalid_mcp_config_aborts_without_overwriting(repo: Path, mcp_config_path: Path) -> None:
    mcp_config_path.write_text("{broken json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Cannot parse"):
        install_google_integration(repo, mcp_config_path=mcp_config_path)

    assert mcp_config_path.read_text(encoding="utf-8") == "{broken json"


def test_uninstall_removes_only_managed_assets(repo: Path, mcp_config_path: Path) -> None:
    (repo / "GEMINI.md").write_text("# User instructions\n", encoding="utf-8")
    mcp_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "foreign-server": {
                        "command": "foreign-cmd",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    install_google_integration(repo, mcp_config_path=mcp_config_path)
    uninstall_google_integration(repo, mcp_config_path=mcp_config_path)

    gemini_text = (repo / "GEMINI.md").read_text(encoding="utf-8")
    assert "# User instructions" in gemini_text
    assert assets.AGENTS_BEGIN not in gemini_text

    mcp_data = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    assert "foreign-server" in mcp_data["mcpServers"]
    assert "wikitoolkit" not in mcp_data["mcpServers"]

    assert not (repo / assets.SKILL_PATH).exists()
    assert not (repo / assets.PLUGIN_DIR / "mcp_config.json").exists()
    assert (repo / ".parrot/wiki.json").exists()


def test_status_and_top_level_cli(repo: Path, mcp_config_path: Path) -> None:
    before = integration_status(repo, mcp_config_path=mcp_config_path)
    assert not before["mcp"]
    assert not before["gemini_md_section"]

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["google", "install", "--path", str(repo), "--no-build"],
    )

    assert result.exit_code == 0, result.output
    assert "Google Antigravity integration installed" in result.output

    after = integration_status(repo, mcp_config_path=mcp_config_path)
    assert after["mcp"]
    assert after["gemini_md_section"]
    assert after["skill"]
    assert after["plugin"]

    status_res = runner.invoke(cli, ["google", "status", "--path", str(repo)])
    assert status_res.exit_code == 0
    assert "✓ wikitoolkit MCP server" in status_res.output

    # Status as JSON
    status_json = runner.invoke(cli, ["google", "status", "--path", str(repo), "--json"])
    assert status_json.exit_code == 0
    parsed = json.loads(status_json.output)
    assert parsed["mcp"] is True


def test_gemini_alias_cli(repo: Path, mcp_config_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["gemini", "install", "--path", str(repo), "--no-build"],
    )
    assert result.exit_code == 0, result.output
    assert "Google Antigravity integration installed" in result.output
