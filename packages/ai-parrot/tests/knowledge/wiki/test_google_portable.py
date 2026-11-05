"""FEAT-633 TASK-4084 — Google/Gemini: portable emission for the USER-GLOBAL config."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import click
import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.bookstore import _is_managed_bookstore_entry
from parrot.knowledge.wiki.google.cli import google
from parrot.knowledge.wiki.google.installer import (
    _current_portable_mode,
    _is_managed_toolkit_entry,
    _is_managed_wikitoolkit_entry,
    install_google_integration,
    portable_mode_of_config,
    reconcile_toolkit_entries,
)
from parrot.knowledge.wiki.project import WikiProjectConfig, config_path, save_project_config
from parrot.mcp import portability

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


def test_default_emission_unchanged(tmp_path: Path, global_cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no managed launcher on PATH a fresh install keeps today's baked emission."""
    monkeypatch.setattr(portability, "managed_launcher_on_path", lambda *_a, **_k: False)
    root = _make_root(tmp_path / "repo")
    _install(root, global_cfg, None)
    servers = json.loads(global_cfg.read_text())["mcpServers"]
    assert servers["wikitoolkit"] == {
        "command": str(root / ".venv" / "bin" / "wikitoolkit"),
        "args": ["mcp"],
        "cwd": str(root.resolve()),
    }
    # The USER-GLOBAL file is shared across repositories: toolkit entries are portable even by default
    # (relative --config, no cwd); only the command is baked when no managed launcher is on PATH.
    assert servers["parrot-stub"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG and "cwd" not in servers["parrot-stub"]
    local = json.loads((root / assets.PLUGIN_DIR / "mcp_config.json").read_text())["mcpServers"]
    assert local["parrot-stub"]["cwd"] == str(root.resolve())


def test_global_toolkit_entry_pinned_to_another_repo_is_replaced(tmp_path: Path, global_cfg: Path) -> None:
    """A parrot-shaped global entry pinned to another repository is upgraded to the shared portable form."""
    other = tmp_path / "other"
    root = _make_root(tmp_path / "repo")
    global_cfg.parent.mkdir(parents=True, exist_ok=True)
    global_cfg.write_text(json.dumps({"mcpServers": {"parrot-stub": {
        "command": str(other / ".venv" / "bin" / "parrot"),
        "args": ["mcp-local", "stub", "--config", str(other / ".parrot" / "mcp-toolkits.yaml")],
        "cwd": str(other),
    }}}))
    _actions, warnings = reconcile_toolkit_entries(root, global_cfg, portable=False)
    assert warnings == []
    entry = json.loads(global_cfg.read_text())["mcpServers"]["parrot-stub"]
    assert entry["args"] == ["mcp-local", "stub", "--config", assets.PORTABLE_TOOLKIT_CONFIG] and "cwd" not in entry


def test_global_portable_entry_survives_disable_in_one_repo(tmp_path: Path, global_cfg: Path) -> None:
    """Another repository may still use a shared global entry: disabling it here only cleans the repo-local file."""
    root = _make_root(tmp_path / "repo")
    reconcile_toolkit_entries(root, global_cfg, portable=False)
    (root / ".parrot" / "mcp-toolkits.yaml").write_text("toolkits: {}\n")
    reconcile_toolkit_entries(root, global_cfg, portable=False)
    assert "parrot-stub" in json.loads(global_cfg.read_text())["mcpServers"]
    local = json.loads((root / assets.PLUGIN_DIR / "mcp_config.json").read_text())["mcpServers"]
    assert "parrot-stub" not in local


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


# --- FEAT-804 M2 (launcher rule, tri-state) and M4 (install root, shared wiki state) ---------------------------


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, global_cfg: Path) -> dict[str, Path]:
    """HOME, PARROT_HOME and PATH confined to tmp_path; no managed launcher on PATH by default."""
    home = tmp_path / "home"
    home.mkdir()
    parrot_home = tmp_path / "parrot-home"
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PARROT_HOME", str(parrot_home))
    monkeypatch.setenv("PATH", str(empty_bin))
    return {"home": home, "parrot_home": parrot_home, "global_cfg": global_cfg}


def _put_managed_launcher_on_path(env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a fake ``$PARROT_HOME/bin/parrot`` and put it on PATH (managed_launcher_on_path → True)."""
    bin_dir = env["parrot_home"] / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "parrot"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return script


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A primary checkout ``main`` and a linked worktree ``wt`` whose gitdir carries a commondir."""
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n")
    return main.resolve(), wt.resolve()


def _primary_config(main: Path) -> bytes:
    """Write a non-default wiki config on the primary checkout and return its bytes."""
    save_project_config(main, WikiProjectConfig(wiki_name="primary-wiki", backend="sqlite"))
    return config_path(main).read_bytes()


def _snapshot(base: Path) -> dict[str, bytes]:
    """Every regular file under ``base`` with its content."""
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def _no_abs_paths(value: Any, root: Path) -> None:
    for text in _strings(value):
        assert not os.path.isabs(text) and str(root) not in text, text


def test_current_portable_mode_tri_state(tmp_path: Path, isolated_env: dict[str, Path]) -> None:
    """No file / only a foreign entry → None; baked managed entry → False; portable managed entry → True."""
    cfg = isolated_env["global_cfg"]
    root = _make_root(tmp_path / "repo")
    assert _current_portable_mode(root, cfg) is None
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "node", "args": ["wiki.js"]}}}))
    assert _current_portable_mode(root, cfg) is None
    _install(root, cfg, False)
    assert _current_portable_mode(root, cfg) is False
    _install(root, cfg, True)
    assert _current_portable_mode(root, cfg) is True


def test_portable_mode_of_config_reads_one_file(tmp_path: Path, isolated_env: dict[str, Path]) -> None:
    """Each config reports its OWN form — the single-file helper never falls back to the other file."""
    cfg = isolated_env["global_cfg"]
    root = _make_root(tmp_path / "repo")
    local = root / assets.PLUGIN_DIR / "mcp_config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    local.parent.mkdir(parents=True, exist_ok=True)

    assert portable_mode_of_config(cfg, root) is None  # missing
    cfg.write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "node", "args": ["wiki.js"]}}}))
    assert portable_mode_of_config(cfg, root) is None  # foreign entry
    cfg.write_text("{", encoding="utf-8")
    assert portable_mode_of_config(cfg, root) is None  # malformed

    cfg.write_text(json.dumps({"mcpServers": {"wikitoolkit": assets.wikitoolkit_mcp_entry(root, portable=True)}}))
    local.write_text(json.dumps({"mcpServers": {"wikitoolkit": assets.wikitoolkit_mcp_entry(root, portable=False)}}))
    assert portable_mode_of_config(cfg, root) is True
    assert portable_mode_of_config(local, root) is False
    # The chaining inference still answers with the repo-local file, which is why a caller that
    # wants one file's own form must use the single-file helper instead of a sacrificial ``root``.
    assert _current_portable_mode(root, cfg) is False


def test_fresh_install_with_managed_launcher_is_portable(
    tmp_path: Path, isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: launcher on PATH, no host config, no flag → portable entries everywhere and no baked note."""
    _put_managed_launcher_on_path(isolated_env, monkeypatch)
    cfg = isolated_env["global_cfg"]
    root = _make_root(tmp_path / "repo")
    actions = install_google_integration(root, gitignore=False, bookstore=False, mcp_config_path=cfg)
    assert not any(a.startswith("note: host config baked") for a in actions)
    servers = json.loads(cfg.read_text())["mcpServers"]
    assert servers["wikitoolkit"] == {"command": "wikitoolkit", "args": ["mcp"]}
    _no_abs_paths(servers, root)
    local = json.loads((root / assets.PLUGIN_DIR / "mcp_config.json").read_text())["mcpServers"]
    assert all("cwd" not in entry for entry in local.values())
    _no_abs_paths(local, root)


def test_fresh_install_without_launcher_is_baked_with_one_note(tmp_path: Path, isolated_env: dict[str, Path]) -> None:
    """AC4: no launcher, no host config → baked form and exactly one note naming the fix."""
    cfg = isolated_env["global_cfg"]
    root = _make_root(tmp_path / "repo")
    actions = install_google_integration(root, gitignore=False, bookstore=False, mcp_config_path=cfg)
    notes = [a for a in actions if a.startswith("note: host config baked to absolute paths")]
    assert notes == [portability.BAKED_NOTE_TEMPLATE.format(prefix=sys.prefix)]
    assert "--portable" in notes[0]
    assert json.loads(cfg.read_text())["mcpServers"]["wikitoolkit"]["cwd"] == str(root.resolve())


def test_reconcile_fresh_repo_reports_the_note_once(tmp_path: Path, isolated_env: dict[str, Path]) -> None:
    """The GoogleAdapter path (portable=None) on a fresh repo with no launcher surfaces the note exactly once."""
    root = _make_root(tmp_path / "repo")
    actions, _warnings = reconcile_toolkit_entries(root, isolated_env["global_cfg"])
    assert sum(a.startswith("note: host config baked") for a in actions) == 1
    local = json.loads((root / assets.PLUGIN_DIR / "mcp_config.json").read_text())["mcpServers"]
    assert local["parrot-stub"]["cwd"] == str(root.resolve())


def test_sticky_modes_and_explicit_migrations_with_launcher(
    tmp_path: Path, isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC5: a baked install stays baked even with the launcher on PATH; --portable / --no-portable migrate."""
    cfg = isolated_env["global_cfg"]
    root = _make_root(tmp_path / "repo")
    _install(root, cfg, False)
    _put_managed_launcher_on_path(isolated_env, monkeypatch)
    actions = install_google_integration(root, gitignore=False, bookstore=False, mcp_config_path=cfg)
    assert not any(a.startswith("note:") for a in actions)
    assert "cwd" in json.loads(cfg.read_text())["mcpServers"]["wikitoolkit"]
    _install(root, cfg, True)
    _install(root, cfg, None)
    assert json.loads(cfg.read_text())["mcpServers"]["wikitoolkit"] == {"command": "wikitoolkit", "args": ["mcp"]}
    _install(root, cfg, False)
    assert "cwd" in json.loads(cfg.read_text())["mcpServers"]["wikitoolkit"]


def test_host_install_keeps_wiki_config_on_primary_checkout(tmp_path: Path, isolated_env: dict[str, Path]) -> None:
    """AC8 (library): an install at a linked worktree keeps the primary wiki.json and writes none in the worktree."""
    main, wt = _linked_worktree(tmp_path)
    before = _primary_config(main)
    _make_root(wt)
    install_google_integration(wt, gitignore=False, bookstore=False, mcp_config_path=isolated_env["global_cfg"])
    assert config_path(main).read_bytes() == before
    assert not config_path(wt).exists()
    assert (wt / assets.GEMINI_PATH).exists() and not (main / assets.GEMINI_PATH).exists()


@pytest.fixture
def build_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``wikitoolkit build`` with a recorder so no provider build ever runs."""
    calls: list[str] = []

    @click.command()
    @click.option("--path", "path_", default=None)
    @click.option("--quiet", is_flag=True)
    def fake_build(path_: str | None, quiet: bool) -> None:
        calls.append(str(path_))

    monkeypatch.setattr("parrot.knowledge.wiki.cli.build", fake_build)
    return calls


def test_host_cli_refuses_linked_worktree(
    tmp_path: Path, isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch, build_calls: list[str]
) -> None:
    """AC7: implicit install/uninstall from a worktree exit 1 naming both paths and write nothing; status works."""
    main, wt = _linked_worktree(tmp_path)
    _primary_config(main)
    _make_root(wt)
    monkeypatch.chdir(wt)
    before = _snapshot(tmp_path)
    runner = CliRunner()
    for verb in (["install", "--no-bookstore", "--no-gitignore"], ["uninstall"]):
        result = runner.invoke(google, verb)
        assert result.exit_code == 1, result.output
        assert str(main) in result.output and str(wt) in result.output and "--path" in result.output
        assert _snapshot(tmp_path) == before
    assert build_calls == []
    status = runner.invoke(google, ["status"])
    assert status.exit_code == 0, status.output
    assert f"Repository: {wt}" in status.output


def test_host_cli_resolves_repository_root_from_subdirectory(
    tmp_path: Path, isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch, build_calls: list[str]
) -> None:
    """AC7: run from a subdirectory of a primary checkout, install targets the checkout root."""
    repo = _make_root(tmp_path / "repo").resolve()
    (repo / ".git").mkdir()
    sub = repo / "pkg" / "sub"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    result = CliRunner().invoke(google, ["install", "--no-bookstore", "--no-gitignore", "--no-build"])
    assert result.exit_code == 0, result.output
    assert (repo / assets.GEMINI_PATH).exists() and not (sub / assets.GEMINI_PATH).exists()
    assert config_path(repo).exists() and not config_path(sub).exists()
    assert build_calls == []


def test_host_cli_worktree_preserves_shared_config_and_build_root(
    tmp_path: Path, isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch, build_calls: list[str]
) -> None:
    """AC8 (CLI): --path <wt> keeps the primary wiki.json, builds the primary checkout, assets go to wt."""
    main, wt = _linked_worktree(tmp_path)
    before = _primary_config(main)
    _make_root(wt)
    monkeypatch.chdir(wt)
    runner = CliRunner()

    result = runner.invoke(google, ["install", "--path", str(wt), "--no-bookstore", "--no-gitignore", "--no-build"])
    assert result.exit_code == 0, result.output
    assert build_calls == []

    result = runner.invoke(google, ["install", "--path", str(wt), "--no-bookstore", "--no-gitignore"])
    assert result.exit_code == 0, result.output
    assert build_calls == [str(main)]

    assert config_path(main).read_bytes() == before
    assert json.loads(config_path(main).read_text())["wiki_name"] == "primary-wiki"
    assert not config_path(wt).exists()
    assert sorted(p.name for p in (wt / ".parrot").iterdir()) == ["mcp-toolkits.yaml"]
    assert (wt / assets.GEMINI_PATH).exists() and not (main / assets.GEMINI_PATH).exists()
    assert sum("note: host config baked" in line for line in result.output.splitlines()) <= 1

    status = runner.invoke(google, ["status", "--path", str(wt), "--json"])
    assert status.exit_code == 0, status.output
    info = json.loads(status.output)
    assert info["root"] == str(wt) and info["config"] is True
