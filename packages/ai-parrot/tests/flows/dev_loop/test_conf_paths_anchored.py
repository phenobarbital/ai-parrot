"""Tests: BASE_DIR-anchored conf paths (FEAT-253 TASK-001).

Verifies that ``WORKTREE_BASE_PATH`` and ``DEV_LOOP_REPO_BASE_PATH`` are
absolute paths rooted at ``navconfig.BASE_DIR`` regardless of the process's
current working directory.

Note: the two "anchored" tests are skipped when the corresponding env vars
are set to a custom absolute path outside BASE_DIR, since that is a valid
operator override and the test only validates the default wiring.
"""

import os

import pytest
from navconfig import BASE_DIR

from parrot import conf

_HAS_CUSTOM_WT = "WORKTREE_BASE_PATH" in os.environ
_HAS_CUSTOM_REPOS = "DEV_LOOP_REPO_BASE_PATH" in os.environ


@pytest.mark.skipif(
    _HAS_CUSTOM_WT,
    reason="WORKTREE_BASE_PATH env override active — skipping default-anchor check",
)
def test_worktree_base_path_anchored_at_base_dir() -> None:
    """WORKTREE_BASE_PATH must be absolute and under BASE_DIR (default wiring)."""
    assert os.path.isabs(conf.WORKTREE_BASE_PATH), (
        f"WORKTREE_BASE_PATH is not absolute: {conf.WORKTREE_BASE_PATH!r}"
    )
    assert conf.WORKTREE_BASE_PATH.startswith(str(BASE_DIR)), (
        f"WORKTREE_BASE_PATH {conf.WORKTREE_BASE_PATH!r} is not under BASE_DIR {BASE_DIR}"
    )


@pytest.mark.skipif(
    _HAS_CUSTOM_WT or _HAS_CUSTOM_REPOS,
    reason="Path env overrides active — skipping default-anchor check",
)
def test_repo_base_path_under_worktree_base() -> None:
    """DEV_LOOP_REPO_BASE_PATH must be absolute, under WORKTREE_BASE_PATH, ending in 'repos'."""
    assert os.path.isabs(conf.DEV_LOOP_REPO_BASE_PATH), (
        f"DEV_LOOP_REPO_BASE_PATH is not absolute: {conf.DEV_LOOP_REPO_BASE_PATH!r}"
    )
    base = os.path.abspath(conf.WORKTREE_BASE_PATH)
    assert os.path.commonpath([base, conf.DEV_LOOP_REPO_BASE_PATH]) == base, (
        f"DEV_LOOP_REPO_BASE_PATH {conf.DEV_LOOP_REPO_BASE_PATH!r} is not under "
        f"WORKTREE_BASE_PATH {base!r}"
    )
    assert conf.DEV_LOOP_REPO_BASE_PATH.rstrip("/").endswith("repos"), (
        f"DEV_LOOP_REPO_BASE_PATH does not end in 'repos': {conf.DEV_LOOP_REPO_BASE_PATH!r}"
    )
