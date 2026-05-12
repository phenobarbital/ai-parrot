"""AgentsFlow — DAG execution engine (FEAT-163).

The new executor replaces ``parrot/bots/flow/fsm.py:AgentsFlow`` with an
event-driven scheduler consuming ``parrot.bots.flows.core`` primitives.

Key components:
    NODE_REGISTRY: Module-level registry mapping node type name → Node subclass.
    @register_node: Decorator factory to register Node subclasses.
    CompletionEvent: Dataclass pushed to the scheduler's completion queue when
        a node finishes (node_id, result, error).
    AgentsFlow: The new DAG executor class. Inherits PersistenceMixin for
        result persistence. Does NOT inherit SynthesisMixin (spec §1 + §5).
        Scheduler in TASK-1067; from_definition in TASK-1068.

See sdd/specs/agentsflow-refactor-spec3.spec.md for the full design.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Type

from pydantic import Field as PydanticField
from navconfig.logging import logging

# ─── flows.core primitives (import, do not redefine) ────────────────────────

from .core.node import AgentNode, EndNode, Node, StartNode
from .core.context import FlowContext
from .core.fsm import AgentTaskMachine
from .core.result import FlowResult
from .core.storage import PersistenceMixin
from .core.storage.synthesis import synthesize_results
from .core.types import DependencyResults

# Declarative layer (read-only; type annotation only in __init__)
from parrot.bots.flow.definition import FlowDefinition  # type: ignore[import-untyped]

# Decision-node legacy wrappers
from parrot.bots.flow.decision_node import (  # type: ignore[import-untyped]
    DecisionFlowNode,
    DecisionMode,
    DecisionNodeConfig,
    DecisionResult,
)
from parrot.bots.flow.interactive_node import (  # type: ignore[import-untyped]
    InteractiveDecisionNode as LegacyInteractiveDecisionNode,
)

# AgentRegistry (type annotation only)
from parrot.registry.registry import AgentRegistry  # type: ignore[import-untyped]


logger = logging.getLogger(__name__)


# ─── CompletionEvent ─────────────────────────────────────────────────────────


@dataclass
class CompletionEvent:
    """Event pushed to the scheduler's completion queue when a node finishes.

    Attributes:
        node_id: Identifier of the node that finished.
        result: The result value returned by the node (``None`` on error).
        error: The exception raised by the node (``None`` on success).
    """

    node_id: str
    result: Any = None
    error: Optional[BaseException] = None


# ─── NODE_REGISTRY + @register_node ──────────────────────────────────────────

NODE_REGISTRY: dict[str, Type[Node]] = {}
"""Module-level mapping of node type name → Node subclass.

Populated at module load time by ``register_node()`` calls at the bottom of
this file (core types: ``"agent"``, ``"start"``, ``"end"``) and by
``TASK-1066`` for ``"decision"``, ``"interactive_decision"``, ``"synthesis"``.
"""


def register_node(name: str) -> Callable[[Type[Node]], Type[Node]]:
    """Register a Node subclass under ``name`` in ``NODE_REGISTRY``.

    This is a decorator factory; apply it to a Node subclass:

    Example::

        @register_node("my-type")
        class MyNode(AgentNode):
            ...

    Args:
        name: The type key under which to register the class. Must be unique
            across the registry.

    Returns:
        A decorator that registers the class and returns it unchanged.

    Raises:
        ValueError: If ``name`` is already registered.
        TypeError: If the decorated class is not a ``Node`` subclass.
    """

    def decorator(cls: Type[Node]) -> Type[Node]:
        if not (isinstance(cls, type) and issubclass(cls, Node)):
            raise TypeError(
                f"@register_node({name!r}) target must be a Node subclass, got {cls!r}"
            )
        if name in NODE_REGISTRY:
            raise ValueError(
                f"Node type {name!r} already registered to "
                f"{NODE_REGISTRY[name].__name__}"
            )
        NODE_REGISTRY[name] = cls
        return cls

    return decorator


# ─── AgentsFlow class skeleton ────────────────────────────────────────────────


class AgentsFlow(PersistenceMixin):
    """DAG executor consuming ``parrot.bots.flows.core`` primitives.

    This is the new-style flow executor that replaces the legacy
    ``parrot.bots.flow.fsm.AgentsFlow``. It operates on a graph of ``Node``
    instances materialized from a ``FlowDefinition`` (see ``from_definition``)
    or built programmatically via ``add_node``.

    Inherits ``PersistenceMixin`` for async result persistence.
    Does **not** inherit ``SynthesisMixin`` — use the ``synthesize_results``
    util as an ``on_complete`` hook instead (spec §1 Goals + §5 AC).

    Args:
        name: Human-readable name for this flow instance (used in logs).
        definition: Optional ``FlowDefinition`` captured for reference.
        agent_registry: Optional ``AgentRegistry`` bound to the flow's
            execution context. Used by ``from_definition`` (TASK-1068) for
            eager agent resolution.
        **kwargs: Forwarded to ``PersistenceMixin`` (and ultimately
            ``object.__init__``).
    """

    def __init__(
        self,
        name: str,
        *,
        definition: Optional[FlowDefinition] = None,
        agent_registry: Optional[AgentRegistry] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self._definition = definition
        self._agent_registry = agent_registry
        self._nodes: dict[str, Node] = {}
        self.logger = logging.getLogger(f"parrot.flow.{name}")

    # ── Graph construction ────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        """Add a ``Node`` instance to the internal graph.

        Args:
            node: The ``Node`` to add. Its ``node_id`` must be unique within
                this flow.

        Raises:
            ValueError: If a node with the same ``node_id`` is already present.
        """
        if node.node_id in self._nodes:
            raise ValueError(
                f"Node {node.node_id!r} already added to flow {self.name!r}"
            )
        self._nodes[node.node_id] = node
        self.logger.debug("Added node %r to flow %r", node.node_id, self.name)

    # ── Class-method factory (placeholder — TASK-1068) ────────────────────

    @classmethod
    def from_definition(
        cls,
        definition: FlowDefinition,
        *,
        agent_registry: Optional[AgentRegistry] = None,
    ) -> "AgentsFlow":
        """Materialize an ``AgentsFlow`` from a ``FlowDefinition``.

        .. note::
            This method is a placeholder. Implementation arrives in TASK-1068.

        Raises:
            NotImplementedError: Always (until TASK-1068 is implemented).
        """
        raise NotImplementedError("Implemented in TASK-1068")

    # ── Scheduler (placeholder — TASK-1067) ──────────────────────────────

    async def run_flow(
        self,
        ctx: Optional[FlowContext] = None,
        *,
        on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Run the flow DAG with event-driven scheduling.

        .. note::
            This method is a placeholder. Event-driven scheduler implementation
            arrives in TASK-1067.

        Raises:
            NotImplementedError: Always (until TASK-1067 is implemented).
        """
        raise NotImplementedError("Implemented in TASK-1067")


# ─── New Node subclasses (TASK-1066) ─────────────────────────────────────────


@register_node("decision")
class DecisionNode(Node):
    """Wraps the legacy DecisionFlowNode as a frozen Pydantic Node.

    Holds a ``DecisionNodeConfig`` and a dict of participating agents;
    constructs a fresh ``DecisionFlowNode`` on each ``execute()`` call so
    per-run state is isolated (B-lite contract).

    Args:
        node_id: Unique identifier within the graph.
        decision_config: Configuration for the decision node (mode, etc.).
        agents: Mapping of agent_name → agent instance participating in the
            decision. These are forwarded to the legacy DecisionFlowNode.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if None.
    """

    node_id: str
    decision_config: DecisionNodeConfig
    agents: Dict[str, Any] = PydanticField(default_factory=dict)
    """Participating agents forwarded to DecisionFlowNode.  Typed as Dict[str, Any]
    because arbitrary agent types (BasicAgent, AbstractBot, etc.) are allowed."""
    dependencies: Set[str] = PydanticField(default_factory=set)
    successors: Set[str] = PydanticField(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> DecisionResult:
        """Execute the decision node.

        Constructs a fresh legacy DecisionFlowNode from the stored config and
        agents, calls its .ask() method with a prompt derived from the context,
        and returns the DecisionResult.

        Args:
            ctx: The current flow execution context.
            deps: Results from completed dependencies.
            **kwargs: Extra execution context (session_id, user_id, timeout, …).

        Returns:
            DecisionResult with final_decision and voting details.
        """
        await self.run_pre_actions(prompt="", **kwargs)

        # Build a fresh legacy node per execute() — no shared per-run state.
        legacy = DecisionFlowNode(
            name=self.node_id,
            agents=self.agents,
            config=self.decision_config,
        )

        # Build a simple prompt from the flow's initial task.
        prompt = getattr(ctx, "initial_task", "") or ""

        result: DecisionResult = await legacy.ask(question=prompt, **kwargs)
        await self.run_post_actions(result=result, **kwargs)
        return result


@register_node("interactive_decision")
class InteractiveDecisionNode(Node):
    """Wraps the legacy CLI-blocking InteractiveDecisionNode as a Pydantic Node.

    Presents a multiple-choice question in the terminal at decision time.
    The underlying implementation uses ``questionary`` and is intentionally
    blocking — HITL improvements are a future spec.

    Args:
        node_id: Unique identifier within the graph.
        question: The prompt text shown to the user.
        options: A list of string options to choose from.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if None.
    """

    node_id: str
    question: str
    options: List[str] = PydanticField(default_factory=list)
    dependencies: Set[str] = PydanticField(default_factory=set)
    successors: Set[str] = PydanticField(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> DecisionResult:
        """Present a CLI menu and return the user's selection as a DecisionResult.

        Constructs a fresh legacy LegacyInteractiveDecisionNode per call so
        per-run state is isolated (B-lite contract).

        Args:
            ctx: The current flow execution context.
            deps: Results from completed dependencies.
            **kwargs: Extra execution context forwarded to the legacy node.

        Returns:
            DecisionResult with the user's selection in final_decision.
        """
        await self.run_pre_actions(prompt=self.question, **kwargs)

        legacy = LegacyInteractiveDecisionNode(
            name=self.node_id,
            question=self.question,
            options=self.options,
        )

        result: DecisionResult = await legacy.ask(question=self.question, **kwargs)
        await self.run_post_actions(result=result, **kwargs)
        return result


@register_node("synthesis")
class SynthesisNode(Node):
    """In-graph result synthesis using the ``synthesize_results`` util.

    Acts as a leaf or near-leaf node that aggregates upstream agent results
    and passes them to the shared ``synthesize_results`` function (TASK-1063).
    The result is a string summary.

    The ``ctx.synthesis_client`` attribute must be set before the scheduler
    runs this node (or a RuntimeError is raised).

    TODO (TASK-1067 integration): Once the scheduler exposes a partial
    ``FlowResult`` on the context, pass it directly to ``synthesize_results``
    instead of constructing a minimal view from ``deps``.

    Args:
        node_id: Unique identifier within the graph.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if None.
    """

    node_id: str
    dependencies: Set[str] = PydanticField(default_factory=set)
    successors: Set[str] = PydanticField(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook."""
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> str:
        """Run LLM synthesis over the accumulated dependency results.

        Builds a minimal ``FlowResult``-like view from ``deps`` and delegates
        to ``synthesize_results(ctx, partial_result)``.

        Args:
            ctx: The current flow execution context. Must have ``synthesis_client``
                set (see ``FlowContext.synthesis_client``).
            deps: Mapping of completed dependency node_id → result string.
            **kwargs: Forwarded to ``synthesize_results`` (max_tokens, temperature,
                user_id, session_id).

        Returns:
            Synthesis summary string.
        """
        await self.run_pre_actions(prompt="synthesis", **kwargs)

        # Build a minimal FlowResult-like object from the dependency results.
        # Once TASK-1067 ships, the scheduler may expose ctx.partial_result instead.
        class _PartialResult:
            """Minimal FlowResult duck-type for synthesize_results."""

            def __init__(self, responses: Dict[str, Any]) -> None:
                self.responses = responses
                self.summary = ""

        partial = _PartialResult(responses=dict(deps))

        summary = await synthesize_results(ctx, partial)  # type: ignore[arg-type]
        await self.run_post_actions(result=summary, **kwargs)
        return summary


# ─── Register built-in core Node types ───────────────────────────────────────
# Must come AFTER the class definitions so the Node subclasses are in scope.

register_node("agent")(AgentNode)
register_node("start")(StartNode)
register_node("end")(EndNode)


# ─── Public API ───────────────────────────────────────────────────────────────

__all__ = [
    "AgentsFlow",
    "CompletionEvent",
    "NODE_REGISTRY",
    "register_node",
    # Node subclasses (TASK-1066)
    "DecisionNode",
    "InteractiveDecisionNode",
    "SynthesisNode",
]
