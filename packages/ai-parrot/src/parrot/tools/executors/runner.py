"""In-process envelope runner shared by LocalToolExecutor and the k8s/qworker worker entrypoints.

The runner takes a deserialized ``ToolExecutionEnvelope``, imports the
referenced class, instantiates it, and invokes the underlying
``_execute`` method (or the toolkit-bound method) returning a
:class:`ToolResult`. It is intentionally minimal: permission checks,
lifecycle events, and result-shape normalisation have already happened
on the caller side (or will, when the result returns).
"""
from __future__ import annotations

import importlib
import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from .abstract import ToolExecutionEnvelope

if TYPE_CHECKING:
    from ..abstract import ToolResult

logger = logging.getLogger(__name__)

# Sentinel markers emitted by ``parrot.cli.tool_worker`` around the
# ToolResult JSON so executors can extract the payload from arbitrary
# stdout/stderr chatter. Kept in sync with the worker module.
RESULT_BEGIN_MARKER = "__PARROT_TOOL_RESULT_BEGIN__"
RESULT_END_MARKER = "__PARROT_TOOL_RESULT_END__"


def parse_sentinel_output(
    output: str, *, metadata: Dict[str, Any]
) -> "ToolResult":
    """Extract the worker's marker-delimited ToolResult from *output*.

    The worker writes the JSON result between
    ``__PARROT_TOOL_RESULT_BEGIN__`` and ``__PARROT_TOOL_RESULT_END__``
    so unrelated log chatter is ignored. Shared by every executor that
    reads worker stdout (K8s pod logs, Docker container logs / exec
    streams).

    Args:
        output: Raw combined stdout/stderr captured from the worker.
        metadata: Executor-identifying keys stamped onto the result's
            metadata in every branch (success and error) so observers
            can correlate.
    """
    from ..abstract import ToolResult

    if RESULT_BEGIN_MARKER not in output or RESULT_END_MARKER not in output:
        return ToolResult(
            success=False,
            status="error",
            result=None,
            error=(
                "Worker did not emit a result block. Last 4KB of logs: "
                + (output[-4096:] if output else "<empty>")
            ),
            metadata=dict(metadata),
        )
    payload = (
        output.split(RESULT_BEGIN_MARKER, 1)[1]
        .split(RESULT_END_MARKER, 1)[0]
        .strip()
    )
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return ToolResult(
            success=False,
            status="error",
            result=None,
            error=f"Worker emitted invalid JSON: {exc}",
            metadata={**metadata, "payload": payload[:512]},
        )
    stamped = dict(data.get("metadata") or {})
    stamped.update(metadata)
    data["metadata"] = stamped
    return ToolResult(**data)


def _import_class(import_path: str) -> type:
    """Resolve ``"<module>:<qualname>"`` into a class.

    ``<qualname>`` may be dotted (nested classes), so we walk attributes
    from the imported module.
    """
    if ":" not in import_path:
        raise ValueError(
            f"Invalid tool import path {import_path!r}: expected "
            "'<module>:<qualname>' format."
        )
    module_path, qualname = import_path.split(":", 1)
    module = importlib.import_module(module_path)
    obj: Any = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    if not isinstance(obj, type):
        raise TypeError(
            f"Resolved {import_path!r} is not a class (got {type(obj).__name__})."
        )
    return obj


async def run_envelope_inprocess(envelope: ToolExecutionEnvelope) -> Any:
    """Execute *envelope* in the current Python process.

    Returns the :class:`ToolResult` produced by the tool's underlying
    ``_execute`` implementation (or by the toolkit-bound method). The
    caller is responsible for any further normalisation — typically
    ``AbstractTool.execute`` does that wrapping.

    Layered behaviour:

    * Plain ``AbstractTool`` subclasses are instantiated and
      ``await tool._execute(**arguments)`` is called.
    * Toolkit-bound envelopes (``method_name is not None``) instantiate
      the toolkit, look up the named method, and call it with
      ``arguments``. This mirrors what :meth:`ToolkitTool._execute`
      would do, minus the ``_pre_execute`` / ``_post_execute`` hooks
      because we want the remote runtime to behave like a pure worker.
    """
    cls = _import_class(envelope.tool_import_path)
    # Defensive: tool_init_kwargs comes from a Pydantic-validated
    # envelope, but a malicious worker could still receive arbitrary
    # JSON. We pass it through as-is — restricting allowed kwargs is
    # the responsibility of whoever signed/transported the envelope.
    init_kwargs: Dict[str, Any] = dict(envelope.tool_init_kwargs or {})

    # Agents-as-Tools: an ``agent_ref`` marks an AgentTool envelope. The
    # wrapped agent is reconstructed from the agent registry (which also
    # runs its async configure()) and handed to the tool constructor.
    agent_ref = init_kwargs.pop("agent_ref", None)
    if agent_ref is not None:
        from ...registry import agent_registry

        agent = await agent_registry.get_instance(agent_ref)
        if agent is None:
            raise ValueError(
                f"Agent {agent_ref!r} is not registered in this worker's "
                "agent registry; cannot reconstruct the AgentTool."
            )
        instance = cls(agent=agent, **init_kwargs)
    else:
        instance = cls(**init_kwargs)

    arguments = dict(envelope.arguments or {})

    if envelope.method_name is None:
        # AbstractTool subclass path
        return await instance._execute(**arguments)

    # Toolkit path — find the bound method, call it.
    bound = getattr(instance, envelope.method_name, None)
    if bound is None:
        raise AttributeError(
            f"Toolkit {envelope.tool_import_path!r} has no method "
            f"{envelope.method_name!r}."
        )
    if not callable(bound):
        raise TypeError(
            f"{envelope.tool_import_path}.{envelope.method_name} is not callable."
        )
    result = bound(**arguments)
    # Toolkit methods are async by contract; await coroutines, return
    # plain values directly so tests / sync stubs still work.
    if hasattr(result, "__await__"):
        result = await result
    return result
