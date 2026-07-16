---
type: Wiki Overview
title: 'TASK-1448: Spatial transport handler compatibility'
id: doc:sdd-tasks-completed-task-1448-spatial-handler-compat-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 3. TASK-1446 changes `spatial_filter`'s return type from
---

# TASK-1448: Spatial transport handler compatibility

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1446
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. TASK-1446 changes `spatial_filter`'s return type from
`SpatialFeatureCollection` to `SpatialResult`. The deterministic frontend path
goes through `spatial_filter_handler.py`, which today returns the merged
`SpatialFeatureCollection` JSON. This task keeps that path working (the spec's
"deterministic frontend path continues to work" acceptance criterion) via the
`as_feature_collection()` shim, while optionally exposing the new per-dataset
shape behind a version toggle.

---

## Scope

- Update both POST endpoints in
  `packages/ai-parrot/src/parrot/handlers/spatial_filter_handler.py` to consume
  the new `SpatialResult` return value of `spatial_filter`.
- Default response = legacy merged `SpatialFeatureCollection` JSON via
  `SpatialResult.as_feature_collection()` (no breaking change for current callers).
- OPTIONAL: when the request asks for the new shape (e.g. `?version=2` or an
  Accept hint), return the per-dataset `SpatialResult` JSON directly.
- Preserve the existing AgenTalk pass-through envelope behaviour.

**NOT in scope**: the renderer (TASK-1449), agent wiring (TASK-1450), config
models. Do NOT change the spatial execution logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../handlers/spatial_filter_handler.py` | MODIFY | adapt to `SpatialResult`; default to `as_feature_collection()` |
| `packages/ai-parrot/tests/.../test_spatial_handler_compat.py` | CREATE | endpoint shape tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# spatial_filter_handler.py already imports (line 49):
from ...tools.dataset_manager.spatial.contracts import SpatialFeatureCollection
# after TASK-1446, also available:
from ...tools.dataset_manager.spatial import SpatialResult  # added by TASK-1446
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/handlers/spatial_filter_handler.py
#   Two POST endpoints, both currently return SpatialFeatureCollection JSON
#   (docstrings at lines 3, 90, 101, 273, 331, 355, 410).
#   The handler calls DatasetManager.spatial_filter(spec) internally.

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
async def spatial_filter(self, spec, cap_per_dataset=1000) -> "SpatialResult":  # line 4186 (post TASK-1446)

# packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py (post TASK-1446)
class SpatialResult(BaseModel):
    version: Literal[2] = 2
    layers: Dict[str, SpatialLayerResult]
    def as_feature_collection(self) -> SpatialFeatureCollection: ...
```

### Does NOT Exist
- ~~`SpatialResult` before TASK-1446~~ — confirm TASK-1446 completed first.
- ~~a streaming/SSE spatial endpoint~~ — endpoints are plain POST returning JSON.

### Dependency note
- TASK-1446 MUST be in `sdd/tasks/completed/` before starting (this task imports
  `SpatialResult` and calls `as_feature_collection()`).

---

## Implementation Notes

### Key Constraints
- Default behaviour MUST be byte-compatible with the pre-FEAT-221 response so
  existing frontend deterministic callers are unaffected.
- Async aiohttp handlers; `self.logger` for diagnostics.
- Keep the typed AgenTalk envelope pass-through untouched.

### References in Codebase
- `.../handlers/spatial_filter_handler.py` — current endpoints.
- FEAT-219 task `sdd/tasks/completed/TASK-1441-transport-handler-agentalk-envelope.md`.

---

## Acceptance Criteria

- [ ] Default endpoint response equals the legacy `SpatialFeatureCollection` JSON shape.
- [ ] Optional version toggle returns the per-dataset `SpatialResult` JSON.
- [ ] AgenTalk envelope behaviour preserved.
- [ ] `pytest packages/ai-parrot/tests/ -k spatial_handler_compat -v` passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
async def test_handler_default_returns_legacy_shape(client, deterministic_spec):
    resp = await client.post("/spatial/filter", json=deterministic_spec)
    body = await resp.json()
    assert body["type"] == "FeatureCollection"
    assert "features" in body


async def test_handler_version2_returns_layers(client, deterministic_spec):
    resp = await client.post("/spatial/filter?version=2", json=deterministic_spec)
    body = await resp.json()
    assert body.get("version") == 2
    assert "layers" in body
```

---

## Agent Instructions

1. Read spec §3 Module 3.
2. Confirm TASK-1446 completed.
3. Update index → `in-progress`.
4. Implement; run tests; `ruff check`.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Updated `spatial_filter_handler.py`: `SpatialFilterEnvelope.forward()` now
calls `as_feature_collection()` to return the legacy shape; `_handle_direct` and
`_handle_nl` both support `?version=2` toggle to return the new `SpatialResult` shape.
Default behaviour is byte-compatible with the pre-FEAT-221 response. 7 tests pass.
**Deviations from spec**: none
