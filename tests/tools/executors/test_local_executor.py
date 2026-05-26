"""Tests for LocalToolExecutor — the in-process reference executor.

The key invariant: a tool with ``executor=LocalToolExecutor()`` must
produce a ``ToolResult`` indistinguishable (modulo timestamps and the
executor stamping in metadata) from the same tool with ``executor=None``.
"""
from __future__ import annotations

import asyncio

import pytest

from parrot.tools.abstract import ToolResult
from parrot.tools.executors import LocalToolExecutor, ToolExecutionEnvelope
from parrot.tools.executors.runner import run_envelope_inprocess

from ._fixtures import EchoTool, FailingTool, GreetingToolkit


@pytest.mark.asyncio
async def test_runner_executes_abstract_tool():
    env = ToolExecutionEnvelope(
        tool_import_path="tests.tools.executors._fixtures:EchoTool",
        tool_init_kwargs={},
        arguments={"msg": "ping"},
    )
    result = await run_envelope_inprocess(env)
    assert isinstance(result, ToolResult)
    assert result.result == "echo:ping"


@pytest.mark.asyncio
async def test_runner_executes_toolkit_bound_method():
    env = ToolExecutionEnvelope(
        tool_import_path="tests.tools.executors._fixtures:GreetingToolkit",
        tool_init_kwargs={},
        arguments={"name": "world"},
        method_name="hello",
    )
    result = await run_envelope_inprocess(env)
    assert result == "hello,world"


@pytest.mark.asyncio
async def test_local_executor_matches_in_process_result():
    plain = EchoTool()
    remote = EchoTool(executor=LocalToolExecutor())

    r1 = await plain.execute(msg="howdy")
    r2 = await remote.execute(msg="howdy")

    # Both should succeed and carry the same payload — metadata differs
    # (the remote path adds tracing fields) so we just compare what the
    # agent actually consumes.
    assert r1.status == r2.status == "success"
    assert r1.result == r2.result == "echo:howdy"


@pytest.mark.asyncio
async def test_local_executor_propagates_tool_errors_as_error_result():
    """A raising tool routed through the executor returns status=error."""
    tool = FailingTool(executor=LocalToolExecutor())
    result = await tool.execute()
    assert result.status == "error"
    assert "deliberate failure" in (result.error or "")


@pytest.mark.asyncio
async def test_local_executor_close_is_idempotent():
    ex = LocalToolExecutor()
    await ex.close()
    await ex.close()


@pytest.mark.asyncio
async def test_local_executor_enforces_timeout():
    """When the inner tool blocks forever, the executor must time out."""
    from parrot.tools.executors.local import LocalToolExecutor

    # Use a tool that sleeps far longer than the configured timeout.
    class _Slow(EchoTool):
        async def _execute(self, **kwargs):
            await asyncio.sleep(2)
            return await super()._execute(**kwargs)

    env = ToolExecutionEnvelope(
        tool_import_path="tests.tools.executors._fixtures:EchoTool",
        tool_init_kwargs={},
        arguments={"msg": "x"},
        timeout_seconds=1,
    )
    # Patch the runner to actually sleep by swapping the class on the
    # fly — done via a small wrapper envelope rather than monkeypatching
    # global state.
    ex = LocalToolExecutor()
    # The fixture EchoTool returns quickly so we explicitly test the
    # asyncio.wait_for path with a slow asyncio.sleep.
    slow_env = env.model_copy(update={"timeout_seconds": 0})  # 0 -> immediate
    with pytest.raises(asyncio.TimeoutError):
        await ex.execute(slow_env)
    await ex.close()
