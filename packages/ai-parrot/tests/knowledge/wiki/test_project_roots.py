"""The project/shared root walks stop at the system temp directory (issue:1270bc83b087).

A stray ``/tmp/.git`` or ``/tmp/.parrot`` left by an unrelated process must never make
``find_project_root`` / ``find_shared_root`` resolve ``/tmp`` as the repo for every
``tmp_path``-based test (which, among other things, mounts the ledger overlay into
"plain" wiki MCP servers and creates ``/tmp/.parrot/ledger`` as a side effect).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    find_project_root,
    find_shared_root,
    load_effective_config,
    save_project_config,
)

@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake system temp dir with a stray ``.git`` and ``.parrot`` at its root."""
    root = tmp_path / "tmproot"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".parrot").mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(root))
    return root


def test_stray_git_at_temp_root_is_not_a_project_root(temp_root: Path) -> None:
    work = temp_root / "pytest-of-x" / "test_case0" / "sub"
    work.mkdir(parents=True)

    assert find_project_root(work) is None
    assert find_shared_root(work) is None


def test_stray_config_at_temp_root_is_not_a_project_root(temp_root: Path) -> None:
    save_project_config(temp_root, WikiProjectConfig(wiki_name="stray"))
    work = temp_root / "scratch"
    work.mkdir()

    assert find_project_root(work) is None


def test_project_below_temp_root_still_resolves(temp_root: Path) -> None:
    project = temp_root / "pytest-of-x" / "test_case0"
    (project / "sub").mkdir(parents=True)
    (project / ".git").mkdir()

    assert find_project_root(project / "sub") == project
    assert find_shared_root(project / "sub") == project


@pytest.mark.parametrize("host", ["claude", "codex", "google"])
def test_host_install_keeps_wiki_config_on_primary_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    """An explicit worktree install preserves its primary checkout's wiki discovery state."""
    primary = tmp_path / "primary"
    admin = primary / ".git" / "worktrees" / "portable"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    save_project_config(primary, WikiProjectConfig(wiki_name="primary-wiki", backend="sqlite"))

    if host == "claude":
        from parrot.knowledge.wiki.claude_code.installer import install_claude_integration

        install_claude_integration(worktree, git_hook=False, gitignore=False, bookstore=False)
    elif host == "codex":
        from parrot.knowledge.wiki.codex.installer import install_codex_integration

        install_codex_integration(worktree, gitignore=False, bookstore=False)
    else:
        from parrot.knowledge.wiki.google import assets
        from parrot.knowledge.wiki.google.installer import install_google_integration

        global_config = tmp_path / "home" / "mcp_config.json"
        monkeypatch.setattr(assets, "default_mcp_config_path", lambda: global_config)
        install_google_integration(worktree, gitignore=False, bookstore=False, mcp_config_path=global_config)

    assert find_project_root(primary / "nested") == primary
    assert load_effective_config(primary).config.wiki_name == "primary-wiki"
    assert not (worktree / ".parrot" / "wiki.json").exists()


def test_configured_project_below_temp_root_wins_over_git_fallback(temp_root: Path) -> None:
    project = temp_root / "scratch" / "repo"
    (project / "nested").mkdir(parents=True)
    (temp_root / "scratch" / ".git").mkdir()
    save_project_config(project, WikiProjectConfig(wiki_name="repo"))

    assert find_project_root(project / "nested") == project
    assert find_shared_root(project / "nested") == temp_root / "scratch"


def test_temp_root_itself_is_never_a_root(temp_root: Path) -> None:
    assert find_project_root(temp_root) is None
    assert find_shared_root(temp_root) is None
