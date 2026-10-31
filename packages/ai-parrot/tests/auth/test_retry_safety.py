"""FEAT-777 M4: turn-local execution evidence."""

import asyncio
from types import SimpleNamespace

import pytest

from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import CredentialResolver
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.pending import collect_auth_requirements
from parrot.auth.retry_safety import TurnExecutionTracker, current_turn_tracker, track_turn
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


def test_unbound_tracker_is_noop() -> None:
    assert current_turn_tracker() is None


def test_single_pre_body_auth_failure_is_safe() -> None:
    """One dispatch, gate refused before body, one requirement -> safe."""
    with track_turn() as t:
        assert current_turn_tracker() is t
        t.mark_dispatch()
        t.mark_pre_body_auth_failure()
        assert t.retry_safe(auth_requirements=1, reported_tool_calls=1) is True
    assert current_turn_tracker() is None


def test_body_started_or_multiple_requirements_is_unsafe() -> None:
    """Any body start, two requirements, unexplained dispatch, or mark_incomplete -> unsafe."""

    def fresh() -> TurnExecutionTracker:
        t = TurnExecutionTracker()
        t.mark_dispatch()
        t.mark_pre_body_auth_failure()
        return t

    assert fresh().retry_safe(auth_requirements=1, reported_tool_calls=1)
    t = fresh()
    t.mark_body_started()
    assert not t.retry_safe(auth_requirements=1, reported_tool_calls=1)
    assert not fresh().retry_safe(auth_requirements=2, reported_tool_calls=1)
    assert not fresh().retry_safe(auth_requirements=0, reported_tool_calls=1)
    t = fresh()
    t.mark_dispatch()  # unexplained dispatch
    assert not t.retry_safe(auth_requirements=1, reported_tool_calls=2)
    assert not fresh().retry_safe(auth_requirements=1, reported_tool_calls=2)
    t = fresh()
    t.mark_incomplete("cancelled")
    assert not t.retry_safe(auth_requirements=1, reported_tool_calls=1)
    assert not TurnExecutionTracker().retry_safe(auth_requirements=1, reported_tool_calls=0)


@pytest.mark.asyncio
async def test_parallel_children_share_tracker_and_turns_are_isolated() -> None:
    """gather() children update one tracker; two concurrent track_turn() contexts never mix."""

    async def child() -> None:
        await asyncio.sleep(0)
        current_turn_tracker().mark_dispatch()

    async def turn(n: int) -> int:
        with track_turn() as t:
            await asyncio.gather(*(child() for _ in range(n)))
            await asyncio.sleep(0)
            return t.dispatches

    assert await asyncio.gather(turn(2), turn(5)) == [2, 5]
    assert current_turn_tracker() is None


class _GatedTool(AbstractTool):
    name = "gated_tool"
    description = "Needs creds"
    credential_provider = "testprovider"
    body_runs = 0

    async def _execute(self, **kwargs) -> ToolResult:
        type(self).body_runs += 1
        return ToolResult(status="success", result="ok", metadata={})


def _broker(token):
    broker = CredentialBroker()

    class _Resolver(CredentialResolver):
        async def resolve(self, channel, user_id):
            return token

        async def get_auth_url(self, channel, user_id):
            return "https://example.com/auth"

    broker.register("testprovider", _Resolver())
    return broker


class _Observer:
    def __init__(self) -> None:
        self.events = []

    async def begin(self, tool_name):
        self.events.append(("begin", tool_name))
        return tool_name

    async def finish(self, observed, **kw):
        self.events.append(("finish", observed))

    async def cancelled(self, observed):
        self.events.append(("cancelled", observed))


@pytest.mark.asyncio
async def test_toolmanager_marks_and_records() -> None:
    """Broker NeedsAuth -> 1 dispatch, 1 pre-body failure, 0 bodies, one payload; plain function -> 1 body."""
    ctx = PermissionContext(
        session=UserSession(user_id="alice@example.com", tenant_id="t", roles=frozenset()), channel="chat"
    )
    manager = ToolManager()
    manager.add_tool(_GatedTool())
    manager.set_broker(_broker(None))
    _GatedTool.body_runs = 0

    with track_turn() as t, collect_auth_requirements() as pending:
        result = await manager.execute_tool("gated_tool", {}, permission_context=ctx, return_tool_result=True)
    assert result.status == "authorization_required"
    assert (t.dispatches, t.pre_body_auth_failures, t.bodies_started) == (1, 1, 0)
    assert len(pending) == 1 and pending[0].provider == "testprovider"
    assert _GatedTool.body_runs == 0
    assert t.retry_safe(auth_requirements=len(pending), reported_tool_calls=1)

    # Credential hit: body runs, so the turn is unsafe.
    manager.set_broker(_broker("tok"))
    with track_turn() as t2, collect_auth_requirements() as pending2:
        await manager.execute_tool("gated_tool", {}, permission_context=ctx, return_tool_result=True)
    assert (t2.dispatches, t2.bodies_started) == (1, 1)
    assert pending2 == []


@pytest.mark.asyncio
async def test_plain_function_marks_body_and_observer_retained() -> None:
    """Both _observed branches count the dispatch; the FEAT-538 observer still sees begin/finish."""
    manager = ToolManager()

    async def fn() -> str:
        return "x"

    for observer in (None, _Observer()):
        manager.set_invocation_observer(observer)
        with track_turn() as t:
            result = await manager._observed(None if observer is None else SimpleNamespace(executed=False), "fn", fn)
        assert result == "x"
        assert (t.dispatches, t.bodies_started) == (1, 1)
    assert [e[0] for e in observer.events] == ["begin", "finish"]
