---
id: F011
query_id: Q011
type: grep
intent: FilterBar parrot_param / LinkedLane.setParam
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F011 — FilterBar parrot_param → setParam; no tool can emit it

## Summary
FilterBar lowers `param:{source,name}` into ChoicePicker + metadata.extensions.parrot_param; Svelte A2UINode calls lane.setParam, else filters locally. qs_build_linked_surface emits exactly one component and cannot add a FilterBar or second source, so examples must call builders.build_linked_surface from a custom TOOL. Validation never checks param.source/name exist; TS setParam does not check declared params (Python ignores undeclared).

## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py`
  lines: 55-58, 90-115
  symbol: `FilterBar`
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte`
  lines: 39-157
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts`
  lines: 176, 218-224
  symbol: `LinkedLane.setParam`
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 339-455
  symbol: `QuerysourceToolkit.build_linked_surface`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py`
  lines: 516-620
  symbol: `_validate_linked_sources`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 477-552
  symbol: `build_linked_surface`
