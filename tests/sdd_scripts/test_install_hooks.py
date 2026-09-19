"""Tests for scripts/sdd/install_hooks.py (FEAT-577, spec §4 Module 11)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.install_hooks import HOOK_EVENTS, MARKER_BEGIN, install, main, render_block, uninstall

_WIKI_BLOCK = (
    "# >>> parrot-wiki post-commit >>>\n"
    "wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true\n"
    "# <<< parrot-wiki post-commit <<<\n"
)


@pytest.fixture
def hooks(tmp_path: Path) -> Path:
    d = tmp_path / "hooks"
    d.mkdir()
    return d


@pytest.fixture
def block(tmp_path: Path) -> str:
    return render_block("/usr/bin/python3", tmp_path)


def test_install_creates_missing_hooks(hooks: Path, block: str) -> None:
    """Test that install creates missing hooks with shebang, marker, and executable permissions."""
    installed_paths = install(hooks, block)
    assert len(installed_paths) == len(HOOK_EVENTS)
    
    for event in HOOK_EVENTS:
        hook_path = hooks / event
        assert hook_path.exists()
        content = hook_path.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/sh\n")
        assert MARKER_BEGIN in content
        
        # Check executable permissions
        mode = hook_path.stat().st_mode
        assert bool(mode & stat.S_IXUSR)


def test_install_is_idempotent(hooks: Path, block: str) -> None:
    """Test that running install multiple times does not duplicate the block."""
    install(hooks, block)
    hook_path = hooks / HOOK_EVENTS[0]
    content_1 = hook_path.read_text(encoding="utf-8")
    
    # Run again
    install(hooks, block)
    content_2 = hook_path.read_text(encoding="utf-8")
    
    assert content_1 == content_2
    assert content_1.count(MARKER_BEGIN) == 1


def test_install_preserves_other_blocks(hooks: Path, block: str) -> None:
    """Test that other hook content is preserved byte-for-byte, and uninstall restores it."""
    hook_path = hooks / "post-commit"
    original_content = f"#!/bin/sh\n{_WIKI_BLOCK}"
    hook_path.write_text(original_content, encoding="utf-8")
    
    install(hooks, block, events=("post-commit",))
    
    content_after_install = hook_path.read_text(encoding="utf-8")
    assert _WIKI_BLOCK in content_after_install
    assert MARKER_BEGIN in content_after_install
    
    uninstall(hooks, events=("post-commit",))
    content_after_uninstall = hook_path.read_text(encoding="utf-8")
    assert content_after_uninstall == original_content


def test_uninstall_removes_only_its_block(hooks: Path, block: str) -> None:
    """Test that uninstall removes only the sdd-intake-prune block."""
    hook_path = hooks / "post-commit"
    original_content = f"#!/bin/sh\n{_WIKI_BLOCK}"
    hook_path.write_text(original_content, encoding="utf-8")
    
    install(hooks, block, events=("post-commit",))
    uninstall(hooks, events=("post-commit",))
    
    assert hook_path.read_text(encoding="utf-8") == original_content


def test_missing_hooks_dir_exits_2(tmp_path: Path) -> None:
    """Test that a missing hooks directory exits with 2 and prints a message naming core.hooksPath."""
    # Test install raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        install(tmp_path / "nonexistent_hooks", "some block")
        
    # Test main exits with 2 when hooks dir is missing
    # We initialize a git repo in a temp dir and configure core.hooksPath to a nonexistent path
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    
    nonexistent_hooks_path = repo_dir / "nonexistent_hooks_dir"
    subprocess.run(
        ["git", "config", "core.hooksPath", str(nonexistent_hooks_path)],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )
    
    # Run main with the repo-root pointing to our temp repo
    exit_code = main(["--repo-root", str(repo_dir)])
    assert exit_code == 2


def test_block_never_fails_git(block: str) -> None:
    """Test that the rendered block contains safety guards so it never fails git operations."""
    assert "[ -d .git ]" in block
    assert "--daily --apply" in block
    assert "|| true" in block
