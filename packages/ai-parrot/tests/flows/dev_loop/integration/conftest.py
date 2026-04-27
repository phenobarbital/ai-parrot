"""Live-test fixtures and skip helpers for the dev-loop integration suite.

These tests exercise the full dispatch + flow path against a real
``claude`` CLI, real Redis, and (optionally) a real Jira sandbox. They
are gated behind the ``live`` pytest marker and skipped automatically
when their prerequisites are missing.
"""

from __future__ import annotations

import os
import shutil
from typing import Iterator

import pytest


def _claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def _redis_available() -> bool:
    try:
        import redis  # noqa: F401
        # Heuristic: presence of REDIS_URL env var or default localhost.
        return True
    except ImportError:
        return False


@pytest.fixture
def skip_unless_claude_available():
    """Skip the test when the ``claude`` CLI or API key is missing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; live test skipped")
    if not _claude_cli_available():
        pytest.skip("`claude` CLI not on PATH; live test skipped")


@pytest.fixture
def skip_unless_redis_available():
    """Skip when ``redis`` is not installed."""
    if not _redis_available():
        pytest.skip("`redis` package not available; live test skipped")


@pytest.fixture
def temp_worktree_base(tmp_path, monkeypatch) -> Iterator[str]:
    """Override ``WORKTREE_BASE_PATH`` to point at an ephemeral tmp dir."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    yield str(tmp_path)
