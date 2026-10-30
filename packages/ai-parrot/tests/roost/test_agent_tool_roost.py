"""Tests for the guarded AgentTool Roost query path."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost.endpoint import RoostFailure
from parrot.roost.messages import AgentAddress, FailureInfo
from parrot.roost.performatives import FailureCode
from parrot.tools.agent import AgentTool


def _agent(*, roost_endpoint: MagicMock | None = None) -> MagicMock:
    agent = MagicMock()
    agent.name = "Worker"
    agent.role = None
    agent.goal = None
    agent.capabilities = None
    agent.conversation = AsyncMock(return_value="legacy answer")
    agent.roost_endpoint = None
    if roost_endpoint is not None:
        agent.roost_endpoint = roost_endpoint
    return agent


def _endpoint(name: str) -> MagicMock:
    endpoint = MagicMock()
    endpoint.agent_name = name
    endpoint.address.return_value = AgentAddress(name=name)
    endpoint.query = AsyncMock(return_value={"salary": 100})
    endpoint.working_memory = MagicMock()
    endpoint.working_memory.store_result = AsyncMock(return_value={"status": "stored"})
    return endpoint


@pytest.mark.asyncio
async def test_roost_path_queries_target_and_stores_native_answer() -> None:
    caller = _endpoint("caller")
    target = _endpoint("worker")
    tool = AgentTool(agent=_agent(roost_endpoint=target))

    result = await tool._execute(question="What is the salary?", _roost_caller=caller)

    assert result == "Answer stored in working memory as 'roost:worker:1'"
    caller.query.assert_awaited_once_with("What is the salary?", receiver=AgentAddress(name="worker"))
    caller.working_memory.store_result.assert_awaited_once_with(
        key="roost:worker:1",
        data={"salary": 100},
        data_type="auto",
    )


@pytest.mark.asyncio
async def test_roost_failure_returns_an_error_string() -> None:
    caller = _endpoint("caller")
    target = _endpoint("worker")
    caller.query.side_effect = RoostFailure(FailureInfo(code=FailureCode.TIMEOUT, detail="query timed out"))
    tool = AgentTool(agent=_agent(roost_endpoint=target))

    result = await tool._execute(question="What is the salary?", _roost_caller=caller)

    assert result == "Error: TIMEOUT: query timed out"
    caller.working_memory.store_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_working_memory_returns_an_error_string() -> None:
    caller = _endpoint("caller")
    caller.working_memory = None
    target = _endpoint("worker")
    tool = AgentTool(agent=_agent(roost_endpoint=target))

    result = await tool._execute(question="What is the salary?", _roost_caller=caller)

    assert result == "Error: Roost caller has no working memory"


@pytest.mark.asyncio
async def test_missing_caller_preserves_the_legacy_path() -> None:
    target = _endpoint("worker")
    agent = _agent(roost_endpoint=target)
    tool = AgentTool(agent=agent)

    result = await tool._execute(question="Use the legacy path")

    assert result == "legacy answer"
    agent.conversation.assert_awaited_once()
    target.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_target_preserves_the_legacy_path() -> None:
    caller = _endpoint("caller")
    agent = _agent()
    tool = AgentTool(agent=agent)

    result = await tool._execute(question="Use the legacy path", _roost_caller=caller)

    assert result == "legacy answer"
    agent.conversation.assert_awaited_once()
    caller.query.assert_not_awaited()
