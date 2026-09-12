import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki.claude_code.installer import (
    _install_mcp_approval,
    _managed_server_names,
    _uninstall_mcp_approval,
    integration_status,
)


@pytest.fixture
def tmp_root_with_config(tmp_path: Path) -> Path:
    """Project root with the 3 builtins disabled + one custom enabled toolkit.

    Disabling the always-on builtins keeps assertions focused on a single
    managed toolkit entry (``parrot-stub``) instead of three.
    """
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  scraping:\n"
        "    class: parrot_tools.scraping.toolkit.WebScrapingToolkit\n"
        "    enabled: false\n"
        "  browsing:\n"
        "    class: parrot_tools.browsing.toolkit.WebBrowsingToolkit\n"
        "    enabled: false\n"
        "  memory:\n"
        "    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit\n"
        "    enabled: false\n"
        "  stub:\n"
        "    class: tests.mcp.stub_toolkit.StubToolkit\n"
        "    env:\n"
        "      FOO: bar\n"
    )
    return tmp_path


def _local(root):
    return json.loads((root / ".claude" / "settings.local.json").read_text())


def test_approval_adds_managed_names(tmp_root_with_config):
    _install_mcp_approval(tmp_root_with_config)
    assert set(_managed_server_names(tmp_root_with_config)) <= set(
        _local(tmp_root_with_config)["enabledMcpjsonServers"]
    )


def test_approval_never_writes_enable_all(tmp_root_with_config):
    _install_mcp_approval(tmp_root_with_config)
    assert "enableAllProjectMcpServers" not in _local(tmp_root_with_config)


def test_approval_preserves_foreign_names(tmp_root_with_config):
    local_dir = tmp_root_with_config / ".claude"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "settings.local.json").write_text(
        json.dumps({"enabledMcpjsonServers": ["some-other-server"]})
    )
    _install_mcp_approval(tmp_root_with_config)
    servers = _local(tmp_root_with_config)["enabledMcpjsonServers"]
    assert "some-other-server" in servers
    assert servers[0] == "some-other-server"


def test_approval_idempotent(tmp_root_with_config):
    action1 = _install_mcp_approval(tmp_root_with_config)
    bytes1 = (tmp_root_with_config / ".claude" / "settings.local.json").read_bytes()
    action2 = _install_mcp_approval(tmp_root_with_config)
    bytes2 = (tmp_root_with_config / ".claude" / "settings.local.json").read_bytes()
    assert bytes1 == bytes2
    assert "already authorized" in action2


def test_approval_rejects_non_list_key(tmp_root_with_config):
    local_dir = tmp_root_with_config / ".claude"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "settings.local.json").write_text(
        json.dumps({"enabledMcpjsonServers": "not-a-list"})
    )
    with pytest.raises(RuntimeError) as exc_info:
        _install_mcp_approval(tmp_root_with_config)
    assert "enabledMcpjsonServers" in str(exc_info.value)


def test_uninstall_removes_only_managed_names(tmp_root_with_config):
    _install_mcp_approval(tmp_root_with_config)
    local_dir = tmp_root_with_config / ".claude"
    local = json.loads((local_dir / "settings.local.json").read_text())
    local["enabledMcpjsonServers"].append("some-other-server")
    (local_dir / "settings.local.json").write_text(json.dumps(local))

    _uninstall_mcp_approval(tmp_root_with_config)
    servers = _local(tmp_root_with_config)["enabledMcpjsonServers"]
    assert servers == ["some-other-server"]


def test_status_reports_approval_and_seeded_yaml(tmp_root_with_config):
    status = integration_status(tmp_root_with_config)
    assert "mcp_servers_authorized" in status and "toolkits_yaml" in status
    assert status["mcp_servers_authorized"] is False
    assert status["toolkits_yaml"] is True

    _install_mcp_approval(tmp_root_with_config)
    status = integration_status(tmp_root_with_config)
    assert status["mcp_servers_authorized"] is True
