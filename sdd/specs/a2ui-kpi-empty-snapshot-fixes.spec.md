---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [a2ui, linked-surfaces, baking]
---

# Feature Specification: A2UI KPI empty-snapshot fixes

**Feature ID**: FEAT-816
**Date**: 2026-11-05
**Status**: approved
**Discovered-from**: `issue:819e882f4064`
**Parent spec**: `sdd/specs/a2ui-linked-surfaces.spec.md` (FEAT-598, M4 / AC16)

## 1. Motivation & Business Requirements

FEAT-598 M4 promises that `build_linked_surface(..., snapshot=False)` gives every source
`{"rows": []}` "so EVERY binding still resolves (bake_envelope never raises)". This holds for
collection bindings (`Chart.data` / `DataTable.data` = `/<key>/rows`), but the axis contract
also allows scalar row bindings such as `KPICard.value = {"path": "/<key>/rows/0/<col>"}`.
With empty rows (no snapshot, or a genuinely empty query result) row `0` does not exist, and
`bake_envelope` raises `BakeError: Unresolvable data-model path '/activity/rows/0/visits'`
(evidence: `artifacts/logs/feat598_contract_probes.log`).

## 2. Architectural Design

Reuse the existing absent-binding mechanism of the baker: a pointer listed in a component's
`metadata.extensions.parrot_optional` is OMITTED (not raised) when it fails to resolve
(`parrot/outputs/a2ui/baking.py` `_resolve_value`). `build_linked_surface` will, for every
component, append each top-level property binding of the form `/<rows-key>/rows/<n>/<col>`
(where `<rows-key>` is a linked source or inline root) to that component's
`parrot_optional` list (merged with any author-supplied entries, order-preserving, no
duplicates). Baking is unchanged; the absent scalar is the "loading / no data" representation
— the baked KPICard simply carries no `value`, and renderers already show a loading state (S9).

## 3. Module Breakdown

### M1 — mark row-scalar bindings optional
- File: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` (`build_linked_surface`).
- Tests: `packages/ai-parrot/tests/outputs/a2ui/linked/test_build_linked_surface.py`
  — no-snapshot KPI fixture and empty-result KPI fixture; both must bake without raising,
  and a snapshot KPI still bakes its value.

## 4. Acceptance Criteria
- [ ] AC1: a KPICard bound to `/activity/rows/0/visits` with `snapshot=False` bakes without `BakeError`.
- [ ] AC2: the same KPICard with an empty (zero-row, column-bearing) frame and `snapshot=True` bakes without `BakeError`.
- [ ] AC3: with a non-empty snapshot the KPICard value is baked to row 0's value (unchanged behaviour).
- [ ] AC4: existing `parrot_optional` entries on a component are preserved.
- [ ] AC5: existing linked-surface tests still pass.

## 5. Out of Scope
Changing `bake_envelope`; frontend renderer changes; non-`rows` scalar bindings.

## 6. Open Questions
None.
