---
id: FC-016
query_id: Q035
type: read
intent: "Read dev_flow definition: stage/node declaration, gates, inputs/outputs — template for stage YAML."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-016 — Declarative flow topology = `FlowDefinition` of `NodeDefinition(id, type)` + `EdgeDefinition(from, to, condition, predicate=CEL)`; nodes resolve by type name from an engine `NODE_REGISTRY`

## Summary

`flows/dev_flow/definition.py` (195 lines, FEAT-412) is pure (no env reads). Nodes are built as `NodeDefinition(id=node_id, type="dev_flow.<id>")` or reused `dev_loop.<id>` types; edges use `condition="on_success"|"on_condition"` with CEL predicates imported (not re-spelled) from the imperative flow so the two graphs cannot drift. There is no stage-level "lead/support/inputs/outputs schema/gate" vocabulary — gates are nodes/actions in the dev_loop session state (FC-017). A stage spec compiler would layer on top of this FlowDefinition.

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

## Notes

The source's "scope grid decides which stages exist" maps to CEL-conditioned edges or to building a different FlowDefinition per scope.
