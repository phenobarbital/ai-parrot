"""FEAT-633 TASK-4083 — Codex: Windows script paths + portable emission + stickiness."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterator

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.codex import assets, bookstore
from parrot.knowledge.wiki.codex.installer import install_codex_integration, reconcile_toolkit_tables
from parrot.knowledge.wiki.project import WikiRemoteConfig  # [rev 0.5] C24 / D7
from parrot.mcp.local_cli import mcp_local


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("wikitoolkit", "parrot"):
        (venv_bin / name).write_text("")
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  memory:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n"
    )
    return tmp_path


def _servers(root: Path) -> dict:
    return tomllib.loads((root / ".codex" / "config.toml").read_text())["mcp_servers"]


def test_portable_entries_no_abs_paths(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    for text in _strings(_servers(root)):
        assert not os.path.isabs(text) and str(root) not in text, text
    block = tomllib.loads(bookstore.mcp_block(root, portable=True).split("\n", 1)[1])
    assert block["mcp_servers"]["bookstore"]["command"] == "bookstore"
    assert "cwd" not in block["mcp_servers"]["bookstore"] and sys.executable not in str(block)
    assert str(root) not in (root / assets.RULES_PATH).read_text()


def test_default_emission_unchanged(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False)
    servers = _servers(root)
    assert servers["wikitoolkit"]["command"] == str(root / ".venv" / "bin" / "wikitoolkit")
    assert servers["parrot-memory"]["args"][-1] == str(root / ".parrot" / "mcp-toolkits.yaml")


def test_portable_transitions_both_ways(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    assert _servers(root)["wikitoolkit"]["command"] == "wikitoolkit"
    install_codex_integration(root, gitignore=False, bookstore=False, portable=False)
    assert _servers(root)["wikitoolkit"]["command"] == str(root / ".venv" / "bin" / "wikitoolkit")


def test_reconcile_sticky(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    install_codex_integration(root, gitignore=False, bookstore=False)  # flag absent → keep portable
    assert _servers(root)["wikitoolkit"]["command"] == "wikitoolkit"
    with (root / ".parrot" / "mcp-toolkits.yaml").open("a") as fh:  # a toolkit added later by `parrot toolkits`
        fh.write("  scraping:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n")
    reconcile_toolkit_tables(root)  # the `parrot toolkits` path (mcp/hosts.py::CodexAdapter.reconcile)
    assert _servers(root)["parrot-scraping"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_remote_portable_sticky(root: Path) -> None:
    """Spec rev 0.5 C24: --remote decides only the wikitoolkit table; the mode comes from the parrot-* tables."""
    remote = WikiRemoteConfig(url="https://h/mcp/w", token_env="WT")
    install_codex_integration(root, gitignore=False, bookstore=False, remote=remote, portable=True)
    assert "url" in _servers(root)["wikitoolkit"] and "command" not in _servers(root)["wikitoolkit"]
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    install_codex_integration(root, gitignore=False, bookstore=False, remote=remote)  # flag absent → keep portable
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    assert str(root) not in (root / assets.RULES_PATH).read_text()
    with (root / ".parrot" / "mcp-toolkits.yaml").open("a") as fh:  # a toolkit added later by `parrot toolkits`
        fh.write("  scraping:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n")
    reconcile_toolkit_tables(root)  # the mcp/hosts.py::CodexAdapter.reconcile path
    assert _servers(root)["parrot-scraping"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_mcp_local_parrot_project_root(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec rev 0.5 C24 (local_cli.py in scope): `parrot mcp-local` takes its root from PARROT_PROJECT."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PARROT_PROJECT", str(root))
    result = CliRunner().invoke(mcp_local, ["--list"])
    assert result.exit_code == 0, result.output
    assert "memory" in result.output
    monkeypatch.delenv("PARROT_PROJECT")
    assert "memory" not in CliRunner().invoke(mcp_local, ["--list"]).output  # falls back to Path.cwd()


def test_mcp_local_relative_config_resolves_against_root(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative explicit ``--config`` resolves against the PARROT_PROJECT root, not the process cwd."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PARROT_PROJECT", str(root))
    result = CliRunner().invoke(mcp_local, ["--config", ".parrot/mcp-toolkits.yaml", "--list"])
    assert result.exit_code == 0, result.output
    assert "memory" in result.output


def test_remote_does_not_reset_portable_mode(root: Path) -> None:
    """[rev 0.5] D7: --remote decides only the wikitoolkit table; the mode comes from the parrot-* tables."""
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    remote = WikiRemoteConfig(url="https://h/mcp/w", token_env="WT")
    install_codex_integration(root, gitignore=False, bookstore=False, remote=remote)  # flag absent
    assert _servers(root)["wikitoolkit"]["url"] == "https://h/mcp/w"
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    assert str(root) not in (root / assets.RULES_PATH).read_text()
    reconcile_toolkit_tables(root)
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_portable_root_independent(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert assets.mcp_block(a, portable=True) == assets.mcp_block(b, portable=True)
    assert bookstore.mcp_block(a, portable=True) == bookstore.mcp_block(b, portable=True)


def test_windows_scripts_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets, "script_path", lambda venv, name: venv / "Scripts" / f"{name}.exe")
    exe = tmp_path / ".venv" / "Scripts" / "parrot.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert assets.resolve_binary(tmp_path, "parrot") == str(exe)
