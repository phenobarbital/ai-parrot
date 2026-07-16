---
type: Wiki Overview
title: 'TASK-1457: Add ArtifactType.MAP + conform StructuredMapRenderer to the base'
id: doc:sdd-tasks-completed-task-1457-artifacttype-map-and-conform-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4 (complete + conform)**. The map leaf already shipped
  under **FEAT-221**
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats.structured_base
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1457: Add ArtifactType.MAP + conform StructuredMapRenderer to the base

**Feature**: FEAT-223 — Structured Artifact Contract
**Spec**: `sdd/specs/structured-artifact-contract.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1454
**Assigned-to**: unassigned

---

## Context

Implements **Module 4 (complete + conform)**. The map leaf already shipped under **FEAT-221**
(`structured-map-output`): `OutputMode.STRUCTURED_MAP` (`outputs.py:72`), `StructuredMapConfig`
(`outputs.py:711`), and `StructuredMapRenderer` (`structured_map.py:97`) all exist and pass tests.
The homologation umbrella (FEAT-223) leaves exactly two gaps for `map`:

1. `ArtifactType.MAP` is missing — it is the ONLY missing map enum member.
2. `StructuredMapRenderer` reimplements envelope routing + JSON extraction inline; it must adopt the
   `StructuredOutputBase` from TASK-1454 so it conforms to the shared contract.

**Do NOT recreate** the config, the renderer, or the OutputMode — they exist.

---

## Scope

- Add `MAP = "map"` to `ArtifactType` (`storage/models.py:244`).
- Retrofit `StructuredMapRenderer` to use `StructuredOutputBase._route_envelope` for its output
  (data excluded → `response.data`; explanation wrapped) and the base's shared `_extract_json_code`
  helper, replacing its inline duplicates. The map renderer's deterministic per-layer column building
  (`_build_columns`, `base_column_types`) stays as-is — only the envelope/JSON-extraction plumbing
  conforms to the base.
- Confirm the map config round-trips through the envelope after the retrofit (output excludes `data`;
  per-layer payloads routed to `response.data`).

**NOT in scope**: creating the base (TASK-1454); chart work (TASK-1455/1456); persisting map artifacts
to storage end-to-end (only the enum member is added here — no new storage tier); the parity test
(TASK-1458, though keep the existing map suite green).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/models.py` | MODIFY | Add `MAP = "map"` to `ArtifactType` |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py` | MODIFY | Adopt `StructuredOutputBase` for envelope routing + JSON extraction; deterministic column building unchanged |
| `packages/ai-parrot/tests/outputs/formats/test_structured_map_renderer.py` | MODIFY | Assert `ArtifactType.MAP` exists + envelope still round-trips after retrofit |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFY before coding. TASK-1454 must be in `tasks/completed/` first.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredMapConfig   # outputs.py:37 / :711  (EXIST — FEAT-221)
from parrot.storage.models import ArtifactType                      # storage/models.py:244
# Within ai-parrot-visualizations:
from parrot.outputs.formats.structured_base import StructuredOutputBase  # CREATED by TASK-1454 — verify name
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/storage/models.py
class ArtifactType(str, Enum):           # :244
    CHART = "chart"; CANVAS = "canvas"; INFOGRAPHIC = "infographic"
    DATAFRAME = "dataframe"; EXPORT = "export"   # ← add MAP = "map"

# packages/ai-parrot/src/parrot/models/outputs.py  (ALREADY EXIST — FEAT-221, do NOT recreate)
class OutputMode(str, Enum):
    STRUCTURED_MAP = "structured_map"    # :72
class StructuredMapConfig(BaseModel):    # :711  (layers, data[input-only], viewport, query, base_layer, title, ...)
    # _validate_column_names (:771) — renderer passes data=[] so validation is skipped

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py  (EXISTS — FEAT-221)
@register_renderer(OutputMode.STRUCTURED_MAP, system_prompt=STRUCTURED_MAP_SYSTEM_PROMPT)  # :96
class StructuredMapRenderer(BaseChart):  # :97
    async def render(self, response, *, environment="html", row_limit=None, **kwargs): ...  # :124
    # Deterministic: SpatialResult -> per-layer _build_columns (base_column_types) -> MapLayer
    # -> StructuredMapConfig(layers, data=[], viewport, query, explanation)
    # -> out = model_dump(... exclude={"data"}); response.data = per-layer payloads   ← route via base now
    # has its own _extract_json_code duplicate (~:624) ← replace with base helper
```

### Does NOT Exist
- ~~`ArtifactType.MAP`~~ — this task adds it (the only missing map symbol).
- ~~A new `StructuredMapConfig` / `StructuredMapRenderer` / `OutputMode.STRUCTURED_MAP`~~ — all exist (FEAT-221). Do NOT recreate.
- ~~A storage persistence tier for map artifacts~~ — out of scope; only the enum member is added.

---

## Implementation Notes

### Key Constraints
- Async; `self.logger` on degradation. Never raise.
- The retrofit must be behavior-preserving: the existing `test_structured_map_renderer.py` suite must
  pass (viewport computation, geojson vs rows payloads, MapQuery extraction unchanged).
- Keep `register_renderer` wiring and the system prompt as-is.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py` — the conformance target.
- `StructuredOutputBase` from TASK-1454 — `_route_envelope` + shared JSON extraction.

---

## Acceptance Criteria

- [ ] `ArtifactType.MAP == "map"` exists.
- [ ] `StructuredMapRenderer` routes its envelope via `StructuredOutputBase` and drops its inline JSON-extraction duplicate.
- [ ] Map config round-trips: output excludes `data`; per-layer payloads land in `response.data`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_map_renderer.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/storage/models.py packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py`
- [ ] `from parrot.storage.models import ArtifactType; ArtifactType.MAP` imports.

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/formats/test_structured_map_renderer.py
from parrot.storage.models import ArtifactType


def test_artifacttype_map_exists():
    assert ArtifactType.MAP == "map"


class TestMapEnvelopeConformance:
    async def test_output_excludes_data(self):
        """After retrofit, the map config output has no 'data' key."""
        ...

    async def test_payloads_routed_to_response_data(self):
        """Per-layer payloads are routed to response.data via the shared base."""
        ...

    async def test_existing_behavior_preserved(self):
        """Viewport / geojson-vs-rows / MapQuery behavior unchanged after the retrofit."""
        ...
```

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-04
**Notes**: Added MAP="map" to ArtifactType. Retrofitted StructuredMapRenderer(StructuredOutputBase, BaseChart) — removed inline _extract_json_code (inherited), replaced step-8 with _route_envelope + explicit payload routing. 18/18 map tests pass, 103 renderer tests green. Linting clean.
**Deviations from spec**: none
