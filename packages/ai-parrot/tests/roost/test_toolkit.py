"""Tests for the LLM-facing Roost origin toolkit."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost.directory import CapabilityMatch, Locality
from parrot.roost.messages import AgentAddress
from parrot.roost.performatives import Performative
from parrot.roost.scoring import Award, Bid
from parrot.roost.toolkit import RoostToolkit


def _endpoint() -> MagicMock:
    endpoint = MagicMock()
    endpoint.agent_name = "caller"
    endpoint.send = AsyncMock(return_value=MagicMock(conversation_id="conversation-1"))
    endpoint.cfp = AsyncMock(
        return_value=Award(
            winner=Bid(
                agent_name="worker",
                cost=1.0,
                time_ms=10.0,
                confidence=0.9,
                message_id="bid-1",
            ),
            decided_by="rule",
            rejected=[],
        )
    )
    endpoint.subscribe = AsyncMock(return_value="subscription-1")
    return endpoint


def test_schemas_expose_only_the_performative_enum_and_no_grant() -> None:
    toolkit = RoostToolkit(_endpoint())

    schemas = {tool.name: tool.get_schema() for tool in toolkit.get_tools()}
    serialized = str(schemas).lower()

    assert "grant" not in serialized
    assert "scope" not in serialized
    assert schemas["send"]["parameters"]["properties"]["performative"]["enum"] == [
        "inform",
        "request",
        "query",
        "subscribe",
    ]
    assert not any(name.startswith("delegate") for name in schemas)


@pytest.mark.asyncio
async def test_send_routes_each_enum_value_through_its_protocol() -> None:
    endpoint = _endpoint()
    endpoint.request = AsyncMock(return_value={"salary": 1})
    endpoint.query = AsyncMock(return_value="answer")
    endpoint.inform = AsyncMock(return_value=MagicMock(conversation_id="conversation-2"))
    toolkit = RoostToolkit(endpoint)
    worker = AgentAddress(name="worker")

    assert await toolkit.send("request", "worker", "hr.people.salary") == {"status": "done", "result": {"salary": 1}}
    endpoint.request.assert_awaited_once_with("hr.people.salary", {}, receiver=worker)
    assert await toolkit.send("query", "worker", "why?") == {"status": "done", "result": "answer"}
    endpoint.query.assert_awaited_once_with("why?", receiver=worker)
    result = await toolkit.send("inform", "worker", "fact", body="hi")
    assert result == {"status": "sent", "conversation_id": "conversation-2"}
    endpoint.inform.assert_awaited_once_with(receivers=[worker], content="fact", body="hi")
    endpoint.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_is_fire_and_forget() -> None:
    endpoint = _endpoint()

    result = await RoostToolkit(endpoint).report("worker", "salary is 100")

    assert result == {"status": "sent", "conversation_id": "conversation-1"}
    assert endpoint.send.await_args.args[0] is Performative.INFORM
    assert endpoint.send.await_args.kwargs["receivers"] == [AgentAddress(name="worker")]


@pytest.mark.asyncio
async def test_call_for_proposals_returns_the_serialized_award() -> None:
    endpoint = _endpoint()

    result = await RoostToolkit(endpoint).call_for_proposals("docs.*", "summarize", bid_window_ms=250)

    assert result["winner"]["agent_name"] == "worker"
    assert result["decided_by"] == "rule"
    endpoint.cfp.assert_awaited_once_with(
        capability_filter="docs.*",
        task="summarize",
        bid_window_ms=250,
    )


@pytest.mark.asyncio
async def test_watch_subscribes_to_a_blackboard_key() -> None:
    endpoint = _endpoint()

    result = await RoostToolkit(endpoint).watch("digest")

    assert result == {"status": "subscribed", "subscription_id": "subscription-1"}
    endpoint.subscribe.assert_awaited_once_with(blackboard_key="digest")


@pytest.mark.asyncio
async def test_find_agents_uses_the_callers_grant_filtered_view() -> None:
    endpoint = _endpoint()
    endpoint.registry.find_capability.return_value = [
        CapabilityMatch(
            agent_name="worker",
            cap_id="docs.summary",
            locality=Locality.IN_PROCESS,
            cost=1.0,
        )
    ]

    result = await RoostToolkit(endpoint).find_agents("summary")

    assert result[0]["agent_name"] == "worker"
    endpoint.registry.find_capability.assert_called_once_with("summary", caller="caller")


@pytest.mark.asyncio
async def test_find_agents_without_a_registry_returns_empty() -> None:
    endpoint = _endpoint()
    endpoint.registry = None

    assert await RoostToolkit(endpoint).find_agents("summary") == []
