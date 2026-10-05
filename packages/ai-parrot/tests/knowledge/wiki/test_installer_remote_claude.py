"""Tests for ``parrot claude install --remote`` (FEAT-569, TASK-3365)."""

import json

from click.testing import CliRunner

from parrot.knowledge.wiki.claude_code import installer
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.installer import integration_status
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config

BASE = ["install", "--no-git-hook", "--no-bookstore", "--no-build", "--no-compaction", "--no-plugin-cli"]


def _servers(root):
    return json.loads((root / ".mcp.json").read_text())["mcpServers"]


def _mcp(root):
    return _servers(root)["wikitoolkit"]


def test_remote_flag_writes_http_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))
    args = [*BASE, "--remote", "--remote-url", "https://h/mcp/w", "--token-env", "WT"]
    r = CliRunner().invoke(claude, args)
    assert r.exit_code == 0, r.output
    assert _mcp(tmp_path) == {"type": "http", "url": "https://h/mcp/w", "headers": {"Authorization": "Bearer ${WT}"}}
    before = (tmp_path / ".mcp.json").read_bytes()
    assert CliRunner().invoke(claude, args).exit_code == 0
    assert (tmp_path / ".mcp.json").read_bytes() == before
    assert integration_status(tmp_path)["mcp_transport"] == "http"
    assert CliRunner().invoke(claude, ["uninstall"]).exit_code == 0
    mcp_file = tmp_path / ".mcp.json"
    assert not mcp_file.exists() or "wikitoolkit" not in json.loads(mcp_file.read_text()).get("mcpServers", {})


def test_remote_from_config_and_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="https://cfg/mcp/w")))
    r = CliRunner().invoke(claude, [*BASE, "--remote"])
    assert r.exit_code == 0, r.output
    assert _mcp(tmp_path)["url"] == "https://cfg/mcp/w"
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))
    assert CliRunner().invoke(claude, [*BASE, "--remote"]).exit_code != 0


def test_stdio_transport_and_none(tmp_path):
    assert integration_status(tmp_path)["mcp_transport"] is None
    installer._install_mcp_json(tmp_path)
    assert integration_status(tmp_path)["mcp_transport"] == "stdio"


def test_foreign_entry_untouched(tmp_path, capsys):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "other"}}}))
    installer._install_mcp_json(tmp_path, remote=WikiRemoteConfig(url="https://h/mcp/w"))
    assert _mcp(tmp_path) == {"command": "other"}
    assert "not managed" in capsys.readouterr().err
    installer._uninstall_mcp_json(tmp_path)
    assert _mcp(tmp_path) == {"command": "other"}
