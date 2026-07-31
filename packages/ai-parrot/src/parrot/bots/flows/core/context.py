"""Flow Primitives — FlowContext.

Shared workflow execution state tracker used by both ``AgentCrew``
and ``AgentsFlow`` orchestration engines.

Extracted from ``parrot.bots.orchestration.crew.FlowContext`` with
node-centric renaming and backward-compat aliases.

Primary names:
    ``node_metadata`` — execution metadata keyed by node_id.
    ``get_input_for_node()`` — assemble input dict for a node.

Backward-compat aliases (forwarded to the primary methods):
    ``agent_metadata`` — property alias for ``node_metadata``.
    ``get_input_for_agent()`` — alias for ``get_input_for_node()``.

FEAT-163 additions:
    ``agent_registry`` — optional ``AgentRegistry`` bound to the context.
    ``resolve_agent(agent_ref)`` — resolve an agent reference to a live agent
        via the bound registry; raises ``AgentNotFoundError`` on miss.
    ``AgentNotFoundError`` — raised when ``resolve_agent`` cannot find the
        requested agent in the registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .result import NodeExecutionInfo
from .types import AgentLike, AgentRef

if TYPE_CHECKING:
    from parrot.core.events.lifecycle import TraceContext
    from parrot.registry.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class AgentNotFoundError(LookupError):
    """Raised when ``FlowContext.resolve_agent`` cannot find the requested agent.

    Inherits from ``LookupError`` so callers can catch it with either
    ``except AgentNotFoundError:`` (specific) or ``except LookupError:``
    (generic lookup failure).
    """


@dataclass
class FlowContext:
    """Execution state tracker for a single flow/crew run.

    Tracks which nodes have completed, their results and responses,
    and metadata for each node's execution. Provides helpers to
    determine whether a node's dependencies are satisfied and to
    build its input payload.

    Primary field: ``node_metadata`` (was ``agent_metadata`` in
    ``parrot.bots.orchestration.crew.FlowContext``). The old name
    is kept as a ``@property`` alias for backward compatibility.

    Args:
        initial_task: The initial prompt/task string given to the flow.
    """

    initial_task: str
    results: Dict[str, Any] = field(default_factory=dict)
    """Mapping of node_id → extracted result value."""

    responses: Dict[str, Any] = field(default_factory=dict)
    """Mapping of node_id → raw response object."""

    node_metadata: Dict[str, NodeExecutionInfo] = field(default_factory=dict)
    """Mapping of node_id → execution metadata (primary field)."""

    completion_order: List[str] = field(default_factory=list)
    """Ordered list of node_ids as they completed."""

    errors: Dict[str, Exception] = field(default_factory=dict)
    """Mapping of node_id → exception raised during execution."""

    active_tasks: Set[str] = field(default_factory=set)
    """Set of node_ids currently executing."""

    completed_tasks: Set[str] = field(default_factory=set)
    """Set of node_ids that have successfully completed."""

    shared_data: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary key-value data shared across all nodes (replaces AgentContext.shared_data)."""

    agent_registry: Optional["AgentRegistry"] = field(default=None)
    """Optional AgentRegistry bound to this context for agent resolution.

    Set by ``AgentsFlow.from_definition()`` (FEAT-163) and available to
    any code that needs to resolve an ``agent_ref`` string at runtime.
    """

    synthesis_client: Optional[Any] = field(default=None)
    """Optional LLM client used by ``synthesize_results`` (FEAT-163 TASK-1063).

    Any ``AbstractClient``-compatible instance that exposes ``ask(prompt=...)``.
    If ``None``, calling ``synthesize_results(ctx, result)`` raises a
    ``RuntimeError``.
    """

    trace_context: Optional["TraceContext"] = field(default=None)
    """W3C TraceContext for this run (FEAT-176 Phase 1.5).

    Seeded by the caller, or lazily created (root span) by
    ``FlowLifecycleAdapter`` on the first event of the run. Nodes and the
    code they invoke can read it to stitch their own spans (client/tool
    lifecycle events) onto the flow's trace.
    """

    # ── Agent resolution ──────────────────────────────────────────────────

    def resolve_agent(self, agent_ref: AgentRef) -> AgentLike:
        """Resolve an agent reference to a live agent instance.

        If *agent_ref* is already an ``AgentLike`` (not a string), return it
        unchanged.  If it is a string, look it up in the bound
        ``agent_registry`` and return the result.

        Args:
            agent_ref: Either an ``AgentLike`` instance (returned as-is) or a
                string agent name looked up via the registry.

        Returns:
            The resolved ``AgentLike`` agent.

        Raises:
            AgentNotFoundError: If *agent_ref* is a string and cannot be found
                in the registry, or if no registry is bound to this context.
        """
        if not isinstance(agent_ref, str):
            # Already an AgentLike instance — pass it through unchanged.
            return agent_ref  # type: ignore[return-value]

        if self.agent_registry is None:
            raise AgentNotFoundError(
                f"Cannot resolve agent_ref={agent_ref!r}: "
                "no agent_registry is bound to this FlowContext. "
                "Pass agent_registry= when constructing FlowContext or "
                "use AgentsFlow.from_definition(agent_registry=...)."
            )

        # AgentRegistry.get_bot_instance returns None on miss (sync lookup).
        agent = self.agent_registry.get_bot_instance(agent_ref)
        if agent is None:
            raise AgentNotFoundError(
                f"Agent not registered: {agent_ref!r}. "
                "Ensure the agent is registered before constructing the flow."
            )
        return agent  # type: ignore[return-value]

    # ── Dependency checking ───────────────────────────────────────────────

    def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool:
        """Return True if all ``dependencies`` are in ``completed_tasks``.

        Args:
            _node_id: The node being evaluated (unused; kept for API symmetry).
            dependencies: Set of node_ids that must complete first.

        Returns:
            ``True`` when all dependencies are satisfied.
        """
        return dependencies.issubset(self.completed_tasks)

    # ── Completion tracking ───────────────────────────────────────────────

    def mark_completed(
        self,
        node_id: str,
        result: Any = None,
        response: Any = None,
        metadata: Optional[NodeExecutionInfo] = None,
    ) -> None:
        """Record that a node has completed and store its outputs.

        Updates ``completed_tasks``, ``completion_order``, and removes
        ``node_id`` from ``active_tasks``.  Stores ``result``,
        ``response``, and ``metadata`` if not ``None``.

        Args:
            node_id: The completed node's unique identifier.
            result: Extracted output value (stored in ``self.results``).
            response: Raw response object (stored in ``self.responses``).
            metadata: Execution metadata (stored in ``self.node_metadata``).
        """
        self.completed_tasks.add(node_id)
        self.completion_order.append(node_id)
        self.active_tasks.discard(node_id)
        if result is not None:
            self.results[node_id] = result
        if response is not None:
            self.responses[node_id] = response
        if metadata is not None:
            self.node_metadata[node_id] = metadata

    def mark_failed(
        self,
        node_id: str,
        error: Exception,
        metadata: Optional[NodeExecutionInfo] = None,
    ) -> None:
        """Record that a node has failed and store the error.

        Removes ``node_id`` from ``active_tasks`` and writes the exception into
        ``errors``.  Optionally stores execution metadata in ``node_metadata``.

        Args:
            node_id: The failed node's unique identifier.
            error: The exception raised during execution.
            metadata: Optional execution metadata (stored in ``self.node_metadata``).
        """
        self.active_tasks.discard(node_id)
        self.errors[node_id] = error
        if metadata is not None:
            self.node_metadata[node_id] = metadata

    # ── Input assembly ────────────────────────────────────────────────────

    def get_input_for_node(
        self,
        node_id: str,
        dependencies: Set[str],
    ) -> Dict[str, Any]:
        """Prepare the input payload for a node.

        If the node has no dependencies the payload contains only the
        ``initial_task``.  Otherwise it also includes a ``dependencies``
        dict with each dependency's result (if available).

        Args:
            node_id: The target node's identifier (unused but kept for symmetry).
            dependencies: Set of node_ids whose results should be included.

        Returns:
            Dict with keys ``"task"`` and optionally ``"dependencies"``.
        """
        if not dependencies:
            return {"task": self.initial_task}

        return {
            "task": self.initial_task,
            "dependencies": {
                dep: self.results.get(dep)
                for dep in dependencies
                if dep in self.results
            },
        }

    # ── Backward-compat aliases ───────────────────────────────────────────

    @property
    def agent_metadata(self) -> Dict[str, NodeExecutionInfo]:
        """Alias for ``node_metadata`` (backward compat with ``crew.FlowContext``)."""
        return self.node_metadata

    def get_input_for_agent(
        self,
        agent_name: str,
        dependencies: Set[str],
    ) -> Dict[str, Any]:
        """Alias for ``get_input_for_node()`` (backward compat with ``crew.FlowContext``).

        Args:
            agent_name: Forwarded as ``node_id`` to the primary method.
            dependencies: Forwarded unchanged.

        Returns:
            Same as ``get_input_for_node()``.
        """
        return self.get_input_for_node(agent_name, dependencies)
