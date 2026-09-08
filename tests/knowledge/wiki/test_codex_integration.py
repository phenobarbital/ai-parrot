"""Offline contracts for ``parrot codex`` WikiToolkit integration."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.knowledge.wiki.codex import assets
from parrot.knowledge.wiki.codex.installer import (
    install_codex_integration,
    integration_status,
    uninstall_codex_integration,
)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "missing-library"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "global"))
    return tmp_path


def test_install_writes_mcp_skill_instructions_and_permissions(repo: Path) -> None:
    actions = install_codex_integration(repo)

    assert len(actions) == 6
    assert assets.AGENTS_BEGIN in (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert (repo / assets.SKILL_PATH).read_text(encoding="utf-8") == assets.SKILL

    config = tomllib.loads((repo / ".codex/config.toml").read_text(encoding="utf-8"))
    server = config["mcp_servers"]["wikitoolkit"]
    assert server["args"] == ["mcp"]
    assert server["default_tools_approval_mode"] == "approve"

    rules = (repo / assets.RULES_PATH).read_text(encoding="utf-8")
    assert 'pattern=["wikitoolkit"]' in rules
    assert 'pattern=["parrot", "wiki"]' in rules
    assert 'decision="allow"' in rules
    assert (repo / ".parrot/wiki.json").exists()
    assert ".parrot/" in (repo / ".gitignore").read_text(encoding="utf-8")


def test_install_is_idempotent_and_preserves_unrelated_config(repo: Path) -> None:
    config_path = repo / ".codex/config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        'model = "gpt-test"\n\n[mcp_servers.other]\ncommand = "other"\n',
        encoding="utf-8",
    )
    rules_path = repo / assets.RULES_PATH
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        'prefix_rule(pattern=["gh", "pr"], decision="prompt")\n',
        encoding="utf-8",
    )

    install_codex_integration(repo)
    first_config = config_path.read_bytes()
    first_rules = rules_path.read_bytes()
    install_codex_integration(repo)

    assert config_path.read_bytes() == first_config
    assert rules_path.read_bytes() == first_rules
    parsed = tomllib.loads(first_config.decode())
    assert parsed["model"] == "gpt-test"
    assert parsed["mcp_servers"]["other"]["command"] == "other"
    assert 'pattern=["gh", "pr"]' in first_rules.decode()


def test_install_replaces_manual_wikitoolkit_mcp_table(repo: Path) -> None:
    config_path = repo / ".codex/config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        '[mcp_servers.wikitoolkit]\ncommand = "old"\nargs = ["legacy"]\n\n' '[mcp_servers.other]\ncommand = "keep"\n',
        encoding="utf-8",
    )

    install_codex_integration(repo)

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert parsed["mcp_servers"]["wikitoolkit"]["args"] == ["mcp"]
    assert parsed["mcp_servers"]["other"]["command"] == "keep"


def test_invalid_config_aborts_without_overwriting(repo: Path) -> None:
    config_path = repo / ".codex/config.toml"
    config_path.parent.mkdir()
    config_path.write_text("[broken", encoding="utf-8")

    with pytest.raises(RuntimeError):
        install_codex_integration(repo)

    assert config_path.read_text(encoding="utf-8") == "[broken"


def test_uninstall_removes_only_managed_assets(repo: Path) -> None:
    (repo / "AGENTS.md").write_text("# User instructions\n", encoding="utf-8")
    install_codex_integration(repo)
    config_path = repo / ".codex/config.toml"
    config_path.write_text(
        'model = "keep"\n\n' + config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    uninstall_codex_integration(repo)

    assert "# User instructions" in (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert assets.AGENTS_BEGIN not in (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert tomllib.loads(config_path.read_text(encoding="utf-8"))["model"] == "keep"
    assert not (repo / assets.SKILL_PATH).exists()
    assert not (repo / assets.RULES_PATH).exists()
    assert (repo / ".parrot/wiki.json").exists()


def test_status_and_top_level_cli(repo: Path) -> None:
    before = integration_status(repo)
    assert not before["mcp"]

    result = CliRunner().invoke(
        cli,
        ["codex", "install", "--path", str(repo), "--no-build"],
    )

    assert result.exit_code == 0, result.output
    assert "Codex integration installed" in result.output
    after = integration_status(repo)
    assert after["mcp"]
    assert after["permissions"]
