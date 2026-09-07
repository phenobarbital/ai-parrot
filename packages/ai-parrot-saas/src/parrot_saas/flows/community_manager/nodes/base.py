"""Base class and registration helper for Community Manager flow nodes.

Two engine details drive this module, and both bite silently if ignored:

* The base :class:`~parrot.bots.flows.core.node.Node` does **not** declare an
  ``fsm`` field — only ``AgentNode`` does — yet the scheduler calls
  ``node.fsm.schedule()`` unconditionally for every node it dispatches. A
  custom node without one raises ``AttributeError`` on first dispatch, with a
  traceback that points at the engine rather than at the node.
* ``NODE_REGISTRY`` is process-global and ``register_node`` raises on a
  duplicate name, so a module re-imported after a ``sys.modules`` purge (as
  test suites do) would fail on the second pass.

Nodes are frozen Pydantic models, so per-run mutable state lives in
``FlowContext.shared_data``, never on the node.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set, Union

from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node
from pydantic import Field

from ..models import ContactChannel  # noqa: F401 - re-resolves annotations


def register_cm_node(name: str):
    """Idempotent :func:`register_node` for Community Manager node types.

    Args:
        name: Registry name, conventionally ``cm.<node>``.

    Returns:
        A class decorator that registers the class once and is a no-op on any
        subsequent import.
    """

    def _decorator(cls):
        if name in NODE_REGISTRY:
            return cls
        return register_node(name)(cls)

    return _decorator


class CMNode(Node):
    """Base node for the Community Manager flow.

    Subclasses implement ``execute(ctx, deps, **kwargs)`` and return one of the
    Pydantic models from :mod:`parrot_saas.flows.community_manager.models`.

    Attributes:
        dependencies: Upstream node ids. Optional — the engine derives them
            from the edge list in explicit-edge mode.
        successors: Downstream node ids. Optional, same reason.
        fsm: Per-run task state machine; auto-created when ``None``.
    """

    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create the FSM the scheduler will drive."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier used by the flow router."""
        return self.node_id

    @staticmethod
    def shared_state(ctx: Union[FlowContext, Dict[str, Any]]) -> Dict[str, Any]:
        """Return the mutable cross-node state mapping for ``ctx``.

        Args:
            ctx: A :class:`FlowContext`, or a plain dict in unit tests.

        Returns:
            The shared mutable mapping.

        Raises:
            TypeError: If ``ctx`` is neither.
        """
        if isinstance(ctx, FlowContext):
            return ctx.shared_data
        if isinstance(ctx, dict):
            return ctx
        raise TypeError(
            f"expected FlowContext or dict, got {type(ctx).__name__}"
        )

    def node_state(
        self, ctx: Union[FlowContext, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Return this node's own slice of the shared state.

        Nodes are frozen, so anything that must survive across a repair-loop
        re-entry (attempt counters, most importantly) lives here.

        Args:
            ctx: The flow execution context.

        Returns:
            A mutable dict scoped to this node id.
        """
        return self.shared_state(ctx).setdefault(self.node_id, {})

    @staticmethod
    async def with_timeout(awaitable, timeout: float, what: str):
        """Await ``awaitable`` under a wall-clock bound.

        The scheduler enforces no timeout of its own — ``FlowMetadata``'s
        ``execution_timeout`` is not honoured and ``on_timeout`` edges never
        fire — so every outbound call a node makes must bound itself.

        Args:
            awaitable: The coroutine to await.
            timeout: Seconds allowed.
            what: Description used in the error message.

        Returns:
            Whatever ``awaitable`` returns.

        Raises:
            TimeoutError: If the budget is exceeded.
        """
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"{what} exceeded {timeout:.0f}s") from exc


__all__ = ("CMNode", "register_cm_node")
