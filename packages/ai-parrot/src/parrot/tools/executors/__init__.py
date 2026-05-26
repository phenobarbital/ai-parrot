"""Remote tool executors for AI-Parrot.

Tools can be marked for off-process execution by passing an
``executor=`` kwarg when constructing an ``AbstractTool`` or
``AbstractToolkit``. The executor takes the validated tool arguments and
returns a ``ToolResult`` from somewhere else — an ephemeral Kubernetes
pod, the Qworker service over HTTP, or a Redis Stream consumer — while
the agent loop keeps its existing in-process contract.

Public API:

* :class:`AbstractToolExecutor` — the interface every executor implements
* :class:`LocalToolExecutor` — reference implementation that runs the
  tool in-process (mostly used for tests and as the default behaviour)
* :class:`K8sToolExecutor` — runs the tool in an ephemeral
  ``batch/v1 Job`` against a Kubernetes cluster
* :class:`QworkerToolExecutor` — dispatches the tool to the Qworker
  service via its HTTP client or via Redis Streams
* :class:`ToolExecutionEnvelope` — the serializable contract that
  travels over the wire to the remote runtime
"""
from __future__ import annotations

from .abstract import (
    AbstractToolExecutor,
    ToolExecutionEnvelope,
    build_envelope_from_tool,
    project_permission_context,
    project_trace_context,
)
from .local import LocalToolExecutor

__all__ = (
    "AbstractToolExecutor",
    "ToolExecutionEnvelope",
    "LocalToolExecutor",
    "build_envelope_from_tool",
    "project_permission_context",
    "project_trace_context",
    # Lazily imported below to avoid pulling kubernetes_asyncio / aiohttp
    # into processes that never use them.
    "K8sToolExecutor",
    "QworkerToolExecutor",
)


def __getattr__(name: str):
    """Lazy-import optional executors to avoid forcing their dependencies."""
    if name == "K8sToolExecutor":
        from .k8s import K8sToolExecutor

        return K8sToolExecutor
    if name == "QworkerToolExecutor":
        from .qworker import QworkerToolExecutor

        return QworkerToolExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
