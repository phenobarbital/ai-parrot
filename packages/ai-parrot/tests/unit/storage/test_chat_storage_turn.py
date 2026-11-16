"""FEAT-886 M3 — ChatStorageTurn: tolerant reader, invalid payloads, round trips."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.memory.persistence import TurnPresentation
from parrot.storage import ChatStorageTurn
from parrot.storage.errors import InvalidTurnPayloadError

UTC = timezone.utc


def _event_payload(**overrides):
    turn = ConversationTurn(
        turn_id="t-1", user_id="u-1", user_message="hi", assistant_response="hello",
        timestamp=datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC), chatbot_id="bot-uuid",
        tool_invocations=[ToolInvocation(tool_name="search", input={"q": "x"}, output="r",
                                         status=ToolStatus.COMPLETED, elapsed_ms=12)],
        tools_used=["search"], sequence=7,
    )
    payload = {
        "agent_name": "MyAgent", "chatbot_id": "bot-uuid", "user_id": "u-1", "session_id": "s-1",
        "turn": turn.to_dict(),
        "presentation": TurnPresentation(
            output="hello", output_mode="markdown", tenant="acme",
            usage={"input_tokens": 3, "output_tokens": 5}, cost_usd=0.0021,
            model="m", provider="p").model_dump(),
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def legacy_row():
    return {
        "turn_id": "legacy-uuid", "timestamp": "2025-01-02T03:04:05",
        "user_message": "q", "assistant_response": "a",
        "output": "a-out", "output_mode": "default", "data": {"k": 1}, "code": "x=1",
        "model": "m", "provider": "p", "response_time_ms": 90,
        "tool_calls": [{"name": "t", "status": "completed", "output": {"r": 1}, "arguments": {"a": 2}}],
        "sources": [{"content": "c", "metadata": {}}], "metadata": {"k": "v"},
    }


def test_event_payload_builds_full_turn():
    t = ChatStorageTurn.from_event_payload(_event_payload())
    assert t.schema_version == 2 and t.agent_id == "MyAgent" and t.chatbot_id == "bot-uuid"
    assert t.sequence == 7 and t.presentation.tenant == "acme" and t.presentation.cost_usd == 0.0021
    assert t.tool_invocations[0]["tool_name"] == "search"
    assert t.timestamp.utcoffset().total_seconds() == 0


def test_legacy_row_loads_as_schema_version_1(legacy_row):
    t = ChatStorageTurn.from_row(legacy_row, user_id="u", agent_id="a", session_id="s")
    assert t.schema_version == 1 and t.sequence == 0
    assert (t.user_id, t.agent_id, t.session_id) == ("u", "a", "s")
    assert t.tool_invocations[0]["tool_name"] == "t" and t.tool_invocations[0]["status"] == "completed"
    assert t.presentation.output == "a-out" and t.presentation.data == {"k": 1}
    assert t.presentation.sources and t.timestamp.tzinfo is not None


def test_legacy_row_without_timestamp_never_raises(legacy_row):
    legacy_row["timestamp"] = "garbage"
    t = ChatStorageTurn.from_row(legacy_row, user_id="u", agent_id="a", session_id="s")
    assert t.metadata["legacy_timestamp_missing"] is True
    assert t.timestamp == datetime(1970, 1, 1, tzinfo=UTC)
    legacy_row["updated_at"] = "2025-05-05T00:00:00+00:00"
    t = ChatStorageTurn.from_row(legacy_row, user_id="u", agent_id="a", session_id="s")
    assert t.timestamp == datetime(2025, 5, 5, tzinfo=UTC)


@pytest.mark.parametrize("field", ["turn_id", "user_id", "session_id", "agent_name", "timestamp", "bad-timestamp"])
def test_invalid_payload(field):
    payload = _event_payload()
    if field == "turn_id":
        payload["turn"].pop("turn_id")
    elif field in ("user_id", "session_id", "agent_name"):
        payload[field] = ""
        if field == "user_id":
            payload["turn"]["user_id"] = ""
    elif field == "timestamp":
        payload["turn"].pop("timestamp")
    else:
        payload["turn"]["timestamp"] = "not-a-date"
    expected = "timestamp" if "timestamp" in field else field
    with pytest.raises(InvalidTurnPayloadError, match=expected):
        ChatStorageTurn.from_event_payload(payload)


def test_non_dict_turn_is_invalid():
    with pytest.raises(InvalidTurnPayloadError):
        ChatStorageTurn.from_event_payload({"turn": "nope"})


def test_naive_timestamp_becomes_utc():
    t = ChatStorageTurn(turn_id="t", user_id="u", session_id="s", agent_id="a",
                        timestamp=datetime(2026, 1, 1, 12, 0), user_message="", assistant_response="")
    assert t.timestamp.tzinfo is not None
    assert t.to_row()["timestamp"].endswith("+00:00")


class _Weird:
    def __str__(self) -> str:
        return "weird"


def test_to_row_is_json_safe():
    t = ChatStorageTurn.from_event_payload(_event_payload())
    t = t.model_copy(update={"presentation": TurnPresentation(output=_Weird(), data={"s": {1, 2}, "b": b"x"})})
    row = t.to_row()
    json.dumps(row)
    assert row["presentation"]["output"] == "weird"


def test_v2_row_round_trip():
    t = ChatStorageTurn.from_event_payload(_event_payload())
    assert ChatStorageTurn.from_row(t.to_row()) == t


def test_to_conversation_turn_projects_and_drops_presentation():
    t = ChatStorageTurn.from_event_payload(_event_payload())
    ct = t.to_conversation_turn()
    assert isinstance(ct.tool_invocations[0], ToolInvocation) and ct.sequence == 7
    assert not hasattr(ct, "presentation")
    zero = t.model_copy(update={"sequence": 0}).to_conversation_turn()
    assert zero.sequence is None


def test_to_messages_keeps_legacy_keys_and_adds_rich_fields():
    msgs = ChatStorageTurn.from_event_payload(_event_payload()).to_messages()
    user, asst = msgs
    assert set(user) == {"role", "content", "timestamp", "turn_id"}
    for key in ("output", "output_mode", "data", "code", "model", "provider", "response_time_ms",
                "tool_calls", "sources", "metadata", "usage", "cost_usd", "tenant", "tool_invocations"):
        assert key in asst
    assert asst["tool_calls"][0]["name"] == "search" and asst["tenant"] == "acme"
