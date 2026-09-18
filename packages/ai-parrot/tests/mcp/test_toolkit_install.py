"""Install orchestration (FEAT-570, TASK-3375)."""

from __future__ import annotations

import json
import sys

import pytest

from parrot.mcp.hosts import HostKind
from parrot.mcp.toolkit_install import (
    ToolkitState,
    dist_available,
    install_toolkits,
    inventory,
    set_toolkits_enabled,
    uninstall_toolkits,
)


def test_dist_available_missing_distribution():
    assert dist_available(["definitely_not_installed_xyz"]) is False


def test_dist_available_core_only_is_true():
    assert dist_available([]) is True


def test_inventory_on_empty_repo_lists_templates_as_not_installed(tmp_path):
    rows = inventory(tmp_path, hosts=[])
    assert rows and all(r.state is ToolkitState.NOT_INSTALLED for r in rows)


def test_inventory_never_includes_wikitoolkit(tmp_path):
    assert "wikitoolkit" not in {r.name for r in inventory(tmp_path, hosts=[])}


def test_inventory_imports_no_toolkit_class(tmp_path):
    """AC1 — listing must stay side-effect free."""
    before = set(sys.modules)
    inventory(tmp_path, hosts=[])
    new = set(sys.modules) - before
    assert not [m for m in new if m.startswith(("parrot_tools", "parrot.tools"))]


def test_install_unknown_name_is_atomic(tmp_path):
    """AC8 — nothing seeded, nothing written."""
    with pytest.raises(ValueError):
        install_toolkits(tmp_path, ["memory", "not-a-template"], hosts=[])
    assert not (tmp_path / ".parrot" / "mcp-toolkits.yaml").exists()


def test_install_hostless_still_seeds_yaml(tmp_path):
    """The `--host`-less path on a fresh checkout: hosts resolve to an empty list."""
    report = install_toolkits(tmp_path, ["memory"], hosts=[])
    assert any("memory" in action for action in report.actions)
    assert (tmp_path / ".parrot" / "mcp-toolkits.yaml").exists()

    rows = inventory(tmp_path, hosts=[])
    row = next(r for r in rows if r.name == "memory")
    assert row.state is ToolkitState.ENABLED


def test_disable_keeps_section_and_kwargs(tmp_path):
    install_toolkits(tmp_path, ["memory"], hosts=[])
    set_toolkits_enabled(tmp_path, ["memory"], False, hosts=[])

    rows = inventory(tmp_path, hosts=[])
    row = next(r for r in rows if r.name == "memory")
    assert row.state is ToolkitState.DISABLED

    text = (tmp_path / ".parrot" / "mcp-toolkits.yaml").read_text(encoding="utf-8")
    assert "memory:" in text
    assert "kwargs: {}" in text


def test_uninstall_drops_only_its_own_approvals(tmp_path):
    """Uninstalling `memory` must never de-authorize `wikitoolkit` (AC5, S3)."""
    install_toolkits(tmp_path, ["memory"], hosts=[HostKind.CLAUDE])

    local_path = tmp_path / ".claude" / "settings.local.json"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    names = local.get("enabledMcpjsonServers", [])
    if "wikitoolkit" not in names:
        names.append("wikitoolkit")
        local["enabledMcpjsonServers"] = names
        local_path.write_text(json.dumps(local), encoding="utf-8")

    mcp_path = tmp_path / ".mcp.json"
    mcp_data = json.loads(mcp_path.read_text(encoding="utf-8"))
    mcp_data.setdefault("mcpServers", {})["wikitoolkit"] = {
        "command": "wikitoolkit",
        "args": ["mcp", "serve"],
    }
    mcp_path.write_text(json.dumps(mcp_data), encoding="utf-8")

    uninstall_toolkits(tmp_path, ["memory"], hosts=[HostKind.CLAUDE])

    local_after = json.loads(local_path.read_text(encoding="utf-8"))
    assert "wikitoolkit" in local_after.get("enabledMcpjsonServers", [])
