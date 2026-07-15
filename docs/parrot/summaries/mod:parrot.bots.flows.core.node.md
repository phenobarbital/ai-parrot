---
type: Wiki Summary
title: parrot.bots.flows.core.node
id: mod:parrot.bots.flows.core.node
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — Node Hierarchy.
relates_to:
- concept: class:parrot.bots.flows.core.node.AgentNode
  rel: defines
- concept: class:parrot.bots.flows.core.node.EndNode
  rel: defines
- concept: class:parrot.bots.flows.core.node.Node
  rel: defines
- concept: class:parrot.bots.flows.core.node.StartNode
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
---

# `parrot.bots.flows.core.node`

Flow Primitives — Node Hierarchy.

Provides the shared Node ABC and concrete node types used by both
``AgentCrew`` and ``AgentsFlow`` orchestration engines.

**Architecture (FEAT-163 / B-lite shape):**

Nodes are frozen Pydantic ``BaseModel`` subclasses
(``model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)``).
This means:

- Field reassignment (``node.node_id = x``) raises ``ValidationError``.
- *Nested* object mutation is allowed: ``node.fsm.start()`` works because
  it mutates the FSM's internal state without reassigning the ``fsm`` field.
- ``_pre_actions`` / ``_post_actions`` are ``PrivateAttr`` lists, also
  mutable (appending does not reassign the field — frozen-safe).

**Concurrent-run safety:**

The scheduler (``AgentsFlow.run_flow``) materializes a *fresh* set of Node
instances per invocation via ``_materialize_nodes()``.  Each concurrent
``run_flow()`` call gets its own independent FSM state.

**Execute signature (changed in FEAT-163):**

``AgentNode.execute(ctx, deps, **kwargs) -> Any``

The old signature ``(prompt, *, timeout, **ctx)`` is gone.  Prompt
derivation now lives in the overridable ``_build_prompt(ctx, deps)`` helper.

Key difference from ``parrot.bots.flow.node``:
  ``Node`` carries a ``node_id`` field (unique per graph instance)
  separate from the ``name`` property (agent identity).

Classes:
    Node — abstract base with ``node_id``, logger, and action hooks.
    AgentNode — wraps an ``AgentLike`` agent + ``AgentTaskMachine`` FSM.
    StartNode — virtual entry-point node (name defaults to ``'__start__'``).
    EndNode — virtual exit-point node (name defaults to ``'__end__'``).

See also:
    ``sdd/specs/agentsflow-refactor-spec3.spec.md`` §2-3 for the full
    architectural rationale (B-lite approach).
    ``sdd/proposals/agentsflow-refactor-spec3.brainstorm.md`` for
    option comparison.

## Classes

- **`Node(BaseModel)`** — Abstract base for all flow/crew nodes (frozen Pydantic).
- **`AgentNode(Node)`** — A graph node that wraps an ``AgentLike`` agent and an FSM.
- **`StartNode(Node)`** — Virtual entry-point node for flow/crew DAGs.
- **`EndNode(Node)`** — Virtual exit-point node for flow/crew DAGs.
