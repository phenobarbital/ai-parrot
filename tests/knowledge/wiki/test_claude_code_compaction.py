"""Tests for the fast-jev-compaction plugin wiring in ``parrot claude install``.

All offline against temp directories; the ``claude`` CLI is never executed
(``_claude_binary`` is patched to ``None`` unless a test fakes it).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.claude_code import compaction
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.compaction import (
    API_KEY_ENV,
    FUNCTION_HOOKS_ENV,
    MARKETPLACE_ENTRY,
    MARKETPLACE_NAME,
    MARKETPLACE_REPO,
    PLUGIN_ID,
    compaction_status,
    install_compaction,
    uninstall_compaction,
)
from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)


@pytest.fixture(autouse=True)
def _no_claude_cli(monkeypatch):
    monkeypatch.setattr(compaction, "_claude_binary", lambda: None)
    monkeypatch.delenv(API_KEY_ENV, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text('"""A module."""\nX = 1\n', encoding="utf-8")
    return tmp_path


def _settings(repo: Path, name: str = "settings.json") -> dict:
    return json.loads((repo / ".claude" / name).read_text(encoding="utf-8"))


class TestInstall:
    def test_fresh_install_writes_declarative_plugin_wiring(self, repo):
        actions = install_compaction(repo)
        settings = _settings(repo)
        assert settings["env"][FUNCTION_HOOKS_ENV] == "1"
        assert settings["extraKnownMarketplaces"][MARKETPLACE_NAME] == MARKETPLACE_ENTRY
        assert settings["extraKnownMarketplaces"][MARKETPLACE_NAME]["source"]["repo"] == MARKETPLACE_REPO
        assert settings["enabledPlugins"][PLUGIN_ID] is True
        assert API_KEY_ENV not in json.dumps(settings)
        assert any("function hooks enabled" in a for a in actions)
        assert any("NOT configured" in a for a in actions)
        assert any("claude CLI — not found" in a for a in actions)
        assert not (repo / ".claude" / "settings.local.json").exists()

    def test_install_is_idempotent_and_preserves_foreign_settings(self, repo):
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "env": {"OTHER": "x"},
                    "enabledPlugins": {"formatter@company": True},
                    "extraKnownMarketplaces": {"company": {"source": {"source": "github", "repo": "org/tools"}}},
                    "hooks": {"PreToolUse": []},
                }
            ),
            encoding="utf-8",
        )
        install_compaction(repo)
        again = install_compaction(repo)
        settings = _settings(repo)
        assert settings["env"] == {"OTHER": "x", FUNCTION_HOOKS_ENV: "1"}
        assert settings["enabledPlugins"] == {"formatter@company": True, PLUGIN_ID: True}
        assert set(settings["extraKnownMarketplaces"]) == {"company", MARKETPLACE_NAME}
        assert settings["hooks"] == {"PreToolUse": []}
        assert any("already installed" in a for a in again)

    def test_foreign_marketplace_with_same_name_is_left_untouched(self, repo):
        (repo / ".claude").mkdir()
        foreign = {"source": {"source": "directory", "path": "./plugins"}}
        (repo / ".claude" / "settings.json").write_text(
            json.dumps({"extraKnownMarketplaces": {MARKETPLACE_NAME: foreign}}), encoding="utf-8"
        )
        actions = install_compaction(repo)
        assert _settings(repo)["extraKnownMarketplaces"][MARKETPLACE_NAME] == foreign
        assert any("WARNING" in a and "left untouched" in a for a in actions)
        assert _settings(repo)["enabledPlugins"][PLUGIN_ID] is True

    def test_explicit_api_key_goes_to_local_settings_only(self, repo):
        actions = install_compaction(repo, api_key="sk-test")
        local = _settings(repo, "settings.local.json")
        assert local["env"][API_KEY_ENV] == "sk-test"
        assert API_KEY_ENV not in json.dumps(_settings(repo))
        assert any("written (git-ignored" in a for a in actions)
        again = install_compaction(repo, api_key="sk-test")
        assert any(f"{API_KEY_ENV} already set" in a for a in again)

    def test_api_key_from_environment_is_reported_not_copied(self, repo, monkeypatch):
        monkeypatch.setenv(API_KEY_ENV, "sk-env")
        actions = install_compaction(repo)
        assert any("found in the environment" in a for a in actions)
        assert not (repo / ".claude" / "settings.local.json").exists()

    def test_corrupt_settings_are_never_clobbered(self, repo):
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Cannot parse"):
            install_compaction(repo)
        assert (repo / ".claude" / "settings.json").read_text(encoding="utf-8") == "{not json"

    def test_wrong_shape_at_needed_key_raises(self, repo):
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": []}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="enabledPlugins"):
            install_compaction(repo)


class TestPluginCli:
    def test_cli_is_invoked_non_interactively_when_available(self, repo, monkeypatch):
        calls: list[dict] = []

        def fake_run(argv, **kwargs):
            calls.append({"argv": argv, **kwargs})
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr(compaction, "_claude_binary", lambda: "/usr/bin/claude")
        monkeypatch.setattr(compaction.subprocess, "run", fake_run)
        actions = install_compaction(repo)
        assert [c["argv"] for c in calls] == [
            ["/usr/bin/claude", "plugin", "marketplace", "add", MARKETPLACE_REPO],
            ["/usr/bin/claude", "plugin", "install", PLUGIN_ID, "--scope", "project", "-y"],
        ]
        for call in calls:
            assert call["stdin"] is subprocess.DEVNULL
            assert call["cwd"] == str(repo.resolve())
            assert call["env"][FUNCTION_HOOKS_ENV] == "1"
            assert call["timeout"] == compaction.PLUGIN_CLI_TIMEOUT
        assert any("marketplace add" in a and "ok" in a for a in actions)
        assert any("--scope project — ok" in a for a in actions)

    def test_cli_failure_is_reported_not_raised(self, repo, monkeypatch):
        monkeypatch.setattr(compaction, "_claude_binary", lambda: "/usr/bin/claude")
        monkeypatch.setattr(
            compaction.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 2, stdout="", stderr="boom"),
        )
        actions = install_compaction(repo)
        assert any("failed (rc=2): boom" in a for a in actions)
        assert _settings(repo)["enabledPlugins"][PLUGIN_ID] is True

    def test_cli_timeout_is_reported(self, repo, monkeypatch):
        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 1)

        monkeypatch.setattr(compaction, "_claude_binary", lambda: "/usr/bin/claude")
        monkeypatch.setattr(compaction.subprocess, "run", slow)
        actions = install_compaction(repo)
        assert any("failed (rc=-1)" in a for a in actions)

    def test_plugin_cli_can_be_disabled(self, repo, monkeypatch):
        monkeypatch.setattr(compaction, "_claude_binary", lambda: "/usr/bin/claude")
        monkeypatch.setattr(compaction.subprocess, "run", lambda *a, **k: pytest.fail("must not run"))
        install_compaction(repo, plugin_cli=False)


class TestUninstallAndStatus:
    def test_uninstall_removes_only_managed_entries(self, repo):
        install_compaction(repo, api_key="sk-test")
        actions = uninstall_compaction(repo)
        settings = _settings(repo)
        assert "enabledPlugins" not in settings
        assert "extraKnownMarketplaces" not in settings
        assert "env" not in settings
        assert any(f"{FUNCTION_HOOKS_ENV} removed" in a for a in actions)
        assert _settings(repo, "settings.local.json")["env"][API_KEY_ENV] == "sk-test"
        assert any("left in place" in a for a in actions)
        assert uninstall_compaction(repo) == []

    def test_uninstall_keeps_flag_and_foreign_entries_when_other_plugins_remain(self, repo):
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "enabledPlugins": {"formatter@company": True},
                    "extraKnownMarketplaces": {MARKETPLACE_NAME: {"source": {"source": "directory", "path": "x"}}},
                }
            ),
            encoding="utf-8",
        )
        install_compaction(repo)
        uninstall_compaction(repo)
        settings = _settings(repo)
        assert settings["enabledPlugins"] == {"formatter@company": True}
        assert settings["extraKnownMarketplaces"][MARKETPLACE_NAME] == {"source": {"source": "directory", "path": "x"}}
        assert settings["env"][FUNCTION_HOOKS_ENV] == "1"

    def test_status_reflects_each_piece(self, repo, monkeypatch):
        assert compaction_status(repo) == {
            "compaction_plugin": False,
            "compaction_function_hooks": False,
            "compaction_api_key": False,
        }
        install_compaction(repo, api_key="sk-test")
        assert compaction_status(repo) == {
            "compaction_plugin": True,
            "compaction_function_hooks": True,
            "compaction_api_key": True,
        }
        uninstall_compaction(repo)
        status = compaction_status(repo)
        assert status["compaction_plugin"] is False and status["compaction_api_key"] is True
        monkeypatch.setenv(API_KEY_ENV, "sk-env")
        assert compaction_status(tmp_path_factory_like(repo))["compaction_api_key"] is True


def tmp_path_factory_like(repo: Path) -> Path:
    """Fresh sibling directory with no settings at all."""
    fresh = repo.parent / "fresh"
    fresh.mkdir(exist_ok=True)
    return fresh


class TestIntegrationWiring:
    def test_library_default_is_opt_in_and_cli_default_is_on(self, repo):
        actions = install_claude_integration(repo)
        assert not any("fast-jev-compaction" in a for a in actions)
        assert integration_status(repo)["compaction_plugin"] is False

        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo), "--no-build"])
        assert result.exit_code == 0, result.output
        assert PLUGIN_ID in result.output
        info = json.loads(runner.invoke(claude, ["status", "--path", str(repo), "--json"]).output)
        assert info["compaction_plugin"] is True
        assert info["compaction_function_hooks"] is True

        result = runner.invoke(claude, ["uninstall", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert f"plugin '{PLUGIN_ID}' removed" in result.output
        info = json.loads(runner.invoke(claude, ["status", "--path", str(repo), "--json"]).output)
        assert info["compaction_plugin"] is False

    def test_cli_no_compaction_and_api_key_option(self, repo):
        runner = CliRunner()
        result = runner.invoke(claude, ["install", "--path", str(repo), "--no-build", "--no-compaction"])
        assert result.exit_code == 0, result.output
        assert "fast-jev-compaction" not in result.output
        assert "enabledPlugins" not in json.dumps(_settings(repo))

        result = runner.invoke(
            claude, ["install", "--path", str(repo), "--no-build", "--typesafe-api-key", "sk-cli", "--no-plugin-cli"]
        )
        assert result.exit_code == 0, result.output
        assert _settings(repo, "settings.local.json")["env"][API_KEY_ENV] == "sk-cli"
        assert "sk-cli" not in json.dumps(_settings(repo))

    def test_status_labels_include_compaction(self, repo):
        install_claude_integration(repo, compaction=True)
        result = CliRunner().invoke(claude, ["status", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "✓ fast-jev-compaction plugin" in result.output
        assert "✓ CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1" in result.output
        assert "✗ TYPESAFE_API_KEY" in result.output
