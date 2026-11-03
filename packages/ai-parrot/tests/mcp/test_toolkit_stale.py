"""FEAT-795 M6 — stale `parrot-<name>` MCP toolkit entries."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from parrot.mcp.toolkit_seed import seed_toolkit_sections, set_section_enabled
from parrot.mcp.toolkit_stale import find_stale_mcp_entries, is_parrot_toolkit_entry


def _entry(name: str, config: str) -> dict[str, object]:
    return {"command": "/venv/bin/parrot", "args": ["mcp-local", name, "--config", config]}


def _write_servers(path: Path, servers: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Return a repo with browsing enabled and scraping disabled."""
    root = tmp_path / "repo"
    root.mkdir()
    seed_toolkit_sections(root, ["browsing", "scraping"])
    set_section_enabled(root, "scraping", False)
    return root


@pytest.fixture
def gemini(tmp_path: Path) -> Path:
    """Return an isolated global Gemini MCP config."""
    path = tmp_path / "gemini_home" / "mcp_config.json"
    _write_servers(path, {})
    return path


def test_shape_test() -> None:
    assert not is_parrot_toolkit_entry("wikitoolkit", {"command": "wikitoolkit", "args": ["mcp"]})
    assert not is_parrot_toolkit_entry("bookstore", {"command": "bookstore", "args": ["mcp"]})
    assert not is_parrot_toolkit_entry("parrot-x", {"command": "python", "args": ["mcp-local", "x"]})
    assert not is_parrot_toolkit_entry("parrot-x", {"command": "parrot", "args": ["mcp-local", "y"]})
    assert is_parrot_toolkit_entry("parrot-x", {"command": r"C:\venv\parrot.exe", "args": ["mcp-local", "x"]})


def test_undeclared_entry_in_mcp_json(repo: Path, gemini: Path) -> None:
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(
        repo / ".mcp.json",
        {"parrot-scraping": _entry("scraping", config), "parrot-browsing": _entry("browsing", config)},
    )

    found = find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [("parrot-scraping", "undeclared")]


def test_retired_toolkit_any_file(repo: Path, gemini: Path) -> None:
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(repo / ".mcp.json", {"parrot-oldkit": _entry("oldkit", config)})
    _write_servers(gemini, {"parrot-oldkit": _entry("oldkit", config)})

    found = find_stale_mcp_entries(repo, ("claude", "google"), gemini_config=gemini)

    assert [(entry.file, entry.reason) for entry in found] == [
        (".mcp.json", "retired-toolkit"),
        (str(gemini), "retired-toolkit"),
    ]


def test_foreign_repo_pinned_config(repo: Path, gemini: Path, tmp_path: Path) -> None:
    foreign_config = tmp_path / "other" / "repo" / ".parrot" / "mcp-toolkits.yaml"
    _write_servers(repo / ".mcp.json", {"parrot-browsing": _entry("browsing", str(foreign_config))})

    found = find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [("parrot-browsing", "foreign-repo")]


def test_global_portable_entry_not_undeclared(repo: Path, gemini: Path) -> None:
    _write_servers(gemini, {"parrot-scraping": _entry("scraping", ".parrot/mcp-toolkits.yaml")})

    assert find_stale_mcp_entries(repo, ("google",), gemini_config=gemini) == []


def test_global_missing_repo(repo: Path, gemini: Path, tmp_path: Path) -> None:
    config = tmp_path / "gone" / ".parrot" / "mcp-toolkits.yaml"
    _write_servers(gemini, {"parrot-browsing": _entry("browsing", str(config))})

    found = find_stale_mcp_entries(repo, ("google",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [("parrot-browsing", "missing-repo")]


def test_codex_tables_inside_and_outside_block(repo: Path, gemini: Path) -> None:
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        """
# arbitrary operator table outside the managed block
[mcp_servers.parrot-scraping]
command = "parrot"
args = ["mcp-local", "scraping", "--config", ".parrot/mcp-toolkits.yaml"]

# BEGIN PARROT MANAGED MCP SERVERS
[mcp_servers.parrot-lsp]
command = "/venv/bin/parrot"
args = ["mcp-local", "lsp", "--config", ".parrot/mcp-toolkits.yaml"]
[mcp_servers.wikitoolkit]
command = "wikitoolkit"
args = ["mcp"]
# END PARROT MANAGED MCP SERVERS
""".lstrip(),
        encoding="utf-8",
    )

    found = find_stale_mcp_entries(repo, ("codex",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [
        ("parrot-lsp", "undeclared"),
        ("parrot-scraping", "undeclared"),
    ]


def test_unparsable_file_skipped(repo: Path, gemini: Path, caplog: pytest.LogCaptureFixture) -> None:
    (repo / ".mcp.json").write_text("{nope", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="parrot.mcp.toolkit_stale"):
        found = find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert found == []
    assert "cannot parse MCP config" in caplog.text


def test_host_filter(repo: Path, gemini: Path, caplog: pytest.LogCaptureFixture) -> None:
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(repo / ".mcp.json", {"parrot-oldkit": _entry("oldkit", config)})
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text("[broken", encoding="utf-8")
    gemini.write_text("{broken", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="parrot.mcp.toolkit_stale"):
        found = find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert [entry.key for entry in found] == ["parrot-oldkit"]
    assert "cannot parse MCP config" not in caplog.text


def test_unknown_host_raises(repo: Path, gemini: Path) -> None:
    with pytest.raises(ValueError, match=r"unknown host\(s\): vscode"):
        find_stale_mcp_entries(repo, ("vscode",), gemini_config=gemini)
