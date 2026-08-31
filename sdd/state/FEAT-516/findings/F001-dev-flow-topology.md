---
id: F001
query_id: Q001
type: wiki_page
intent: Map the concrete dev_flow and dev_loop package structures before selecting implementation boundaries.
executed_at: 2026-08-31T15:09:15+02:00
duration_ms: 77900
parent_id: null
depth: 0
---

# F001 - Dev-flow reuses dev-loop nodes in an explicit-edge graph

## Summary

The existing FEAT-412 design makes `dev_flow` a sibling package but reuses the planner-through-handoff chain from `dev_loop`. Both builders materialize registered nodes from a declarative definition, then execute a programmatic explicit-edge graph because OR joins and bounded conditional back-edges require those scheduler semantics.

## Citations

- path: `sdd/specs/sdd-dev-flow.spec.md`
  lines: 72-132
  symbol: `Architectural Design`
  excerpt: |
    A new sibling package `parrot/flows/dev_flow/` reuses the dev_loop node types.
    The graph uses AgentsFlow explicit-edge mode for OR joins.
- path: `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py`
  lines: 137-172
  symbol: `build_dev_flow`
  excerpt: |
    staged = AgentsFlow.from_definition(..., node_factories=factories)
    flow = AgentsFlow(name=name, on_node_event=publisher)
    flow.add_edge(FEEDBACK_ROUTER, DEVELOPMENT, predicate=_feedback_retry)

## Notes

Wiki orientation returned the existing dev-flow spec as the highest-scoring page.

