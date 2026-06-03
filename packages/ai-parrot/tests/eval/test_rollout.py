"""Unit tests for rollout strategies + user simulators (TASK-1423)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.eval import ConversationalRollout, SingleTurnRollout
from parrot.eval.models import EvalTask
from parrot.eval.rollout import LLMUserSimulator, UserSimulator
from parrot.eval.sandbox.base import NoopSandbox


async def test_single_turn_records_trajectory():
    """SingleTurnRollout.run() returns a Trajectory with final_output set."""
    bot = AsyncMock()
    bot.ask.return_value = type("M", (), {"content": "done"})()

    task = EvalTask(task_id="t", inputs={"query": "hi"})
    sandbox = NoopSandbox()
    async with sandbox:
        tr = await SingleTurnRollout().run(bot, task, sandbox)

    assert tr.task_id == "t"
    assert tr.final_output is not None
    assert tr.latency_ms >= 0.0
    bot.ask.assert_awaited_once()


async def test_single_turn_uses_query_from_inputs():
    """SingleTurnRollout passes task.inputs['query'] to bot.ask()."""
    bot = AsyncMock()
    bot.ask.return_value = type("M", (), {"content": "answer"})()

    task = EvalTask(task_id="t", inputs={"query": "test-question"})
    async with NoopSandbox() as sb:
        tr = await SingleTurnRollout().run(bot, task, sb)

    bot.ask.assert_awaited_once_with("test-question")


async def test_single_turn_captures_error_on_exception():
    """SingleTurnRollout captures bot exceptions in trajectory.error."""
    bot = AsyncMock()
    bot.ask.side_effect = RuntimeError("boom")

    task = EvalTask(task_id="t", inputs={"query": "x"})
    async with NoopSandbox() as sb:
        tr = await SingleTurnRollout().run(bot, task, sb)

    assert tr.error is not None
    assert "boom" in tr.error


async def test_conversational_rollout_stops_on_none():
    """ConversationalRollout stops when simulator returns None."""
    bot = AsyncMock()
    bot.conversation.return_value = type("M", (), {"content": "agent reply"})()

    call_count = 0

    class FiniteSimulator(UserSimulator):
        async def respond(self, conversation, scenario):
            nonlocal call_count
            call_count += 1
            return None  # stop immediately

    task = EvalTask(task_id="t", inputs={"query": "start"}, user_scenario="do X")
    rollout = ConversationalRollout(user_sim=FiniteSimulator(), max_turns=5)
    async with NoopSandbox() as sb:
        tr = await rollout.run(bot, task, sb)

    assert tr.task_id == "t"
    assert len(tr.turns) >= 1  # at least one user turn
    assert call_count == 1  # simulator called once


async def test_conversational_rollout_respects_max_turns():
    """ConversationalRollout stops after max_turns even if simulator continues."""
    bot = AsyncMock()
    bot.conversation.return_value = type("M", (), {"content": "ok"})()

    class InfiniteSimulator(UserSimulator):
        async def respond(self, conversation, scenario):
            return "more"

    task = EvalTask(task_id="t", inputs={"query": "start"}, user_scenario="loop")
    rollout = ConversationalRollout(user_sim=InfiniteSimulator(), max_turns=3)
    async with NoopSandbox() as sb:
        tr = await rollout.run(bot, task, sb)

    # 3 turns max means 3 user + 3 agent turns (6 total), but simulator
    # may prevent the last user turn from starting a new agent turn.
    assert len(tr.turns) <= 8
    assert bot.conversation.await_count == 3


async def test_llm_user_simulator_calls_ask():
    """LLMUserSimulator.respond calls client.ask()."""
    client = AsyncMock()
    client.model = "gpt-4o-mini"

    class FakeResponse:
        content = "next user message"

    client.ask.return_value = FakeResponse()

    sim = LLMUserSimulator(client)
    result = await sim.respond([], "do something")

    client.ask.assert_awaited_once()
    assert result == "next user message"


async def test_llm_user_simulator_returns_none_on_task_complete():
    """LLMUserSimulator returns None when the model responds TASK_COMPLETE."""
    client = AsyncMock()
    client.model = "gpt-4o-mini"
    client.ask.return_value = type("R", (), {"content": "TASK_COMPLETE"})()

    sim = LLMUserSimulator(client)
    result = await sim.respond([], "do something")
    assert result is None


async def test_llm_user_simulator_returns_none_on_error():
    """LLMUserSimulator returns None (not raises) on client error."""
    client = AsyncMock()
    client.model = "gpt-4o-mini"
    client.ask.side_effect = RuntimeError("client down")

    sim = LLMUserSimulator(client)
    result = await sim.respond([], "do something")
    assert result is None
