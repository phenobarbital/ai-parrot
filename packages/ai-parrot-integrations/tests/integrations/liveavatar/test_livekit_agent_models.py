"""Unit tests for the Phase C data models (FEAT-243, TASK-001).

These tests must pass WITHOUT the ``liveavatar-voice`` extra installed — the
models are pure Pydantic and carry no ``livekit-agents`` import.
"""

import json

import pytest

from parrot.integrations.liveavatar.livekit_agent.models import (
    AvatarJobMetadata,
    StructuredOutputMessage,
)


def test_job_metadata_parsing():
    """``ctx.job.metadata`` JSON parses into a fully-populated model."""
    raw = json.dumps(
        {
            "ws_url": "wss://example.livekit.cloud",
            "session_id": "s1",
            "agent_name": "demo",
            "tenant_id": "t1",
        }
    )

    meta = AvatarJobMetadata.model_validate_json(raw)

    assert meta.ws_url == "wss://example.livekit.cloud"
    assert meta.session_id == "s1"
    assert meta.agent_name == "demo"
    assert meta.tenant_id == "t1"


def test_job_metadata_optional_tenant_defaults_none():
    """``tenant_id`` is optional and defaults to ``None`` (single-tenant)."""
    meta = AvatarJobMetadata(ws_url="wss://x", session_id="s", agent_name="a")
    assert meta.tenant_id is None


def test_job_metadata_requires_core_fields():
    """ws_url / session_id / agent_name are mandatory."""
    with pytest.raises(ValueError):
        AvatarJobMetadata.model_validate({"ws_url": "wss://x"})


def test_structured_output_message_contract():
    """StructuredOutputMessage carries the P4 bridge schema."""
    msg = StructuredOutputMessage(
        type="chart",
        session_id="s1",
        payload={"k": "v"},
    )

    assert msg.type == "chart"
    assert msg.session_id == "s1"
    assert msg.payload == {"k": "v"}
    assert msg.turn_id is None


def test_structured_output_message_roundtrip():
    """model_dump round-trips the full payload including turn_id."""
    msg = StructuredOutputMessage(
        type="data",
        session_id="s2",
        payload={"rows": [1, 2, 3]},
        turn_id="turn-7",
    )

    dumped = msg.model_dump()

    assert dumped == {
        "type": "data",
        "session_id": "s2",
        "payload": {"rows": [1, 2, 3]},
        "turn_id": "turn-7",
    }
    assert StructuredOutputMessage(**dumped) == msg
