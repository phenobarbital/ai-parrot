"""Tests for WaitStrategy enum + HumanTool.wait_strategy + SUSPEND branch.

FEAT-204 / TASK-1379
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.human import WaitStrategy
from parrot.human.tool import HumanTool, HumanToolInput
from parrot.core.exceptions import HumanInteractionInterrupt


# ---------------------------------------------------------------------------
# WaitStrategy enum tests
# ---------------------------------------------------------------------------


def test_wait_strategy_values():
    """WaitStrategy enum values are stable strings as specified."""
    assert WaitStrategy.BLOCK.value == "block"
    assert WaitStrategy.SUSPEND.value == "suspend"
    assert WaitStrategy.HOT_THEN_SUSPEND.value == "hot"


def test_wait_strategy_is_str_enum():
    """WaitStrategy inherits from str — can be used wherever a string is expected."""
    assert WaitStrategy.BLOCK == "block"
    assert WaitStrategy.SUSPEND == "suspend"


# ---------------------------------------------------------------------------
# HumanToolInput schema tests
# ---------------------------------------------------------------------------


def test_wait_strategy_not_in_llm_schema():
    """wait_strategy MUST NOT appear in HumanToolInput (LLM-facing schema)."""
    assert "wait_strategy" not in HumanToolInput.model_fields


def test_wait_strategy_not_in_tool_args_schema():
    """The tool's args_schema JSON schema must not expose wait_strategy."""
    tool = HumanTool(manager=None)
    schema = tool.args_schema.model_json_schema()
    assert "wait_strategy" not in schema.get("properties", {})


# ---------------------------------------------------------------------------
# HumanTool.wait_strategy field tests
# ---------------------------------------------------------------------------


def test_default_wait_strategy_is_block():
    """HumanTool defaults to BLOCK strategy."""
    tool = HumanTool(manager=None)
    assert tool.wait_strategy == WaitStrategy.BLOCK


def test_wait_strategy_set_to_suspend():
    """HumanTool can be constructed with SUSPEND strategy."""
    tool = HumanTool(manager=None, wait_strategy=WaitStrategy.SUSPEND)
    assert tool.wait_strategy == WaitStrategy.SUSPEND


def test_wait_strategy_attribute_overridable():
    """wait_strategy is a plain instance attribute that can be overridden."""
    tool = HumanTool(manager=None)
    tool.wait_strategy = WaitStrategy.SUSPEND
    assert tool.wait_strategy == WaitStrategy.SUSPEND


# ---------------------------------------------------------------------------
# SUSPEND branch: calls request_human_input_async, raises interrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_raises_interrupt():
    """SUSPEND _execute calls request_human_input_async and raises the interrupt."""
    fake_manager = MagicMock()
    fake_manager.request_human_input_async = AsyncMock(return_value="known-id")
    fake_manager.request_human_input = AsyncMock(
        side_effect=AssertionError("BLOCK path must NOT be called in SUSPEND mode")
    )
    fake_manager.channels = {}

    tool = HumanTool(manager=fake_manager, wait_strategy=WaitStrategy.SUSPEND)

    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        await tool._execute(question="approve?", interaction_type="approval")

    exc = exc_info.value
    assert exc.interaction_id == "known-id"
    assert exc.prompt == "approve?"

    fake_manager.request_human_input_async.assert_called_once()
    fake_manager.request_human_input.assert_not_called()


@pytest.mark.asyncio
async def test_suspend_does_not_call_block_path():
    """SUSPEND path never calls the blocking request_human_input."""
    fake_manager = MagicMock()
    fake_manager.request_human_input_async = AsyncMock(return_value="iid-1")
    fake_manager.request_human_input = AsyncMock(
        side_effect=RuntimeError("must not be called")
    )
    fake_manager.channels = {}

    tool = HumanTool(manager=fake_manager, wait_strategy=WaitStrategy.SUSPEND)

    with pytest.raises(HumanInteractionInterrupt):
        await tool._execute(question="Q", interaction_type="free_text")

    fake_manager.request_human_input.assert_not_called()


@pytest.mark.asyncio
async def test_suspend_interrupt_carries_policy_id():
    """When policy_id is provided, the interrupt carries it."""
    fake_manager = MagicMock()
    fake_manager.request_human_input_async = AsyncMock(return_value="iid-p")
    fake_manager.channels = {}

    tool = HumanTool(manager=fake_manager, wait_strategy=WaitStrategy.SUSPEND)

    with pytest.raises(HumanInteractionInterrupt) as exc_info:
        await tool._execute(
            question="approve?",
            interaction_type="approval",
            policy_id="pol-123",
        )

    assert exc_info.value.policy_id == "pol-123"


# ---------------------------------------------------------------------------
# BLOCK path: unchanged behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_path_calls_request_human_input():
    """BLOCK path (default) still awaits request_human_input — no regression."""
    from parrot.human.models import InteractionResult, InteractionStatus, InteractionType

    fake_result = InteractionResult(
        interaction_id="iid-block",
        status=InteractionStatus.COMPLETED,
        consolidated_value="yes",
    )

    fake_manager = MagicMock()
    fake_manager.request_human_input = AsyncMock(return_value=fake_result)
    fake_manager.request_human_input_async = AsyncMock(
        side_effect=AssertionError("ASYNC path must NOT be called in BLOCK mode")
    )
    fake_manager.channels = {}

    tool = HumanTool(manager=fake_manager, wait_strategy=WaitStrategy.BLOCK)

    result = await tool._execute(question="Q", interaction_type="approval")

    fake_manager.request_human_input.assert_called_once()
    fake_manager.request_human_input_async.assert_not_called()
    assert result == "yes"


@pytest.mark.asyncio
async def test_default_block_path_unchanged():
    """Default (no wait_strategy kwarg) uses BLOCK — no regression."""
    from parrot.human.models import InteractionResult, InteractionStatus

    fake_result = InteractionResult(
        interaction_id="iid-def",
        status=InteractionStatus.COMPLETED,
        consolidated_value="ok",
    )

    fake_manager = MagicMock()
    fake_manager.request_human_input = AsyncMock(return_value=fake_result)
    fake_manager.channels = {}

    tool = HumanTool(manager=fake_manager)  # default: BLOCK
    result = await tool._execute(question="Q", interaction_type="free_text")

    fake_manager.request_human_input.assert_called_once()
    assert result == "ok"


# ---------------------------------------------------------------------------
# HOT_THEN_SUSPEND: reserved — treated as BLOCK for now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hot_then_suspend_falls_back_to_block():
    """HOT_THEN_SUSPEND is reserved; currently falls back to BLOCK behaviour."""
    from parrot.human.models import InteractionResult, InteractionStatus

    fake_result = InteractionResult(
        interaction_id="iid-hot",
        status=InteractionStatus.COMPLETED,
        consolidated_value="ok",
    )

    fake_manager = MagicMock()
    fake_manager.request_human_input = AsyncMock(return_value=fake_result)
    fake_manager.channels = {}

    tool = HumanTool(
        manager=fake_manager, wait_strategy=WaitStrategy.HOT_THEN_SUSPEND
    )
    result = await tool._execute(question="Q", interaction_type="free_text")

    fake_manager.request_human_input.assert_called_once()
    assert result == "ok"
