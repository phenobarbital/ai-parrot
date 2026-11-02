"""FEAT-788 — remaining FEAT-747 review fixes (issue:d09c6c185547)."""

import asyncio

import pytest

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.endpoint import RoostFailure
from parrot.roost.messages import AgentAddress
from parrot.roost.performatives import FailureCode, InteractionProtocol, Performative

from .test_endpoint import GRANTED, make_endpoint

SCHEMA = {"type": "object", "required": ["salary"], "properties": {"salary": {"type": "integer"}}}


async def _pair(tool_result: object):
    carrier = InProcessCarrier()
    hr = make_endpoint(
        "hr",
        carrier,
        config=RoostAgentConfig(capabilities=["hr.people.salary"], backing="deterministic"),
        tool_result=tool_result,
    )
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await hr.start()
    await caller.start()
    return hr, caller


@pytest.mark.asyncio
async def test_audit_direction_follows_role() -> None:
    """AC-1: every caller-side entry is ``received``, every server-side entry ``served``."""
    hr, caller = await _pair({"salary": 1})
    try:
        await caller.request("hr.people.salary", {}, receiver=AgentAddress(name="hr"), timeout=1)
        assert {e.direction for e in caller.ledger.entries()} == {"received"}
        assert {e.direction for e in hr.ledger.entries()} == {"served"}
        for entry in caller.ledger.entries():
            assert {entry.sender, entry.receiver} == {"caller", "hr"}
        for entry in hr.ledger.entries():
            assert {entry.sender, entry.receiver} == {"caller", "hr"}
    finally:
        await caller.stop()
        await hr.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer,schema",
    [({"salary": "lots"}, SCHEMA), ({"salary": 1}, {"type": "nonsense"})],
)
async def test_query_schema_mismatch_is_typed_failure(answer: object, schema: dict) -> None:
    """AC-2: a non-conforming answer (or an invalid schema) raises ``FailureCode.SCHEMA``."""
    hr, caller = await _pair(answer)
    try:
        with pytest.raises(RoostFailure) as info:
            await caller.query(
                {"tool": "hr_people_salary"}, receiver=AgentAddress(name="hr"), timeout=1, expected_schema=schema
            )
        assert info.value.failure.code is FailureCode.SCHEMA
    finally:
        await caller.stop()
        await hr.stop()


@pytest.mark.asyncio
async def test_query_schema_match_returns_answer() -> None:
    """AC-2: a conforming answer is returned unchanged."""
    result = {"salary": 7}
    hr, caller = await _pair(result)
    try:
        out = await caller.query(
            {"tool": "hr_people_salary"}, receiver=AgentAddress(name="hr"), timeout=1, expected_schema=SCHEMA
        )
        assert out is result
    finally:
        await caller.stop()
        await hr.stop()


@pytest.mark.asyncio
async def test_award_attenuates_winner_grant() -> None:
    """AC-4: the winner's effective grant is the intersection; a tool outside it is refused."""
    carrier = InProcessCarrier()
    bidder = make_endpoint(
        "bidder",
        carrier,
        config=RoostAgentConfig(
            capabilities=["hr.people.salary", "fin.ledger.read"],
            backing="deterministic",
            grant=InterAgentGrant(scopes=["hr.people.*", "fin.*"]),
            bid={"cost": 1.0, "time_ms": 10.0, "confidence": 0.9},
        ),
    )
    requester = make_endpoint("requester", carrier, config=RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"])))
    await bidder.start()
    await requester.start()
    try:
        award = await requester.cfp(capability_filter="hr.people.salary", task={"x": 1}, bid_window_ms=100)
        assert award.winner is not None and award.winner.agent_name == "bidder"
        for _ in range(50):
            if bidder.effective_grant(award_conversation(bidder)) is not None:
                break
            await asyncio.sleep(0.01)
        cid = award_conversation(bidder)
        assert bidder.effective_grant(cid).scopes == ["hr.people.*"]

        refused = []
        bidder._refuse = _capture(refused)  # type: ignore[method-assign]
        from parrot.roost.messages import RoostMessage

        msg = RoostMessage(
            performative=Performative.REQUEST,
            protocol=InteractionProtocol.REQUEST,
            conversation_id=cid,
            sender=AgentAddress(name="requester"),
            receivers=[AgentAddress(name="bidder")],
            content={"tool": "fin_ledger_read"},
            permission_context=object(),
        )
        await bidder._run_tool(msg)
        assert refused and "attenuated" in refused[0]
        bidder.tool_manager.execute_tool.assert_not_awaited()
    finally:
        await requester.stop()
        await bidder.stop()


def award_conversation(ep) -> str:
    return next(iter(ep._awarded_grants), "")


def _capture(sink: list):
    async def _refuse(msg, detail: str) -> None:
        sink.append(detail)

    return _refuse
