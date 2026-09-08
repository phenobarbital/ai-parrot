"""Unit tests for FEAT-525 compaction data models + ConversationTurn schema v2."""

import pytest

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import (
    ContextBudget,
    TokenCount,
    ToolInvocation,
    ToolStatus,
    TurnState,
)
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage
from parrot.tools.compression.tee import attach_tee_pointer


def test_turn_roundtrip_v2():
    inv = ToolInvocation(tool_name="q", input={"b": 1, "a": 2}, output="rows", elapsed_ms=12)
    t = ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="hi",
        assistant_response="yo",
        chatbot_id="bot",
        tool_invocations=[inv],
        error=None,
        token_count=TokenCount(user=1, assistant=1, tools=2, total=4, tokenizer="heuristic"),
        schema_version=2,
        norm_version="1",
    )
    assert ConversationTurn.from_dict(t.to_dict()) == t


def test_turn_legacy_dict_defaults():
    legacy = {
        "turn_id": "t",
        "user_id": "u",
        "user_message": "a",
        "assistant_response": "b",
        "tools_used": ["x"],
        "timestamp": "2026-09-04T00:00:00",
        "metadata": {},
    }
    t = ConversationTurn.from_dict(legacy)
    assert t.tool_invocations == [] and t.error is None and t.token_count is None
    assert t.state is TurnState.RAW and t.schema_version == 1 and t.norm_version is None
    assert t.tools_used == ["x"]


def test_from_ai_message_fills_invocations():
    result = attach_tee_pointer({"rows": [1, 2]}, key="__tee__:q:abc:1", reason="lossy")
    msg = AIMessage(
        input="hi",
        output="ok",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(input_tokens=10, output_tokens=2),
        tool_calls=[
            ToolCall(id="1", name="q", arguments={"sql": "x"}, result=result, execution_time=1.5),
            ToolCall(id="2", name="w", arguments={}, error="boom"),
        ],
    )
    t = ConversationTurn.from_ai_message(user_message="u", response=msg, user_id="u1", chatbot_id="bot")
    a, b = t.tool_invocations
    assert a.tool_name == "q" and a.wm_key == "__tee__:q:abc:1" and a.elapsed_ms == 1500
    assert a.status is ToolStatus.COMPLETED
    assert b.status is ToolStatus.ERROR and b.error == "boom"
    assert t.tools_used == ["q", "w"]


def test_context_budget_validation():
    with pytest.raises(ValueError):
        ContextBudget(window=1000, reserve_output=900, reserve_fixed=200)
    assert ContextBudget(window=32_000).available == 19_712
