"""Tests for inter-agent message models and EnvelopeLike compatibility."""

import secrets
import pytest
from typing import Protocol, runtime_checkable

from parrot.interagent import (
    Budget,
    CallMessage,
    CancelMessage,
    HelloMessage,
    ProgressMessage,
    ResultMessage,
    WelcomeMessage,
    PROTOCOL_MAJOR,
    CallCost,
    CallerIdentity,
    CapabilityCategory,
    ContractDelta,
    SquawkCapability,
    SquawkContract,
    ReturnsSpec,
    PolicyAnnotations,
)
from parrot.interagent.errors import SquawkErrorCode


def test_budget_model() -> None:
    """Budget model accepts all constraint types."""
    budget = Budget(tokens=1000, ms=5000, rows=100)
    assert budget.tokens == 1000
    assert budget.ms == 5000
    assert budget.rows == 100


def test_budget_partial() -> None:
    """Budget model accepts partial constraints."""
    budget = Budget(ms=5000)
    assert budget.tokens is None
    assert budget.ms == 5000


def test_budget_frozen() -> None:
    """Budget is frozen and immutable."""
    budget = Budget(ms=5000)
    with pytest.raises(Exception):  # pydantic freezes the model
        budget.ms = 1000


def test_hello_message() -> None:
    """HelloMessage model accepts all fields."""
    msg = HelloMessage(
        agent_id="hr.agent",
        token=b"secret-token",
        known_hashes={"hr.reports": "sha256:abc"},
        known_digests=("sha256:def",),
        trace_id="0" * 32,
    )
    assert msg.protocol_major == PROTOCOL_MAJOR
    assert msg.agent_id == "hr.agent"
    assert msg.token == b"secret-token"


def test_welcome_message() -> None:
    """WelcomeMessage model accepts contract delta."""
    category = CapabilityCategory(
        name="hr.reports",
        capabilities=(
            SquawkCapability(
                cap_id="hr.reports.list",
                category="hr.reports",
                description="List reports",
                input_schema={"type": "object"},
                returns=ReturnsSpec(kind="inline", schema={"type": "object"}),
                backing="deterministic",
            ),
        ),
    )
    contract = SquawkContract(agent_id="hr", major=1, categories=(category,))
    delta = ContractDelta(changed=(category,), unchanged=(), removed=())

    msg = WelcomeMessage(
        session_id="sess-123",
        delta=delta,
        max_frame_bytes=65536,
    )
    assert msg.session_id == "sess-123"
    assert len(msg.delta.changed) == 1


def test_call_message_basic() -> None:
    """CallMessage model accepts all fields."""
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.list",
        contract_hash="sha256:" + "0" * 64,
        args=b'{"query": "test"}',
        budget=Budget(ms=5000),
        trace_id="0" * 32,
        correlation_id="corr-1",
        idempotency_key="idem-1",
    )
    assert msg.envelope_id == "e1"
    assert msg.cap_id == "hr.reports.list"


def test_call_message_trace_property() -> None:
    """CallMessage.trace returns a TraceContext with correct kwargs."""
    trace_id = "0" * 32
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.list",
        contract_hash="sha256:" + "0" * 64,
        args=b"test",
        trace_id=trace_id,
        correlation_id="corr-1",
        idempotency_key="idem-1",
    )
    ctx = msg.trace
    assert ctx.trace_id == trace_id
    assert len(ctx.span_id) == 16  # 8 bytes = 16 hex chars


def test_call_message_budget_properties() -> None:
    """CallMessage exposes budget_ms and token_budget properties."""
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.list",
        contract_hash="sha256:" + "0" * 64,
        args=b"test",
        budget=Budget(tokens=1000, ms=5000),
        trace_id="0" * 32,
        correlation_id="corr-1",
        idempotency_key="idem-1",
    )
    assert msg.budget_ms == 5000
    assert msg.token_budget == 1000


def test_call_message_with_caller() -> None:
    """CallMessage accepts optional caller identity."""
    caller = CallerIdentity(agent_id="client.agent", network="local", subject="user-1")
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.list",
        contract_hash="sha256:" + "0" * 64,
        args=b"test",
        trace_id="0" * 32,
        correlation_id="corr-1",
        idempotency_key="idem-1",
        caller=caller,
    )
    assert msg.caller is not None
    assert msg.caller.agent_id == "client.agent"


def test_result_message_ok() -> None:
    """ResultMessage with OK status accepts inline data."""
    msg = ResultMessage(
        status="OK",
        inline=b"result data",
        transfer="none",
        cost=CallCost(tokens_in=100, tokens_out=200, duration_ms=500),
        trace_id="0" * 32,
        correlation_id="corr-1",
    )
    assert msg.status == "OK"
    assert msg.inline == b"result data"


def test_result_message_error() -> None:
    """ResultMessage with error code."""
    msg = ResultMessage(
        status=SquawkErrorCode.POLICY_DENIED,
        cost=CallCost(tokens_in=100, tokens_out=200, duration_ms=500),
        trace_id="0" * 32,
        correlation_id="corr-1",
        detail="Access denied",
    )
    assert msg.status == SquawkErrorCode.POLICY_DENIED
    assert msg.detail == "Access denied"


def test_progress_message() -> None:
    """ProgressMessage model."""
    msg = ProgressMessage(
        op_id="op-1",
        phase="processing",
        frame=b"frame-bytes",
        frame_index=0,
        is_last=False,
    )
    assert msg.op_id == "op-1"
    assert msg.frame == b"frame-bytes"


def test_cancel_message() -> None:
    """CancelMessage model."""
    msg = CancelMessage(op_id="op-1", trace_id="0" * 32)
    assert msg.op_id == "op-1"


# EnvelopeLike structural check (AC22)
@runtime_checkable
class EnvelopeLike(Protocol):
    """Minimal EnvelopeLike protocol matching Roost's spec."""

    envelope_id: str
    correlation_id: str
    trace_id: str
    budget_ms: int | None
    token_budget: int | None
    caller: CallerIdentity | None
    idempotency_key: str


def test_call_message_satisfies_envelope_like() -> None:
    """CallMessage structurally satisfies EnvelopeLike protocol."""
    msg = CallMessage(
        envelope_id="e1",
        cap_id="hr.reports.list",
        contract_hash="sha256:" + "0" * 64,
        args=b"test",
        budget=Budget(tokens=1000, ms=5000),
        trace_id="0" * 32,
        correlation_id="corr-1",
        idempotency_key="idem-1",
    )
    # Verify runtime_checkable protocol
    assert isinstance(msg, EnvelopeLike)
    # Verify attribute presence
    assert hasattr(msg, "envelope_id")
    assert hasattr(msg, "correlation_id")
    assert hasattr(msg, "trace_id")
    assert hasattr(msg, "budget_ms")
    assert hasattr(msg, "token_budget")
    assert hasattr(msg, "caller")
    assert hasattr(msg, "idempotency_key")
    # Verify values
    assert msg.envelope_id == "e1"
    assert msg.correlation_id == "corr-1"
    assert msg.budget_ms == 5000
    assert msg.token_budget == 1000
    assert msg.idempotency_key == "idem-1"


def test_extra_fields_forbidden() -> None:
    """Models forbid extra fields."""
    with pytest.raises(Exception):
        Budget(extra_field="not allowed")  # type: ignore[arg-type]

    with pytest.raises(Exception):
        CallMessage(
            envelope_id="e1",
            cap_id="c",
            contract_hash="h",
            args=b"a",
            trace_id="0" * 32,
            correlation_id="c",
            idempotency_key="k",
            extra_field="not allowed",  # type: ignore[arg-type]
        )