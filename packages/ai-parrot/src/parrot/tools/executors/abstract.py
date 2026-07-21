"""Abstract executor interface and serializable envelope.

The envelope is the contract that crosses the process boundary. Anything
inside it must be JSON-serializable; anything not in it cannot be relied
on by the remote runtime.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..abstract import AbstractTool, ToolResult
    from ...auth.permission import PermissionContext
    from ...core.events.lifecycle.trace import TraceContext


# Sentinel used by build_envelope_from_tool to flag tools whose import
# path cannot be reconstructed (anonymous classes, classes defined in
# __main__, etc.). The executor implementations raise a clear error
# instead of silently shipping a broken envelope.
_UNRESOLVABLE_IMPORT_PATH = "<unresolvable>"


class ToolExecutionEnvelope(BaseModel):
    """The wire-format payload describing a single remote tool invocation.

    Attributes:
        tool_import_path: Dotted Python path of the tool class, formatted
            as ``"<module>:<qualname>"`` so the remote worker can do
            ``importlib.import_module(module)`` and ``getattr(cls)``.
        tool_init_kwargs: Constructor arguments captured from the caller's
            instance. Forwarded as ``cls(**tool_init_kwargs)`` on the
            remote side. The ``executor`` kwarg is stripped before
            transit so the remote tool runs locally.
        method_name: For ``ToolkitTool`` envelopes, the name of the bound
            method to invoke on the reconstructed toolkit. ``None`` for
            plain ``AbstractTool`` subclasses.
        arguments: Validated tool arguments (the kwargs that would
            normally be passed to ``_execute``).
        permission_context: JSON projection of the caller's
            ``PermissionContext``. The remote side does NOT re-run
            permission checks — Layer 2 enforcement happens on the
            caller before the envelope is sent. This is informational.
        trace_context: JSON projection of the parent span so the remote
            runtime can mint a child span and keep the trace connected.
        timeout_seconds: Maximum wall-clock seconds to wait for the
            remote runtime to return a result.
        webhook_callback_url: When set, the executor returns immediately
            with a ``"pending"`` ToolResult; the remote runtime POSTs the
            final ToolResult to this URL when it completes. The webhook
            handler is registered separately.
        envelope_version: Schema version. Bumped when the contract
            changes in a backwards-incompatible way.
    """

    tool_import_path: str
    tool_init_kwargs: Dict[str, Any] = Field(default_factory=dict)
    method_name: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    permission_context: Optional[Dict[str, Any]] = None
    trace_context: Optional[Dict[str, Any]] = None
    timeout_seconds: int = 300
    webhook_callback_url: Optional[str] = None
    envelope_version: int = 1


def project_trace_context(tc: "TraceContext | None") -> Optional[Dict[str, Any]]:
    """Project a TraceContext into a JSON-safe dict.

    Returns ``None`` when *tc* is ``None`` so envelopes stay compact.
    """
    if tc is None:
        return None
    return {
        "trace_id": tc.trace_id,
        "span_id": tc.span_id,
        "trace_flags": tc.trace_flags,
        "trace_state": tc.trace_state,
        "parent_span_id": tc.parent_span_id,
    }


def project_permission_context(
    pctx: "PermissionContext | None",
) -> Optional[Dict[str, Any]]:
    """Project a PermissionContext into a JSON-safe dict.

    Only stable, request-scoped fields are exported — no resolver,
    no live callables. Roles convert from frozenset → list. The trace
    context piggy-backs on its own field in the envelope, not on this
    projection, so it is omitted here.
    """
    if pctx is None:
        return None
    session = pctx.session
    return {
        "session": {
            "user_id": session.user_id,
            "tenant_id": session.tenant_id,
            "roles": sorted(session.roles) if session.roles else [],
        },
        "request_id": pctx.request_id,
        "channel": pctx.channel,
        "extra": dict(pctx.extra) if pctx.extra else {},
    }


def _resolve_import_path(obj: Any) -> str:
    """Return ``"<module>:<qualname>"`` for *obj*'s class.

    Tools defined in ``__main__`` or whose module cannot be re-imported
    return the sentinel value; callers should raise a clear error rather
    than ship an unusable envelope.
    """
    cls = obj.__class__
    module = getattr(cls, "__module__", "")
    qualname = getattr(cls, "__qualname__", cls.__name__)
    if not module or module == "__main__":
        return _UNRESOLVABLE_IMPORT_PATH
    return f"{module}:{qualname}"


def build_envelope_from_tool(
    tool: "AbstractTool",
    arguments: Dict[str, Any],
    permission_context: "PermissionContext | None" = None,
    trace_context: "TraceContext | None" = None,
    timeout_seconds: int = 300,
    webhook_callback_url: Optional[str] = None,
) -> ToolExecutionEnvelope:
    """Construct a ToolExecutionEnvelope from a tool instance.

    The tool's ``_init_kwargs`` (captured by ``AbstractTool.__init__``)
    travel as ``tool_init_kwargs``. The ``executor`` kwarg is stripped
    so the remote-side reconstruction runs the tool locally inside the
    worker process.

    For :class:`ToolkitTool` instances, the toolkit class is what gets
    imported on the remote side, not ``ToolkitTool`` itself; the
    ``method_name`` field tells the worker which method to call on the
    reconstructed toolkit. ``tool_init_kwargs`` then carries the
    toolkit's constructor arguments (not the ToolkitTool's).

    For :class:`AgentTool` instances (Agents-as-Tools), the wrapped
    agent cannot travel as a live object; instead the agent's name is
    shipped as an ``agent_ref`` init kwarg and the worker reconstructs
    the agent from the agent registry (``parrot.registry``). This
    requires the agent to be registered under its name on the worker
    side too, and the worker environment to carry whatever credentials
    the sub-agent's LLM needs.

    Raises:
        ValueError: When the tool's class cannot be imported by path
            (e.g. defined in ``__main__``), or when an ``AgentTool``
            wraps an agent that is not resolvable through the agent
            registry. Such tools cannot be executed remotely.
    """
    # AgentTool needs special handling — the wrapped agent is a live,
    # non-serializable object, so we ship a registry reference instead.
    agent_parts = _agent_tool_envelope_parts(tool)
    if agent_parts is not None:
        import_path, init_kwargs = agent_parts
        return ToolExecutionEnvelope(
            tool_import_path=import_path,
            tool_init_kwargs=init_kwargs,
            method_name=None,
            arguments=dict(arguments),
            permission_context=project_permission_context(permission_context),
            trace_context=project_trace_context(trace_context),
            timeout_seconds=timeout_seconds,
            webhook_callback_url=webhook_callback_url,
        )

    # ToolkitTool needs special handling — the *toolkit* is what we
    # import on the remote side, not the synthetic ToolkitTool wrapper.
    # We detect this by attribute rather than isinstance to avoid a
    # circular import between this module and toolkit.py.
    bound_method = getattr(tool, "bound_method", None)
    toolkit = getattr(bound_method, "__self__", None) if bound_method else None

    if toolkit is not None and hasattr(toolkit, "_init_kwargs"):
        import_path = _resolve_import_path(toolkit)
        init_kwargs = _strip_executor(toolkit._init_kwargs)
        method_name = getattr(tool, "_method_name", None) or bound_method.__name__
    elif toolkit is not None:
        # Toolkit doesn't expose _init_kwargs — most don't. Fall back to
        # importing the class with no arguments. Callers who need
        # bespoke construction must override the toolkit's
        # ``_get_clone_kwargs`` or supply a custom executor.
        import_path = _resolve_import_path(toolkit)
        init_kwargs = {}
        method_name = getattr(tool, "_method_name", None) or bound_method.__name__
    else:
        import_path = _resolve_import_path(tool)
        init_kwargs = _strip_executor(getattr(tool, "_init_kwargs", {}))
        method_name = None

    if import_path == _UNRESOLVABLE_IMPORT_PATH:
        raise ValueError(
            f"Cannot build remote execution envelope for {tool!r}: "
            "its class is not importable by path "
            "(defined in __main__ or an anonymous class). Move the "
            "tool class into a regular module to make it remoteable."
        )

    return ToolExecutionEnvelope(
        tool_import_path=import_path,
        tool_init_kwargs=init_kwargs,
        method_name=method_name,
        arguments=dict(arguments),
        permission_context=project_permission_context(permission_context),
        trace_context=project_trace_context(trace_context),
        timeout_seconds=timeout_seconds,
        webhook_callback_url=webhook_callback_url,
    )


def _strip_executor(init_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Remove the ``executor`` key so the remote tool runs in-process.

    Live executor instances are never serializable and would also cause
    infinite recursion (remote tool spawning another remote tool).
    """
    if not init_kwargs:
        return {}
    return {k: v for k, v in init_kwargs.items() if k != "executor"}


def _agent_tool_envelope_parts(
    tool: Any,
) -> Optional[tuple[str, Dict[str, Any]]]:
    """Build ``(import_path, init_kwargs)`` for an AgentTool, or None.

    Returns ``None`` for anything that is not an ``AgentTool`` so
    :func:`build_envelope_from_tool` falls through to the normal paths.

    The wrapped agent travels as an ``agent_ref`` (its registry name);
    ``parrot.tools.executors.runner`` resolves it back through
    ``parrot.registry.agent_registry.get_instance()`` on the worker
    side. Live-only extras (``context_filter``, ``execution_memory``)
    cannot cross the process boundary and are dropped — cross-
    pollination state stays on the caller.

    Raises:
        ValueError: When the wrapped agent is not registered in the
            agent registry under its name (nothing for the worker to
            reconstruct).
    """
    try:
        from ..agent import AgentTool
    except ImportError:  # pragma: no cover - agent module always ships
        return None
    if not isinstance(tool, AgentTool):
        return None

    agent = tool.agent
    agent_name = getattr(agent, "name", None)
    metadata = None
    if agent_name:
        try:
            from ...registry import agent_registry

            metadata = agent_registry.get_metadata(agent_name)
        except ImportError:
            metadata = None
    if not agent_name or metadata is None:
        raise ValueError(
            f"Cannot build remote execution envelope for AgentTool "
            f"{tool.name!r}: the wrapped agent {agent_name!r} is not "
            "resolvable through the agent registry. Register it with "
            "@register_agent (or agent_registry.register) under the same "
            "name — the remote worker reconstructs the agent from the "
            "registry, and its environment must also provide the "
            "sub-agent's LLM credentials."
        )
    return (
        "parrot.tools.agent:AgentTool",
        {
            "agent_ref": agent_name,
            "tool_name": tool.name,
            "tool_description": tool.description,
            "use_conversation_method": tool.use_conversation_method,
        },
    )


class AbstractToolExecutor(ABC):
    """Pluggable transport that runs a tool somewhere other than here.

    Concrete executors translate a :class:`ToolExecutionEnvelope` into
    whatever protocol the remote runtime speaks (HTTP, gRPC, k8s API,
    Redis Streams, etc.) and return a :class:`ToolResult` once the
    remote side finishes — either by waiting synchronously up to
    ``envelope.timeout_seconds`` or by returning a ``pending``
    ToolResult and arranging for the final result to arrive via webhook.

    Concrete implementations:

    * :class:`LocalToolExecutor` — in-process; reference / tests
    * :class:`K8sToolExecutor` — ephemeral Pod via kubernetes-asyncio
    * :class:`QworkerToolExecutor` — Qworker service (HTTP / Redis)
    """

    @abstractmethod
    async def execute(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        """Run the tool described by *envelope* and return its ToolResult.

        Implementations must:

        * raise :class:`asyncio.TimeoutError` (or a structured
          ``ToolResult(status="error", error="timeout")``) when the
          remote side fails to respond within ``envelope.timeout_seconds``.
        * never re-run permission checks. Those happen on the caller.
        * propagate ``envelope.trace_context`` to the worker so the trace
          stays connected.

        Returns:
            The final ToolResult, or a ``ToolResult(status="pending")``
            with ``metadata["job_id"]`` set when the executor was
            constructed with a webhook delivery configuration.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release any pooled resources (HTTP sessions, k8s clients, etc.).

        Idempotent: calling ``close()`` multiple times must not raise.
        """
