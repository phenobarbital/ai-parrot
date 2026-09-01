"""Unit tests for managed Codex ``.codex/config.toml`` toolkit tables.

FEAT-485 TASK-2649: ``_install_mcp`` now regenerates the whole managed MCP
marker block from `.parrot/mcp-toolkits.yaml` on every install — the
wikitoolkit table plus one ``[mcp_servers.parrot-<name>]`` table per
enabled toolkit section. Re-running reconciles (disabled/deleted sections
disappear because the block is fully regenerated); uninstall removes the
whole marker block (everything managed) in one step; a foreign table
outside the block with a colliding name is left untouched and reported.
"""

import tomllib
from pathlib import Path

import pytest
from parrot.knowledge.wiki.codex import assets
from parrot.knowledge.wiki.codex.installer import (
    _install_mcp,
    uninstall_codex_integration,
)


@pytest.fixture
def tmp_root_with_config(tmp_path: Path) -> Path:
    """Project root with the 3 builtins disabled + one custom enabled toolkit.

    Disabling the always-on builtins keeps assertions focused on a single
    managed toolkit table (``parrot-stub``) instead of three.
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


def _config(root: Path) -> dict:
    return tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))


def test_install_writes_toolkit_tables(tmp_root_with_config):
    """Enabled sections get a `[mcp_servers.parrot-<name>]` table."""
    root = tmp_root_with_config

    _install_mcp(root)

    doc = _config(root)
    servers = doc["mcp_servers"]
    assert "wikitoolkit" in servers
    stub = servers["parrot-stub"]
    assert stub["command"] == assets.resolve_binary(root, "parrot")
    assert stub["args"] == ["mcp-local", "stub"]
    assert stub["env"] == {"FOO": "bar"}
    assert "parrot-scraping" not in servers
    assert "parrot-browsing" not in servers
    assert "parrot-memory" not in servers


def test_install_is_idempotent(tmp_root_with_config):
    """A second run with no config change is byte-identical."""
    root = tmp_root_with_config
    _install_mcp(root)
    config_path = root / ".codex" / "config.toml"
    before = config_path.read_bytes()

    status = _install_mcp(root)

    assert config_path.read_bytes() == before
    assert status == ".codex/config.toml — wikitoolkit MCP already current"


def test_disabled_section_table_removed_on_rerun(tmp_root_with_config):
    """Disabling a previously-enabled section drops its table on re-run."""
    root = tmp_root_with_config
    _install_mcp(root)
    assert "parrot-stub" in _config(root)["mcp_servers"]

    cfg_path = root / ".parrot" / "mcp-toolkits.yaml"
    text = cfg_path.read_text(encoding="utf-8").replace(
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    env:\n      FOO: bar\n",
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: false\n    env:\n      FOO: bar\n",
    )
    cfg_path.write_text(text, encoding="utf-8")

    _install_mcp(root)

    assert "parrot-stub" not in _config(root)["mcp_servers"]


def test_wikitoolkit_table_unchanged(tmp_root_with_config):
    """The wikitoolkit table content is unaffected by toolkit reconciliation."""
    root = tmp_root_with_config

    _install_mcp(root)

    server = _config(root)["mcp_servers"]["wikitoolkit"]
    assert server["args"] == ["mcp"]
    assert server["default_tools_approval_mode"] == "approve"
    assert server["command"] == assets.resolve_binary(root, "wikitoolkit")


def test_uninstall_removes_tables(tmp_root_with_config):
    """Uninstall removes the whole managed block — wikitoolkit + toolkits."""
    root = tmp_root_with_config
    _install_mcp(root)

    uninstall_codex_integration(root)

    config_path = root / ".codex" / "config.toml"
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    assert assets.MCP_BEGIN not in text
    assert "parrot-stub" not in text


def test_toml_always_valid(tmp_root_with_config):
    """The written config.toml always parses, with or without toolkits."""
    root = tmp_root_with_config

    _install_mcp(root)

    # tomllib.loads succeeding is the assertion — raises on invalid TOML.
    tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))


def test_foreign_table_outside_block_untouched(tmp_root_with_config):
    """A foreign table outside the marker block is preserved."""
    root = tmp_root_with_config
    config_path = root / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text('[mcp_servers.other]\ncommand = "keep"\n', encoding="utf-8")

    _install_mcp(root)

    doc = _config(root)
    assert doc["mcp_servers"]["other"]["command"] == "keep"
    assert "parrot-stub" in doc["mcp_servers"]


def test_colliding_foreign_table_omitted_with_warning(tmp_root_with_config, capsys):
    """A foreign `parrot-<name>` table outside the block is never overwritten."""
    root = tmp_root_with_config
    config_path = root / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text('[mcp_servers.parrot-stub]\ncommand = "foreign"\n', encoding="utf-8")

    _install_mcp(root)

    doc = _config(root)
    assert doc["mcp_servers"]["parrot-stub"]["command"] == "foreign"
    captured = capsys.readouterr()
    assert "parrot-stub" in captured.err
    assert "not written by" in captured.err
