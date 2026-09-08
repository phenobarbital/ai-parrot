"""Bookstore installer ownership, portability, and CLI contracts."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.knowledge.bookstore.catalog import CatalogStore
from parrot.knowledge.wiki.codex.bookstore import (
    MCP_BEGIN,
    SKILL_PATH,
    bookstore_status,
    install_bookstore,
    uninstall_bookstore,
)
from parrot.knowledge.wiki.codex.bookstore_assets import BOOKSTORE_SKILL


@pytest.fixture(autouse=True)
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep discovery independent of the developer's personal library."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "global"))
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "indexed"))
    CatalogStore(tmp_path / "indexed/library.db")


def test_install_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "target project"
    root.mkdir()
    config = root / ".codex/config.toml"
    config.parent.mkdir()
    original = 'model = "keep"\n[mcp_servers.other]\ncommand = "keep"\n'
    config.write_text(original)
    install_bookstore(root)
    first = config.read_bytes()
    server = tomllib.loads(first.decode())["mcp_servers"]["bookstore"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "parrot.knowledge.bookstore.cli", "mcp"]
    assert server["cwd"] == str(root)
    assert "PARROT_LIBRARY_DIR" in server["env_vars"]
    assert (root / SKILL_PATH).read_text() == BOOKSTORE_SKILL
    install_bookstore(root)
    assert config.read_bytes() == first
    assert all(bookstore_status(root).values())
    uninstall_bookstore(root)
    assert config.read_text() == original
    assert not any(bookstore_status(root).values())


@pytest.mark.parametrize("header", ["[mcp_servers.bookstore]", '[mcp_servers."bookstore"]'])
def test_foreign_server_and_skill_survive(tmp_path: Path, header: str) -> None:
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    original = f'{header}\ncommand = "custom"\n'
    config.write_text(original)
    skill = tmp_path / SKILL_PATH
    skill.parent.mkdir(parents=True)
    skill.write_text("Custom skill")
    actions = install_bookstore(tmp_path)
    assert any("user configuration preserved" in action for action in actions)
    assert config.read_text() == original
    uninstall_bookstore(tmp_path)
    assert config.read_text() == original
    assert skill.read_text() == "Custom skill"


def test_edited_skill_survives_uninstall(tmp_path: Path) -> None:
    install_bookstore(tmp_path)
    skill = tmp_path / SKILL_PATH
    edited = skill.read_text() + "\nUser guidance.\n"
    skill.write_text(edited)
    install_bookstore(tmp_path)
    uninstall_bookstore(tmp_path)
    assert skill.read_text() == edited


@pytest.mark.parametrize("text", ["[broken", MCP_BEGIN + '\n[mcp_servers.bookstore]\ncommand = "custom"\n'])
def test_invalid_or_incomplete_config_untouched(tmp_path: Path, text: str) -> None:
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    config.write_text(text)
    with pytest.raises(RuntimeError):
        install_bookstore(tmp_path)
    assert config.read_text() == text
    assert not (tmp_path / SKILL_PATH).exists()


def test_cli_default_opt_out_and_uninstall(tmp_path: Path) -> None:
    runner = CliRunner()
    arguments = ["codex", "install", "--path", str(tmp_path), "--no-build"]
    result = runner.invoke(cli, arguments + ["--no-bookstore"])
    assert result.exit_code == 0, result.output
    assert not any(bookstore_status(tmp_path).values())

    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    config = tmp_path / ".codex/config.toml"
    first = config.read_bytes()
    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    assert config.read_bytes() == first
    status = runner.invoke(cli, ["codex", "status", "--path", str(tmp_path), "--json"])
    assert status.exit_code == 0, status.output
    assert '"bookstore_mcp": true' in status.output
    result = runner.invoke(cli, ["codex", "uninstall", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert not any(bookstore_status(tmp_path).values())


def test_missing_library_silently_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("PARROT_LIBRARY_DIR")
    assert install_bookstore(tmp_path) == []
    assert not (tmp_path / ".codex/config.toml").exists()
    assert not (tmp_path / SKILL_PATH).exists()
    assert capsys.readouterr() == ("", "")
    result = CliRunner().invoke(cli, ["codex", "install", "--path", str(tmp_path), "--no-build"])
    assert result.exit_code == 0, result.output
    assert "bookstore" not in result.output.lower()
    assert not any(bookstore_status(tmp_path).values())


def test_missing_library_removes_only_managed_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_bookstore(tmp_path)
    config = tmp_path / ".codex/config.toml"
    config.write_text(config.read_text() + '\n[mcp_servers.other]\ncommand = "keep"\n')
    monkeypatch.delenv("PARROT_LIBRARY_DIR")
    assert install_bookstore(tmp_path) == []
    assert tomllib.loads(config.read_text())["mcp_servers"] == {"other": {"command": "keep"}}
    assert (tmp_path / SKILL_PATH).exists()


@pytest.mark.parametrize("scope", ["project", "global", "override"])
def test_available_library_enables_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str) -> None:
    monkeypatch.delenv("PARROT_LIBRARY_DIR")
    (tmp_path / ".git").mkdir()
    if scope == "project":
        location = tmp_path / ".parrot/library"
    elif scope == "global":
        location = tmp_path / "global/library"
    else:
        location = tmp_path / "custom"
        monkeypatch.setenv("PARROT_LIBRARY_DIR", str(location))
    assert install_bookstore(tmp_path) == []
    CatalogStore(location / "library.db")
    assert install_bookstore(tmp_path)
    assert all(bookstore_status(tmp_path).values())
