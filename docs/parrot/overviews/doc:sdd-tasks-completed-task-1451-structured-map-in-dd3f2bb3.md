---
type: Wiki Overview
title: 'TASK-1451: Structured map end-to-end integration tests'
id: doc:sdd-tasks-completed-task-1451-structured-map-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §4 Integration Tests + §5 Acceptance Criteria. Validates the full pipeline:'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial
  rel: mentions
---

# TASK-1451: Structured map end-to-end integration tests

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1445, TASK-1446, TASK-1447, TASK-1448, TASK-1449, TASK-1450
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests + §5 Acceptance Criteria. Validates the full pipeline:
NL spatial query → `PandasAgent` (STRUCTURED_MAP) → `spatial_filter` per-dataset
result → `StructuredMapRenderer` → `StructuredMapConfig` + `response.data`, and
confirms the deterministic frontend path still works (no regression).

---

## Scope

- Add integration tests under `packages/ai-parrot/tests/integration/`:
  - `test_structured_map_e2e_llm_mode` — NL query → config + `response.data`.
  - `test_structured_map_e2e_multi_dataset` — two datasets → two layers, per-layer
    capping + viewport union.
  - `test_deterministic_handler_unchanged` — frontend path receives the legacy
    `SpatialFeatureCollection` shape.
- Add shared fixtures (`two_dataset_spatial_result`, `map_profiles`) if not already
  provided by earlier tasks; otherwise reuse.

**NOT in scope**: implementation of any module (all are dependencies). This task is
tests only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_structured_map_e2e.py` | CREATE | end-to-end + multi-dataset + handler-unchanged |
| `packages/ai-parrot/tests/integration/conftest.py` | MODIFY | shared map fixtures (if needed) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredMapConfig  # post TASK-1445
from parrot.outputs.formats import get_renderer                    # outputs/formats/__init__.py
from parrot.tools.dataset_manager.spatial import (
    SpatialFilterSpec, SpatialResult, SpatialLayerResult,          # post TASK-1446
)
```

### Existing Signatures to Use
```python
# Reference existing e2e test for shape/patterns:
# packages/ai-parrot/tests/integration/test_structured_table_e2e.py  (FEAT-218)
# packages/ai-parrot/tests/bots/test_pandasagent_structured_table.py
```

### Does NOT Exist
- ~~a live geospatial test DB~~ — use fixtures / mocked `spatial_filter` returning a `SpatialResult`; do NOT hit real PostGIS/BigQuery in unit/integration CI.

### Dependency note
- ALL of TASK-1445..1450 MUST be in `sdd/tasks/completed/` before starting.

---

## Implementation Notes

### Key Constraints
- `pytest-asyncio` for async tests; reuse the FEAT-218 e2e harness style.
- Mock the spatial execution (no real DB) — assert on the structured contract, not on geometry math.
- Assert the homologation invariants: `data` excluded from `output`, rows in
  `response.data`, `(out, explanation)` shape, per-layer capping preserved.

### References in Codebase
- `packages/ai-parrot/tests/integration/test_structured_table_e2e.py`.
- `packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py`.

---

## Acceptance Criteria

- [ ] `test_structured_map_e2e_llm_mode` passes — config + `response.data` produced.
- [ ] `test_structured_map_e2e_multi_dataset` passes — two layers, viewport union, per-layer counts.
- [ ] `test_deterministic_handler_unchanged` passes — legacy FeatureCollection shape.
- [ ] Full suite green: `pytest packages/ai-parrot/tests/ -k structured_map -v`.
- [ ] `ruff check` clean on new test files.

---

## Test Specification

```python
import pytest
from parrot.models.outputs import OutputMode


async def test_structured_map_e2e_llm_mode(pandas_agent, spatial_query):
    resp = await pandas_agent.ask(spatial_query, output_mode=OutputMode.STRUCTURED_MAP)
    out = resp.output  # config without data
    assert "data" not in out
    assert out["layers"]
    assert resp.data is not None


async def test_structured_map_e2e_multi_dataset(pandas_agent, multi_dataset_query):
    resp = await pandas_agent.ask(multi_dataset_query, output_mode=OutputMode.STRUCTURED_MAP)
    layers = {l["layer"] for l in resp.output["layers"]}
    assert len(layers) == 2
    assert resp.output["viewport"]["bbox"] is not None


async def test_deterministic_handler_unchanged(spatial_client, deterministic_spec):
    resp = await spatial_client.post("/spatial/filter", json=deterministic_spec)
    body = await resp.json()
    assert body["type"] == "FeatureCollection"
```

---

## Agent Instructions

1. Read spec §4 and §5.
2. Confirm TASK-1445..1450 completed.
3. Update index → `in-progress`.
4. Implement; run the suite; `ruff check`.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Created `test_structured_map_e2e.py` with 8 tests covering:
- e2e LLM mode (config + response.data produced)
- multi-dataset (two layers, viewport union, per-layer counts)
- capping preserved (capped=True, total_count in MapLayer)
- deterministic handler unchanged (legacy FeatureCollection shape)
- homologation invariants (data excluded, never raises, no HTML)
- no regression on STRUCTURED_TABLE
All 8 tests pass. `satellite_available` marker skips renderer tests when
ai-parrot-visualizations is not installed.
**Deviations from spec**: No `conftest.py` modifications needed (no shared fixtures
with other integration tests; fixtures defined inline).
