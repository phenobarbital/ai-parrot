"""Tests for SuspendingWebHumanTool (FEAT-204 / TASK-1381)."""
from __future__ import annotations

import pytest

from parrot.handlers.web_hitl import SuspendingWebHumanTool, WebHumanTool


# ---------------------------------------------------------------------------
# Class relationship tests
# ---------------------------------------------------------------------------


def test_suspending_is_subclass_of_web_human_tool():
    """SuspendingWebHumanTool must subclass WebHumanTool."""
    assert issubclass(SuspendingWebHumanTool, WebHumanTool)


def test_suspend_strategy():
    """SuspendingWebHumanTool has wait_strategy == SUSPEND."""
    tool = SuspendingWebHumanTool()
    assert isinstance(tool, WebHumanTool)
    # Verify by value so this test works regardless of which parrot.human
    # module is cached (main-repo vs worktree).
    assert str(tool.wait_strategy) in ("suspend", "WaitStrategy.SUSPEND")


def test_block_tool_unchanged():
    """WebHumanTool (blocking) still defaults to BLOCK — no regression."""
    tool = WebHumanTool()
    assert str(tool.wait_strategy) in ("block", "WaitStrategy.BLOCK")


# ---------------------------------------------------------------------------
# Constructor argument forwarding
# ---------------------------------------------------------------------------


def test_default_targets_forwarded():
    """default_targets kwarg is forwarded to the base class."""
    tool = SuspendingWebHumanTool(default_targets=["user-1"])
    assert tool.default_targets == ["user-1"]


def test_source_agent_forwarded():
    """source_agent kwarg is forwarded to the base class."""
    tool = SuspendingWebHumanTool(source_agent="my-agent")
    assert tool.source_agent == "my-agent"


def test_no_default_targets_by_default():
    """Default construction has no pre-set targets (resolved at call time)."""
    tool = SuspendingWebHumanTool()
    assert tool.default_targets == []


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


def test_importable_from_module():
    """SuspendingWebHumanTool is importable from parrot.handlers.web_hitl."""
    from parrot.handlers.web_hitl import SuspendingWebHumanTool as T  # noqa: F401
    assert T is SuspendingWebHumanTool
