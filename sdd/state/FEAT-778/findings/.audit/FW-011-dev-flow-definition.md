---
id: FW-011
query_id: Q011
type: wiki_page
intent: "Declarative dev-flow topology: stage/edge declaration"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-011 — Flows are declared as `FlowDefinition(nodes=[NodeDefinition(id,type)], edges=[EdgeDefinition(from,to,condition,predicate)])` with CEL predicates; node *types* resolve from an engine `NODE_REGISTRY`; nodes carry no lead/support/inputs/outputs/gate fields

## Summary

`flows/dev_flow/definition.py` builds the dev-flow as a `FlowDefinition` (`parrot.bots.flows.flow.definition`): `NodeDefinition(id=..., type="dev_loop.<id>")` and `EdgeDefinition(**{"from": A}, to=B, condition="on_success"|"on_condition"|"on_error", predicate=<CEL>)`. Node ids/CEL predicates are imported from `dev_loop/definition.py` so the two graphs cannot drift. Execution uses the engine's explicit-edge mode because `from_definition`'s AND-join scheduler cannot fire OR-joins. `FlowDefinition._validate_acyclic` exempts `on_condition` back-edges (bounded retry loop). The module is pure (no env reads at import).

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py`
  lines: 1-120
  symbol: `build_dev_flow_definition`
  wiki_page_id: file:packages/ai-parrot/src/parrot/flows/dev_flow/definition.py
  score: 1.00
  excerpt: |
    from parrot.bots.flows.flow.definition import EdgeDefinition, FlowDefinition, NodeDefinition
    def _dev_loop_node(node_id: str) -> NodeDefinition:
        return NodeDefinition(id=node_id, type=f"dev_loop.{node_id}")
    EdgeDefinition(**{"from": DEV_INTAKE}, to=IDEATION, condition="on_condition", predicate=_CEL_IS_NL_REQUEST)
    return FlowDefinition(flow="dev-flow", description=..., nodes=nodes, edges=edges)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py`
  symbol: `_CEL_QA_PASSED, PLANNER, DEVELOPMENT, QA, FAILURE, CLOSE`
  wiki_page_id: file:packages/ai-parrot/src/parrot/flows/dev_flow/definition.py
  score: 1.00
  excerpt: |
    from parrot.flows.dev_loop.definition import (_CEL_FEEDBACK_ACCEPT, ..., CLOSE, DEVELOPMENT, FAILURE, ...)

## Notes

The source's stage YAML (`lead`, `support`, `mode`, `inputs`, `outputs: {schema}`, `gate`) has no equivalent in `NodeDefinition`; a stage would be a *new node type* registered in `NODE_REGISTRY` whose config carries those fields, compiled into a `FlowDefinition`. The "compiler fails on unknown expert / schema-less artifact" rule can live in the stage node's Pydantic config validator.
[cross-lane: type=read, intent=read parrot/bots/flows/flow/definition.py NodeDefinition fields (config?) and NODE_REGISTRY]
