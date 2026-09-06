"""Bookstore PageIndex installer contracts for Google Antigravity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.cli import cli
from parrot.knowledge.bookstore.catalog import CatalogStore
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.bookstore import SKILL_PATH, bookstore_status, install_bookstore, uninstall_bookstore
from parrot.knowledge.wiki.google.bookstore_assets import BOOKSTORE_SKILL


@pytest.fixture
def mcp_config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "global_mcp/mcp_config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture(autouse=True)
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mcp_config_path: Path) -> None:
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "global"))
    monkeypatch.setenv("PARROT_LIBRARY_DIR", str(tmp_path / "indexed"))
    monkeypatch.setattr(assets, "default_mcp_config_path", lambda: mcp_config_path)
    CatalogStore(tmp_path / "indexed/library.db")


def test_install_roundtrip(tmp_path: Path, mcp_config_path: Path) -> None:
    root = tmp_path / "target_project"
    root.mkdir()
    original = {"mcpServers": {"other": {"command": "keep"}}}
    mcp_config_path.write_text(json.dumps(original), encoding="utf-8")

    install_bookstore(root, mcp_path=mcp_config_path)
    first_data = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    server = first_data["mcpServers"]["bookstore"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "parrot.knowledge.bookstore.cli", "mcp"]
    assert server["cwd"] == str(root.resolve())
    assert (root / SKILL_PATH).read_text(encoding="utf-8") == BOOKSTORE_SKILL

    # Idempotent re-run
    install_bookstore(root, mcp_path=mcp_config_path)
    assert json.loads(mcp_config_path.read_text(encoding="utf-8")) == first_data
    assert all(bookstore_status(root, mcp_path=mcp_config_path).values())

    # Uninstall
    uninstall_bookstore(root, mcp_path=mcp_config_path)
    assert json.loads(mcp_config_path.read_text(encoding="utf-8")) == original
    assert not any(bookstore_status(root, mcp_path=mcp_config_path).values())


def test_foreign_server_and_skill_survive(tmp_path: Path, mcp_config_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    original = {"mcpServers": {"bookstore": {"command": "custom_bookstore"}}}
    mcp_config_path.write_text(json.dumps(original), encoding="utf-8")

    skill = root / SKILL_PATH
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("Custom skill", encoding="utf-8")

    actions = install_bookstore(root, mcp_path=mcp_config_path)
    assert any("user configuration preserved" in a for a in actions)
    assert json.loads(mcp_config_path.read_text(encoding="utf-8")) == original

    uninstall_bookstore(root, mcp_path=mcp_config_path)
    assert json.loads(mcp_config_path.read_text(encoding="utf-8")) == original
    assert skill.read_text(encoding="utf-8") == "Custom skill"


def test_edited_skill_survives_uninstall(tmp_path: Path, mcp_config_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    install_bookstore(root, mcp_path=mcp_config_path)
    skill = root / SKILL_PATH
    edited = skill.read_text(encoding="utf-8") + "\nUser guidance.\n"
    skill.write_text(edited, encoding="utf-8")

    install_bookstore(root, mcp_path=mcp_config_path)
    uninstall_bookstore(root, mcp_path=mcp_config_path)
    assert skill.read_text(encoding="utf-8") == edited


def test_cli_default_opt_out_and_uninstall(tmp_path: Path, mcp_config_path: Path) -> None:
    runner = CliRunner()
    arguments = ["google", "install", "--path", str(tmp_path), "--no-build"]
    result = runner.invoke(cli, arguments + ["--no-bookstore"])
    assert result.exit_code == 0, result.output
    assert not any(bookstore_status(tmp_path, mcp_path=mcp_config_path).values())

    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    assert all(bookstore_status(tmp_path, mcp_path=mcp_config_path).values())
