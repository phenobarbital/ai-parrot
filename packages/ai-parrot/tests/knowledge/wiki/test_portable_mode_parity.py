"""FEAT-633 R4: Claude and Codex infer the sticky portable mode with the same truth table.

A baked install whose ``wikitoolkit`` binary resolves nowhere (no project venv, nothing on PATH) falls back
to the bare ``wikitoolkit`` command — the same text as the portable form. That bare entry is therefore
ambiguous; the managed ``parrot-*`` entries (absolute vs relative ``--config``) break the tie, and with none
of them the bare entry means portable. Both hosts must agree, so a plain re-install never silently converts
a baked install to portable.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from parrot.knowledge.wiki.claude_code import assets as claude_assets
from parrot.knowledge.wiki.claude_code import installer as claude
from parrot.knowledge.wiki.codex import assets as codex_assets
from parrot.knowledge.wiki.codex import installer as codex

_TOOLKITS = "toolkits:\n  memory:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo with no project venv and no binaries on PATH: baked emission falls back to bare names."""
    monkeypatch.setattr("shutil.which", lambda *_args, **_kwargs: None)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(_TOOLKITS)
    return tmp_path


def _install_claude(root: Path, portable: bool | None) -> None:
    claude.install_claude_integration(root, git_hook=False, gitignore=False, bookstore=False, portable=portable)


def _install_codex(root: Path, portable: bool | None) -> None:
    codex.install_codex_integration(root, gitignore=False, bookstore=False, portable=portable)


def _claude_servers(root: Path) -> dict:
    return json.loads((root / ".mcp.json").read_text())["mcpServers"]


def _codex_servers(root: Path) -> dict:
    return tomllib.loads((root / ".codex" / "config.toml").read_text())["mcp_servers"]


def test_baked_install_falls_back_to_the_bare_wikitoolkit_command(root: Path) -> None:
    """Precondition of the ambiguity: the baked wikitoolkit entry IS the bare command on both hosts."""
    _install_claude(root, False)
    _install_codex(root, False)
    assert _claude_servers(root)["wikitoolkit"]["command"] == "wikitoolkit"
    assert _codex_servers(root)["wikitoolkit"]["command"] == "wikitoolkit"
    assert _claude_servers(root)["parrot-memory"]["args"][-1] != claude_assets.PORTABLE_TOOLKIT_CONFIG
    assert _codex_servers(root)["parrot-memory"]["args"][-1] != codex_assets.PORTABLE_TOOLKIT_CONFIG


@pytest.mark.parametrize(
    "first, expected",
    [
        (False, False),  # bare wikitoolkit + baked parrot-* → baked (the R4 regression on Claude)
        (True, True),  # bare wikitoolkit + portable parrot-* → portable
    ],
)
def test_bare_wikitoolkit_tie_broken_by_toolkit_entries(root: Path, first: bool, expected: bool) -> None:
    _install_claude(root, first)
    _install_codex(root, first)
    assert claude._current_portable_mode(root) is expected
    assert codex._current_portable_mode(root) is expected


def test_plain_reinstall_keeps_a_baked_install_baked(root: Path) -> None:
    """Re-running install without --portable on a bare+baked install must not migrate it to portable."""
    _install_claude(root, False)
    _install_codex(root, False)
    _install_claude(root, None)
    _install_codex(root, None)
    assert "cwd" in _claude_servers(root)["parrot-memory"]
    assert _claude_servers(root)["parrot-memory"]["args"][-1] != claude_assets.PORTABLE_TOOLKIT_CONFIG
    assert _codex_servers(root)["parrot-memory"]["args"][-1] != codex_assets.PORTABLE_TOOLKIT_CONFIG


def test_explicit_portable_migrates_a_baked_install(root: Path) -> None:
    """--portable on a baked install migrates every managed entry, on both hosts."""
    _install_claude(root, False)
    _install_codex(root, False)
    _install_claude(root, True)
    _install_codex(root, True)
    assert claude._current_portable_mode(root) is True and codex._current_portable_mode(root) is True
    assert "cwd" not in _claude_servers(root)["parrot-memory"]
    assert _claude_servers(root)["parrot-memory"]["args"][-1] == claude_assets.PORTABLE_TOOLKIT_CONFIG
    assert _codex_servers(root)["parrot-memory"]["args"][-1] == codex_assets.PORTABLE_TOOLKIT_CONFIG


def test_bare_wikitoolkit_without_toolkit_entries_is_portable(root: Path) -> None:
    (root / ".parrot" / "mcp-toolkits.yaml").write_text("toolkits: {}\n")
    _install_claude(root, True)
    _install_codex(root, True)
    assert claude._current_portable_mode(root) is True
    assert codex._current_portable_mode(root) is True


def test_mixed_toolkit_entries_are_portable(root: Path) -> None:
    """Sticky: ANY portable managed parrot-* entry keeps the install portable."""
    _install_claude(root, True)
    servers = _claude_servers(root)
    baked = dict(servers["parrot-memory"])
    baked["args"] = [*baked["args"][:3], str(root / ".parrot" / "mcp-toolkits.yaml")]
    baked["cwd"] = str(root)
    servers["parrot-other"] = {**baked, "args": ["mcp-local", "other", *baked["args"][2:]]}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": servers}))
    assert claude._current_portable_mode(root) is True


def test_no_config_is_baked(root: Path) -> None:
    assert claude._current_portable_mode(root) is False
    assert codex._current_portable_mode(root) is False
