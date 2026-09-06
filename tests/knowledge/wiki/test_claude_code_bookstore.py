"""Bookstore installer ownership, portability, and CLI contracts (Claude Code).

Mirrors ``test_codex_bookstore.py``, adapted for Claude Code's JSON
``.mcp.json`` shape and ``.claude/skills/<name>/SKILL.md`` layout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.knowledge.bookstore.catalog import CatalogStore
from parrot.knowledge.wiki.claude_code.bookstore import (
    SKILL_PATH,
    bookstore_status,
    install_bookstore,
    uninstall_bookstore,
)
from parrot.knowledge.wiki.claude_code.bookstore_assets import BOOKSTORE_SKILL


@pytest.fixture(autouse=True)
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep discovery independent of the developer's personal library."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "global"))
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "indexed"))
    CatalogStore(tmp_path / "indexed/library.db")


def test_install_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "target project"
    root.mkdir()
    mcp_json = root / ".mcp.json"
    original = {"mcpServers": {"other": {"command": "keep"}}}
    mcp_json.write_text(json.dumps(original), encoding="utf-8")
    install_bookstore(root)
    first = mcp_json.read_bytes()
    server = json.loads(first.decode())["mcpServers"]["bookstore"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "parrot.knowledge.bookstore.cli", "mcp"]
    assert server["cwd"] == str(root)
    assert (root / SKILL_PATH).read_text() == BOOKSTORE_SKILL
    install_bookstore(root)
    assert mcp_json.read_bytes() == first
    assert all(bookstore_status(root).values())
    uninstall_bookstore(root)
    assert json.loads(mcp_json.read_text())["mcpServers"] == {"other": {"command": "keep"}}
    assert not any(bookstore_status(root).values())


def test_foreign_server_and_skill_survive(tmp_path: Path) -> None:
    mcp_json = tmp_path / ".mcp.json"
    original = {"mcpServers": {"bookstore": {"command": "custom", "args": ["serve"]}}}
    mcp_json.write_text(json.dumps(original), encoding="utf-8")
    skill = tmp_path / SKILL_PATH
    skill.parent.mkdir(parents=True)
    skill.write_text("Custom skill")
    actions = install_bookstore(tmp_path)
    assert any("user configuration preserved" in action for action in actions)
    assert json.loads(mcp_json.read_text()) == original
    uninstall_bookstore(tmp_path)
    assert json.loads(mcp_json.read_text()) == original
    assert skill.read_text() == "Custom skill"


def test_edited_skill_survives_uninstall(tmp_path: Path) -> None:
    install_bookstore(tmp_path)
    skill = tmp_path / SKILL_PATH
    edited = skill.read_text() + "\nUser guidance.\n"
    skill.write_text(edited)
    install_bookstore(tmp_path)
    uninstall_bookstore(tmp_path)
    assert skill.read_text() == edited


def test_invalid_mcp_json_treated_as_empty(tmp_path: Path) -> None:
    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text("not json", encoding="utf-8")
    install_bookstore(tmp_path)
    assert json.loads(mcp_json.read_text())["mcpServers"]["bookstore"]["args"] == [
        "-m",
        "parrot.knowledge.bookstore.cli",
        "mcp",
    ]


def test_cli_default_opt_out_and_uninstall(tmp_path: Path) -> None:
    runner = CliRunner()
    arguments = ["claude", "install", "--path", str(tmp_path), "--no-build", "--no-git-hook"]
    result = runner.invoke(cli, arguments + ["--no-bookstore"])
    assert result.exit_code == 0, result.output
    assert not any(bookstore_status(tmp_path).values())

    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    mcp_json = tmp_path / ".mcp.json"
    first = mcp_json.read_bytes()
    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    assert mcp_json.read_bytes() == first
    status = runner.invoke(cli, ["claude", "status", "--path", str(tmp_path), "--json"])
    assert status.exit_code == 0, status.output
    assert '"bookstore_mcp": true' in status.output
    result = runner.invoke(cli, ["claude", "uninstall", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert not any(bookstore_status(tmp_path).values())


def test_missing_library_silently_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("PARROT_LIBRARY_DIR")
    assert install_bookstore(tmp_path) == []
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / SKILL_PATH).exists()
    assert capsys.readouterr() == ("", "")
    result = CliRunner().invoke(
        cli, ["claude", "install", "--path", str(tmp_path), "--no-build", "--no-git-hook"]
    )
    assert result.exit_code == 0, result.output
    assert "bookstore" not in result.output.lower()
    assert not any(bookstore_status(tmp_path).values())


def test_missing_library_removes_only_managed_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_bookstore(tmp_path)
    mcp_json = tmp_path / ".mcp.json"
    data = json.loads(mcp_json.read_text())
    data["mcpServers"]["other"] = {"command": "keep"}
    mcp_json.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.delenv("PARROT_LIBRARY_DIR")
    assert install_bookstore(tmp_path) == []
    assert json.loads(mcp_json.read_text())["mcpServers"] == {"other": {"command": "keep"}}
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
