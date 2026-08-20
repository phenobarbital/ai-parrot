"""Derive LLM tools from an agentd daemon's ``exposed_methods`` allowlist.

``exposed_methods`` and the agent's LLM toolbox were two disconnected
surfaces: the allowlist governs ``agent.invoke`` (RPC, the MCP proxy,
``/invoke`` in the REPL), while the tools the model may call during a
conversation come from the agent's own ``agent_tools()``. A daemon could
therefore expose ``sync_transcripts`` over RPC while the agent, asked the
very thing that method answers, had no way to call it — it would apologise
instead of acting.

This module closes that gap: for each allowlisted method it builds an
`AbstractTool` whose argument schema is derived from the method signature
and whose description comes from its docstring, so declaring a method in
``exposed_methods`` is enough for the model to reach it.

Wired from `AgentDaemon.run()`; opt out (or narrow the set) with
`AgentServiceConfig.expose_as_tools`.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Iterable, Sequence

from pydantic import BaseModel, Field, create_model

from parrot.tools.abstract import AbstractTool, ToolResult

logger = logging.getLogger(__name__)


def build_method_tools(
    agent: Any,
    method_names: Sequence[str],
    skip_existing: Iterable[str] = (),
) -> list[AbstractTool]:
    """Build one `AbstractTool` per agent method name.

    Methods that cannot be turned into a tool are skipped with a warning
    rather than raising: a malformed signature on one method must not stop
    a daemon from booting.

    Args:
        agent: The agent instance owning the methods.
        method_names: Method names to expose (typically
            `AgentServiceConfig.exposed_methods`).
        skip_existing: Tool names the agent already registers, so a
            hand-written tool always wins over a derived one.

    Returns:
        The derived tools, in the order the names were given.
    """
    already = set(skip_existing)
    tools: list[AbstractTool] = []
    for name in method_names:
        if name.startswith("_"):
            continue
        if name in already:
            logger.debug(
                "agentd: %r already exposed as a tool by the agent; not deriving one",
                name,
            )
            continue
        method = getattr(agent, name, None)
        if method is None or not callable(method):
            logger.warning(
                "agentd: exposed_methods names %r, which is not a callable "
                "on %s — no tool derived",
                name,
                type(agent).__name__,
            )
            continue
        try:
            tools.append(_build_tool(name, method))
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.warning(
                "agentd: could not derive a tool for %r: %s", name, exc
            )
    return tools


def _build_tool(name: str, method: Callable[..., Any]) -> AbstractTool:
    """Build a single tool wrapping one bound method.

    Args:
        name: Method (and resulting tool) name.
        method: The bound method to call.

    Returns:
        A ready-to-register tool.
    """
    schema = _schema_from_signature(name, method)
    description = _description(name, method)

    class _MethodTool(AbstractTool):
        """Tool that forwards its arguments to one agent method."""

        args_schema = schema

        async def _execute(self, **kwargs: Any) -> ToolResult:
            try:
                result = method(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return ToolResult(result=result)
            except Exception as exc:  # noqa: BLE001 — surfaced to the model
                # The model gets the failure as a tool result and can retry
                # or explain, instead of the whole turn blowing up.
                return ToolResult(
                    success=False, status="error", result=None, error=str(exc)
                )

    _MethodTool.__name__ = f"{name.title().replace('_', '')}Tool"
    return _MethodTool(name=name, description=description)


def _schema_from_signature(name: str, method: Callable[..., Any]) -> type[BaseModel]:
    """Derive a pydantic argument schema from a method signature.

    Parameters with annotations keep them; unannotated ones fall back to
    ``Any``. Parameters with defaults become optional. ``*args`` and
    ``**kwargs`` are ignored — a tool schema has to be a closed set of
    named arguments for the model to fill in.

    Args:
        name: Method name, used for the generated model's name.
        method: The bound method to inspect.

    Returns:
        A pydantic model class usable as ``args_schema``.
    """
    signature = inspect.signature(method)
    fields: dict[str, Any] = {}
    for param in signature.parameters.values():
        if param.name in ("self", "cls"):
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = (
            Any if param.annotation is inspect.Parameter.empty else param.annotation
        )
        if param.default is inspect.Parameter.empty:
            fields[param.name] = (annotation, Field(...))
        else:
            fields[param.name] = (annotation, Field(default=param.default))
    model_name = f"{name.title().replace('_', '')}Args"
    return create_model(model_name, **fields)


def _description(name: str, method: Callable[..., Any]) -> str:
    """Build the tool description from the method's docstring.

    Uses the docstring up to the ``Args:`` section — the summary and any
    prose explaining when to use the method, which is exactly what the
    model needs at tool-selection time — and falls back to the method
    name when there is no docstring at all.

    Args:
        name: Method name, used for the fallback text.
        method: The bound method to inspect.

    Returns:
        A description string.
    """
    doc = inspect.getdoc(method) or ""
    body = doc.split("\nArgs:")[0].split("\nReturns:")[0].split("\nRaises:")[0]
    text = " ".join(line.strip() for line in body.strip().splitlines()).strip()
    return text or f"Call the agent's {name}() method."
