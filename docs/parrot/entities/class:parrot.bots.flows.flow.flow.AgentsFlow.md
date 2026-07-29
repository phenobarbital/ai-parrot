---
type: Wiki Entity
title: AgentsFlow
id: class:parrot.bots.flows.flow.flow.AgentsFlow
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DAG executor consuming ``parrot.bots.flows.core`` primitives.
relates_to:
- concept: class:parrot.bots.flows.core.storage.persistence.PersistenceMixin
  rel: extends
---

# AgentsFlow

Defined in [`parrot.bots.flows.flow.flow`](../summaries/mod:parrot.bots.flows.flow.flow.md).

```python
class AgentsFlow(PersistenceMixin)
```

DAG executor consuming ``parrot.bots.flows.core`` primitives.

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
    on_node_event: Optional callback ``(event, node_id, info) -> None``
        (sync or async) — or a sequence of them — invoked by the
        scheduler on lifecycle transitions. ``event`` is one of
        ``"flow_started"``, ``"node_started"``, ``"node_completed"``,
        ``"node_failed"``, ``"node_skipped"``, ``"flow_completed"``
        (flow-level events carry ``node_id=""``). ``info`` carries
        ``"flow"`` (name) and ``"context"`` (the run's FlowContext),
        plus per-event extras: ``"duration_ms"`` on completions and
        failures, ``"error"``/``"error_type"`` on failures,
        ``"node_count"`` on flow_started, and ``"status"`` +
        outcome counts on flow_completed. Exceptions raised by a
        callback are logged, never propagated. More listeners can be
        attached later via :meth:`add_node_event_listener`.
    **kwargs: Forwarded to ``PersistenceMixin`` (and ultimately
        ``object.__init__``).

## Methods

- `def add_node(self, node: Node) -> None` — Add a ``Node`` instance to the internal graph.
- `def add_edge(self, from_: str, to: str, *, condition: str='always', predicate: Optional[Union[str, Callable[[Any], bool]]]=None) -> FlowEdge` — Declare a transition edge between two programmatically-added nodes.
- `def add_node_event_listener(self, callback: Callable[[str, str, Dict[str, Any]], Any]) -> None` — Attach an additional node-event listener.
- `def from_definition(cls, definition: FlowDefinition, *, agent_registry: Optional[AgentRegistry]=None, node_factories: Optional[dict[str, Callable[['NodeDefinition', set[str], set[str]], Node]]]=None) -> 'AgentsFlow'` — Materialize an executable ``AgentsFlow`` from a ``FlowDefinition``.
- `async def run_flow(self, ctx: Optional[Union[FlowContext, str]]=None, *, on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...]=()) -> FlowResult` — Run the flow DAG with event-driven scheduling.
