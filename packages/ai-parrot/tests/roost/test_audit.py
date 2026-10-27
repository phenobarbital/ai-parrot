"""Tests for the Roost audit ledger (FEAT-747 M10)."""

import hashlib
from unittest.mock import AsyncMock

import pytest

from parrot.roost.audit import RoostAuditLedger
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP
from parrot.roost.performatives import Performative as P
from parrot.security.audit_ledger import AuditLedger


def _msg(envelope, content=None, **kw) -> RoostMessage:
    return RoostMessage(
        performative=P.INFORM,
        protocol=IP.INFORM,
        conversation_id=kw.pop("conversation_id", "c"),
        envelope=envelope,
        sender=AgentAddress(name="a"),
        receivers=[AgentAddress(name="b")],
        content=content,
        **kw,
    )


async def test_sign_verify_join(envelope):
    led = RoostAuditLedger()
    m = _msg(envelope, content={"salary": 1})
    s = await led.record(m, direction="received", self_name="a")
    r = await led.record(m, direction="served", self_name="b")
    assert await led.verify(s) and await led.verify(r)
    assert len(led.entries(trace_id=m.trace_id())) == 2
    assert {e.direction for e in led.entries(trace_id=m.trace_id())} == {"served", "received"}
    s.body = "tampered"
    assert not await led.verify(s)


async def test_filters_and_digests(envelope):
    led = RoostAuditLedger()
    e1 = await led.record(_msg(envelope, content="handle-1"), direction="served", self_name="b")
    e2 = await led.record(_msg(envelope, content=object(), conversation_id="d"), direction="served", self_name="b")
    assert e1.result_digest == hashlib.sha256(b"handle-1").hexdigest()
    assert e2.result_digest is None
    assert led.entries(conversation_id="d") == [e2]
    assert led.entries(trace_id="nope") == []


async def test_storage_fail_closed(envelope):
    storage = AsyncMock()
    storage.store.side_effect = RuntimeError("down")
    led = RoostAuditLedger(storage=storage)
    with pytest.raises(RuntimeError):
        await led.record(_msg(envelope), direction="served", self_name="b")
    assert led.entries() == []


async def test_never_calls_audit_ledger_append(envelope, monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr(AuditLedger, "append", called)
    storage = AsyncMock()
    led = RoostAuditLedger(storage=storage)
    entry = await led.record(_msg(envelope), direction="served", self_name="b")
    storage.store.assert_awaited_once_with(entry)
    called.assert_not_called()
