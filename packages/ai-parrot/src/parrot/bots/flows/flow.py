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
from typing import Any, Awaitable, Callable, Optional, Tuple, Type

from navconfig.logging import logging

# ─── flows.core primitives (import, do not redefine) ────────────────────────

from .core.node import AgentNode, EndNode, Node, StartNode
from .core.context import FlowContext
from .core.result import FlowResult
from .core.storage import PersistenceMixin

# Declarative layer (read-only; type annotation only in __init__)
from parrot.bots.flow.definition import FlowDefinition  # type: ignore[import-untyped]

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
]
