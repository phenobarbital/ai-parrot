import json

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    integration_status,
    reconcile_toolkit_entries,
    toolkit_server_names,
    uninstall_claude_integration,
)


@pytest.fixture
def repo_root(tmp_path):
    """Minimal repo structure for installer tests."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".parrot").mkdir()
    return tmp_path


def _write_bounded_source_section(repo_root):
    """Declare a single enabled `bounded-source` toolkit section directly.

    Seeding is no longer performed by `install_claude_integration`
    (FEAT-570 TASK-3377) — tests that need an enabled section write the
    config file themselves instead of relying on the removed `toolkits=`
    keyword.
    """
    (repo_root / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  bounded-source:\n"
        "    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n"
        "    kwargs: {}\n"
    )


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
        mcp_json.write_text(json.dumps({"mcpServers": {"other-server": {"command": "other"}}}))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "other-server" in data["mcpServers"]
        assert "wikitoolkit" in data["mcpServers"]

    def test_install_updates_stale_entry(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "old-stale-command"}}}))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["wikitoolkit"]["command"] == "wikitoolkit"

    def test_install_recovers_from_malformed_mcp_servers(self, repo_root):
        # "mcpServers" is not a dict — must not crash, just reset it.
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({"mcpServers": ["not", "a", "dict"]}))
        install_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "wikitoolkit" in data["mcpServers"]


class TestToolkitOnlyReconciler:
    """FEAT-570 TASK-3371 — the toolkit-only reconciler never touches wikitoolkit."""

    def test_reconcile_toolkit_entries_preserves_wikitoolkit(self, repo_root):
        # Seed .mcp.json with a wikitoolkit entry + one managed parrot-bounded-source entry.
        _write_bounded_source_section(repo_root)
        install_claude_integration(repo_root, bookstore=False)
        mcp_json = repo_root / ".mcp.json"
        before = json.loads(mcp_json.read_text())
        wikitoolkit_before = before["mcpServers"]["wikitoolkit"]
        assert "parrot-bounded-source" in before["mcpServers"]

        actions, warnings = reconcile_toolkit_entries(repo_root)

        after = json.loads(mcp_json.read_text())
        assert after["mcpServers"]["wikitoolkit"] == wikitoolkit_before
        assert "parrot-bounded-source" in after["mcpServers"]
        assert isinstance(actions, list)
        assert isinstance(warnings, list)

    def test_reconcile_toolkit_entries_preserves_foreign_entry(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"], "env": {}},
                        "parrot-bounded-source": {"command": "some-other-binary", "args": ["not", "ours"]},
                    }
                }
            )
        )
        (repo_root / ".parrot" / "mcp-toolkits.yaml").write_text(
            "toolkits:\n"
            "  bounded-source:\n"
            "    class: parrot_tools.scraping.toolkit.BoundedSourceToolkit\n"
            "    kwargs: {}\n"
        )

        wikitoolkit_before = json.loads(mcp_json.read_text())["mcpServers"]["wikitoolkit"]
        actions, warnings = reconcile_toolkit_entries(repo_root)

        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["wikitoolkit"] == wikitoolkit_before
        assert data["mcpServers"]["parrot-bounded-source"] == {
            "command": "some-other-binary",
            "args": ["not", "ours"],
        }
        assert len(warnings) == 1
        assert "parrot-bounded-source" in warnings[0]

    def test_toolkit_server_names_excludes_wikitoolkit(self, repo_root):
        _write_bounded_source_section(repo_root)
        install_claude_integration(repo_root, bookstore=False)
        names = toolkit_server_names(repo_root)
        assert "wikitoolkit" not in names
        assert "parrot-bounded-source" in names


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
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "other-server": {"command": "other"},
                        "wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]},
                    }
                }
            )
        )
        uninstall_claude_integration(repo_root)
        data = json.loads(mcp_json.read_text())
        assert "other-server" in data["mcpServers"]
        assert "wikitoolkit" not in data["mcpServers"]

    def test_uninstall_removes_file_when_empty(self, repo_root):
        mcp_json = repo_root / ".mcp.json"
        mcp_json.write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}}}))
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


class TestReconciliationAfterSeedingCut:
    """FEAT-570 TASK-3377 — seeding left `install_claude_integration`; reconciliation didn't."""

    def test_install_reconciles_enabled_sections_without_seeding(self, repo_root):
        _write_bounded_source_section(repo_root)
        actions = install_claude_integration(repo_root, bookstore=False)
        servers = json.loads((repo_root / ".mcp.json").read_text())["mcpServers"]
        assert "parrot-bounded-source" in servers
        assert not any("no local MCP toolkits configured" in a for a in actions)

    def test_install_no_approve_flag_skips_approval(self, repo_root):
        install_claude_integration(repo_root, approve_mcp=False, bookstore=False)
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "enabledMcpjsonServers" not in local

    def test_install_approve_flag_adds_enabled_servers(self, repo_root):
        _write_bounded_source_section(repo_root)
        install_claude_integration(repo_root, approve_mcp=True, bookstore=False)
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "wikitoolkit" in local["enabledMcpjsonServers"]
        assert "parrot-bounded-source" in local["enabledMcpjsonServers"]

    def test_empty_toolkit_config_hints_at_new_command(self, repo_root):
        actions = install_claude_integration(repo_root, bookstore=False)
        assert any("parrot toolkits install" in a for a in actions)


class TestToolkitTemplateDrift:
    def test_missing_keys_recurses_mappings_only(self):
        from parrot.mcp.toolkit_seed import _missing_keys

        template = {"class": "X", "kwargs": {"roster": [1, 2], "complexity": {"strong_models": []}}}
        existing = {"class": "Y", "kwargs": {"roster": [1]}}
        assert _missing_keys(template, existing) == ["kwargs.complexity"]

    def test_template_drift_empty_for_unparseable_file(self, repo_root):
        from parrot.mcp.toolkit_seed import template_drift

        (repo_root / ".parrot" / "mcp-toolkits.yaml").write_text("toolkits: [unbalanced\n")
        assert template_drift(repo_root, "sdd-coder") == []

    def test_template_drift_ignores_enabled_switch(self, repo_root):
        from parrot.mcp.toolkit_seed import template_drift

        (repo_root / ".parrot" / "mcp-toolkits.yaml").write_text(
            "toolkits:\n"
            "  targeted-writer:\n"
            "    class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit\n"
            f"    kwargs:\n      repo_root: {repo_root}\n"
        )
        assert template_drift(repo_root, "targeted-writer") == []


class TestInstallCLIToolkitOptions:
    """CLI-level coverage: hard-cut removal of --toolkits/--all-toolkits (AC9)."""

    def test_toolkits_flag_is_rejected(self, repo_root):
        # AC9 — hard cut: the flag must not be silently accepted.
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build", "--toolkits=memory"])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()

    def test_all_toolkits_flag_is_rejected(self, repo_root):
        # AC9 — hard cut: the flag must not be silently accepted.
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build", "--all-toolkits"])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()

    def test_empty_toolkit_config_hints_at_new_command(self, repo_root):
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build"])
        assert result.exit_code == 0, result.output
        assert "parrot toolkits install" in result.output

    def test_cli_no_approve_mcp_skips_approval(self, repo_root):
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build", "--no-approve-mcp"])
        assert result.exit_code == 0, result.output
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "enabledMcpjsonServers" not in local
