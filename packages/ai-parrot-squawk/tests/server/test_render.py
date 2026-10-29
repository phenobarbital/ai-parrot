"""Tests for server/render.py."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from parrot.interagent import (
    BusPayloadSerializer,
    CallCost,
    CallMessage,
    CallerIdentity,
    ProgressMessage,
    ResultMessage,
    ServedLedgerEntry,
    CancelMessage,
)
from parrot.squawk.server.render import render_entry, render_envelope

_SER = BusPayloadSerializer()


def test_render_entry_basic():
    e = ServedLedgerEntry(
        entry_id="e1",
        created_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        caller=CallerIdentity(agent_id="agent1", network="net1", subject="subj1"),
        cap_id="cap1",
        category="cat1",
        contract_hash="h1",
        args_digest="sha256:abc123",
        result_kind="inline",
        result_digest="sha256:def456",
        cost=CallCost(duration_ms=100, tokens_in=10, tokens_out=20),
        backing="llm_backed",
        status="OK",
        trace_id="trace1",
        signature="sig1234567890ab",
        policy_applied=["p1", "p2"],
        data_classes=["c1", "c2"],
    )
    out = render_entry(e)
    assert "[2025-01-01T12:00:00+00:00]" in out
    assert "OK cap1" in out
    assert "caller=agent1@net1" in out
    assert "backing=llm_backed" in out
    assert "args=sha256:abc123" in out
    assert "result=inline:sha256:def456" in out
    assert "cost=100ms/10+20tok" in out
    assert "policy=p1,p2" in out
    assert "classes=c1,c2" in out
    assert "trace=trace1" in out
    assert "sig=sig123456789…" in out


def test_render_envelope_call():
    msg = CallMessage(
        envelope_id="env1",
        cap_id="cap1",
        contract_hash="h1",
        args=b"args123",
        budget={},
        correlation_id="corr1",
        idempotency_key="idem1",
        trace_id="trace1",
        reply_to=None,
    )
    payload = _SER.to_payload(msg)
    out = render_envelope(payload)
    assert "CALL cap1" in out
    assert "hash=h1" in out
    assert "args=<" in out and "bytes sha256:" in out
    assert "corr=corr1" in out
    assert "idem=idem1" in out
    assert "trace=trace1" in out


def test_render_envelope_result():
    msg = ResultMessage(
        status="OK",
        inline=b"detail123",
        transfer="none",
        cost=CallCost(duration_ms=50, tokens_in=5, tokens_out=10),
        trace_id="trace1",
        correlation_id="corr1",
    )
    payload = _SER.to_payload(msg)
    out = render_envelope(payload)
    assert "RESULT" in out
    assert "status=OK" in out
    assert "transfer=none" in out
    assert "cost=50ms/5+10tok" in out
    assert "inline=<" in out and "bytes sha256:" in out
    assert "detail123" not in out
    assert "trace=trace1" in out


def test_render_envelope_progress():
    msg = ProgressMessage(
        op_id="op1",
        phase="phase1",
        frame_index=1,
        frame=b"frame123",
        is_last=True,
    )
    payload = _SER.to_payload(msg)
    out = render_envelope(payload)
    assert "PROGRESS op=op1" in out
    assert "phase=phase1" in out
    assert "frame#1" in out
    assert "<8 bytes sha256:" in out
    assert "last=True" in out


def test_render_envelope_cancel():
    msg = CancelMessage(op_id="op1", trace_id="trace1")
    payload = _SER.to_payload(msg)
    out = render_envelope(payload)
    assert "CANCEL op=op1" in out
    assert "trace=trace1" in out
