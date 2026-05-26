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
import logging
from typing import Any, Dict

from .abstract import ToolExecutionEnvelope

logger = logging.getLogger(__name__)


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
