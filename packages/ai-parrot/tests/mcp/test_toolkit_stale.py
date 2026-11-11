"""FEAT-795 M6 — stale `parrot-<name>` MCP toolkit entries."""

from __future__ import annotations

import json
import logging
import tomllib
from pathlib import Path

import pytest

from parrot.mcp.toolkit_seed import seed_toolkit_sections, set_section_enabled
from parrot.mcp.toolkit_stale import (
    StaleMcpEntry,
    find_stale_mcp_entries,
    is_parrot_toolkit_entry,
    remove_stale_mcp_entries,
)

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


def test_remove_mcp_json_keeps_others(repo: Path, gemini: Path, tmp_path: Path) -> None:
    """Remove a stale JSON toolkit entry without changing unrelated servers."""
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    foreign = str(tmp_path / "foreign" / ".parrot" / "mcp-toolkits.yaml")
    servers = {
        "wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]},
        "bookstore": {"command": "bookstore", "args": ["mcp"]},
        "parrot-x": {"command": "python", "args": ["mcp-local", "x"]},
        "parrot-scraping": _entry("scraping", config),
        "parrot-browsing": _entry("browsing", foreign),
    }
    _write_servers(repo / ".mcp.json", servers)

    lines = remove_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)
    remaining = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]

    assert set(remaining) == {"wikitoolkit", "bookstore", "parrot-x"}
    assert {key: remaining[key] for key in remaining} == {key: servers[key] for key in remaining}
    assert ".mcp.json#parrot-scraping — removed (undeclared)" in lines
    assert ".mcp.json#parrot-browsing — removed (foreign-repo)" in lines


def test_codex_tables_removed_inside_and_outside_block(repo: Path, gemini: Path) -> None:
    """Remove stale Codex tables wherever they are while retaining valid TOML."""
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    wikitoolkit = '[mcp_servers.wikitoolkit]\ncommand = "wikitoolkit"\nargs = ["mcp"]\n'
    config.write_text(
        "\n".join(
            (
                '[mcp_servers.parrot-scraping]\ncommand = "parrot"\nargs = ["mcp-local", "scraping"]\n',
                "# >>> parrot-wiki Codex MCP >>>",
                '[mcp_servers.parrot-lsp]\ncommand = "parrot"\nargs = ["mcp-local", "lsp"]\n',
                wikitoolkit,
                "# <<< parrot-wiki Codex MCP >>>",
            )
        ),
        encoding="utf-8",
    )

    remove_stale_mcp_entries(repo, ("codex",), gemini_config=gemini)
    result = config.read_text(encoding="utf-8")

    assert "parrot-scraping" not in result
    assert "parrot-lsp" not in result
    assert wikitoolkit in result
    assert tomllib.loads(result)["mcp_servers"] == {"wikitoolkit": {"command": "wikitoolkit", "args": ["mcp"]}}


def test_codex_emptied_block_removed(repo: Path, gemini: Path) -> None:
    """Remove a Codex managed block when its final server table is stale."""
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        "# >>> parrot-wiki Codex MCP >>>\n"
        '[mcp_servers.parrot-scraping]\ncommand = "parrot"\nargs = ["mcp-local", "scraping"]\n'
        "# <<< parrot-wiki Codex MCP >>>\n",
        encoding="utf-8",
    )

    remove_stale_mcp_entries(repo, ("codex",), gemini_config=gemini)

    assert "parrot-wiki Codex MCP" not in config.read_text(encoding="utf-8")


def test_claude_approvals_dropped(repo: Path, gemini: Path) -> None:
    """Remove only approvals associated with removed Claude toolkit servers."""
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(repo / ".mcp.json", {"parrot-scraping": _entry("scraping", config)})
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps({"enabledMcpjsonServers": ["wikitoolkit", "parrot-scraping", "bookstore"]}), encoding="utf-8"
    )

    lines = remove_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert json.loads(settings.read_text(encoding="utf-8"))["enabledMcpjsonServers"] == ["wikitoolkit", "bookstore"]
    assert ".claude/settings.local.json — 1 MCP server approval(s) removed" in lines


def test_keep_matches_file_key(repo: Path, gemini: Path) -> None:
    """Retain a stale entry selected by its displayed file and key."""
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    path = repo / ".mcp.json"
    _write_servers(path, {"parrot-scraping": _entry("scraping", config)})
    before = path.read_bytes()

    lines = remove_stale_mcp_entries(repo, ("claude",), keep=[".mcp.json#parrot-scraping"], gemini_config=gemini)

    assert path.read_bytes() == before
    assert lines == [".mcp.json#parrot-scraping — kept (--keep)"]


def test_unparsable_file_untouched(repo: Path, gemini: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave a file untouched if it becomes invalid after stale detection."""
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text("[broken", encoding="utf-8")
    before = config.read_bytes()
    entry = StaleMcpEntry(
        host="codex", file=".codex/config.toml", key="parrot-scraping", reason="undeclared", detail="test"
    )
    monkeypatch.setattr("parrot.mcp.toolkit_stale.find_stale_mcp_entries", lambda *args, **kwargs: [entry])

    lines = remove_stale_mcp_entries(repo, ("codex",), gemini_config=gemini)

    assert config.read_bytes() == before
    assert len(lines) == 1
    assert lines[0].startswith("warning: .codex/config.toml — not changed (")


def test_reregister_note(repo: Path, gemini: Path, tmp_path: Path) -> None:
    """Advise re-registration when an enabled toolkit loses a foreign entry."""
    foreign = tmp_path / "foreign" / ".parrot" / "mcp-toolkits.yaml"
    _write_servers(repo / ".mcp.json", {"parrot-browsing": _entry("browsing", str(foreign))})

    lines = remove_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert lines.count("note: re-register with `parrot toolkits install browsing`") == 1


def test_dry_run_mcp_writes_nothing(repo: Path, gemini: Path) -> None:
    """Plan stale cleanup without writing any selected host configuration file."""
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    claude = repo / ".mcp.json"
    codex = repo / ".codex" / "config.toml"
    plugin = repo / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    _write_servers(claude, {"parrot-scraping": _entry("scraping", config)})
    codex.parent.mkdir()
    codex.write_text('[mcp_servers.parrot-scraping]\ncommand = "parrot"\nargs = ["mcp-local", "scraping"]\n')
    _write_servers(plugin, {"parrot-scraping": _entry("scraping", config)})
    before = {path: path.read_bytes() for path in (claude, codex, plugin, gemini)}

    lines = remove_stale_mcp_entries(repo, ("claude", "codex", "google"), dry_run=True, gemini_config=gemini)

    assert all(line.startswith("plan:") for line in lines)
    assert {path: path.read_bytes() for path in before} == before


def test_nothing_stale(repo: Path, gemini: Path) -> None:
    """Report an empty result when no selected host has stale toolkit entries."""
    assert remove_stale_mcp_entries(repo, ("claude", "codex", "google"), gemini_config=gemini) == [
        "no stale MCP entries"
    ]


def test_codex_quoted_table_removed(repo: Path, gemini: Path) -> None:
    """A quoted `[mcp_servers."parrot-x"]` table and its sub-tables are removed, not just reported."""
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    wikitoolkit = '[mcp_servers.wikitoolkit]\ncommand = "wikitoolkit"\n'
    config.write_text(
        '[mcp_servers."parrot-scraping"]\ncommand = "parrot"\nargs = ["mcp-local", "scraping"]\n\n'
        '[mcp_servers."parrot-scraping".env]\nX = "1"\n\n' + wikitoolkit,
        encoding="utf-8",
    )

    lines = remove_stale_mcp_entries(repo, ("codex",), gemini_config=gemini)

    assert tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"] == {
        "wikitoolkit": {"command": "wikitoolkit"}
    }
    assert any("parrot-scraping" in line for line in lines)


def test_codex_unremovable_layout_reported_not_claimed(repo: Path, gemini: Path) -> None:
    """An entry in a layout the remover cannot cut (inline in `[mcp_servers]`) is warned about, file untouched."""
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    original = '[mcp_servers]\nparrot-scraping = { command = "parrot", args = ["mcp-local", "scraping"] }\n'
    config.write_text(original, encoding="utf-8")

    lines = remove_stale_mcp_entries(repo, ("codex",), gemini_config=gemini)

    assert config.read_text(encoding="utf-8") == original
    assert any(line.startswith("warning:") and "not changed" in line for line in lines)


_AGENT_SECTION = (
    "  agent-finance:\n"
    "    class: parrot.mcp.agent_toolkit.AgentToolkit\n"
    "    kwargs:\n"
    "      agent: finance\n"
    "    env: {}\n"
)


def _add_agent_section(root: Path) -> None:
    """Append an agent section the way seed_agent_sections lays it out."""
    path = root / ".parrot" / "mcp-toolkits.yaml"
    path.write_text(path.read_text(encoding="utf-8") + _AGENT_SECTION, encoding="utf-8")


def test_agent_section_not_retired(repo: Path, gemini: Path) -> None:
    _add_agent_section(repo)
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(repo / ".mcp.json", {"parrot-agent-finance": _entry("agent-finance", config)})

    assert find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini) == []


def test_unreadable_config_keeps_agent_entries(repo: Path, gemini: Path) -> None:
    (repo / ".parrot" / "mcp-toolkits.yaml").write_text("toolkits: [", encoding="utf-8")
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(
        repo / ".mcp.json",
        {
            "parrot-agent-finance": _entry("agent-finance", config),
            "parrot-oldkit": _entry("oldkit", config),
        },
    )

    found = find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [("parrot-oldkit", "retired-toolkit")]


def test_removed_agent_section_is_retired(repo: Path, gemini: Path) -> None:
    config = str(repo / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(repo / ".mcp.json", {"parrot-agent-finance": _entry("agent-finance", config)})

    found = find_stale_mcp_entries(repo, ("claude",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [("parrot-agent-finance", "retired-toolkit")]


def test_global_agent_entry_from_other_repo_not_retired(repo: Path, gemini: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / ".parrot").mkdir(parents=True)
    other_config = str(other / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(gemini, {"parrot-agent-hr": _entry("agent-hr", other_config)})

    assert find_stale_mcp_entries(repo, ("google",), gemini_config=gemini) == []

    deleted_config = str(tmp_path / "deleted" / ".parrot" / "mcp-toolkits.yaml")
    _write_servers(gemini, {"parrot-agent-hr": _entry("agent-hr", deleted_config)})
    found = find_stale_mcp_entries(repo, ("google",), gemini_config=gemini)

    assert [(entry.key, entry.reason) for entry in found] == [("parrot-agent-hr", "missing-repo")]
