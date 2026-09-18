"""HostAdapter contract over three asymmetric hosts (FEAT-570, TASK-3374)."""
from __future__ import annotations

import sys
from pathlib import Path

from parrot.mcp.hosts import HostKind, detect_hosts, get_adapter


def test_detect_hosts_empty_repo(tmp_path, monkeypatch):
    """A bare directory has no host configs, so nothing is detected.

    Google's primary config is user-global (`Path.home()`-relative), so this
    must redirect `Path.home()` under `tmp_path` — otherwise the result would
    depend on whatever `~/.gemini/config/mcp_config.json` happens to exist on
    the machine running the test (see `GoogleAdapter.__init__` docstring).
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert detect_hosts(tmp_path) == []


def test_detect_hosts_finds_claude_and_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("", encoding="utf-8")
    found = detect_hosts(tmp_path)
    assert HostKind.CLAUDE in found and HostKind.CODEX in found


def test_only_google_is_user_scoped():
    assert get_adapter(HostKind.CLAUDE).is_repo_scoped() is True
    assert get_adapter(HostKind.CODEX).is_repo_scoped() is True
    assert get_adapter(HostKind.GOOGLE).is_repo_scoped() is False


def test_detect_hosts_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    detect_hosts(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_google_config_paths_returns_two_others_one(tmp_path):
    """Google reads two config files (user-global + repo plugin); the others one."""
    assert len(get_adapter(HostKind.GOOGLE).config_paths(tmp_path)) == 2
    assert len(get_adapter(HostKind.CLAUDE).config_paths(tmp_path)) == 1
    assert len(get_adapter(HostKind.CODEX).config_paths(tmp_path)) == 1


def test_inspect_imports_no_toolkit(tmp_path, monkeypatch):
    """AC1 — inspection reads config files, never imports a toolkit class."""
    # Redirect Google's user-global config under `Path.home()` so this never
    # touches the real developer `~/.gemini` directory.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    before = set(sys.modules)
    for kind in HostKind:
        get_adapter(kind).inspect(tmp_path, ["demo"])
    new_modules = set(sys.modules) - before

    assert not any(name.startswith(("parrot_tools", "parrot.tools")) for name in new_modules)
