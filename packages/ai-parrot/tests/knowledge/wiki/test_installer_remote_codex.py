"""Tests for the Codex remote (native HTTP) MCP registration (FEAT-569 TASK-3366)."""

import tomllib

from click.testing import CliRunner
from parrot.knowledge.wiki.codex.cli import codex
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config

_FLAGS = ["--no-bookstore", "--no-build", "--no-gitignore"]


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))


def _table(root):
    return tomllib.loads((root / ".codex" / "config.toml").read_text())["mcp_servers"]["wikitoolkit"]


def test_remote_table(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    args = ["install", "--remote", "--remote-url", "https://h/mcp/w", "--token-env", "WT", *_FLAGS]
    first = CliRunner().invoke(codex, args)
    assert first.exit_code == 0, first.output
    assert _table(tmp_path) == {
        "url": "https://h/mcp/w",
        "bearer_token_env_var": "WT",
        "default_tools_approval_mode": "approve",
    }
    before = (tmp_path / ".codex" / "config.toml").read_bytes()
    second = CliRunner().invoke(codex, args)
    assert second.exit_code == 0, second.output
    assert (tmp_path / ".codex" / "config.toml").read_bytes() == before


def test_remote_missing_source(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert CliRunner().invoke(codex, ["install", "--remote", *_FLAGS]).exit_code != 0


def test_default_stays_stdio(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert CliRunner().invoke(codex, ["install", *_FLAGS]).exit_code == 0
    table = _table(tmp_path)
    assert table["args"] == ["mcp"] and "url" not in table


def test_uninstall_removes_remote_block(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    args = ["install", "--remote", "--remote-url", "https://h/mcp/w", *_FLAGS]
    assert CliRunner().invoke(codex, args).exit_code == 0
    assert CliRunner().invoke(codex, ["uninstall"]).exit_code == 0
    cfg = tmp_path / ".codex" / "config.toml"
    assert not cfg.exists() or "wikitoolkit" not in cfg.read_text()
