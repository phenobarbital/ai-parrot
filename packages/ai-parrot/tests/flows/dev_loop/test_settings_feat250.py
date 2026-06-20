"""Defaults for the FEAT-250 dev-loop settings (TASK-004)."""
from __future__ import annotations

import parrot.conf as conf


def test_dev_loop_feat250_defaults():
    assert conf.DEV_LOOP_REVISION_TRIGGER == "changes_requested"
    assert conf.DEV_LOOP_CODEREVIEW_MODEL == "claude-sonnet-4-6"
    assert conf.DEV_LOOP_REPOS == []


def test_repo_base_path_under_worktree_base():
    # The clone base path must live under WORKTREE_BASE_PATH (R4).
    assert conf.DEV_LOOP_REPO_BASE_PATH.startswith(conf.WORKTREE_BASE_PATH)
    assert conf.DEV_LOOP_REPO_BASE_PATH.endswith("repos")
