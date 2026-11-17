---
id: F015
query_id: Q035
type: read
intent: "Read dev_flow definition: stage/node declaration, gates, inputs/outputs — template for stage YAML."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 600
parent_id: null
depth: 0
merged_from: [FC-016-dev-flow-definition, FW-011-dev-flow-definition]
---

# F015 — Declarative flow topology = `FlowDefinition` of `NodeDefinition(id, type)` + `EdgeDefinition(from, to, condition, predicate=CEL)`; nodes resolve by type name from an engine `NODE_REGISTRY`

## Summary

*[FC-016-dev-flow-definition]* `flows/dev_flow/definition.py` (195 lines, FEAT-412) is pure (no env reads). Nodes are built as `NodeDefinition(id=node_id, type="dev_flow.<id>")` or reused `dev_loop.<id>` types; edges use `condition="on_success"|"on_condition"` with CEL predicates imported (not re-spelled) from the imperative flow so the two graphs cannot drift. There is no stage-level "lead/support/inputs/outputs schema/gate" vocabulary — gates are nodes/actions in the dev_loop session state (FC-017). A stage spec compiler would layer on top of this FlowDefinition.

*[FW-011-dev-flow-definition]* `flows/dev_flow/definition.py` builds the dev-flow as a `FlowDefinition` (`parrot.bots.flows.flow.definition`): `NodeDefinition(id=..., type="dev_loop.<id>")` and `EdgeDefinition(**{"from": A}, to=B, condition="on_success"|"on_condition"|"on_error", predicate=<CEL>)`. Node ids/CEL predicates are imported from `dev_loop/definition.py` so the two graphs cannot drift. Execution uses the engine's explicit-edge mode because `from_definition`'s AND-join scheduler cannot fire OR-joins. `FlowDefinition._validate_acyclic` exempts `on_condition` back-edges (bounded retry loop). The module is pure (no env reads at import).

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py`
  lines: 1-37
  symbol: `module docstring`
  excerpt: |
    """Declarative dev-flow topology (FEAT-412).
    Authors the ``dev-flow`` graph as a :class:`FlowDefinition` ...
    same CEL predicates (imported, not re-spelled, so the two graphs cannot ...
    This module is pure: no env reads at import time."""

- path: `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py`
  lines: 104-117
  symbol: `_dev_flow_node / _dev_loop_node`
  excerpt: |
    return NodeDefinition(id=node_id, type=f"dev_flow.{node_id}")
    return NodeDefinition(id=node_id, type=f"dev_loop.{node_id}")  # resolve from engine NODE_REGISTRY

- path: `packages/ai-parrot/src/parrot/flows/dev_flow/definition.py`
  lines: 119-160
  symbol: `build_dev_flow_definition`
  excerpt: |
    EdgeDefinition(**{"from": DEV_INTAKE}, to=IDEATION, condition="on_condition", predicate=_CEL_IS_NL_REQUEST)
    EdgeDefinition(**{"from": IDEATION}, to=PLANNER, condition="on_success")

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

*[FC-016-dev-flow-definition]* The source's "scope grid decides which stages exist" maps to CEL-conditioned edges or to building a different FlowDefinition per scope.

*[FW-011-dev-flow-definition]* The source's stage YAML (`lead`, `support`, `mode`, `inputs`, `outputs: {schema}`, `gate`) has no equivalent in `NodeDefinition`; a stage would be a *new node type* registered in `NODE_REGISTRY` whose config carries those fields, compiled into a `FlowDefinition`. The "compiler fails on unknown expert / schema-less artifact" rule can live in the stage node's Pydantic config validator.
[cross-lane: type=read, intent=read parrot/bots/flows/flow/definition.py NodeDefinition fields (config?) and NODE_REGISTRY]
