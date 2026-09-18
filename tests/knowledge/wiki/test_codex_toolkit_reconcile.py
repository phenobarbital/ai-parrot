"""Codex toolkit-only reconciliation (FEAT-570, TASK-3372)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from parrot.knowledge.wiki.codex import assets
from parrot.knowledge.wiki.codex.installer import _install_mcp, reconcile_toolkit_tables


def _write_toolkits_yaml(root: Path, *, memory_enabled: bool = True) -> None:
    parrot_dir = root / ".parrot"
    parrot_dir.mkdir(parents=True, exist_ok=True)
    (parrot_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  memory:\n"
        "    class: tests.mcp.stub_toolkit.StubToolkit\n"
        f"    enabled: {'true' if memory_enabled else 'false'}\n",
        encoding="utf-8",
    )


def _config(root: Path) -> dict:
    return tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))


def test_reconcile_preserves_wikitoolkit_table(tmp_path, monkeypatch):
    """AC5 — the wiki table inside the managed block is not ours to rewrite."""
    root = tmp_path
    _write_toolkits_yaml(root, memory_enabled=True)
    _install_mcp(root)

    wikitoolkit_before = _config(root)["mcp_servers"]["wikitoolkit"]

    # If reconcile regenerated the wikitoolkit table (instead of preserving its
    # existing text), this monkeypatch would leak a new `command` value into it.
    monkeypatch.setattr(assets, "resolve_binary", lambda root, name: f"/changed/{name}")

    actions, warnings = reconcile_toolkit_tables(root)

    doc = _config(root)
    assert warnings == []
    assert actions
    assert doc["mcp_servers"]["wikitoolkit"] == wikitoolkit_before
    # The toolkit table, unlike wikitoolkit, IS regenerated on every reconcile.
    assert doc["mcp_servers"]["parrot-memory"]["command"] == "/changed/parrot"


def test_reconcile_skips_foreign_table_outside_block(tmp_path):
    """A hand-written [mcp_servers.parrot-memory] outside the markers is untouched."""
    root = tmp_path
    _write_toolkits_yaml(root, memory_enabled=True)
    config_path = root / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('[mcp_servers.parrot-memory]\ncommand = "foreign"\n', encoding="utf-8")

    actions, warnings = reconcile_toolkit_tables(root)

    doc = _config(root)
    assert doc["mcp_servers"]["parrot-memory"]["command"] == "foreign"
    assert any("parrot-memory" in warning for warning in warnings)
    # AC5 — a toolkit-only reconcile never introduces a wikitoolkit table.
    assert "wikitoolkit" not in doc.get("mcp_servers", {})
    assert actions == [".codex/config.toml — toolkit tables already current"]


def test_reconcile_output_is_valid_toml(tmp_path):
    """AC12 — the written file always parses as TOML."""
    root = tmp_path
    _write_toolkits_yaml(root, memory_enabled=True)

    reconcile_toolkit_tables(root)

    # tomllib.loads succeeding on the written file is the assertion.
    tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))


def test_reconcile_drops_disabled_section(tmp_path):
    """A disabled section's table disappears from the regenerated block."""
    root = tmp_path
    _write_toolkits_yaml(root, memory_enabled=True)
    reconcile_toolkit_tables(root)
    assert "parrot-memory" in _config(root)["mcp_servers"]

    _write_toolkits_yaml(root, memory_enabled=False)
    reconcile_toolkit_tables(root)

    assert "parrot-memory" not in _config(root).get("mcp_servers", {})


def test_reconcile_is_idempotent(tmp_path):
    """Reconciling twice in a row with no config change reports no change."""
    root = tmp_path
    _write_toolkits_yaml(root, memory_enabled=True)
    reconcile_toolkit_tables(root)
    config_path = root / ".codex" / "config.toml"
    before = config_path.read_bytes()

    actions, warnings = reconcile_toolkit_tables(root)

    assert config_path.read_bytes() == before
    assert warnings == []
    assert actions == [".codex/config.toml — toolkit tables already current"]
