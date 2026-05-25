"""Tests for how AbstractTool.execute() dispatches via the executor.

The contract under test:

* ``AbstractTool(executor=None)`` runs in-process via ``_execute``.
* ``AbstractTool(executor=<X>)`` builds an envelope from the validated
  arguments and hands it to the executor, while keeping permission
  checks, arg validation, and ToolResult normalisation on the caller
  side.
* The executor is stripped from the envelope's ``tool_init_kwargs`` so
  the worker side runs the tool locally (no recursive remote dispatch).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from parrot.tools.abstract import ToolResult
from parrot.tools.executors.abstract import (
    AbstractToolExecutor,
    ToolExecutionEnvelope,
)

from ._fixtures import EchoTool, GreetingToolkit


class _RecordingExecutor(AbstractToolExecutor):
    """Captures envelopes so tests can inspect what got dispatched."""

    def __init__(self, response: ToolResult) -> None:
        self.response = response
        self.envelopes: list[ToolExecutionEnvelope] = []
        self.closed = False

    async def execute(
        self, envelope: ToolExecutionEnvelope
    ) -> ToolResult:
        self.envelopes.append(envelope)
        return self.response

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_executor_receives_validated_arguments():
    response = ToolResult(status="success", result="from-executor")
    ex = _RecordingExecutor(response=response)
    tool = EchoTool(executor=ex)

    result = await tool.execute(msg="hello")

    assert result.status == "success"
    assert result.result == "from-executor"
    assert len(ex.envelopes) == 1
    env = ex.envelopes[0]
    assert env.arguments == {"msg": "hello"}
    assert env.tool_import_path.endswith(":EchoTool")
    assert "executor" not in env.tool_init_kwargs


@pytest.mark.asyncio
async def test_no_executor_means_in_process():
    """When ``executor=None`` the legacy ``_execute`` path is taken."""
    tool = EchoTool()  # no executor
    result = await tool.execute(msg="ping")
    assert result.status == "success"
    assert result.result == "echo:ping"


@pytest.mark.asyncio
async def test_toolkit_executor_propagates_to_generated_tools():
    """A toolkit with executor= passes it to every ToolkitTool it makes."""
    response = ToolResult(status="success", result=42)
    ex = _RecordingExecutor(response=response)
    toolkit = GreetingToolkit(executor=ex)

    tools = toolkit.get_tools()
    assert all(t.executor is ex for t in tools)

    hello = next(t for t in tools if t.name == "greeting_hello")
    result = await hello.execute(name="alice")
    assert result.result == 42
    env = ex.envelopes[0]
    assert env.tool_import_path.endswith(":GreetingToolkit")
    assert env.method_name == "hello"
    assert env.arguments == {"name": "alice"}


@pytest.mark.asyncio
async def test_executor_errors_become_error_toolresult():
    class _Boom(AbstractToolExecutor):
        async def execute(self, envelope):
            raise RuntimeError("transport down")

        async def close(self):
            return None

    tool = EchoTool(executor=_Boom())
    result = await tool.execute(msg="x")
    assert result.status == "error"
    assert "transport down" in (result.error or "")
