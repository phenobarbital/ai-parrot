"""Install orchestration (FEAT-570, TASK-3375)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from parrot.mcp.hosts import HostKind, get_adapter
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


def test_install_portable_form_across_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Toolkit orchestration preserves form, failures, foreign entries and one-note output."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    foreign_codex = tmp_path / ".codex"
    foreign_codex.mkdir()
    (foreign_codex / "config.toml").write_text('[mcp_servers.parrot-foreign]\ncommand = "external"\n', encoding="utf-8")
    hosts = list(HostKind)

    portable_report = install_toolkits(tmp_path, ["memory"], hosts=hosts, portable=True)

    claude_config = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    claude_entry = claude_config["mcpServers"]["parrot-memory"]
    assert claude_entry["command"] == "parrot"
    assert not any(str(tmp_path) in value for value in claude_entry.get("args", []))

    codex_text = (foreign_codex / "config.toml").read_text(encoding="utf-8")
    assert '[mcp_servers.parrot-foreign]\ncommand = "external"' in codex_text
    assert 'command = "parrot"' in codex_text

    google_global = tmp_path / ".gemini" / "config" / "mcp_config.json"
    google_config = json.loads(google_global.read_text(encoding="utf-8"))
    assert google_config["mcpServers"]["parrot-memory"]["command"] == "parrot"
    assert not portable_report.failed_hosts

    google_plugin = tmp_path / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    plugin_config = json.loads(google_plugin.read_text(encoding="utf-8"))
    plugin_config["mcpServers"]["wikitoolkit"] = {"command": "wikitoolkit", "args": ["mcp"]}
    google_plugin.write_text(json.dumps(plugin_config), encoding="utf-8")

    sticky_report = set_toolkits_enabled(tmp_path, ["memory"], True, hosts=hosts, portable=None)
    assert not [action for action in sticky_report.actions if action.startswith("note: host config baked")]
    sticky_claude = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert sticky_claude["mcpServers"]["parrot-memory"]["command"] == "parrot"

    original_get_adapter = get_adapter

    class FailingCodexAdapter:
        """Test-only adapter that preserves per-host failure isolation coverage."""

        def reconcile(self, root: Path, *, portable: bool | None = None) -> tuple[list[str], list[str]]:
            raise OSError("codex unavailable")

    def get_adapter_with_failure(kind: HostKind) -> object:
        return FailingCodexAdapter() if kind is HostKind.CODEX else original_get_adapter(kind)

    monkeypatch.setattr("parrot.mcp.toolkit_install.get_adapter", get_adapter_with_failure)
    failed_report = install_toolkits(tmp_path, ["memory"], hosts=hosts, portable=False)
    assert failed_report.failed_hosts == {HostKind.CODEX: "codex unavailable"}
    assert any("memory — already installed" == warning for warning in failed_report.warnings)

    fallback_root = tmp_path / "fallback"
    monkeypatch.setattr("parrot.mcp.portability.managed_launcher_on_path", lambda: False)
    fallback_report = install_toolkits(fallback_root, ["memory"], hosts=hosts)
    fallback_notes = [action for action in fallback_report.actions if action.startswith("note: host config baked")]
    assert len(fallback_notes) == 1


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
