# TASK-5230: Mark linked row-scalar bindings optional so empty snapshots bake

**Feature**: FEAT-816 a2ui-kpi-empty-snapshot-fixes
**Spec**: `sdd/specs/a2ui-kpi-empty-snapshot-fixes.spec.md`
**Discovered-from**: `issue:819e882f4064`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
`build_linked_surface(snapshot=False)` (or an empty query result) yields `{"rows": []}`; a
`KPICard.value = {"path": "/<key>/rows/0/<col>"}` binding then makes `bake_envelope` raise.

## Scope
In `build_linked_surface`, add each top-level `{"path": "/<key>/rows/<n>/..."}` property binding
(key in sources ∪ inline) to that component's `metadata.extensions.parrot_optional`, merged
with existing entries.

**NOT in scope**: changes to `baking.py`, UI renderers.

## Files to Modify
- `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
- `packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py`

## Codebase Contract
### Verified Imports
- `from parrot.outputs.a2ui.baking import bake_envelope`
- `from parrot.outputs.a2ui.builders import build_linked_surface`
### Existing Signatures
- `builders.py`: `def build_linked_surface(components, sources, frames, *, surface_id, snapshot=True, max_snapshot_rows=500, catalog_id=..., inline=None) -> CreateSurface`
- `baking.py`: `_optional_paths(component)` reads `component.metadata.extensions.root["parrot_optional"]`.
### Does NOT Exist
- No `absent`/`loading` sentinel in the data model; do not invent one.

## Acceptance Criteria
See spec AC1–AC5.

## Validation Commands
```bash
PYTHONPATH=$PWD/packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py -q
ruff check packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
```

## Completion Note
(pending)
