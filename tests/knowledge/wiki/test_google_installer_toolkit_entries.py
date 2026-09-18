"""Unit tests for managed Google Antigravity mcp_config.json toolkit entries."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.cli import google
from parrot.knowledge.wiki.google.installer import (
    _install_mcp,
    reconcile_toolkit_entries,
    toolkit_config_paths,
    uninstall_google_integration,
)


@pytest.fixture
def mcp_config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "global_mcp/mcp_config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def tmp_root_with_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mcp_config_path: Path) -> Path:
    """Project root with the 3 builtins disabled + one custom enabled toolkit."""
    monkeypatch.setattr(assets, "default_mcp_config_path", lambda: mcp_config_path)
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir(parents=True, exist_ok=True)
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
        "      FOO: bar\n",
        encoding="utf-8",
    )
    return tmp_path


def _config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_install_writes_toolkit_entries(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    _install_mcp(root, mcp_path=mcp_config_path)

    doc = _config(mcp_config_path)
    servers = doc["mcpServers"]
    assert "wikitoolkit" in servers
    stub = servers["parrot-stub"]
    assert stub["command"] == assets.resolve_binary(root, "parrot")
    assert stub["args"] == ["mcp-local", "stub", "--config", str(root.resolve() / ".parrot" / "mcp-toolkits.yaml")]
    assert stub["cwd"] == str(root.resolve())
    assert stub["env"] == {"FOO": "bar"}
    assert "parrot-scraping" not in servers
    assert "parrot-browsing" not in servers
    assert "parrot-memory" not in servers


def test_google_entry_pins_config_keeps_cwd(tmp_root_with_config: Path):
    """`toolkit_mcp_entries` carries both --config and the pre-existing cwd."""
    root = tmp_root_with_config
    from parrot.mcp.toolkit_config import load_toolkits_config

    cfg = load_toolkits_config(root)
    entries = assets.toolkit_mcp_entries(root, {"stub": cfg.toolkits["stub"]})

    entry = entries["parrot-stub"]
    assert "--config" in entry["args"]
    assert entry["args"][-1] == str(root.resolve() / ".parrot" / "mcp-toolkits.yaml")
    assert entry["cwd"] == str(root.resolve())


def test_google_legacy_entry_adopted(tmp_root_with_config: Path, mcp_config_path: Path, capsys):
    """A pre-FEAT-556 two-arg entry is recognized as managed and upgraded, with no stderr warning."""
    root = tmp_root_with_config
    mcp_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "parrot-stub": {
                        "command": assets.resolve_binary(root, "parrot"),
                        "args": ["mcp-local", "stub"],
                        "cwd": str(root.resolve()),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    _install_mcp(root, mcp_path=mcp_config_path)

    servers = _config(mcp_config_path)["mcpServers"]
    assert servers["parrot-stub"]["args"] == [
        "mcp-local",
        "stub",
        "--config",
        str(root.resolve() / ".parrot" / "mcp-toolkits.yaml"),
    ]
    stderr = capsys.readouterr().err
    assert "Warning:" not in stderr


def test_install_is_idempotent(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    _install_mcp(root, mcp_path=mcp_config_path)
    before = mcp_config_path.read_bytes()

    _install_mcp(root, mcp_path=mcp_config_path)
    assert mcp_config_path.read_bytes() == before


def test_disabled_section_table_removed_on_rerun(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    _install_mcp(root, mcp_path=mcp_config_path)
    assert "parrot-stub" in _config(mcp_config_path)["mcpServers"]

    cfg_path = root / ".parrot" / "mcp-toolkits.yaml"
    text = cfg_path.read_text(encoding="utf-8").replace(
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    env:\n      FOO: bar\n",
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: false\n    env:\n      FOO: bar\n",
    )
    cfg_path.write_text(text, encoding="utf-8")

    _install_mcp(root, mcp_path=mcp_config_path)
    assert "parrot-stub" not in _config(mcp_config_path)["mcpServers"]


def test_foreign_colliding_toolkit_preserved(tmp_root_with_config: Path, mcp_config_path: Path, capsys):
    root = tmp_root_with_config
    mcp_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "parrot-stub": {
                        "command": "foreign_parrot",
                        "args": ["foreign_arg"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    _install_mcp(root, mcp_path=mcp_config_path)
    servers = _config(mcp_config_path)["mcpServers"]
    assert servers["parrot-stub"]["command"] == "foreign_parrot"
    stderr = capsys.readouterr().err
    assert "already exists and was not written by `parrot google install`" in stderr


def test_toolkit_config_paths_reports_user_global_first(tmp_path: Path):
    paths = toolkit_config_paths(tmp_path, mcp_path=tmp_path / "mcp_config.json")
    assert paths[0] == tmp_path / "mcp_config.json"
    assert paths[1] == tmp_path / ".agents" / "plugins" / "parrot" / "mcp_config.json"


def test_reconcile_preserves_wikitoolkit_entry(tmp_root_with_config: Path, mcp_config_path: Path):
    """AC5 — the wiki server is not ours to touch, in either file."""
    root = tmp_root_with_config
    wiki_entry = {"command": "wikitoolkit", "args": ["mcp"], "cwd": str(root.resolve())}
    plugin_mcp_file = root / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    plugin_mcp_file.parent.mkdir(parents=True, exist_ok=True)

    mcp_config_path.write_text(json.dumps({"mcpServers": {"wikitoolkit": wiki_entry}}), encoding="utf-8")
    plugin_mcp_file.write_text(json.dumps({"mcpServers": {"wikitoolkit": wiki_entry}}), encoding="utf-8")

    reconcile_toolkit_entries(root, mcp_path=mcp_config_path)

    assert _config(mcp_config_path)["mcpServers"]["wikitoolkit"] == wiki_entry
    assert _config(plugin_mcp_file)["mcpServers"]["wikitoolkit"] == wiki_entry


def test_reconcile_preserves_foreign_toolkit_entry(tmp_root_with_config: Path, mcp_config_path: Path, capsys):
    root = tmp_root_with_config
    mcp_config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "parrot-stub": {
                        "command": "foreign_parrot",
                        "args": ["foreign_arg"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    actions, warnings = reconcile_toolkit_entries(root, mcp_path=mcp_config_path)

    servers = _config(mcp_config_path)["mcpServers"]
    assert servers["parrot-stub"]["command"] == "foreign_parrot"
    assert any("parrot-stub" in w for w in warnings)
    stderr = capsys.readouterr().err
    assert "already exists and was not written by `parrot google install`" in stderr


def test_reconcile_updates_both_config_files(tmp_root_with_config: Path, mcp_config_path: Path):
    root = tmp_root_with_config
    actions, warnings = reconcile_toolkit_entries(root, mcp_path=mcp_config_path)

    plugin_mcp_file = root / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    primary_servers = _config(mcp_config_path)["mcpServers"]
    plugin_servers = _config(plugin_mcp_file)["mcpServers"]

    assert "parrot-stub" in primary_servers
    assert "parrot-stub" in plugin_servers
    assert primary_servers["parrot-stub"] == plugin_servers["parrot-stub"]
    assert not warnings
    assert any("parrot-stub" in a for a in actions)


class TestInstallCLIToolkitOptions:
    """CLI-level coverage: hard-cut removal of --toolkits/--all-toolkits (AC9)."""

    def test_toolkits_flag_is_rejected(self, tmp_path: Path):
        # AC9 — hard cut: the flag must not be silently accepted.
        runner = CliRunner()
        result = runner.invoke(google, ["install", "--path", str(tmp_path), "--no-build", "--toolkits=memory"])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()

    def test_all_toolkits_flag_is_rejected(self, tmp_path: Path):
        # AC9 — hard cut: the flag must not be silently accepted.
        runner = CliRunner()
        result = runner.invoke(google, ["install", "--path", str(tmp_path), "--no-build", "--all-toolkits"])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()

    def test_empty_toolkit_config_hints_at_new_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mcp_config_path: Path
    ):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        monkeypatch.setattr(assets, "default_mcp_config_path", lambda: mcp_config_path)

        runner = CliRunner()
        result = runner.invoke(
            google,
            ["install", "--path", str(repo_root), "--no-build", "--no-bookstore", "--no-gitignore"],
        )
        assert result.exit_code == 0, result.output
        assert "parrot toolkits install" in result.output

    def test_install_command_still_reconciles_enabled_toolkits(self, tmp_root_with_config: Path, mcp_config_path: Path):
        """The flag cut must not break reconciliation for a repo with enabled sections."""
        root = tmp_root_with_config

        runner = CliRunner()
        result = runner.invoke(
            google,
            ["install", "--path", str(root), "--no-build", "--no-bookstore", "--no-gitignore"],
        )
        assert result.exit_code == 0, result.output

        servers = _config(mcp_config_path)["mcpServers"]
        assert "parrot-stub" in servers
