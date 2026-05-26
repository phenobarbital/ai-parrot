"""In-process reference executor.

Mostly exists so tests can exercise the executor-dispatch path without
needing a Kubernetes cluster or a Qworker instance. The same code that
runs in the ``parrot-tools`` worker image is reused here verbatim so
behaviour stays consistent across runtimes.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .abstract import AbstractToolExecutor, ToolExecutionEnvelope
from .runner import run_envelope_inprocess

if TYPE_CHECKING:
    from ..abstract import ToolResult


class LocalToolExecutor(AbstractToolExecutor):
    """Executor that runs the tool in the current Python process.

    Used as the reference implementation: it imports the tool by path,
    instantiates it from ``envelope.tool_init_kwargs``, and awaits its
    ``_execute(**envelope.arguments)``. Because it shares the runner
    module with the worker entrypoint, this is what the
    ``K8sToolExecutor`` worker pod ends up doing inside its own
    process — and what unit tests can exercise without ceremony.
    """

    async def execute(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        # The runner enforces the envelope timeout itself when the tool
        # is long-lived, but we also wrap it here so a stuck tool can't
        # exceed the caller's budget.
        return await asyncio.wait_for(
            run_envelope_inprocess(envelope),
            timeout=envelope.timeout_seconds,
        )

    async def close(self) -> None:
        return None
