"""GateError surfacing in the devloop bridge and dispatch service (TASK-5619)."""

from __future__ import annotations

import logging

import pytest

from parrot.bots.flows.core.gates import GateError, GateErrorCode
from parrot.integrations.devloop import service as svc
from parrot.integrations.devloop.bridge import LoopbackRestChannel, gate_error_result
from parrot.integrations.devloop.models import Requester, RunRecord

_REQ = Requester(transport="slack", tenant_id="T", user_id="U1")


@pytest.mark.parametrize(
    "code,status,reason",
    [
        (GateErrorCode.NOT_FOUND, 404, "not_found"),
        (GateErrorCode.NOT_PENDING, 409, "already_resolved"),
        (GateErrorCode.STORE_UNAVAILABLE, 400, "STORE_UNAVAILABLE"),
    ],
)
def test_gate_error_result_mapping(code, status, reason):
    res = gate_error_result(GateError(code, "x"))
    assert (res.ok, res.status, res.reason) == (False, status, reason)


@pytest.mark.asyncio
async def test_bridge_resolve_gate_catches_gate_error(monkeypatch):
    ch = LoopbackRestChannel("unix:///tmp/none.sock", token="t")

    async def _boom(path, body):
        raise GateError(GateErrorCode.NOT_PENDING, "done")

    monkeypatch.setattr(ch, "_post", _boom)
    res = await ch.resolve_gate("r", "g", resolution="approved", resolved_by="u")
    assert res.reason == "already_resolved" and res.status == 409


class _RaisingChannel:
    def __init__(self, code):
        self.code = code

    async def resolve_gate(self, *a, **kw):
        raise GateError(self.code, "nope")


def _service(code):
    s = object.__new__(svc.DevLoopDispatchService)
    s.logger = logging.getLogger("test")

    async def _owned(run_id, requester):
        return object()

    s._require_owned = _owned
    s._channel = lambda record: _RaisingChannel(code)
    return s


@pytest.mark.asyncio
async def test_service_resolve_gate_reports_not_found():
    res = await _service(GateErrorCode.NOT_FOUND).resolve_gate("r", "g", _REQ, "approved")
    assert res.reason == "not_found"


@pytest.mark.asyncio
async def test_service_answer_gate_reports_not_pending():
    res = await _service(GateErrorCode.NOT_PENDING).answer_gate("r", "g", _REQ, {"q": "a"})
    assert res.reason == "already_resolved"
