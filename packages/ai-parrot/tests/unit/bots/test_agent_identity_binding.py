"""Unit tests for TASK-1501 — agent identity ContextVar bound around bot invocations.

FEAT-228. Verifies the ContextVar token-based set/reset pattern used in
BaseBot.ask / ask_stream / invoke / conversation.

These tests verify the core mechanism (token set/reset) that TASK-1501
inserts into the four public bot invocation methods.  Full end-to-end
verification (with a real BaseBot) lives in the integration tests.

The bots module requires compiled Cython extensions; these unit tests
focus on the pure-Python context-propagation contract that the wrapping
implements, using lightweight coroutines rather than a full bot.
"""

from __future__ import annotations

import asyncio

import pytest

from parrot.observability.context import current_agent_name


# ---------------------------------------------------------------------------
# Helpers that simulate what base.py now does in each method
# ---------------------------------------------------------------------------


async def _simulated_bot_ask(name: str, inner_call) -> None:
    """Mirrors the FEAT-228 wrapping in BaseBot.ask:
      token = current_agent_name.set(self.name)
      try:
          ...body that calls inner_call()...
      finally:
          current_agent_name.reset(token)
    """
    token = current_agent_name.set(name)
    try:
        await inner_call()
    finally:
        current_agent_name.reset(token)


async def _simulated_bot_ask_stream(name: str, inner_call) -> list:
    """Mirrors the FEAT-228 wrapping in BaseBot.ask_stream (async generator)."""
    collected = []
    token = current_agent_name.set(name)
    try:
        async for item in inner_call():
            collected.append(item)
    finally:
        current_agent_name.reset(token)
    return collected


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_set_binds_name() -> None:
    """Token-based set binds name and is visible to inner coroutine."""
    seen: list[str | None] = []

    async def inner():
        seen.append(current_agent_name.get())

    await _simulated_bot_ask("porygon", inner)
    assert seen == ["porygon"]


@pytest.mark.asyncio
async def test_token_reset_restores_none_after_call() -> None:
    """After the simulated invocation completes, var reverts to None."""
    async def _noop():
        pass

    await _simulated_bot_ask("porygon", _noop)
    assert current_agent_name.get() is None


@pytest.mark.asyncio
async def test_token_reset_on_exception() -> None:
    """Token reset happens even when the body raises."""
    async def raiser():
        raise RuntimeError("intentional")

    try:
        await _simulated_bot_ask("porygon", raiser)
    except RuntimeError:
        pass
    assert current_agent_name.get() is None


@pytest.mark.asyncio
async def test_nested_invocations_restore_outer() -> None:
    """Inner invocation (nested agent) restores the outer agent's name."""
    inner_seen: list[str | None] = []
    outer_seen_after: list[str | None] = []

    async def inner_bot_call():
        inner_seen.append(current_agent_name.get())

    async def outer_body():
        # Simulate inner bot invocation
        await _simulated_bot_ask("inner-bot", inner_bot_call)
        # After inner completes, outer's name is restored
        outer_seen_after.append(current_agent_name.get())

    await _simulated_bot_ask("outer-bot", outer_body)

    assert inner_seen == ["inner-bot"]
    assert outer_seen_after == ["outer-bot"]
    assert current_agent_name.get() is None


@pytest.mark.asyncio
async def test_task_spawned_inside_call_inherits_name() -> None:
    """A task spawned inside the invocation scope inherits the agent name."""
    seen_in_task: list[str | None] = []

    async def task_body():
        seen_in_task.append(current_agent_name.get())

    async def body_with_spawn():
        t = asyncio.create_task(task_body())
        await t

    await _simulated_bot_ask("porygon", body_with_spawn)
    assert seen_in_task == ["porygon"]


@pytest.mark.asyncio
async def test_ask_stream_token_binding() -> None:
    """Stream invocation: token set before first yield, reset after generator exhausts."""
    seen: list[str | None] = []

    async def stream_inner():
        seen.append(current_agent_name.get())
        yield "chunk1"
        seen.append(current_agent_name.get())
        yield "chunk2"

    result = await _simulated_bot_ask_stream("stream-bot", stream_inner)
    assert result == ["chunk1", "chunk2"]
    assert seen == ["stream-bot", "stream-bot"]
    assert current_agent_name.get() is None
