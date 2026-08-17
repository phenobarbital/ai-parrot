"""Idempotent ``NODE_REGISTRY`` registration for Thales node types (FEAT-425).

Verified during TASK-2231: ``AgentsFlow``'s ``checkpoint=True`` (FEAT-399)
unconditionally calls ``to_definition()`` as a fail-fast export check
(``_ensure_checkpointer``), and that export requires every node's class to
resolve via the global ``NODE_REGISTRY`` — regardless of whether the flow
is assembled declaratively (``from_definition``) or programmatically
(``add_node``/``add_edge``, what Thales actually uses). This directly
mirrors ``parrot.flows.dev_loop.nodes.base.register_dev_loop_node`` (FEAT-250),
which exists for the exact same reason.

``register_node()`` (the engine's own decorator) raises on a duplicate
registration; this wrapper makes registration a no-op when ``name`` is
already registered, so re-imports of ``parrot.flows.thales`` never raise.
"""

from __future__ import annotations

from typing import Type, TypeVar

from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node

NodeT = TypeVar("NodeT", bound=Type[Node])


def register_thales_node(name: str):
    """Idempotent ``@register_node`` for the Thales node types (FEAT-425)."""

    def _decorator(cls: NodeT) -> NodeT:
        if name in NODE_REGISTRY:
            return cls
        return register_node(name)(cls)

    return _decorator
