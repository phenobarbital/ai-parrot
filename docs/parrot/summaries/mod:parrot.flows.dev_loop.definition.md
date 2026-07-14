---
type: Wiki Summary
title: parrot.flows.dev_loop.definition
id: mod:parrot.flows.dev_loop.definition
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative dev-loop topology — ``FlowDefinition`` authoring (FEAT-250 G1).
relates_to:
- concept: func:parrot.flows.dev_loop.definition.build_dev_loop_definition
  rel: defines
- concept: mod:parrot.bots.flows.flow.definition
  rel: references
---

# `parrot.flows.dev_loop.definition`

Declarative dev-loop topology — ``FlowDefinition`` authoring (FEAT-250 G1).

This module expresses the dev-loop graph declaratively as a
:class:`FlowDefinition` (nodes + edges), replacing the imperative wiring that
used to live inline in :func:`parrot.flows.dev_loop.flow.build_dev_loop_flow`.
The node types are the ``dev_loop.*`` types registered via ``@register_node``
on each node class; the live dependencies are injected at materialization time
by :func:`parrot.flows.dev_loop.factories.build_dev_loop_node_factories`.

Routing predicates are expressed as CEL strings on ``on_condition`` edges.
``cel_evaluator`` coerces a Pydantic node result via ``model_dump()``, so
``result.kind`` (``WorkBrief``) and ``result.passed`` (``QAReport``) resolve
exactly as the legacy Python callables (``_is_bug`` / ``_qa_passed`` …) did.

> **Execution note (engine limitation).** The graph below merges the bug and
> non-bug paths at ``research`` — an **OR-join**. The engine's
> ``from_definition`` scheduler uses an AND-join (a node spawns only when *all*
> its predecessors completed), which cannot fire ``research`` when the
> ``bug_intake`` branch is skipped. The dev-loop therefore *executes* in the
> engine's explicit-edge mode (OR-join + skip-propagation) — see
> ``flow.build_dev_loop_flow``. This module remains the single declarative
> source of the topology (used for materialization, validation, the parity
> test, and visualization).

## Functions

- `def build_dev_loop_definition(*, revision: bool=False) -> FlowDefinition` — Return the declarative dev-loop :class:`FlowDefinition`.
