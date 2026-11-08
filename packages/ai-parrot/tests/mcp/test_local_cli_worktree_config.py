"""``parrot mcp-local`` portable ``--config`` resolution from inside a linked git worktree (issue:3f9828cebaaf).

``parrot sdd launch worker`` starts Claude Code in a feature worktree; the main checkout's portable ``.mcp.json``
is found by walking up, but the stdio servers start in the worktree, where the gitignored
``.parrot/mcp-toolkits.yaml`` does not exist. The server must borrow the main checkout's file while keeping the
worktree as its project root.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from parrot.mcp.local_cli import _DEFAULT_TOOLKIT_CONFIG, _linked_worktree_config, _resolve_root_and_config

RELATIVE = Path(".parrot") / "mcp-toolkits.yaml"


def _write_config(root: Path) -> Path:
    config = root / RELATIVE
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("toolkits: {}\n", encoding="utf-8")
    return config


@pytest.fixture
def fake_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A main checkout plus a linked worktree laid out exactly as git does, without running git."""
    main = tmp_path / "main"
    gitdir = main / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    (main / ".mcp.json").write_text("{}", encoding="utf-8")
    config = _write_config(main)
    worktree = tmp_path / "worktrees" / "wt"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return main, worktree, config


def test_linked_worktree_borrows_main_checkout_config(fake_worktree: tuple[Path, Path, Path]) -> None:
    main, worktree, config = fake_worktree
    root, resolved = _resolve_root_and_config(worktree, RELATIVE, None)
    assert root == worktree
    assert resolved == config
    assert resolved is not None and resolved.is_file()


def test_linked_worktree_default_config_path_is_borrowed_too(fake_worktree: tuple[Path, Path, Path]) -> None:
    _, worktree, config = fake_worktree
    root, resolved = _resolve_root_and_config(worktree, None, None)
    assert root == worktree
    assert resolved == config


def test_subdirectory_of_linked_worktree_resolves_upward(fake_worktree: tuple[Path, Path, Path]) -> None:
    _, worktree, config = fake_worktree
    nested = worktree / "packages" / "pkg"
    nested.mkdir(parents=True)
    root, resolved = _resolve_root_and_config(nested, RELATIVE, None)
    assert root == nested  # unchanged: no ancestor up to the boundary holds the file
    assert resolved == config


def test_worktree_with_its_own_config_wins(fake_worktree: tuple[Path, Path, Path]) -> None:
    _, worktree, _ = fake_worktree
    own = _write_config(worktree)
    root, resolved = _resolve_root_and_config(worktree, RELATIVE, None)
    assert root == worktree
    assert resolved == own


def test_plain_checkout_without_config_keeps_legacy_behaviour(tmp_path: Path) -> None:
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    root, resolved = _resolve_root_and_config(main, RELATIVE, None)
    assert root == main
    assert resolved == main / RELATIVE  # explicit --config stays an operator error when absent
    root, resolved = _resolve_root_and_config(main, None, None)
    assert (root, resolved) == (main, None)


def test_pinned_project_skips_worktree_fallback(fake_worktree: tuple[Path, Path, Path]) -> None:
    _, worktree, _ = fake_worktree
    pinned = worktree.parent / "pinned"
    pinned.mkdir()
    root, resolved = _resolve_root_and_config(worktree, RELATIVE, str(pinned))
    assert root == pinned
    assert resolved == pinned / RELATIVE


def test_absolute_config_is_left_alone(fake_worktree: tuple[Path, Path, Path]) -> None:
    _, worktree, config = fake_worktree
    assert _resolve_root_and_config(worktree, config, None) == (worktree, config)


def test_linked_worktree_config_ignores_non_gitdir_marker(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    (root / ".git").write_text("not a worktree pointer\n", encoding="utf-8")
    assert _linked_worktree_config(root, _DEFAULT_TOOLKIT_CONFIG) is None


def test_linked_worktree_config_is_none_for_a_git_directory(tmp_path: Path) -> None:
    root = tmp_path / "main"
    (root / ".git").mkdir(parents=True)
    assert _linked_worktree_config(root, RELATIVE) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_real_git_worktree_resolves_main_checkout_config(tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

    def run(*args: str) -> None:
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True, env=env)

    run("init", "-q", "-b", "main")
    (main / "README.md").write_text("x\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "init")
    config = _write_config(main)
    worktree = tmp_path / "wt"
    run("worktree", "add", "-q", str(worktree), "-b", "feature")
    root, resolved = _resolve_root_and_config(worktree, RELATIVE, None)
    assert root == worktree
    assert resolved == config
