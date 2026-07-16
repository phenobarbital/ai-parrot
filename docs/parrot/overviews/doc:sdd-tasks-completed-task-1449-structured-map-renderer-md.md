---
type: Wiki Overview
title: 'TASK-1449: StructuredMapRenderer'
id: doc:sdd-tasks-completed-task-1449-structured-map-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Overview + §3 Module 4 (G1, G3, G5–G10). The renderer is the heart
  of the
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

# TASK-1449: StructuredMapRenderer

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1445, TASK-1446, TASK-1447
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + §3 Module 4 (G1, G3, G5–G10). The renderer is the heart of the
feature: it deterministically turns the per-dataset `SpatialResult` (in
`response.data`) into a `StructuredMapConfig`, mirroring `StructuredTableRenderer`
exactly (extract → types → rows → optional LLM refine → build config → exclude
`data` → route to `response.data` → return `(out, explanation)`; never raise).

---

## Scope

- Create
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py`
  with `StructuredMapRenderer(BaseChart)` decorated
  `@register_renderer(OutputMode.STRUCTURED_MAP, system_prompt=STRUCTURED_MAP_SYSTEM_PROMPT)`.
- `render(response, *, environment="html", row_limit=None, **kwargs)`:
  1. Read the per-dataset `SpatialResult` from `response.data`.
  2. For each dataset/layer build a `MapLayer`:
     - columns from the profile's `property_cols`, typed via `base_column_types`
       (derive a DataFrame from `feature.properties` rows), titles/formats from
       the profile hints (TASK-1447), default `data_shape` from the profile.
     - `data_shape="rows"` → flatten features to rows via `canonical_records`,
       carrying a geometry reference (lat/lng or geometry dict); `data_shape="geojson"`
       → pass features through.
     - `tooltip_template` from profile (`tooltip_template` or `description_template`),
       `label_field` from `label_col`; per-layer `total_count`/`capped`/`geodesic`.
  3. Optional LLM refine pass for labels/format hints (deterministic wins; hard
     types never changed) — mirror `StructuredTableRenderer._apply_llm_refine`.
  4. Compute `MapViewport` from the union of feature bounds (bbox + optional center).
     Build `MapQuery` from the originating `SpatialFilterSpec` (see Implementation Notes).
  5. Build `StructuredMapConfig`; `out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})`;
     set `response.data` to the per-layer payload; return `(out, explanation)`.
  6. Any error → return `(None, error_message)`; NEVER raise.
- Register the module in `_MODULE_MAP` in
  `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`:
  `OutputMode.STRUCTURED_MAP: ('.structured_map',)`.
- Add `STRUCTURED_MAP_SYSTEM_PROMPT` (narrow refine prompt, mirroring
  `STRUCTURED_TABLE_SYSTEM_PROMPT`).

**NOT in scope**: agent wiring (TASK-1450), config models (TASK-1445), spatial
backend (TASK-1446/1447).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/.../formats/structured_map.py` | CREATE | `StructuredMapRenderer` + system prompt |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | add `_MODULE_MAP` entry |
| `packages/ai-parrot/tests/outputs/formats/test_structured_map_renderer.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# in structured_map.py — mirror structured_table.py imports:
from .chart import BaseChart                                   # structured_table.py:27
from . import register_renderer                                # structured_table.py:28
from ...models.outputs import OutputMode, StructuredMapConfig, MapLayer, MapColumn, MapViewport, MapQuery  # (post TASK-1445)
from ...outputs.formats.table import TableRenderer             # structured_table.py:30
from ...outputs.formats.table_types import base_column_types, canonical_records  # structured_table.py:31
```

### Existing Signatures to Use (mirror StructuredTableRenderer)
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py
@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=STRUCTURED_TABLE_SYSTEM_PROMPT)  # line 87
class StructuredTableRenderer(BaseChart):                       # line 88
    def __init__(self, row_limit: int = DEFAULT_ROW_LIMIT, **kwargs): ...   # line 105
    async def render(self, response, *, environment="html",
                     row_limit=None, **kwargs) -> Tuple[Any, Optional[Any]]:  # line 117
        explanation = getattr(response, "response", None) or None            # line 157
        df = self._table_renderer._extract_data(response)                    # line 163
        col_types = base_column_types(df)                                    # line 175
        rows, total_rows, truncated = canonical_records(df, row_limit=...)   # line 178
        out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})   # line 215
        response.data = cfg.data                                             # line 223
        return out, explanation                                              # line 226
    async def _apply_llm_refine(self, columns, response) -> list[TableColumn]:  # line 233
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]: ...               # line 325
    def _render_chart_content(self, chart_obj, **kwargs) -> str: return ""   # line 356  (abstract stub)

# packages/ai-parrot/src/parrot/outputs/formats/table_types.py
def base_column_types(df: pd.DataFrame) -> dict[str, str]: ...               # line 42
def canonical_records(df: pd.DataFrame, row_limit: int = 1000) -> tuple[list[dict], int, bool]: ...  # line 70

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None): ...
_MODULE_MAP: dict = { OutputMode.STRUCTURED_TABLE: ('.structured_table',), ... }
def get_renderer(mode) -> Type[Renderer]: ...   # lazy-imports the module then reads RENDERERS[mode]
```

### Does NOT Exist
- ~~`StructuredMapRenderer`~~ — this task creates it.
- ~~a viewport/bbox helper anywhere~~ — compute inline from feature coordinates.
- ~~`TableRenderer._extract_data` for GeoJSON~~ — `_extract_data` expects DataFrame-like;
  for map, read `SpatialResult` from `response.data` directly, do NOT route GeoJSON through it.
- ~~`response.code` carrying the map config~~ — unlike STRUCTURED_CHART, the map renderer
  BUILDS the config from `response.data` (table-style), it does not read a pre-emitted config from `response.code`.

### Dependency note
- TASK-1445 (models), TASK-1446 (`SpatialResult`), TASK-1447 (profile hints) MUST
  be in `sdd/tasks/completed/` first.

---

## Implementation Notes

### Pattern to Follow
- Copy `structured_table.py` structure 1:1; swap the data source from
  DataFrame-extraction to `SpatialResult` (in `response.data`) iterated per layer.
- The LLM refine pass and `_extract_json_code` helper port over almost verbatim.
- Mirror the "never raise → `(None, msg)`" contract and the DataFrame-truthiness
  guard (explicit None/empty checks before assigning `response.data`).

### MapQuery source
- The originating `SpatialFilterSpec` (point/radius/unit) is needed for `MapQuery`.
  Read it from the spatial result/artifacts if carried; otherwise leave
  `query=None` (it is Optional in `StructuredMapConfig`). Do NOT fabricate it.
  *(How the spec is threaded to the renderer is finalized in TASK-1450; this task
  must tolerate its absence.)*

### Key Constraints
- Empty layer (zero features) → still emit the `MapLayer` (columns/metadata),
  empty payload — never drop it (spec §2 Edge Cases).
- `data_shape="rows"` with no flat columns → fall back to GeoJSON + log.

### References in Codebase
- `packages/ai-parrot-visualizations/.../formats/structured_table.py` — full template.
- `packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py` — test patterns.

---

## Acceptance Criteria

- [ ] `get_renderer(OutputMode.STRUCTURED_MAP)` resolves `StructuredMapRenderer` (lazy import via `_MODULE_MAP`).
- [ ] `render` returns `(config_without_data, explanation)` and sets `response.data` to the per-layer payload.
- [ ] One `MapLayer` per dataset; columns typed via `base_column_types`; tooltip from profile.
- [ ] Both `data_shape="geojson"` and `"rows"` produce valid payloads.
- [ ] Viewport bbox computed from feature bounds.
- [ ] LLM refine cannot change hard types; renderer NEVER raises (malformed → `(None, msg)`).
- [ ] Empty-layer dataset preserved.
- [ ] `pytest packages/ai-parrot/tests/outputs/formats/test_structured_map_renderer.py -v` passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot.outputs.formats import get_renderer
from parrot.models.outputs import OutputMode


def test_renderer_registered():
    assert get_renderer(OutputMode.STRUCTURED_MAP) is not None


async def test_render_builds_layers(map_response_two_layers):
    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    out, explanation = await r.render(map_response_two_layers)
    assert "data" not in out
    assert {l["layer"] for l in out["layers"]} == {"schools", "malls"}
    assert out["viewport"]["bbox"] is not None


async def test_render_never_raises_on_garbage(garbage_response):
    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    out, msg = await r.render(garbage_response)
    assert out is None and isinstance(msg, str)


async def test_empty_layer_preserved(map_response_with_empty_layer):
    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    out, _ = await r.render(map_response_with_empty_layer)
    assert any(l["layer"] == "malls" for l in out["layers"])
```

---

## Agent Instructions

1. Read spec §2 Overview + §3 Module 4 and `structured_table.py` in full.
2. Confirm TASK-1445/1446/1447 completed.
3. Update index → `in-progress`.
4. Implement; run tests; `ruff check`.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Created `structured_map.py` in `ai-parrot-visualizations` with
`StructuredMapRenderer(BaseChart)` decorated with
`@register_renderer(OutputMode.STRUCTURED_MAP, ...)`. Registered in `_MODULE_MAP`.
Implements: per-dataset layer building from SpatialResult, column type inference via
`base_column_types`, profile-based titles/formats/tooltip/label, geojson and rows
data shapes, viewport computation from feature bounds, LLM refine with deterministic-
wins guard, never-raise contract. 14 tests pass.
**Deviations from spec**: Used inline rows builder instead of canonical_records (since
we need to include _geometry reference; canonical_records doesn't carry geometry).
