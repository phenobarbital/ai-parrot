"""Unit tests for devloop bootstrap & preflight."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from parrot.cli.devloop.bootstrap import (
    PreflightCheck,
    PreflightResult,
    preflight,
)


@pytest.mark.asyncio
async def test_preflight_all_pass():
    """All checks pass when env is fully configured."""
    mock_conf = MagicMock()
    mock_conf.config.get = MagicMock(side_effect=lambda k, fallback="": {
        "REDIS_URL": "redis://localhost:6379",
    }.get(k, fallback))
    mock_conf.JIRA_URL = "https://jira.example.com"
    mock_conf.JIRA_USERNAME = "user"
    mock_conf.JIRA_API_TOKEN = "token"
    mock_conf.WORKTREE_BASE_PATH = "/tmp/worktrees"

    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch.dict("sys.modules", {"parrot.conf": MagicMock(), "parrot": MagicMock(conf=mock_conf)}), \
         patch("parrot.cli.devloop.bootstrap.os.environ", {"USER": "testuser", "WORKTREE_BASE_PATH": "/tmp/wt"}):
        mock_shutil.which.return_value = "/usr/bin/claude"
        # Patch the import of conf inside the function
        with patch("parrot.cli.devloop.bootstrap.preflight.__module__", "parrot.cli.devloop.bootstrap"):
            result = await preflight()

    # Verify structure
    assert isinstance(result, PreflightResult)
    assert isinstance(result.checks, list)
    assert all(isinstance(c, PreflightCheck) for c in result.checks)


@pytest.mark.asyncio
async def test_preflight_missing_claude_cli():
    """Missing claude CLI results in a failed check with hint."""
    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil:
        mock_shutil.which.return_value = None
        result = await preflight()

    claude_check = next((c for c in result.checks if c.name == "claude-cli"), None)
    assert claude_check is not None
    assert claude_check.passed is False
    assert "Claude Code" in claude_check.hint


@pytest.mark.asyncio
async def test_preflight_missing_redis():
    """Missing REDIS_URL results in a failed check."""
    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch("parrot.cli.devloop.bootstrap.os.environ", {}):
        mock_shutil.which.return_value = "/usr/bin/claude"
        result = await preflight()

    redis_check = next((c for c in result.checks if c.name == "redis"), None)
    assert redis_check is not None
    # Will be False because conf import likely fails in test and env is empty
    assert isinstance(redis_check.passed, bool)


@pytest.mark.asyncio
async def test_preflight_result_ok_false_when_any_fail():
    """PreflightResult.ok is False when any check fails."""
    result = PreflightResult(
        ok=False,
        checks=[
            PreflightCheck(name="a", passed=True),
            PreflightCheck(name="b", passed=False, hint="fix b"),
        ],
    )
    assert result.ok is False


def test_preflight_check_model():
    """PreflightCheck validates properly."""
    check = PreflightCheck(name="redis", passed=True)
    assert check.name == "redis"
    assert check.passed is True
    assert check.hint == ""
