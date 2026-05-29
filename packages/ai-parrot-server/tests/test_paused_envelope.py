"""Tests for PausedEnvelope model (FEAT-204 / TASK-1382)."""
from __future__ import annotations

import pytest
from parrot.handlers.agent import PausedEnvelope


def test_paused_envelope_status_is_paused():
    """PausedEnvelope always has status == 'paused'."""
    env = PausedEnvelope(
        turn_id="t1",
        interaction_id="t1",
        interaction_type="free_text",
        question="approve?",
    )
    assert env.status == "paused"


def test_paused_envelope_structured():
    """PausedEnvelope carries turn_id, interaction_type, options correctly."""
    env = PausedEnvelope(
        turn_id="t1",
        interaction_id="t1",
        interaction_type="single_choice",
        question="pick one",
        options=[{"key": "a", "label": "A"}],
        form_schema=None,
    )
    d = env.model_dump()
    assert d["status"] == "paused"
    assert d["options"][0]["key"] == "a"
    assert d["turn_id"] == "t1"
    assert d["interaction_id"] == "t1"
    assert d["interaction_type"] == "single_choice"


def test_paused_envelope_form_type():
    """PausedEnvelope carries form_schema for form-type interactions."""
    schema = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
    env = PausedEnvelope(
        turn_id="t2",
        interaction_id="t2",
        interaction_type="form",
        question="fill form",
        form_schema=schema,
    )
    d = env.model_dump()
    assert d["form_schema"] == schema
    assert d["options"] is None


def test_paused_envelope_optional_fields_default_none():
    """Optional fields default to None."""
    env = PausedEnvelope(
        turn_id="t3",
        interaction_id="t3",
        interaction_type="approval",
        question="approve?",
    )
    d = env.model_dump()
    assert d["context"] is None
    assert d["options"] is None
    assert d["form_schema"] is None
    assert d["default_response"] is None
    assert d["deadline"] is None
    assert d["source_agent"] is None


def test_paused_envelope_turn_id_equals_interaction_id():
    """OQ-1: turn_id wraps interaction_id — they share the same value."""
    env = PausedEnvelope(
        turn_id="iid-xyz",
        interaction_id="iid-xyz",
        interaction_type="approval",
        question="approve?",
    )
    assert env.turn_id == env.interaction_id


def test_paused_envelope_context_and_deadline():
    """context and deadline fields are included when provided."""
    env = PausedEnvelope(
        turn_id="t4",
        interaction_id="t4",
        interaction_type="free_text",
        question="write comment",
        context="Ticket XYZ-123",
        deadline="2026-05-30T12:00:00+00:00",
    )
    d = env.model_dump()
    assert d["context"] == "Ticket XYZ-123"
    assert d["deadline"] == "2026-05-30T12:00:00+00:00"
