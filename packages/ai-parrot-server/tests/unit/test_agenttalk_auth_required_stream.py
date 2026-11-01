"""FEAT-777 M4: AgentTalk auth-required responses in both modes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2.models import AuthRequiredEnvelope
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement
from parrot.auth.retry_safety import track_turn
from parrot.handlers.agent import AgentTalk


def _handler() -> AgentTalk:
    """Build the minimal AgentTalk instance needed by the response helpers."""
    handler = object.__new__(AgentTalk)
    handler.logger = Mock()
    return handler


def _payload(*, provider: str = "o365", tool_name: str = "calendar_create") -> AuthRequiredPayload:
    """Build a needs-auth payload with device-code fields."""
    return AuthRequiredPayload(
        provider=provider,
        tool_name=tool_name,
        message="Connect your account",
        auth_kind="device_code",
        auth_url="https://example.test/start",
        user_code="ABCD-EFGH",
        verification_uri="https://example.test/device",
        expires_in=900,
    )


@pytest.mark.asyncio
async def test_agenttalk_stream_auth_required_trailer() -> None:
    """The trailer follows the envelope and preserves device-code payload fields."""
    handler = _handler()
    stream_resp = SimpleNamespace(write=AsyncMock(), drain=AsyncMock())
    ai_message = SimpleNamespace(turn_id="t1", tool_calls=[SimpleNamespace(name="calendar_create")])

    with collect_auth_requirements() as pending, track_turn() as tracker:
        payload = _payload()
        record_auth_requirement(payload)
        tracker.mark_dispatch()
        tracker.mark_pre_body_auth_failure()
        handler._turn_auth_pending = pending
        await handler._write_auth_required_trailer(stream_resp, ai_message)

    trailer = stream_resp.write.await_args.args[0]
    assert trailer.startswith(b"\n\x00")
    data = json.loads(trailer[2:])
    assert data["auth_required"]["user_code"] == "ABCD-EFGH"
    assert data["auth_required"]["verification_uri"] == "https://example.test/device"
    assert data["turn_id"] == "t1"
    assert data["retry_safe"] is True


@pytest.mark.asyncio
async def test_agenttalk_auth_required_from_tool_result() -> None:
    """A collected payload becomes an envelope, while an empty collector stays a normal reply."""
    handler = _handler()
    ai_message = SimpleNamespace(tool_calls=[SimpleNamespace(name="calendar_create")])

    with collect_auth_requirements() as pending, track_turn() as tracker:
        record_auth_requirement(_payload())
        tracker.mark_dispatch()
        tracker.mark_pre_body_auth_failure()
        handler._turn_auth_pending = pending
        auth = handler._turn_auth_requirement(ai_message)

    assert auth is not None
    payload, retry_safe = auth
    envelope = AuthRequiredEnvelope(**payload.model_dump(), retry_safe=retry_safe)
    assert envelope.model_dump()["type"] == "auth_required"
    assert envelope.retry_safe is True

    handler._turn_auth_pending = []
    assert handler._turn_auth_requirement(ai_message) is None


@pytest.mark.asyncio
async def test_agenttalk_retry_safety() -> None:
    """Only one pre-dispatch requirement is retry-safe; bodies and multiple requirements are not."""
    handler = _handler()
    ai_message = SimpleNamespace(tool_calls=[SimpleNamespace(), SimpleNamespace()])

    with collect_auth_requirements() as pending, track_turn() as tracker:
        record_auth_requirement(_payload())
        tracker.mark_dispatch()
        tracker.mark_body_started()
        handler._turn_auth_pending = pending
        assert handler._turn_auth_requirement(ai_message) == (pending[0], False)

    with collect_auth_requirements() as pending, track_turn() as tracker:
        record_auth_requirement(_payload())
        record_auth_requirement(_payload(tool_name="calendar_delete"))
        tracker.mark_dispatch()
        tracker.mark_pre_body_auth_failure()
        tracker.mark_dispatch()
        tracker.mark_pre_body_auth_failure()
        handler._turn_auth_pending = pending
        assert handler._turn_auth_requirement(ai_message) == (pending[0], False)
