"""FEAT-633 TASK-4082 — `parrot claude install --portable`: transitions, stickiness, reconcile."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki import cli as wiki_cli
from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.installer import (
    _is_managed_toolkit_entry,
    _is_our_command,
    _is_wikitoolkit_entry,  # [rev 0.5] D6
    install_claude_integration,
    reconcile_toolkit_entries,
)
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config  # [rev 0.5] D7
from parrot.mcp import portability


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Repo with a project venv so the baked form is distinguishable from the portable one."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".parrot").mkdir()
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("wikitoolkit", "parrot"):
        (venv_bin / name).write_text("")
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  bounded-source:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {}\n"
    )
    return tmp_path


def _servers(root: Path) -> dict:
    return json.loads((root / ".mcp.json").read_text())["mcpServers"]


def _install(root: Path, portable: bool | None, remote: WikiRemoteConfig | None = None) -> None:  # [rev 0.5] remote
    install_claude_integration(
        root, git_hook=False, gitignore=False, bookstore=False, portable=portable, remote=remote
    )


def test_default_install_unchanged(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh host without the managed launcher retains baked output and names the fallback once."""
    monkeypatch.setattr(portability, "managed_launcher_on_path", lambda: False)
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root)


def test_fresh_install_uses_managed_launcher(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh host emits portable entries when the managed launcher is on PATH."""
    monkeypatch.setattr(portability, "managed_launcher_on_path", lambda: True)
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)


def test_baked_fallback_note_is_emitted_once(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The integration boundary, rather than nested reconcilers, reports a baked fallback."""
    monkeypatch.setattr(portability, "managed_launcher_on_path", lambda: False)
    actions = install_claude_integration(repo_root, git_hook=False, gitignore=False, bookstore=False)
    assert sum(action.startswith("note: host config baked to absolute paths") for action in actions) == 1


def _linked_worktree(primary: Path) -> Path:
    """Create lightweight linked-worktree metadata that install_root classifies without Git commands."""
    primary.mkdir()
    (primary / ".git").mkdir()
    worktree = primary.parent / "worktree"
    worktree.mkdir()
    git_dir = primary / ".git" / "worktrees" / "worktree"
    git_dir.mkdir(parents=True)
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    (worktree / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    return worktree


def test_host_cli_worktree_preserves_shared_config_and_build_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit worktree installs write host assets locally but use the primary wiki configuration and build root."""
    primary = tmp_path / "primary"
    worktree = _linked_worktree(primary)
    config = WikiProjectConfig(
        wiki_name="primary-wiki",
        remote=WikiRemoteConfig(url="https://wiki.example/mcp", token_env="WIKITOOLKIT_TOKEN"),
    )
    save_project_config(primary, config)
    captured: list[Path] = []

    @click.command()
    @click.option("--path", "path_", required=True)
    @click.option("--quiet", is_flag=True)
    def fake_wiki_build(path_: str, quiet: bool) -> None:
        """Capture the wiki build root without running a provider build."""
        captured.append(Path(path_))

    monkeypatch.setattr(wiki_cli, "build", fake_wiki_build)
    result = CliRunner().invoke(
        claude,
        [
            "install",
            "--path",
            str(worktree),
            "--no-git-hook",
            "--no-gitignore",
            "--no-bookstore",
            "--no-compaction",
            "--no-welcome",
            "--remote",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == [primary]
    assert config.wiki_name == "primary-wiki"
    assert _servers(worktree)["wikitoolkit"]["url"] == "https://wiki.example/mcp"
    assert not (worktree / ".parrot" / "wiki.json").exists()
    assert (worktree / ".mcp.json").exists()

    captured.clear()
    no_build_result = CliRunner().invoke(
        claude,
        [
            "install",
            "--path",
            str(worktree),
            "--no-build",
            "--no-git-hook",
            "--no-gitignore",
            "--no-bookstore",
            "--no-compaction",
            "--no-welcome",
        ],
    )
    assert no_build_result.exit_code == 0, no_build_result.output
    assert captured == []


def test_host_cli_refuses_implicit_worktree_writes_but_allows_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Implicit linked-worktree writes fail before artifacts are created, while status remains read-only."""
    primary = tmp_path / "primary"
    worktree = _linked_worktree(primary)
    monkeypatch.chdir(worktree)
    runner = CliRunner()
    install_result = runner.invoke(claude, ["install", "--no-build", "--no-welcome"])
    assert install_result.exit_code == 1
    assert str(primary) in install_result.output
    assert "--path" in install_result.output
    assert not (worktree / ".mcp.json").exists()
    status_result = runner.invoke(claude, ["status"])
    assert status_result.exit_code == 0, status_result.output


def test_portable_transitions_both_ways(repo_root: Path) -> None:
    """Spec §4: default→portable and portable→default land exactly the requested form."""
    _install(repo_root, True)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
    assert _servers(repo_root)["parrot-bounded-source"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    _install(repo_root, False)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root)
    assert "cwd" in _servers(repo_root)["parrot-bounded-source"]
    _install(repo_root, True)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)


def test_reconcile_respects_portable(repo_root: Path) -> None:
    """Spec §4: a plain re-install and the `parrot toolkits` path keep a portable install portable."""
    _install(repo_root, True)
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
    # [rev 0.5] D7: a toolkit enabled later follows the existing portable parrot-* entries
    cfg = repo_root / ".parrot" / "mcp-toolkits.yaml"
    cfg.write_text(cfg.read_text() + "  reader:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {}\n")
    reconcile_toolkit_entries(repo_root)  # what mcp/hosts.py::ClaudeAdapter.reconcile calls
    assert "cwd" not in _servers(repo_root)["parrot-reader"]


def test_plain_reinstall_keeps_portable_wikitoolkit_without_toolkits(repo_root: Path) -> None:
    """[rev 0.5] spec §3 M5(c): with no parrot-* entry, the managed stdio wikitoolkit entry decides the mode and is kept."""
    (repo_root / ".parrot" / "mcp-toolkits.yaml").write_text("toolkits: {}\n")
    _install(repo_root, True)
    _install(repo_root, None)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)


def test_remote_does_not_reset_portable_mode(repo_root: Path) -> None:
    """[rev 0.5] D7: --remote decides only the wikitoolkit key; an http entry cannot decide, so the mode comes from the parrot-* entries."""
    _install(repo_root, True)
    _install(repo_root, None, remote=WikiRemoteConfig(url="https://h/mcp/w", token_env="WT"))
    assert _servers(repo_root)["wikitoolkit"]["type"] == "http"
    assert "cwd" not in _servers(repo_root)["parrot-bounded-source"]
    settings = (repo_root / ".claude" / "settings.json").read_text()
    assert assets.hook_command(repo_root, portable=True) in settings and str(repo_root) not in settings
    reconcile_toolkit_entries(repo_root)
    assert "cwd" not in _servers(repo_root)["parrot-bounded-source"]


def test_portable_install_no_abs_paths(repo_root: Path) -> None:
    _install(repo_root, True)
    text = (repo_root / ".mcp.json").read_text() + (repo_root / ".claude" / "settings.json").read_text()
    assert str(repo_root) not in text

    def _strings(node: object):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for key, value in node.items():
                yield from _strings(key)
                yield from _strings(value)
        elif isinstance(node, list):
            for item in node:
                yield from _strings(item)

    for name in (".mcp.json", ".claude/settings.json"):
        for value in _strings(json.loads((repo_root / name).read_text())):
            assert not os.path.isabs(value), f"{name}: absolute path {value!r}"


def test_foreign_toolkit_entry_untouched(repo_root: Path) -> None:
    foreign = {"command": "node", "args": ["server.js"]}
    (repo_root / ".mcp.json").write_text(json.dumps({"mcpServers": {"parrot-bounded-source": foreign}}))
    for mode in (True, False):
        _install(repo_root, mode)
        assert _servers(repo_root)["parrot-bounded-source"] == foreign


def test_windows_paths_detected(repo_root: Path) -> None:
    """codex S4: Windows script paths are recognised as ours."""
    win = {"command": "C:\\r\\.venv\\Scripts\\parrot.exe", "args": ["mcp-local", "x"]}
    assert _is_managed_toolkit_entry(win, repo_root, "x")
    assert _is_our_command("C:\\r\\.venv\\Scripts\\wikitoolkit.exe claude-hook")
    # spec rev 0.5 C24: _is_wikitoolkit_entry matches the script basename, `.exe` included
    assert _is_wikitoolkit_entry({"command": "C:\\r\\.venv\\Scripts\\wikitoolkit.exe", "args": ["mcp"]})


def test_remote_portable_sticky(repo_root: Path) -> None:
    """Spec rev 0.5 C24: --remote decides only the wikitoolkit key; the mode comes from the parrot-* entries."""
    remote = WikiRemoteConfig(url="https://h/mcp/w", token_env="WT")
    kwargs = {"git_hook": False, "gitignore": False, "bookstore": False, "remote": remote}
    install_claude_integration(repo_root, portable=True, **kwargs)
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry_remote(remote.url, remote.token_env)
    assert _servers(repo_root)["parrot-bounded-source"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    install_claude_integration(repo_root, **kwargs)  # flag absent → keep portable (http wikitoolkit entry)
    assert "cwd" not in _servers(repo_root)["parrot-bounded-source"]
    assert str(repo_root) not in (repo_root / ".claude" / "settings.json").read_text()
    with (repo_root / ".parrot" / "mcp-toolkits.yaml").open("a") as fh:  # a toolkit added later by `parrot toolkits`
        fh.write("  bounded-source-2:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {}\n")
    reconcile_toolkit_entries(repo_root)  # the mcp/hosts.py::ClaudeAdapter.reconcile path
    assert _servers(repo_root)["parrot-bounded-source-2"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_windows_wikitoolkit_entry_is_managed() -> None:
    """[rev 0.5] D6: basename match without .exe; a different basename stays foreign."""
    assert _is_wikitoolkit_entry({"command": "C:\\r\\.venv\\Scripts\\wikitoolkit.exe", "args": ["mcp"]})
    assert _is_wikitoolkit_entry({"command": "/r/.venv/bin/wikitoolkit", "args": ["mcp"]})
    assert not _is_wikitoolkit_entry({"command": "/r/bin/my-wikitoolkit", "args": ["mcp"]})


def test_cli_portable_flag(repo_root: Path) -> None:
    result = CliRunner().invoke(
        claude, ["install", "--path", str(repo_root), "--no-build", "--no-compaction", "--no-git-hook", "--portable"]
    )
    assert result.exit_code == 0, result.output
    assert _servers(repo_root)["wikitoolkit"] == assets.mcp_json_entry(repo_root, portable=True)
