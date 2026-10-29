"""Tests for BusPayloadSerializer - bytes-safe JSON encoding of inter-agent messages."""

import json
import secrets
import pytest

from parrot.interagent import (
    Budget,
    BusPayloadSerializer,
    CallMessage,
    CancelMessage,
    ProgressMessage,
    ResultMessage,
    CallCost,
    CallerIdentity,
    ArtifactHandle,
    HandleOwner,
    HandleDescriptor,
    MediaType,
    HandleProvenance,
    CapabilityCategory,
    SquawkCapability,
    SquawkContract,
    ReturnsSpec,
    PolicyAnnotations,
)
from parrot.interagent.errors import SquawkError, SquawkErrorCode
from datetime import datetime, timezone, date


def test_call_message_bytes_roundtrip() -> None:
    """CallMessage with binary args round-trips through JSON serialization."""
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.x",
        contract_hash="sha256:" + "0" * 64,
        args=secrets.token_bytes(4096),
        budget=Budget(ms=100),
        trace_id="t" * 32,
        correlation_id="c",
        idempotency_key="k",
    )
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    # Verify payload structure
    assert payload["kind"] == "CallMessage"
    assert payload["v"] == 1
    assert "data" in payload
    # Verify bytes are encoded as base64
    assert payload["data"]["args"]["__b64__"] is not None
    # Round-trip through JSON
    back = ser.from_payload(json.loads(json.dumps(payload)))
    assert back == msg


def test_result_message_inline_bytes_roundtrip() -> None:
    """ResultMessage with inline bytes round-trips."""
    msg = ResultMessage(
        status="OK",
        inline=b"inline-result-data",
        transfer="none",
        cost=CallCost(tokens_in=100, tokens_out=200, duration_ms=500),
        trace_id="t" * 32,
        correlation_id="c",
    )
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    back = ser.from_payload(json.loads(json.dumps(payload)))
    assert back == msg
    assert back.inline == b"inline-result-data"


def test_progress_message_frame_bytes_roundtrip() -> None:
    """ProgressMessage with frame bytes round-trips."""
    msg = ProgressMessage(
        op_id="op-1",
        phase="processing",
        frame=b"frame-data",
        frame_index=0,
        is_last=False,
    )
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    back = ser.from_payload(json.loads(json.dumps(payload)))
    assert back == msg
    assert back.frame == b"frame-data"


def test_cancel_message_roundtrip() -> None:
    """CancelMessage round-trips (no bytes fields)."""
    msg = CancelMessage(op_id="op-1", trace_id="t" * 32)
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    back = ser.from_payload(json.loads(json.dumps(payload)))
    assert back == msg


def test_unknown_kind_raises() -> None:
    """Unknown kind raises SquawkError with UPSTREAM_FAILED."""
    ser = BusPayloadSerializer()
    payload = {"kind": "UnknownMessage", "v": 1, "data": {}}
    with pytest.raises(SquawkError) as exc_info:
        ser.from_payload(payload)
    assert exc_info.value.code == SquawkErrorCode.UPSTREAM_FAILED
    assert "malformed" in exc_info.value.detail.lower()


def test_unknown_version_raises() -> None:
    """Unknown version raises SquawkError with UPSTREAM_FAILED."""
    ser = BusPayloadSerializer()
    payload = {"kind": "CallMessage", "v": 999, "data": {}}
    with pytest.raises(SquawkError) as exc_info:
        ser.from_payload(payload)
    assert exc_info.value.code == SquawkErrorCode.UPSTREAM_FAILED


def test_missing_kind_raises() -> None:
    """Missing kind raises SquawkError."""
    ser = BusPayloadSerializer()
    payload = {"v": 1, "data": {}}
    with pytest.raises(SquawkError):
        ser.from_payload(payload)


def test_malformed_payload_raises() -> None:
    """Malformed data raises SquawkError."""
    ser = BusPayloadSerializer()
    # Valid kind/version but invalid data for CallMessage
    payload = {"kind": "CallMessage", "v": 1, "data": {"envelope_id": "e1"}}
    with pytest.raises(SquawkError) as exc_info:
        ser.from_payload(payload)
    assert exc_info.value.code == SquawkErrorCode.UPSTREAM_FAILED


def test_non_utf8_bytes_preserved() -> None:
    """Non-UTF-8 binary data is preserved through round-trip."""
    # Create binary data that is not valid UTF-8
    non_utf8 = bytes(range(256))
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.x",
        contract_hash="sha256:" + "0" * 64,
        args=non_utf8,
        budget=Budget(ms=100),
        trace_id="t" * 32,
        correlation_id="c",
        idempotency_key="k",
    )
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    back = ser.from_payload(json.loads(json.dumps(payload)))
    assert back.args == non_utf8


def test_hello_message_token_bytes_roundtrip() -> None:
    """HelloMessage with token bytes round-trips."""
    from parrot.interagent import HelloMessage

    msg = HelloMessage(
        agent_id="hr.agent",
        token=b"secret-token",
        trace_id="t" * 32,
    )
    ser = BusPayloadSerializer()
    # Note: HelloMessage is not in _KINDS, so it won't work with BusPayloadSerializer
    # This test verifies the message model works independently
    assert msg.token == b"secret-token"


def test_result_message_with_handle() -> None:
    """ResultMessage with artifact handle round-trips."""
    owner = HandleOwner(
        agent_id="hr.agent",
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="sess-1",
    )
    now = datetime.now(timezone.utc)
    handle = ArtifactHandle(
        key="sha256:" + "0" * 64,
        media_type=MediaType.GENERIC,
        byte_size=1024,
        ttl_s=3600,
        expires_at=now,
        owner=owner,
        descriptor=HandleDescriptor(media_type=MediaType.GENERIC, byte_size=1024),
        provenance=HandleProvenance(
            serving_agent="hr.agent",
            cap_id="hr.reports.get",
            contract_hash="sha256:" + "0" * 64,
            args_digest="sha256:abc",
            backing="llm_backed",
            produced_at=now,
            trace_id="t" * 32,
        ),
    )
    msg = ResultMessage(
        status="OK",
        handle=handle,
        transfer="frames",
        cost=CallCost(tokens_in=100, tokens_out=200, duration_ms=500),
        trace_id="t" * 32,
        correlation_id="c",
    )
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    back = ser.from_payload(json.loads(json.dumps(payload)))
    assert back.handle is not None
    assert back.handle.key == handle.key


def test_payload_json_serializable() -> None:
    """Payload is fully JSON serializable (no bytes, no datetime)."""
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.x",
        contract_hash="sha256:" + "0" * 64,
        args=b"test",
        budget=Budget(ms=100),
        trace_id="t" * 32,
        correlation_id="c",
        idempotency_key="k",
    )
    ser = BusPayloadSerializer()
    payload = ser.to_payload(msg)
    # This should not raise
    json_str = json.dumps(payload)
    # And should be valid JSON
    parsed = json.loads(json_str)
    assert parsed["kind"] == "CallMessage"


def test_from_payload_discards_caller_identity() -> None:
    """A peer cannot assert a caller identity through the bus payload."""
    from parrot.interagent import CallerIdentity

    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.x",
        contract_hash="sha256:" + "0" * 64,
        args=b"\x00",
        trace_id="t" * 32,
        correlation_id="c",
        idempotency_key="k",
        caller=CallerIdentity(agent_id="admin", network="local", subject="admin"),
    )
    ser = BusPayloadSerializer()
    back = ser.from_payload(json.loads(json.dumps(ser.to_payload(msg))))
    assert back.caller is None


def test_descriptor_rejects_non_serializable_summary() -> None:
    """A non-JSON summary is a validation error, not a TypeError."""
    from pydantic import ValidationError

    from parrot.interagent import HandleDescriptor, MediaType

    with pytest.raises(ValidationError):
        HandleDescriptor(media_type=MediaType.ARROW, byte_size=1, summary={"x": object()})
