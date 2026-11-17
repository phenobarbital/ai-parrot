"""select_tests._default_base_ref — null-safe base ref (FEAT-830, issue:bfb29d4ffe49)."""

from __future__ import annotations

import os

import pytest

from parrot.sdd.scripts import select_tests


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ({}, "origin/dev"),
        ({"base_branch": None}, "origin/dev"),
        ({"base_branch": "  "}, "origin/dev"),
        ({"base_branch": "staging"}, "origin/staging"),
    ],
)
def test_default_base_ref(header: dict, expected: str) -> None:
    """A missing, null or blank base_branch falls back to origin/dev."""
    assert select_tests._default_base_ref(header) == expected


def test_worktree_env_prepends_worktree_package_sources(tmp_path, monkeypatch) -> None:
    """issue:f241f38501c9 — children must import the worktree's packages, not the main checkout's."""
    (tmp_path / "packages" / "a" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "b" / "src").mkdir(parents=True)
    (tmp_path / "packages" / "c").mkdir(parents=True)  # no src: ignored
    monkeypatch.setenv("PYTHONPATH", "/inherited")
    entries = select_tests._worktree_env(tmp_path)["PYTHONPATH"].split(os.pathsep)
    assert entries == [str(tmp_path / "packages" / "a" / "src"), str(tmp_path / "packages" / "b" / "src"), "/inherited"]


def test_worktree_env_without_packages_layout_is_unchanged(tmp_path, monkeypatch) -> None:
    """A foreign repo with no packages/ dir keeps the inherited environment."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    assert "PYTHONPATH" not in select_tests._worktree_env(tmp_path)


def test_child_resolves_symbol_from_worktree_not_main_checkout(tmp_path) -> None:
    """issue:f241f38501c9 — the real child-process path imports the worktree's copy.

    The sentinel module exists only inside the tmp "worktree"; no installed copy has it, so the
    import succeeds only if the child's PYTHONPATH points at the worktree's ``packages/*/src``.
    """
    import subprocess
    import sys

    src = tmp_path / "packages" / "sentinel-pkg" / "src"
    src.mkdir(parents=True)
    (src / "f241_sentinel_mod.py").write_text("SENTINEL = 'from-worktree'\n")

    result = select_tests._run_in_worktree(
        [sys.executable, "-c", "import f241_sentinel_mod as m; print(m.SENTINEL, m.__file__)"],
        tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("from-worktree")
    assert str(tmp_path) in result.stdout

    # Control: a plain child without the wiring cannot see the sentinel.
    bare = subprocess.run(
        [sys.executable, "-c", "import f241_sentinel_mod"], cwd=tmp_path, capture_output=True, text=True
    )
    assert bare.returncode != 0
