import json

import pytest
from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)


@pytest.fixture
def repo_root(tmp_path):
    """Minimal repo structure for installer tests."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".parrot").mkdir()
    return tmp_path


class TestMCPJsonInstall:
    def test_install_creates_mcp_json(self, repo_root):
        install_claude_integration(repo_root)
        mcp_json = repo_root / ".mcp.json"
        assert mcp_json.exists()
        data = json.loads(mcp_json.read_text())
        assert "wikitoolkit" in data["mcpServers"]
        assert data["mcpServers"]["wikitoolkit"]["command"] == "wikitoolkit"
        assert data["mcpServers"]["wikitoolkit"]["args"] == ["mcp"]

    def test_install_idempotent(self, repo_root):
        install_claude_integration(repo_root)
        install_claude_integration(repo_root)
        data = json.loads((repo_root / ".mcp.json").read_text())
        assert len(data["mcpServers"]) == 1

    def test_install_preserves_other_servers(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {"other-server": {"command": "other"}}
        }))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "other-server" in data["mcpServers"]
        assert "wikitoolkit" in data["mcpServers"]

    def test_install_updates_stale_entry(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {"wikitoolkit": {"command": "old-stale-command"}}
        }))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["wikitoolkit"]["command"] == "wikitoolkit"


class TestMCPJsonUninstall:
    def test_uninstall_removes_entry(self, repo_root):
        install_claude_integration(repo_root)
        uninstall_claude_integration(repo_root)
        mcp_json = repo_root / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text())
            assert "wikitoolkit" not in data.get("mcpServers", {})

    def test_uninstall_preserves_other_servers(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "other-server": {"command": "other"},
                "wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}
            }
        }))
        uninstall_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "other-server" in data["mcpServers"]
        assert "wikitoolkit" not in data["mcpServers"]

    def test_uninstall_removes_file_when_empty(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {"wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}}
        }))
        uninstall_claude_integration(repo_root)
        assert not mcp_json.exists()

    def test_uninstall_noop_when_no_mcp_json(self, repo_root):
        # Should not raise even though .mcp.json never existed.
        actions = uninstall_claude_integration(repo_root)
        assert isinstance(actions, list)


class TestIntegrationStatus:
    def test_status_reports_mcp_json(self, repo_root):
        status = integration_status(repo_root)
        assert "mcp_json" in status
        assert status["mcp_json"] is False
        install_claude_integration(repo_root)
        status = integration_status(repo_root)
        assert status["mcp_json"] is True
