"""Unit tests for rollout strategies + user simulators (TASK-1423)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.eval import ConversationalRollout, SingleTurnRollout
from parrot.eval.models import EvalTask
from parrot.eval.rollout import LLMUserSimulator, UserSimulator
from parrot.eval.sandbox.base import NoopSandbox
from parrot.models.basic import CompletionUsage, ToolCall


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


def _ai_message_like(text: str = "Revenue was $1,243,500.") -> object:
    """Create a minimal object with the AIMessage attributes rollouts read."""
    return type(
        "Msg",
        (),
        {
            "content": text,
            "model": "fake:model-under-test",
            "usage": CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            "tool_calls": [
                ToolCall(
                    id="t1",
                    name="get_revenue",
                    arguments={"q": "Q3"},
                    result={"revenue": 1243500},
                    execution_time=0.02,
                )
            ],
            "metadata": {"guardrails": {"groundedness": {"score": 1.0}}},
        },
    )()


async def test_single_turn_copies_usage_tool_calls_model_metadata():
    """Single-turn rollouts retain the complete response accounting data."""
    bot = AsyncMock()
    bot.ask.return_value = _ai_message_like()

    async with NoopSandbox() as sandbox:
        trajectory = await SingleTurnRollout().run(bot, EvalTask(task_id="t", inputs={"query": "q"}), sandbox)

    assert trajectory.tokens.total == 15
    assert trajectory.turns[0].tool_calls[0].name == "get_revenue"
    assert trajectory.turns[0].tool_calls[0].latency_ms == 20.0
    assert trajectory.model == "fake:model-under-test"
    assert "guardrails" in trajectory.response_metadata


async def test_single_turn_defaults_without_usage():
    """Bare mock responses preserve trajectory enrichment defaults."""
    bot = AsyncMock()
    bot.ask.return_value = type("M", (), {"content": "x"})()

    async with NoopSandbox() as sandbox:
        trajectory = await SingleTurnRollout().run(bot, EvalTask(task_id="t", inputs={"query": "q"}), sandbox)

    assert trajectory.tokens.prompt == 0
    assert trajectory.tokens.completion == 0
    assert trajectory.tokens.total == 0
    assert trajectory.turns[0].tool_calls == []
    assert trajectory.model is None
    assert trajectory.response_metadata == {}


async def test_conversational_accumulates_tokens():
    """Conversational rollouts aggregate response usage for every agent turn."""
    bot = AsyncMock()
    bot.conversation.return_value = _ai_message_like()

    class ThreeTurnSimulator(UserSimulator):
        """Supply two follow-up messages before ending the conversation."""

        def __init__(self) -> None:
            self.calls = 0

        async def respond(self, conversation, scenario):
            self.calls += 1
            return "follow up" if self.calls < 3 else None

    rollout = ConversationalRollout(user_sim=ThreeTurnSimulator(), max_turns=5)
    async with NoopSandbox() as sandbox:
        trajectory = await rollout.run(
            bot,
            EvalTask(task_id="t", inputs={"query": "q"}, user_scenario="scenario"),
            sandbox,
        )

    agent_turns = [turn for turn in trajectory.turns if turn.role == "agent"]
    assert trajectory.tokens.total == 45
    assert trajectory.model == "fake:model-under-test"
    assert len(agent_turns) == 3
    assert all(len(turn.tool_calls) == 1 for turn in agent_turns)
