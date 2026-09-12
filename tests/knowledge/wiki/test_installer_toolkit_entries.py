"""Unit tests for managed ``.mcp.json`` toolkit-entry reconciliation.

FEAT-485 TASK-2648: ``_install_mcp_json``/``_uninstall_mcp_json`` now
reconcile one ``parrot-<name>`` entry per enabled toolkit section on top
of the pre-existing wikitoolkit entry — add/update/remove managed
entries, never touch foreign entries, and skip (with a stderr warning) a
foreign entry whose name collides with a managed one.
"""

import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.claude_code.installer import (
    _install_mcp_json,
    _uninstall_mcp_json,
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


def _servers(root: Path) -> dict:
    return json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


def test_install_writes_toolkit_entries(tmp_root_with_config):
    """Enabled sections get a `parrot-<name>` entry; disabled ones don't."""
    root = tmp_root_with_config

    _install_mcp_json(root)

    servers = _servers(root)
    assert "wikitoolkit" in servers
    assert servers["parrot-stub"] == {
        "command": assets.resolve_parrot_bin(root),
        "args": ["mcp-local", "stub", "--config", str(root / ".parrot" / "mcp-toolkits.yaml")],
        "cwd": str(root),
        "env": {"FOO": "bar"},
    }
    assert "parrot-scraping" not in servers
    assert "parrot-browsing" not in servers
    assert "parrot-memory" not in servers


def test_install_is_idempotent(tmp_root_with_config):
    """A second run with no config change writes nothing and says so."""
    root = tmp_root_with_config
    _install_mcp_json(root)
    before = (root / ".mcp.json").read_text(encoding="utf-8")

    status = _install_mcp_json(root)

    after = (root / ".mcp.json").read_text(encoding="utf-8")
    assert after == before
    assert status == ".mcp.json — wikitoolkit entry already current"


def test_disabled_section_entry_removed_on_rerun(tmp_root_with_config):
    """Disabling a previously-enabled section removes its managed entry."""
    root = tmp_root_with_config
    _install_mcp_json(root)
    assert "parrot-stub" in _servers(root)

    cfg_path = root / ".parrot" / "mcp-toolkits.yaml"
    text = cfg_path.read_text(encoding="utf-8").replace(
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    env:\n      FOO: bar\n",
        "  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: false\n    env:\n      FOO: bar\n",
    )
    cfg_path.write_text(text, encoding="utf-8")

    status = _install_mcp_json(root)

    assert "parrot-stub" not in _servers(root)
    assert "removed" in status


def test_foreign_entry_untouched(tmp_root_with_config):
    """A foreign entry with an unrelated name is never modified."""
    root = tmp_root_with_config
    foreign = {"command": "some-other-cli", "args": ["serve"], "env": {}}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"other-tool": foreign}}), encoding="utf-8")

    _install_mcp_json(root)

    assert _servers(root)["other-tool"] == foreign


def test_colliding_foreign_entry_skipped_with_warning(tmp_root_with_config, capsys):
    """A `parrot-<name>` entry not in our managed shape is left untouched."""
    root = tmp_root_with_config
    foreign = {"command": "some-other-cli", "args": ["serve"], "env": {}}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"parrot-stub": foreign}}), encoding="utf-8")

    _install_mcp_json(root)

    assert _servers(root)["parrot-stub"] == foreign
    captured = capsys.readouterr()
    assert "parrot-stub" in captured.err
    assert "not written by" in captured.err


def test_wikitoolkit_entry_unchanged(tmp_root_with_config):
    """The wikitoolkit entry content is byte-identical to pre-feature output."""
    root = tmp_root_with_config

    _install_mcp_json(root)

    assert _servers(root)["wikitoolkit"] == assets.mcp_json_entry(root)


def test_toolkit_entry_pins_config_and_cwd(tmp_root_with_config):
    """Pinned entries include --config and cwd for worktree compatibility."""
    _install_mcp_json(tmp_root_with_config)
    servers = _servers(tmp_root_with_config)
    entry = servers["parrot-stub"]
    assert entry["args"][:2] == ["mcp-local", "stub"]
    assert entry["args"][2:] == ["--config", str(tmp_root_with_config / ".parrot" / "mcp-toolkits.yaml")]
    assert entry["cwd"] == str(tmp_root_with_config)


def test_legacy_entry_is_adopted_and_upgraded(tmp_root_with_config, capsys):
    """A two-arg entry from an older install is upgraded, not skipped."""
    root = tmp_root_with_config
    # Write a legacy (pre-FEAT-556) entry
    legacy_entry = {
        "command": assets.resolve_parrot_bin(root),
        "args": ["mcp-local", "stub"],
        "env": {"FOO": "bar"},
    }
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"wikitoolkit": assets.mcp_json_entry(root), "parrot-stub": legacy_entry}}),
        encoding="utf-8",
    )

    _install_mcp_json(root)

    # Entry should be upgraded to pinned shape
    servers = _servers(root)
    entry = servers["parrot-stub"]
    assert entry["args"][:2] == ["mcp-local", "stub"]
    assert entry["args"][2:] == ["--config", str(root / ".parrot" / "mcp-toolkits.yaml")]
    assert entry["cwd"] == str(root)
    # No warning should be emitted
    captured = capsys.readouterr()
    assert "Warning" not in captured.err
    assert "not written by" not in captured.err


def test_foreign_entry_untouched(tmp_root_with_config, capsys):
    """Existing FEAT-485 behaviour must not regress."""
    root = tmp_root_with_config
    foreign = {"command": "some-other-cli", "args": ["serve"], "env": {}}
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"parrot-stub": foreign}}),
        encoding="utf-8",
    )

    _install_mcp_json(root)

    assert _servers(root)["parrot-stub"] == foreign
    captured = capsys.readouterr()
    assert "parrot-stub" in captured.err
    assert "not written by" in captured.err


def test_uninstall_removes_managed_only(tmp_root_with_config):
    """Uninstall removes exactly the managed set; foreign entries survive."""
    root = tmp_root_with_config
    mcp_json = root / ".mcp.json"
    _install_mcp_json(root)

    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    foreign = {"command": "some-other-cli", "args": ["serve"], "env": {}}
    data["mcpServers"]["other-tool"] = foreign
    mcp_json.write_text(json.dumps(data), encoding="utf-8")

    status = _uninstall_mcp_json(root)

    assert status is not None
    servers = _servers(root)
    assert "wikitoolkit" not in servers
    assert "parrot-stub" not in servers
    assert servers["other-tool"] == foreign
