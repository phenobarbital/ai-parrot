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
from parrot.mcp.toolkit_seed import available_templates


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
        # Seed .mcp.json with a wikitoolkit entry + one managed parrot-memory entry.
        install_claude_integration(repo_root, toolkits=["bounded-source"], bookstore=False)
        mcp_json = repo_root / ".mcp.json"
        before = json.loads(mcp_json.read_text())
        wikitoolkit_before = before["mcpServers"]["wikitoolkit"]

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
        install_claude_integration(repo_root, toolkits=["bounded-source"], bookstore=False)
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


class TestSeedingAndApproval:
    def test_install_seeds_before_reconciliation(self, repo_root):
        install_claude_integration(repo_root, toolkits=["bounded-source"], bookstore=False)
        servers = json.loads((repo_root / ".mcp.json").read_text())["mcpServers"]
        assert "parrot-bounded-source" in servers
        assert (repo_root / ".parrot" / "mcp-toolkits.yaml").exists()

    def test_toolkits_default_is_empty(self, repo_root):
        install_claude_integration(repo_root, bookstore=False)
        assert not (repo_root / ".parrot" / "mcp-toolkits.yaml").exists()

    def test_install_no_approve_flag_skips_approval(self, repo_root):
        install_claude_integration(repo_root, approve_mcp=False, bookstore=False)
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "enabledMcpjsonServers" not in local

    def test_install_approve_flag_adds_enabled_servers(self, repo_root):
        install_claude_integration(repo_root, toolkits=["bounded-source"], approve_mcp=True, bookstore=False)
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "wikitoolkit" in local["enabledMcpjsonServers"]
        assert "parrot-bounded-source" in local["enabledMcpjsonServers"]

    def test_all_toolkits_seeds_every_template(self, repo_root):
        templates = available_templates()
        install_claude_integration(repo_root, toolkits=templates, bookstore=False)
        yaml_path = repo_root / ".parrot" / "mcp-toolkits.yaml"
        assert yaml_path.exists()
        content = yaml_path.read_text()
        for template in templates:
            assert f"{template}:" in content

    def test_reinstall_reports_keys_missing_from_existing_section(self, repo_root):
        # A section seeded before its template gained a key is never rewritten,
        # but the missing key must be surfaced instead of silently skipped.
        yaml_path = repo_root / ".parrot" / "mcp-toolkits.yaml"
        yaml_path.write_text(
            "toolkits:\n"
            "  sdd-coder:\n"
            "    class: parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit\n"
            "    kwargs:\n"
            "      roster:\n"
            "        - {label: haiku, kind: native, model: haiku}\n"
        )
        before = yaml_path.read_text()
        actions = install_claude_integration(repo_root, toolkits=["sdd-coder"], bookstore=False)
        assert yaml_path.read_text() == before
        warnings = [a for a in actions if "lacks template key(s)" in a]
        assert len(warnings) == 1
        assert "'sdd-coder'" in warnings[0]
        assert "kwargs.complexity" in warnings[0]
        assert "kwargs.roster" not in warnings[0]

    def test_reinstall_of_current_section_reports_no_drift(self, repo_root):
        install_claude_integration(repo_root, toolkits=["sdd-coder"], bookstore=False)
        actions = install_claude_integration(repo_root, toolkits=["sdd-coder"], bookstore=False)
        assert not [a for a in actions if "lacks template key(s)" in a]


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
    """CLI-level coverage: options, hint, exception mapping (AC bullets 4-7)."""

    def test_cli_seeds_named_toolkit_and_approves(self, repo_root):
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build", "--toolkits=bounded-source"])
        assert result.exit_code == 0, result.output
        assert (repo_root / ".parrot" / "mcp-toolkits.yaml").exists()
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "parrot-bounded-source" in local["enabledMcpjsonServers"]
        assert "Start a new Claude Code session" in result.output

    def test_cli_all_toolkits_seeds_every_template(self, repo_root):
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build", "--all-toolkits"])
        assert result.exit_code == 0, result.output
        yaml_path = repo_root / ".parrot" / "mcp-toolkits.yaml"
        assert yaml_path.exists()
        content = yaml_path.read_text()
        for template in available_templates():
            assert f"{template}:" in content

    def test_cli_no_toolkit_flag_prints_hint_and_seeds_nothing(self, repo_root):
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build"])
        assert result.exit_code == 0, result.output
        assert not (repo_root / ".parrot" / "mcp-toolkits.yaml").exists()
        assert "--toolkits" in result.output
        assert "--all-toolkits" in result.output
        for template in available_templates():
            assert template in result.output

    def test_cli_no_approve_mcp_skips_approval(self, repo_root):
        runner = CliRunner()
        result = runner.invoke(
            claude,
            ["install", "--path", str(repo_root), "--no-build", "--toolkits=bounded-source", "--no-approve-mcp"],
        )
        assert result.exit_code == 0, result.output
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "enabledMcpjsonServers" not in local

    def test_cli_seeder_value_error_is_click_exception(self, repo_root, monkeypatch):
        def _boom(root, names):
            raise ValueError("boom")

        import parrot.mcp.toolkit_seed as toolkit_seed_module

        monkeypatch.setattr(toolkit_seed_module, "seed_toolkit_sections", _boom)
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo_root), "--no-build", "--toolkits=bounded-source"])
        assert result.exit_code != 0
        assert not isinstance(result.exception, ValueError)
