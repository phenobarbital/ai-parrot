---
type: Wiki Summary
title: parrot.bots.flows.flow.flow
id: mod:parrot.bots.flows.flow.flow
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AgentsFlow — DAG execution engine (FEAT-163).
relates_to:
- concept: class:parrot.bots.flows.flow.flow.AgentsFlow
  rel: defines
- concept: class:parrot.bots.flows.flow.flow.CompletionEvent
  rel: defines
- concept: class:parrot.bots.flows.flow.flow.DecisionNode
  rel: defines
- concept: class:parrot.bots.flows.flow.flow.FlowEdge
  rel: defines
- concept: class:parrot.bots.flows.flow.flow.InteractiveDecisionFlowNode
  rel: defines
- concept: class:parrot.bots.flows.flow.flow.SynthesisNode
  rel: defines
- concept: func:parrot.bots.flows.flow.flow.register_node
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.node
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.storage
  rel: references
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.bots.flows.flow.cel_evaluator
  rel: references
- concept: mod:parrot.bots.flows.flow.definition
  rel: references
- concept: mod:parrot.bots.flows.flow.nodes
  rel: references
- concept: mod:parrot.registry.registry
  rel: references
---

# `parrot.bots.flows.flow.flow`

AgentsFlow — DAG execution engine (FEAT-163).

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

## Classes

- **`CompletionEvent`** — Event pushed to the scheduler's completion queue when a node finishes.
- **`FlowEdge`** — Programmatic transition edge between two nodes.
- **`AgentsFlow(PersistenceMixin)`** — DAG executor consuming ``parrot.bots.flows.core`` primitives.
- **`DecisionNode(Node)`** — Wraps the legacy DecisionFlowNode as a frozen Pydantic Node.
- **`InteractiveDecisionFlowNode(Node)`** — DAG-executor wrapper for the CLI-blocking interactive decision node.
- **`SynthesisNode(Node)`** — In-graph result synthesis using the ``synthesize_results`` util.

## Functions

- `def register_node(name: str) -> Callable[[Type[Node]], Type[Node]]` — Register a Node subclass under ``name`` in ``NODE_REGISTRY``.
