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


def test_run_sites_pass_worktree_env(tmp_path, monkeypatch) -> None:
    """Both subprocess.run call sites must pass env=_worktree_env(...) (mutation guard)."""
    import inspect

    src = inspect.getsource(select_tests)
    assert src.count("env=_worktree_env(worktree)") == 2
