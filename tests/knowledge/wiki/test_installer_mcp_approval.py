import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki.claude_code.installer import (
    _install_mcp_approval,
    _install_mcp_json,
    _managed_server_names,
    _uninstall_mcp_approval,
    _uninstall_mcp_json,
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
    # `_managed_server_names` only confirms a `parrot-<name>` entry via its
    # current `.mcp.json` shape (FEAT-556 fix) — reconcile first, exactly
    # like `install_claude_integration` orders these two calls.
    _install_mcp_json(tmp_root_with_config)
    _install_mcp_approval(tmp_root_with_config)
    managed = _managed_server_names(tmp_root_with_config)
    assert "parrot-stub" in managed
    assert set(managed) <= set(_local(tmp_root_with_config)["enabledMcpjsonServers"])


def test_approval_never_writes_enable_all(tmp_root_with_config):
    _install_mcp_approval(tmp_root_with_config)
    assert "enableAllProjectMcpServers" not in _local(tmp_root_with_config)


def test_approval_preserves_foreign_names(tmp_root_with_config):
    local_dir = tmp_root_with_config / ".claude"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "settings.local.json").write_text(json.dumps({"enabledMcpjsonServers": ["some-other-server"]}))
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
    (local_dir / "settings.local.json").write_text(json.dumps({"enabledMcpjsonServers": "not-a-list"}))
    with pytest.raises(RuntimeError) as exc_info:
        _install_mcp_approval(tmp_root_with_config)
    assert "enabledMcpjsonServers" in str(exc_info.value)


def test_uninstall_removes_only_managed_names(tmp_root_with_config):
    _install_mcp_json(tmp_root_with_config)
    _install_mcp_approval(tmp_root_with_config)
    local_dir = tmp_root_with_config / ".claude"
    local = json.loads((local_dir / "settings.local.json").read_text())
    local["enabledMcpjsonServers"].append("some-other-server")
    (local_dir / "settings.local.json").write_text(json.dumps(local))

    # Mirrors `uninstall_claude_integration`'s order: capture the confirmed
    # managed names `.mcp.json` reconciliation just removed, then feed them
    # to approval-uninstall — never blanket-strip every `parrot-*` name.
    _, removed_toolkit_names = _uninstall_mcp_json(tmp_root_with_config)
    _uninstall_mcp_approval(tmp_root_with_config, removed_toolkit_names)
    servers = _local(tmp_root_with_config)["enabledMcpjsonServers"]
    assert servers == ["some-other-server"]


def test_approval_never_authorizes_foreign_collision(tmp_root_with_config):
    """FEAT-556 CRITICAL fix: a foreign `parrot-stub` entry must never be
    silently authorized just because a `stub` toolkit section is enabled.
    """
    mcp_json = tmp_root_with_config / ".mcp.json"
    mcp_json.write_text(json.dumps({"mcpServers": {"parrot-stub": {"command": "some-other-cli", "args": ["serve"]}}}))

    _install_mcp_json(tmp_root_with_config)  # skips the foreign entry, warns
    _install_mcp_approval(tmp_root_with_config)

    managed = _managed_server_names(tmp_root_with_config)
    assert "parrot-stub" not in managed
    servers = _local(tmp_root_with_config)["enabledMcpjsonServers"]
    assert "parrot-stub" not in servers
    assert "wikitoolkit" in servers


def test_uninstall_preserves_foreign_parrot_prefixed_name(tmp_root_with_config):
    """A hand-approved, unrelated `parrot-<name>` server survives uninstall."""
    local_dir = tmp_root_with_config / ".claude"
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "settings.local.json").write_text(json.dumps({"enabledMcpjsonServers": ["parrot-unrelated-server"]}))

    _, removed_toolkit_names = _uninstall_mcp_json(tmp_root_with_config)  # no .mcp.json — nothing removed
    _uninstall_mcp_approval(tmp_root_with_config, removed_toolkit_names)
    servers = _local(tmp_root_with_config)["enabledMcpjsonServers"]
    assert servers == ["parrot-unrelated-server"]


def test_status_reports_approval_and_seeded_yaml(tmp_root_with_config):
    status = integration_status(tmp_root_with_config)
    assert "mcp_servers_authorized" in status and "toolkits_yaml" in status
    assert status["mcp_servers_authorized"] is False
    assert status["toolkits_yaml"] is True

    _install_mcp_approval(tmp_root_with_config)
    status = integration_status(tmp_root_with_config)
    assert status["mcp_servers_authorized"] is True


# ---------------------------------------------------------------------------
# Server-level tool allow rules: approving a server only makes its tools
# visible; without `mcp__<server>` every call still prompts and an unattended
# agent (sdd-worker filing ledger issues) stalls.
# ---------------------------------------------------------------------------


def _allow(root):
    return _local(root).get("permissions", {}).get("allow", [])


def test_approval_allows_every_managed_server_tool(tmp_root_with_config):
    _install_mcp_json(tmp_root_with_config)
    _install_mcp_approval(tmp_root_with_config)
    allow = _allow(tmp_root_with_config)
    assert "mcp__wikitoolkit" in allow
    assert "mcp__parrot-stub" in allow


def test_approval_backfills_allow_rules_for_already_authorized_servers(tmp_root_with_config):
    """An install predating the allow rules gets them on the next run, even with every server approved."""
    _install_mcp_json(tmp_root_with_config)
    local_dir = tmp_root_with_config / ".claude"
    local_dir.mkdir(parents=True, exist_ok=True)
    managed = _managed_server_names(tmp_root_with_config)
    (local_dir / "settings.local.json").write_text(
        json.dumps({"enabledMcpjsonServers": managed, "permissions": {"allow": ["Bash(ls:*)"]}})
    )
    action = _install_mcp_approval(tmp_root_with_config)
    assert "allow rule" in action
    allow = _allow(tmp_root_with_config)
    assert allow[0] == "Bash(ls:*)"
    assert {f"mcp__{name}" for name in managed} <= set(allow)


def test_uninstall_removes_only_managed_allow_rules(tmp_root_with_config):
    _install_mcp_json(tmp_root_with_config)
    _install_mcp_approval(tmp_root_with_config)
    local = _local(tmp_root_with_config)
    local["permissions"]["allow"] += ["mcp__some-other-server", "mcp__parrot-foreign"]
    (tmp_root_with_config / ".claude" / "settings.local.json").write_text(json.dumps(local))
    _uninstall_mcp_approval(tmp_root_with_config, ["parrot-stub"])
    allow = _allow(tmp_root_with_config)
    assert "mcp__wikitoolkit" not in allow
    assert "mcp__parrot-stub" not in allow
    assert {"mcp__some-other-server", "mcp__parrot-foreign"} <= set(allow)


def test_toolkit_approvals_never_touch_wikitoolkit_allow_rule(tmp_root_with_config):
    """`parrot toolkits` must neither grant nor revoke the wiki server (FEAT-570 AC5)."""
    from parrot.knowledge.wiki.claude_code.installer import (
        install_toolkit_approvals,
        uninstall_toolkit_approvals,
    )

    _install_mcp_json(tmp_root_with_config)
    install_toolkit_approvals(tmp_root_with_config)
    allow = _allow(tmp_root_with_config)
    assert "mcp__parrot-stub" in allow
    assert "mcp__wikitoolkit" not in allow

    local = _local(tmp_root_with_config)
    local["permissions"]["allow"].append("mcp__wikitoolkit")
    (tmp_root_with_config / ".claude" / "settings.local.json").write_text(json.dumps(local))
    uninstall_toolkit_approvals(tmp_root_with_config, ["parrot-stub"])
    allow = _allow(tmp_root_with_config)
    assert "mcp__parrot-stub" not in allow
    assert "mcp__wikitoolkit" in allow
