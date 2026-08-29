# TASK-2566: E2E conformance tests, frontend guide rewrite, migration note

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2563, TASK-2564, TASK-2565
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 — the closing gate. End-to-end conformance across the whole
bridge (agent → envelope → satellite renderer), frontend guide rewrite for the
v2 artifact contract + envelope, and the migration note documenting the
0.30 → 0.32 shim window (G6).

---

## Scope

- Integration tests (`packages/ai-parrot/tests/integration/`):
  - `test_structured_chart_e2e_a2ui` — PandasAgent chart → envelope validates;
    `EChartsRenderer.render(envelope)` succeeds; legacy G1–G3/G6 asserts pass.
  - `test_structured_table_e2e_a2ui` — `bake_envelope` expands `ChildTemplate`
    rows == dataModel rows; `PDFRenderer`/SSR render.
  - `test_structured_map_e2e_a2ui` — multi-layer map →
    `FoliumMapRenderer.render(envelope)` HTML contains N layers.
  - `test_frontend_guide_examples_validate` — every JSON example in the
    frontend guide passes `validate_message`.
- Rewrite `docs/frontend/structured-artifacts-frontend-guide.md`:
  §2.5 v2 artifact contract (`surfaceId`, `schemaVersion: 2`, component-node
  `definition`) + envelope consumption; §4–6 payload examples updated to real
  v1.0 envelopes; shim snippet (`artifact_definition_to_legacy`); note the one
  additive `surfaceId` key on `response.output`.
- Create `docs/migration/feat-473-structured-a2ui.md`: what changed, v1→v2
  artifact diff, shim usage, window "supported through 0.31, removed in 0.32".
- Run the full AC-13 gate and fix any residual failures in test code (not in
  feature code — regressions go back to the owning task).

**NOT in scope**: any production-code change beyond what Modules 1–6 landed
(file bugs against the owning task instead).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_structured_chart_e2e.py` | CREATE | chart e2e |
| `packages/ai-parrot/tests/integration/test_structured_table_e2e.py` | CREATE | table e2e + bake |
| `packages/ai-parrot/tests/integration/test_structured_map_e2e.py` | CREATE | map e2e |
| `packages/ai-parrot/tests/integration/test_frontend_guide_examples.py` | CREATE | guide JSON validation |
| `docs/frontend/structured-artifacts-frontend-guide.md` | MODIFY | v2 contract + envelope + shim |
| `docs/migration/feat-473-structured-a2ui.md` | CREATE | migration + deprecation window |

---

## Codebase Contract (Anti-Hallucination)

> By this task all Module 1–6 code exists on the feature branch. Anchors below
> are for the pieces this task consumes.

### Verified Imports
```python
# [470-wt → merged dev]
from parrot.outputs.a2ui.baking import bake_envelope           # baking.py:356 (expands ChildTemplate per data row)
from parrot.outputs.a2ui.catalog import validate_message, validate_envelope
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer
from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer
# from this feature:
from parrot.outputs.a2ui.adapters.structured import chart_to_surface, table_to_surface, map_to_surface
from parrot.outputs.a2ui.compat import artifact_definition_to_legacy, is_legacy_artifact
from parrot.outputs.a2ui.artifacts import attach_structured_artifact
```

### Existing Signatures to Use
```python
# docs/frontend/structured-artifacts-frontend-guide.md exists on dev — REWRITE sections, keep doc identity.
# AC-13 gate (exact command):
#   pytest packages/ai-parrot/tests/outputs packages/ai-parrot/tests/bots \
#          packages/ai-parrot/tests/integration -k "structured or a2ui"
# plus ruff on changed files.
```

### Does NOT Exist
- ~~`docs/migration/feat-473-structured-a2ui.md`~~ — this task creates it.
- ~~PDF/SSR structured-specific renderers~~ — reuse the generic FEAT-470 `pdf`/`ssr_html` A2UI renderers.

---

## Implementation Notes

### Key Constraints
- Guide examples must be REAL validated payloads — the
  `test_frontend_guide_examples_validate` test extracts fenced JSON blocks
  from the guide and runs `validate_message` on each.
- Deprecation window wording: target 0.30.0; shim supported through **0.31**,
  removed in **0.32** (AC-7).
- Document that `surfaceId` is the ONLY change to `response.output` (strict
  frontend validators gotcha, spec §7).
- E2E tests may stub LLM clients — the structured path itself is deterministic.

### References in Codebase
- `docs/migration/feat-201-ai-parrot-embeddings.md` — migration-note format precedent
- FEAT-470 conformance suite — envelope validation test patterns

---

## Acceptance Criteria

- [ ] All four integration tests pass (spec §4 Integration table)
- [ ] Every JSON example in the guide validates (`validate_message`)
- [ ] Guide documents v2 contract, envelope, shim, `surfaceId` key; migration note states the 0.30 → 0.32 window (AC-7)
- [ ] AC-13 gate green: `pytest packages/ai-parrot/tests/outputs packages/ai-parrot/tests/bots packages/ai-parrot/tests/integration -k "structured or a2ui"`; ruff clean on changed files
- [ ] All 13 spec acceptance criteria checked off in the spec

---

## Test Specification

```python
# tests/integration/test_structured_*_e2e.py — per spec §4 Integration table
async def test_structured_chart_e2e_a2ui(): ...
async def test_structured_table_e2e_a2ui(): ...
async def test_structured_map_e2e_a2ui(): ...
def test_frontend_guide_examples_validate(): ...
```

---

## Agent Instructions

1. Verify TASK-2563, TASK-2564 and TASK-2565 are all in `sdd/tasks/completed/`.
2. Run the AC-13 gate BEFORE writing anything to get the baseline.
3. Implement, verify all 13 spec ACs, move to completed, update index, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
