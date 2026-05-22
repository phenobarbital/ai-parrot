# -*- coding: utf-8 -*-
"""Tests for the HandoffTool.

Covers:
- Legacy synchronous / asynchronous interrupt behaviour (pre-existing)
- DeprecationWarning fires exactly once per process (TASK-1283)
- Dedup short-circuit: returns value without interrupt when manager resolves
  within the polling window (TASK-1283)
- Fallback to interrupt when manager does not resolve in window (TASK-1283)
"""

from __future__ import annotations

import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.core.tools.handoff import HandoffTool
from parrot.human.models import InteractionResult, InteractionStatus


# ── Legacy tests (pre-existing) ────────────────────────────────────────────


def test_handoff_tool_raises_interrupt():
    """Synchronous execution of HandoffTool raises an interrupt."""
    HandoffTool._deprecation_warned = True  # suppress warning for legacy test
    tool = HandoffTool()
    prompt_msg = "Please provide your project ID."

    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        tool._execute(prompt=prompt_msg)

    assert prompt_msg in str(exc_info.value)
    assert exc_info.value.prompt == prompt_msg


@pytest.mark.asyncio
async def test_handoff_tool_arun_raises_interrupt():
    """Asynchronous execution of HandoffTool raises an interrupt (no manager)."""
    HandoffTool._deprecation_warned = True  # suppress warning for legacy test
    tool = HandoffTool()
    prompt_msg = "Please select the environment for deployment."

    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        await tool._aexecute(prompt=prompt_msg)

    assert prompt_msg in str(exc_info.value)
    assert exc_info.value.prompt == prompt_msg


# ── DeprecationWarning tests ────────────────────────────────────────────────


class TestDeprecationWarning:

    def setup_method(self):
        """Reset the class-level flag before each test."""
        HandoffTool._deprecation_warned = False

    def teardown_method(self):
        """Restore the flag so other tests are not affected."""
        HandoffTool._deprecation_warned = False

    def test_warning_fires_once_per_process(self):
        """DeprecationWarning is emitted exactly once regardless of instances."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            HandoffTool()
            HandoffTool()
            HandoffTool()

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1

    def test_warning_message_points_to_human_tool(self):
        """DeprecationWarning message mentions HumanTool and policy_id."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            HandoffTool()

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) == 1
        msg = str(dep_warnings[0].message)
        assert "HumanTool" in msg
        assert "policy_id" in msg


# ── Dedup / short-circuit tests ─────────────────────────────────────────────


class TestDedup:

    def setup_method(self):
        """Suppress deprecation warnings for dedup tests."""
        HandoffTool._deprecation_warned = True

    def teardown_method(self):
        HandoffTool._deprecation_warned = False

    @pytest.mark.asyncio
    async def test_returns_message_when_manager_resolves_in_window(self):
        """Returns action_metadata['message'] without raising interrupt."""
        mgr = AsyncMock()
        mgr.request_human_input_async = AsyncMock(return_value="iid-123")
        result = InteractionResult(
            interaction_id="iid-123",
            status=InteractionStatus.COMPLETED,
            consolidated_value="approved",
            action_metadata={"message": "Ticket TKT-42 opened."},
        )
        # Resolve on the first poll
        mgr.get_result = AsyncMock(return_value=result)

        tool = HandoffTool(manager=mgr)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            ret = await tool._aexecute(prompt="Deploy to prod?", policy_id="p1")

        assert ret == "Ticket TKT-42 opened."

    @pytest.mark.asyncio
    async def test_returns_consolidated_value_when_no_action_message(self):
        """Returns consolidated_value when action_metadata has no 'message'."""
        mgr = AsyncMock()
        mgr.request_human_input_async = AsyncMock(return_value="iid-456")
        result = InteractionResult(
            interaction_id="iid-456",
            status=InteractionStatus.COMPLETED,
            consolidated_value="yes",
        )
        mgr.get_result = AsyncMock(return_value=result)

        tool = HandoffTool(manager=mgr)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            ret = await tool._aexecute(prompt="Proceed?")

        assert ret == "yes"

    @pytest.mark.asyncio
    async def test_raises_interrupt_when_manager_does_not_resolve_in_window(self):
        """Raises HumanInteractionInterrupt with interaction_id when poll exhausted."""
        mgr = AsyncMock()
        mgr.request_human_input_async = AsyncMock(return_value="iid-789")
        # Never resolves during the polling window
        mgr.get_result = AsyncMock(return_value=None)

        tool = HandoffTool(manager=mgr)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HumanInteractionInterrupt) as exc_info:
                await tool._aexecute(prompt="Approve?", policy_id="pol-1")

        assert exc_info.value.prompt == "Approve?"
        assert exc_info.value.interaction_id == "iid-789"
        assert exc_info.value.policy_id == "pol-1"

    @pytest.mark.asyncio
    async def test_raises_interrupt_when_no_manager_configured(self):
        """No manager — raises HumanInteractionInterrupt with no interaction_id."""
        tool = HandoffTool(manager=None)

        with pytest.raises(HumanInteractionInterrupt) as exc_info:
            await tool._aexecute(prompt="Need input.", policy_id="pol-2")

        assert exc_info.value.prompt == "Need input."
        assert exc_info.value.interaction_id is None

