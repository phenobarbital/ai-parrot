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


# --- FEAT-786: fail-closed endpoint callers -----------------------------------------------------


@pytest.mark.asyncio
async def test_grant_denied_returns_an_error_string() -> None:
    from parrot.roost.grant import GrantDenied

    caller = _endpoint("caller")
    caller.query.side_effect = GrantDenied("worker")
    tool = AgentTool(agent=_agent(roost_endpoint=_endpoint("worker")))

    result = await tool._execute(question="What is the salary?", _roost_caller=caller)

    assert result == "Error: grant denied: worker"
    caller.working_memory.store_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_permission_context_is_bound_only_during_the_query() -> None:
    from parrot.auth.context import _pctx_var

    seen: list[object] = []
    caller = _endpoint("caller")

    async def _query(*args, **kwargs):
        seen.append(_pctx_var.get())
        return {"salary": 100}

    caller.query.side_effect = _query
    pctx = object()
    tool = AgentTool(agent=_agent(roost_endpoint=_endpoint("worker")))
    tool._current_pctx = pctx

    await tool._execute(question="q", _roost_caller=caller)

    assert seen == [pctx]
    assert _pctx_var.get() is None


@pytest.mark.asyncio
async def test_no_call_context_keeps_the_ambient_request_context() -> None:
    from parrot.auth.context import _pctx_var

    seen: list[object] = []
    caller = _endpoint("caller")

    async def _query(*args, **kwargs):
        seen.append(_pctx_var.get())
        return {"salary": 100}

    caller.query.side_effect = _query
    ambient = object()
    token = _pctx_var.set(ambient)
    try:
        tool = AgentTool(agent=_agent(roost_endpoint=_endpoint("worker")))
        await tool._execute(question="q", _roost_caller=caller)
        assert seen == [ambient]
        assert _pctx_var.get() is ambient
    finally:
        _pctx_var.reset(token)


@pytest.mark.asyncio
async def test_execute_entrypoint_binds_the_tool_manager_context() -> None:
    """End to end through AbstractTool.execute: the ``_permission_context`` kwarg reaches the endpoint."""
    from parrot.auth.context import _pctx_var

    seen: list[object] = []
    caller = _endpoint("caller")

    async def _query(*args, **kwargs):
        seen.append(_pctx_var.get())
        return {"salary": 100}

    caller.query.side_effect = _query
    tool = AgentTool(agent=_agent(roost_endpoint=_endpoint("worker")))
    tool.roost_caller = caller
    pctx = MagicMock()

    await tool.execute(question="q", _permission_context=pctx)

    assert seen == [pctx]
    assert _pctx_var.get() is None
