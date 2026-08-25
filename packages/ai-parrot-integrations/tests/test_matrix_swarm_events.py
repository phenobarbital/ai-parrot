"""Tests for swarm event models — FEAT-463 TASK-2478."""

import pytest
from pydantic import ValidationError

from parrot.integrations.matrix.events import (
    AgentAnswer,
    FeedbackEventContent,
    ParrotEventType,
    TaskEventContent,
)


def test_new_event_types():
    assert ParrotEventType.FEEDBACK == "m.parrot.feedback"
    assert ParrotEventType.CHANNEL == "m.parrot.channel"
    assert ParrotEventType.TUNNEL == "m.parrot.tunnel"


def test_task_content_new_fields_default():
    t = TaskEventContent(task_id="1", content="q")
    assert t.hops == 0
    assert t.correlation_id is None
    assert t.expected_schema is None
    assert t.origin_session is None


def test_agent_answer_schema_ok():
    AgentAnswer(answer={"total": 3}).validate_against({"type": "object", "required": ["total"]})


def test_agent_answer_schema_fail():
    with pytest.raises(ValueError):
        AgentAnswer(answer={"x": 1}).validate_against({"type": "object", "required": ["total"]})


def test_agent_answer_from_text_json_and_raw():
    assert AgentAnswer.from_text('{"answer": "42", "confidence": 0.9}').confidence == 0.9
    assert AgentAnswer.from_text("plain reply").answer == "plain reply"


def test_feedback_rating_bounds():
    with pytest.raises(ValidationError):
        FeedbackEventContent(
            correlation_id="c",
            about_event_id="$e",
            from_agent="a",
            to_agent="b",
            rating=9,
        )
