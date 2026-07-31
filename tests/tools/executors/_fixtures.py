"""Test fixtures for the remote tool executor suite.

Defining tool classes in a regular module (not ``__main__``) is required
because ``build_envelope_from_tool`` records the class's import path so
the remote worker can reconstruct it. Tests that need a tool class
should import from here.
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.tools.executors.abstract import AbstractToolExecutor
from parrot.tools.toolkit import AbstractToolkit


class EchoArgs(AbstractToolArgsSchema):
    """Arg schema for EchoTool — single ``msg`` string."""

    msg: str = Field(..., description="Message to echo back")


class EchoTool(AbstractTool):
    """Trivial async tool used to exercise the executor dispatch path."""

    name = "echo_tool"
    description = "Echo back a message."
    args_schema = EchoArgs

    async def _execute(self, **kwargs) -> ToolResult:
        msg = kwargs.get("msg", "")
        return ToolResult(
            success=True,
            status="success",
            result=f"echo:{msg}",
            metadata={"tool": "echo_tool", "received_kwargs": dict(kwargs)},
        )


class FailingTool(AbstractTool):
    """Tool whose ``_execute`` always raises, to exercise error paths."""

    name = "failing_tool"
    description = "Always raises."
    args_schema = AbstractToolArgsSchema

    async def _execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("deliberate failure")


class CalcArgs(AbstractToolArgsSchema):
    a: int = Field(..., description="left operand")
    b: int = Field(..., description="right operand")


class GreetingToolkit(AbstractToolkit):
    """Toolkit fixture used to exercise the toolkit dispatch path."""

    tool_prefix = "greeting"

    async def hello(self, name: str) -> str:
        """Return a greeting for *name*."""
        return f"hello,{name}"

    async def add(self, a: int, b: int) -> int:
        """Return ``a + b``."""
        return a + b


class ClosableExecutor(AbstractToolExecutor):
    """Executor fixture for ExecutionPolicy tests.

    Lives in an importable module so ``EXECUTOR_REGISTRY`` entries can
    reference it by path. Records construction kwargs and close calls.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.envelopes: list = []
        self.closed = False

    async def execute(self, envelope: Any) -> ToolResult:
        self.envelopes.append(envelope)
        return ToolResult(status="success", result="from-closable")

    async def close(self) -> None:
        self.closed = True
