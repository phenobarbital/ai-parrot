"""Build a runnable Community Manager :class:`AgentsFlow` for one tenant.

Uses the two-step recipe established by ``parrot.flows.dev_flow``: stage the
graph through ``from_definition`` (so the node factories run and produce live
nodes), extract the materialised nodes, then add them to a **fresh**
``AgentsFlow`` and re-declare every edge imperatively.

The second step is not ceremony. Declaring edges puts the scheduler into
explicit-edge mode, which is the only mode with OR-join semantics, skip
propagation and cyclic back-edges — and this graph needs all three: ``close``
has six predecessors and the guardrail repair loop is a cycle. A flow left
bound to its definition uses an AND-join and would never fire ``close``.

Edges come from :data:`~parrot_saas.flows.community_manager.definition.EDGES`,
the same tuple the declarative definition is built from, so the two cannot
drift.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from parrot.bots.flows.flow.flow import AgentsFlow

from ...tenancy.context import TenantContext
from . import definition as topo
from .factories import build_cm_node_factories


class _NullAgentRegistry:
    """Minimal registry satisfying ``from_definition``'s contract.

    The flow contains no ``type="agent"`` nodes — its LLM nodes hold an
    already-configured agent injected by their factory — so nothing is ever
    resolved through this. It exists because ``from_definition`` requires an
    ``agent_registry`` argument, and passing a real
    :class:`~parrot.registry.registry.AgentRegistry` would be actively wrong:
    that class creates directories, writes ``agents.yaml`` and appends to
    ``sys.path`` in its constructor, so instantiating one per tenant is not an
    option.
    """

    def get_bot_instance(self, name: str) -> None:
        """Always ``None`` — no agent-typed nodes exist in this graph."""
        return None

    def has(self, name: str) -> bool:
        """Always ``False``."""
        return False

    async def get_instance(self, name: str, request: Any = None, **kwargs: Any):
        """Always ``None``."""
        return None


def build_community_manager_flow(
    *,
    tenant: TenantContext,
    run_id: Optional[str] = None,
    checkpoint: bool = False,
    checkpoint_store: Optional[Any] = None,
    durable: bool = False,
    durable_store: Optional[Any] = None,
    on_node_event: Optional[Any] = None,
    agent_registry: Optional[Any] = None,
    **dependencies: Any,
) -> AgentsFlow:
    """Assemble the flow for ``tenant``.

    Args:
        tenant: The tenant this instance serves.
        run_id: Flow id, used as the checkpoint key. Defaults to a fresh UUID.
        checkpoint: Enable per-node checkpointing. Safe to turn on because
            every predicate in this graph is a CEL string; a single Python
            callable would make ``to_definition()`` raise and the engine would
            fail before running any node.
        checkpoint_store: Ephemeral checkpoint store (name or instance).
        durable: Also write through to a durable store.
        durable_store: The durable store (name or instance).
        on_node_event: Lifecycle listener(s) for telemetry.
        agent_registry: Registry bound to the flow context. Defaults to
            :class:`_NullAgentRegistry`.
        **dependencies: Forwarded to :func:`build_cm_node_factories`
            (``triage_agent``, ``review_source``, ``ruleset``, ``issuer``, …).

    Returns:
        A wired :class:`AgentsFlow` ready for ``run_flow()``.
    """
    registry = agent_registry or _NullAgentRegistry()
    staged = AgentsFlow.from_definition(
        topo.build_cm_flow_definition(),
        agent_registry=registry,
        node_factories=build_cm_node_factories(tenant=tenant, **dependencies),
    )
    nodes = staged._materialize_nodes()  # noqa: SLF001 - the documented recipe

    kwargs: dict[str, Any] = {}
    if checkpoint_store is not None:
        kwargs["checkpoint_store"] = checkpoint_store
    if durable_store is not None:
        kwargs["durable_store"] = durable_store

    flow = AgentsFlow(
        name=f"cm.{tenant.tenant_id}",
        flow_id=run_id,
        checkpoint=checkpoint,
        durable=durable,
        on_node_event=on_node_event,
        **kwargs,
    )
    for node in nodes.values():
        flow.add_node(node)
    for source, target, condition, predicate in topo.EDGES:
        flow.add_edge(source, target, condition=condition, predicate=predicate)
    return flow


def executable_edges(flow: AgentsFlow) -> set[tuple[str, str, str, Optional[str]]]:
    """Return a flow's declared edges as a comparable set.

    Used by the drift test that asserts the imperative graph matches the
    declarative one.

    Args:
        flow: A built flow.

    Returns:
        Set of ``(from, to, condition, predicate)`` tuples.
    """
    return {
        (edge.from_, edge.to, edge.condition, edge.predicate)
        for edge in flow._edges  # noqa: SLF001 - test/introspection helper
    }


def declared_edges() -> set[tuple[str, str, str, Optional[str]]]:
    """Return the declarative topology's edges as a comparable set."""
    result: set[tuple[str, str, str, Optional[str]]] = set()
    for source, target, condition, predicate in topo.EDGES:
        # add_edge promotes a predicate-bearing edge to "on_condition"; mirror
        # that here so the two sets are compared on equal terms.
        effective = "on_condition" if predicate else condition
        result.add((source, target, effective, predicate))
    return result


__all__ = (
    "build_community_manager_flow",
    "declared_edges",
    "executable_edges",
)
