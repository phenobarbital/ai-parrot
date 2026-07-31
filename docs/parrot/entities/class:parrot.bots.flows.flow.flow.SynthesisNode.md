---
type: Wiki Entity
title: SynthesisNode
id: class:parrot.bots.flows.flow.flow.SynthesisNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-graph result synthesis using the ``synthesize_results`` util.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# SynthesisNode

Defined in [`parrot.bots.flows.flow.flow`](../summaries/mod:parrot.bots.flows.flow.flow.md).

```python
class SynthesisNode(Node)
```

In-graph result synthesis using the ``synthesize_results`` util.

Acts as a leaf or near-leaf node that aggregates upstream agent results
and passes them to the shared ``synthesize_results`` function (TASK-1063).
The result is a string summary.

The ``ctx.synthesis_client`` attribute must be set before the scheduler
runs this node (or a RuntimeError is raised).

NOTE: FEAT-196 deferred — once the scheduler exposes a partial FlowResult
on the context, pass it directly to ``synthesize_results`` instead of
constructing a minimal view from ``deps``. Tracked as tech debt post-migration.

Args:
    node_id: Unique identifier within the graph.
    dependencies: Set of node_ids that must complete first.
    successors: Set of node_ids that depend on this one.
    fsm: Auto-created if None.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create FSM and call parent hook.
- `def name(self) -> str` — Node identifier.
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> str` — Run LLM synthesis over the accumulated dependency results.
