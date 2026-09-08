"""Unit tests for FEAT-525 AbstractBot budget integration."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle.events import Stage2CompactionNeededEvent
from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import CompactionCommit, ContextBudget
from parrot.memory.render import render_history


@pytest.fixture
def bot(make_bot):
    return make_bot(llm_model="claude-sonnet-5")


def test_default_budget_from_model(make_bot, caplog):
    assert make_bot(llm_model="claude-sonnet-5").context_budget.window == 200_000

    with caplog.at_level("INFO"):
        b = make_bot(llm_model="mystery-1")
        b.context_budget
        b.context_budget
    assert b.context_budget.window == 32_000
    assert sum("32" in r.message for r in caplog.records if r.levelname == "INFO") == 1


def test_kill_switches_and_ceiling(make_bot, monkeypatch):
    assert make_bot(context_budget=False).context_budget is None

    monkeypatch.setenv("PARROT_COMPACTION_DISABLED", "1")
    assert make_bot().context_budget is None
    monkeypatch.delenv("PARROT_COMPACTION_DISABLED")

    b = make_bot(context_budget=ContextBudget(window=50_000), max_context_turns=12)
    assert b.context_budget.max_turns == 12
    assert make_bot().context_budget.max_turns == 30
    assert make_bot().max_context_turns is None


async def test_render_context_history_plain_when_disabled(make_bot):
    disabled_bot = make_bot(context_budget=False)
    history = ConversationHistory(
        session_id="s",
        user_id="u",
        chatbot_id=disabled_bot.memory_key_id,
        turns=[
            ConversationTurn(
                turn_id="t1",
                user_id="u",
                user_message="hi",
                assistant_response="hello",
                chatbot_id=disabled_bot.memory_key_id,
            )
        ],
    )
    rendered, result = await disabled_bot.render_context_history(history)
    assert result is None
    expected = render_history(
        history, max_turns=disabled_bot.max_context_turns or 30, current_chatbot_id=disabled_bot.memory_key_id
    )
    assert rendered == expected


async def test_calibration_pairing_in_save_turn(bot):
    mem = bot.conversation_memory
    await mem.create_history("u", "s", chatbot_id=bot.memory_key_id)
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="q",
        assistant_response="a",
        chatbot_id=bot.memory_key_id,
        metadata={"usage": {"input_tokens": 150, "output_tokens": 5}},
    )
    await bot.save_conversation_turn("u", "s", turn, compaction=CompactionCommit(100, "t1", False))
    comp = (await mem.get_history("u", "s", chatbot_id=bot.memory_key_id)).metadata["compaction"]
    assert comp["calibration"] == pytest.approx(1.5)
    assert comp["boundary_turn_id"] == "t1"


async def test_stage2_event_emitted_once(bot, event_recorder):
    mem = bot.conversation_memory
    await mem.create_history("u", "s", chatbot_id=bot.memory_key_id)
    for i in range(2):
        turn = ConversationTurn(
            turn_id=f"t{i}", user_id="u", user_message="q", assistant_response="a", chatbot_id=bot.memory_key_id
        )
        await bot.save_conversation_turn(
            "u",
            "s",
            turn,
            compaction=CompactionCommit(100, "t1", True, history_estimate=20_000, dropped_turns=3),
        )
    stage2_events = [e for e in event_recorder if isinstance(e, Stage2CompactionNeededEvent)]
    assert len(stage2_events) == 1
    assert stage2_events[0].history_estimate == 20_000
    assert stage2_events[0].dropped_turns == 3
    assert stage2_events[0].session_id == "s"


def test_recovery_tool_registered(make_bot):
    budgeted = make_bot(llm_model="claude-sonnet-5")
    assert "read_omitted_content" in budgeted.tool_manager.list_tools()

    unbudgeted = make_bot(context_budget=False)
    assert "read_omitted_content" not in unbudgeted.tool_manager.list_tools()

    before = budgeted.tool_manager.list_tools().count("read_omitted_content")
    budgeted._register_recovery_tool()
    after = budgeted.tool_manager.list_tools().count("read_omitted_content")
    assert before == after == 1


async def test_flush_failure_falls_back_to_plain(bot, monkeypatch, caplog):
    mem = bot.conversation_memory
    await mem.create_history("u", "s", chatbot_id=bot.memory_key_id)
    for i in range(3):
        turn = ConversationTurn(
            turn_id=f"t{i}", user_id="u", user_message=f"q{i}", assistant_response=f"a{i}", chatbot_id=bot.memory_key_id
        )
        await mem.add_turn("u", "s", turn, chatbot_id=bot.memory_key_id)
    history = await mem.get_history("u", "s", chatbot_id=bot.memory_key_id)

    async def boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(mem.omission_store, "put_many", boom)

    with caplog.at_level("WARNING"):
        rendered, result = await bot.render_context_history(history)

    assert result is None
    assert any("omission flush failed" in r.message for r in caplog.records)
    assert history.metadata.get("compaction") is None
