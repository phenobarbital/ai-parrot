"""ToolNode — deterministic tool execution node for AgentCrew.

Provides a crew member that is NOT an LLM agent but a direct tool caller:
it invokes an ``AbstractTool`` with statically declared ``args``/``kwargs``
(pass-through) and wraps the outcome so it is indistinguishable from an
agent-execution result to the rest of the flow machinery (``FlowResult``,
context summaries, persistence, FSM lifecycle). No LLM tokens are spent.

Template placeholders — resolved deterministically at execution time from
prior results (never via an LLM):

- ``{input}`` — the node's input. Sequential/loop modes: the composed
  previous input; parallel mode: the task's query; flow mode: the last
  completed dependency's output (or the initial task when the node has
  no dependencies).
- ``{nodes.<node_name>.output}`` — the stored output of a previously
  completed node. Avoid dots in node ids: they are ambiguous inside
  this placeholder syntax.

A string value that consists of exactly one placeholder is replaced by the
referenced value with its native type preserved (a dict result passes
through to the tool as a dict). Placeholders embedded in a larger string
are substituted via ``str()``. Literal braces that do not match the
placeholder grammar (e.g. inline JSON) are left untouched.
"""
from __future__ import annotations

import asyncio
import re
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Set,
    Tuple,
    runtime_checkable,
)

from pydantic import Field

from datamodel.parsers.json import json_encoder  # pylint: disable=E0611 # noqa

from ....tools.abstract import ToolResult
from ..core.fsm import AgentTaskMachine
from ..core.node import Node


@runtime_checkable
class ToolLike(Protocol):
    """Structural protocol for any object usable as a ToolNode tool.

    Mirrors the ``AgentLike`` pattern from ``flows.core.types``: using a
    Protocol (rather than requiring an ``AbstractTool`` subclass) keeps the
    node testable with lightweight doubles while every real
    ``AbstractTool`` satisfies the contract.

    Attributes:
        name: Tool identifier.

    Methods:
        execute: Async call returning a ``ToolResult``-shaped object.
    """

    name: str

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the tool and return a ``ToolResult``."""
        ...


class TemplateResolutionError(ValueError):
    """A template placeholder references a node with no stored result."""


class ToolNodeExecutionError(RuntimeError):
    """The wrapped tool reported failure (``ToolResult.success == False``)."""


# ``{input}`` or ``{nodes.<node name>.output}`` — node names may contain
# spaces ("Data Fetcher"); the non-greedy group stops at the first
# ``.output}`` suffix.
_PLACEHOLDER_RE = re.compile(r"\{(input|nodes\.(.+?)\.output)\}")


def resolve_templates(
    value: Any,
    *,
    input_text: str,
    results: Mapping[str, Any],
) -> Any:
    """Recursively resolve template placeholders inside a value.

    Walks nested dicts/lists/tuples and substitutes placeholders found in
    string values. Non-string leaves pass through unchanged.

    Args:
        value: The value to resolve (str, dict, list, tuple, or any leaf).
        input_text: Replacement for the ``{input}`` placeholder.
        results: Mapping of node_id → stored output, used to resolve
            ``{nodes.<node_name>.output}`` placeholders.

    Returns:
        The value with all placeholders resolved. A string that is exactly
        one placeholder returns the referenced value with native type
        preserved; embedded placeholders are substituted via ``str()``.

    Raises:
        TemplateResolutionError: If a ``{nodes.<name>.output}`` placeholder
            references a node absent from ``results``.
    """
    if isinstance(value, str):

        def _lookup(match: re.Match) -> Any:
            if match.group(1) == "input":
                return input_text
            node_name = match.group(2)
            if node_name not in results:
                raise TemplateResolutionError(
                    f"Placeholder '{{nodes.{node_name}.output}}' cannot be "
                    f"resolved: node '{node_name}' has no result yet. "
                    f"Available nodes: {sorted(results.keys())}"
                )
            return results[node_name]

        if full := _PLACEHOLDER_RE.fullmatch(value):
            # Exact single placeholder — preserve the native type.
            return _lookup(full)
        return _PLACEHOLDER_RE.sub(lambda m: str(_lookup(m)), value)
    if isinstance(value, dict):
        return {
            key: resolve_templates(item, input_text=input_text, results=results)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            resolve_templates(item, input_text=input_text, results=results)
            for item in value
        ]
    return value


def extract_tool_output(tool_result: ToolResult) -> str:
    """Return the string form of a ``ToolResult`` payload.

    Used wherever the crew stores node outputs as strings
    (``FlowContext.results``, context summaries, ``NodeResult``).

    Args:
        tool_result: The tool execution result to stringify.

    Returns:
        The raw string when the payload already is one, otherwise its JSON
        encoding (falling back to ``str()`` for non-serialisable payloads).
    """
    payload = tool_result.result
    if isinstance(payload, str):
        return payload
    try:
        encoded = json_encoder(payload)
    except Exception:  # pylint: disable=W0703
        return str(payload)
    return encoded if isinstance(encoded, str) else str(encoded)


class ToolNode(Node):
    """Deterministic tool-caller crew node (no LLM involved).

    Registered into a crew via ``AgentCrew.add_tool_node()``, this node
    participates in every execution mode: sequential/parallel/loop runs
    dispatch to :meth:`call_tool` (via ``AgentCrew._execute_agent``), while
    flow mode invokes :meth:`execute` with the same contract as
    ``AgentNode.execute``.

    Duck-typing notes:

    - ``is_configured`` defaults to ``True`` so ``_ensure_agent_ready``
      never attempts LLM configuration.
    - ``agent`` is a self-referencing property: flow-mode plumbing reads
      ``node.agent.name`` and ``build_node_metadata`` probes agent
      attributes with ``getattr(..., None)`` — both are safe on this model.
    - The FSM lifecycle is driven externally by the crew scheduler, exactly
      as for ``CrewAgentNode``.

    Args:
        tool: The tool to invoke (any ``AbstractTool`` or ``ToolLike``).
        node_id: Unique identifier for this node within the crew.
        args: Positional arguments passed through to the tool (template
            placeholders allowed in string values).
        kwargs: Keyword arguments passed through to the tool (template
            placeholders allowed in string values).
        description: Optional human-readable description.
        dependencies: Node ids that must complete before this node runs.
        successors: Node ids dispatched after this node completes.
        fsm: Optional pre-built FSM (auto-created when ``None``).
    """

    tool: ToolLike
    node_id: str
    args: List[Any] = Field(default_factory=list)
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None
    is_configured: bool = True

    def model_post_init(self, __context: Any) -> None:
        """Auto-create the FSM if not provided; initialise logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            # object.__setattr__ is the frozen-Pydantic escape hatch for
            # setting a field inside model_post_init (see core/node.py).
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identity (same as ``node_id`` for tool nodes)."""
        return self.node_id

    @property
    def agent(self) -> "ToolNode":
        """Self-reference for flow-mode plumbing that reads ``node.agent``."""
        return self

    async def configure(self) -> None:
        """No-op — the wrapped tool needs no LLM configuration."""

    # ── Template resolution ───────────────────────────────────────────────

    def _resolve_call(
        self,
        input_text: str,
        results: Mapping[str, Any],
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """Resolve template placeholders in the declared args/kwargs.

        Args:
            input_text: Replacement for ``{input}`` placeholders.
            results: Prior node outputs for ``{nodes.<name>.output}``.

        Returns:
            Tuple of (resolved positional args, resolved keyword args).
        """
        resolved_args = resolve_templates(
            self.args, input_text=input_text, results=results
        )
        resolved_kwargs = resolve_templates(
            self.kwargs, input_text=input_text, results=results
        )
        return resolved_args, resolved_kwargs

    def _render_call(
        self,
        resolved_args: List[Any],
        resolved_kwargs: Dict[str, Any],
    ) -> str:
        """Human-readable call description (used as the log/memory prompt)."""
        try:
            args_repr = json_encoder(resolved_args)
            kwargs_repr = json_encoder(resolved_kwargs)
        except Exception:  # pylint: disable=W0703
            args_repr = str(resolved_args)
            kwargs_repr = str(resolved_kwargs)
        return f"tool:{self.tool.name}(args={args_repr}, kwargs={kwargs_repr})"

    def _derive_input(self, ctx: Any, deps: Mapping[str, Any]) -> str:
        """Derive the ``{input}`` value in flow mode.

        Returns the last completed dependency's output when the node has
        dependencies, otherwise the flow's initial task.

        Args:
            ctx: The current ``FlowContext``.
            deps: Dependency results (unused directly; ordering comes from
                ``ctx.completion_order``).

        Returns:
            The derived input string.
        """
        if self.dependencies:
            completion_order = getattr(ctx, "completion_order", None) or []
            ctx_results = getattr(ctx, "results", {}) or {}
            for dep in reversed(completion_order):
                if dep in self.dependencies and dep in ctx_results:
                    value = ctx_results[dep]
                    return value if isinstance(value, str) else str(value)
        return getattr(ctx, "initial_task", "") or ""

    # ── Execution ─────────────────────────────────────────────────────────

    async def _invoke(
        self,
        resolved_args: List[Any],
        resolved_kwargs: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> ToolResult:
        """Invoke the wrapped tool with already-resolved arguments.

        Args:
            resolved_args: Positional arguments for the tool.
            resolved_kwargs: Keyword arguments for the tool.
            timeout: Optional per-call timeout in seconds.

        Returns:
            The successful ``ToolResult``.

        Raises:
            ToolNodeExecutionError: If the tool reports failure.
            asyncio.TimeoutError: If the call exceeds ``timeout``.
        """
        coro = self.tool.execute(*resolved_args, **resolved_kwargs)
        tool_result: ToolResult = (
            await asyncio.wait_for(coro, timeout) if timeout else await coro
        )
        if not tool_result.success:
            raise ToolNodeExecutionError(
                f"ToolNode '{self.node_id}' (tool '{self.tool.name}') failed "
                f"[{tool_result.status}]: {tool_result.error}"
            )
        return tool_result

    async def call_tool(
        self,
        *,
        input_text: str,
        results: Mapping[str, Any],
        timeout: Optional[float] = None,
    ) -> ToolResult:
        """Resolve templates and invoke the tool (sequential/parallel/loop path).

        Does NOT fire pre/post actions — the sequential, parallel, and loop
        modes fire ``run_pre_actions``/``run_post_actions`` externally around
        ``_execute_agent``, so firing them here would double-invoke hooks.

        Args:
            input_text: The node's input for ``{input}`` placeholders.
            results: Prior node outputs for ``{nodes.<name>.output}``.
            timeout: Optional per-call timeout in seconds.

        Returns:
            The successful ``ToolResult``.

        Raises:
            TemplateResolutionError: If a placeholder cannot be resolved.
            ToolNodeExecutionError: If the tool reports failure.
        """
        resolved_args, resolved_kwargs = self._resolve_call(input_text, results)
        return await self._invoke(resolved_args, resolved_kwargs, timeout)

    async def execute(
        self,
        ctx: Any,
        deps: Mapping[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute the tool node in flow mode.

        Signature/return contract mirrors ``AgentNode.execute`` so
        ``AgentCrew._execute_parallel_agents`` can consume the result
        uniformly.

        **The FSM lifecycle (start/succeed/fail) is managed externally by
        the scheduler — do NOT touch ``self.fsm`` here.**

        Args:
            ctx: The current flow execution context.
            deps: Mapping of completed dependency node_id → result.
            **kwargs: Scheduler kwargs; ``timeout`` is honoured, the rest
                are ignored (never forwarded to the tool).

        Returns:
            Dict with keys ``'response'`` (the ``ToolResult``),
            ``'output'`` (string form), ``'execution_time'`` and
            ``'prompt'`` (rendered call description).
        """
        timeout = kwargs.pop("timeout", None)
        input_text = self._derive_input(ctx, deps)
        ctx_results = getattr(ctx, "results", {}) or {}
        resolved_args, resolved_kwargs = self._resolve_call(
            input_text, ctx_results
        )
        prompt = self._render_call(resolved_args, resolved_kwargs)
        await self.run_pre_actions(prompt=prompt)
        start_time = asyncio.get_running_loop().time()
        tool_result = await self._invoke(resolved_args, resolved_kwargs, timeout)
        execution_time = asyncio.get_running_loop().time() - start_time
        await self.run_post_actions(result=tool_result)
        return {
            "response": tool_result,
            "output": extract_tool_output(tool_result),
            "execution_time": execution_time,
            "prompt": prompt,
        }
