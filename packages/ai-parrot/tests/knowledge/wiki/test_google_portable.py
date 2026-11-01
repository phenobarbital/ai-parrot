"""FEAT-633 TASK-4084 — Google/Gemini: portable emission for the USER-GLOBAL config."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.bookstore import _is_managed_bookstore_entry
from parrot.knowledge.wiki.google.installer import (
    _is_managed_toolkit_entry,
    _is_managed_wikitoolkit_entry,
    install_google_integration,
    reconcile_toolkit_entries,
)

_TOOLKITS = "toolkits:\n  stub:\n    class: tests.mcp.stub_toolkit.StubToolkit\n"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _make_root(path: Path) -> Path:
    (path / ".parrot").mkdir(parents=True)
    (path / ".parrot" / "mcp-toolkits.yaml").write_text(_TOOLKITS)
    venv_bin = path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("wikitoolkit", "parrot"):
        (venv_bin / name).write_text("")
    return path


def _install(root: Path, cfg: Path, portable: bool | None) -> None:
    install_google_integration(root, gitignore=False, bookstore=False, mcp_config_path=cfg, portable=portable)


@pytest.fixture
def global_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "gemini" / "mcp_config.json"
    monkeypatch.setattr(assets, "default_mcp_config_path", lambda: cfg)  # never touch the real ~/.gemini
    return cfg


def test_portable_config_two_roots(tmp_path: Path, global_cfg: Path) -> None:
    """Spec §4: --portable output from two different roots is byte-identical (committable / shareable)."""
    cfg_a, cfg_b = tmp_path / "a.json", tmp_path / "b.json"
    root_a, root_b = _make_root(tmp_path / "repo-a"), _make_root(tmp_path / "repo-b")
    _install(root_a, cfg_a, True)
    _install(root_b, cfg_b, True)
    assert cfg_a.read_bytes() == cfg_b.read_bytes()
    plugin = Path(assets.PLUGIN_DIR) / "mcp_config.json"
    assert (root_a / plugin).read_bytes() == (root_b / plugin).read_bytes()


def test_portable_entries_no_abs_paths(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, True)
    servers = json.loads(global_cfg.read_text())["mcpServers"]
    assert all("cwd" not in entry for entry in servers.values())
    for text in _strings(servers):
        assert not os.path.isabs(text) and str(root) not in text, text
    bookstore_entry = assets.bookstore_mcp_entry(root, portable=True)
    assert bookstore_entry == {"command": "bookstore", "args": ["mcp"]} and sys.executable not in str(bookstore_entry)


def test_default_emission_unchanged(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, None)
    servers = json.loads(global_cfg.read_text())["mcpServers"]
    assert servers["wikitoolkit"] == {
        "command": str(root / ".venv" / "bin" / "wikitoolkit"),
        "args": ["mcp"],
        "cwd": str(root.resolve()),
    }
    assert servers["parrot-stub"]["cwd"] == str(root.resolve())


def test_portable_transitions_and_sticky_reconcile(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, True)
    _install(root, global_cfg, False)
    assert "cwd" in json.loads(global_cfg.read_text())["mcpServers"]["wikitoolkit"]
    _install(root, global_cfg, True)
    _install(root, global_cfg, None)  # flag absent keeps portable
    assert json.loads(global_cfg.read_text())["mcpServers"]["wikitoolkit"] == {"command": "wikitoolkit", "args": ["mcp"]}
    (root / ".parrot" / "mcp-toolkits.yaml").write_text(
        _TOOLKITS + "  stub2:\n    class: tests.mcp.stub_toolkit.StubToolkit\n"
    )
    reconcile_toolkit_entries(root, global_cfg)  # the GoogleAdapter path — sticky
    entry = json.loads(global_cfg.read_text())["mcpServers"]["parrot-stub2"]
    assert entry["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG and "cwd" not in entry


def test_foreign_entries_untouched(tmp_path: Path, global_cfg: Path) -> None:
    root = _make_root(tmp_path / "repo")
    foreign = {"command": "node", "args": ["wiki.js"]}
    global_cfg.parent.mkdir(parents=True, exist_ok=True)
    global_cfg.write_text(json.dumps({"mcpServers": {"wikitoolkit": foreign, "parrot-stub": foreign}}))
    for mode in (True, False):
        _install(root, global_cfg, mode)
        servers = json.loads(global_cfg.read_text())["mcpServers"]
        assert servers["wikitoolkit"] == foreign and servers["parrot-stub"] == foreign


def test_windows_paths_detected(tmp_path: Path) -> None:
    """codex S4: PurePosixPath no longer mis-reads Windows script paths."""
    assert _is_managed_wikitoolkit_entry({"command": "C:\\r\\.venv\\Scripts\\wikitoolkit.exe", "args": ["mcp"]}, tmp_path)
    assert _is_managed_toolkit_entry({"command": "C:\\r\\.venv\\Scripts\\parrot.exe", "args": ["mcp-local", "x"]}, tmp_path, "x")
    assert _is_managed_toolkit_entry(
        {"command": "parrot", "args": ["mcp-local", "x", "--config", assets.PORTABLE_TOOLKIT_CONFIG]}, tmp_path, "x"
    )
    assert _is_managed_bookstore_entry({"command": "bookstore", "args": ["mcp"]})
