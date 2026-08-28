# TASK-2561: Core adapter (`adapters/structured.py`) + `build_map` + `data_model=` passthrough

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2560
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 — the heart of the feature. A pure, deterministic, core-side
adapter converts a typed structured config + already-extracted rows into a
validated v1.0 `CreateSurface` (G1, G3, G4). No LLM involvement; TOOL origin;
core never imports agents, `DatasetManager`, clients, or `SpatialResult` (D4
one-way import rule).

---

## Scope

- Create `parrot/outputs/a2ui/adapters/structured.py`:
  - Constants `SCHEMA_VERSION = 2`, `ROWS_PATH = "/rows"`,
    `LAYER_FEATURES_PATH = "/layers/{i}/features"`,
    `DEFAULT_ROW_LIMIT = 1000` (re-declared; core must not import satellite).
  - `config_to_component_props(cfg, *, exclude=frozenset({"data","datasets"})) -> dict`
    — `model_dump(mode="json", by_alias=True)`, `None` dropped, exclude applied.
  - `chart_to_surface(cfg, rows, *, surface_id, row_limit=DEFAULT_ROW_LIMIT)`,
    `table_to_surface(...)`, `map_to_surface(cfg, layer_features, ...)` —
    root component `id="root"`, `catalogId=DEFAULT_CATALOG_ID`, props top-level
    camelCase, `data` → `{"path": "/rows"}` (per-layer for maps), populated
    `dataModel`; overflow beyond `row_limit` → `truncated`/`totalRows` (table)
    or per-layer `capped`/`totalCount` (map); empty rows still build (`rows: []`,
    `totalRows: 0`).
  - `root_component(envelope) -> dict` — `createSurface.components[0]`.
  - Every surface passes `validate_envelope(origin=ProducerOrigin.TOOL)` and
    `validate_message` (jsonschema).
- `builders.py`: add `build_map(*, layers, viewport=None, base_layer=None,
  title=None, description=None, query=None, data_model=None, surface_id="map")`;
  add `data_model=` passthrough to `build_chart`/`build_datatable`/`build_map`;
  add `origin: ProducerOrigin = ProducerOrigin.LLM` kwarg to `build_surface`
  (resolved spec §8: gain an `origin=` kwarg; default unchanged).
- Export the new names from `adapters/__init__.py`.
- Unit tests (spec §4 Module-2 rows).

**NOT in scope**: satellite `_route_envelope` hook (TASK-2563), artifact
helper/compat (TASK-2562), catalog schemas (TASK-2560).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/structured.py` | CREATE | `*_to_surface`, `config_to_component_props`, `root_component` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/__init__.py` | MODIFY | export new adapter API |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `build_map`, `data_model=`, `origin=` on `build_surface` |
| `packages/ai-parrot/tests/outputs/a2ui/test_structured_adapter.py` | CREATE | round-trip, caps, layers, serialization |

---

## Codebase Contract (Anti-Hallucination)

> **[470-wt]** lines verified on `feat-470-a2ui-v1-dialect` @ `0da976674`
> (2026-08-29). **Re-verify against `dev` after the FEAT-470 merge.**

### Verified Imports
```python
# core dev @ 8b40e0c
from parrot.models.outputs import StructuredChartConfig, StructuredTableConfig, StructuredMapConfig  # models/outputs.py:319/530/746
# [470-wt]
from parrot.outputs.a2ui.models import CreateSurface, Component, ChildTemplate  # models.py:446/400/212
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_datatable  # builders.py:49/78/140
from parrot.outputs.a2ui.catalog import validate_envelope, validate_message  # catalog/__init__.py:324/281
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin  # base.py:52/80
from parrot.outputs.a2ui.serialization import serialize, A2UI_VERSION  # serialization.py:104/55  (A2UI_VERSION == "v1.0")
```

### Existing Signatures to Use
```python
# [470-wt] builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                  data_model: dict[str, Any] | None = None) -> CreateSurface  # :49 — validates origin=LLM INSIDE today
def build_chart(*, chart_type, x, y, title=None, data_binding=None, show_legend=True, surface_id="chart") -> CreateSurface  # :78
def build_datatable(*, columns, data_binding=None, title=None, total_rows=None, truncated=False, surface_id="table") -> CreateSurface  # :140
# [470-wt] models.py
class Component(BaseModel):    # :400  id, component, catalog_id (alias catalogId :431); extra props → model_extra
class CreateSurface(A2UIMessageBase):  # :446  surface_id :465, catalog_id :466, send_data_model :467, components :468, data_model (alias dataModel) :469
# serialize(surface) → {"version": "v1.0", "createSurface": {...}}
# dataModel shapes (spec §2):
#   Chart/DataTable: {"rows": [...]}          Map: {"layers": [{"features": [...]}, ...]}
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.adapters.structured`~~ — dev `adapters/` holds only `infographic.py` (+`__init__.py`); this task creates it.
- ~~`builders.build_map`~~ — must be created.
- ~~`build_chart(..., data_model=)`~~ / ~~`build_datatable(..., data_model=)`~~ — only `build_surface` accepts it today.
- ~~`build_surface(..., origin=)`~~ — this task adds it.
- ~~`SpatialResult` importable from `parrot.outputs.*`~~ — lives in `parrot/tools/dataset_manager/spatial/contracts.py`; the adapter must NOT import it. Maps take plain per-layer feature-dict lists.
- ~~`a2ui_max_rows` or any new A2UI row-cap setting~~ — reuse `row_limit`.

---

## Implementation Notes

### Key Constraints
- Adapter is **pure**: no LLM, no I/O, no satellite imports (AC-1, D1/D4).
- Do NOT reuse `emission.finalize_a2ui_response` — it flips `output_mode` to
  `A2UI`, breaking STRUCTURED_* routing (spec §7).
- `surface_id` is supplied by the caller (satellite mints it); default builders
  keep their own defaults.
- Rows arrive already canonicalised (`canonical_records()` runs satellite-side);
  the adapter treats them as JSON-ready dicts.
- Legacy chart `type: "map"` stays valid in the enum for parity.
- Google-style docstrings, strict typing, module logger.

### References in Codebase
- `adapters/infographic.py` (dev) — existing adapter module shape to mirror
- `builders.py` [470-wt] — builder → `build_surface` delegation pattern

---

## Acceptance Criteria

- [ ] `chart_to_surface` round-trip: props == `cfg.model_dump(by_alias, exclude data/None)` + `data={"path":"/rows"}`; `dataModel.rows` == rows (AC-1/AC-4)
- [ ] `table_to_surface` with 1500 rows, `row_limit=1000` → 1000 rows in dataModel, `truncated=True`, `totalRows=1500` (AC-4)
- [ ] `map_to_surface`: layer *i* binds `/layers/i/features`; per-layer `capped`/`totalCount`; empty layer → `features: []` (AC-4)
- [ ] `build_map()` exists, mirrors siblings; all three builders accept `data_model=` (AC-11)
- [ ] Every surface passes `validate_envelope(TOOL)` + `validate_message`; `serialize()` → `{"version":"v1.0","createSurface":{...}}`, root id `"root"`, parrot `catalogId` (AC-1)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_structured_adapter.py -v`; ruff clean

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/test_structured_adapter.py
def test_chart_to_surface_round_trip(chart_cfg): ...
def test_table_to_surface_row_cap(rows_1500): ...
def test_map_to_surface_layers_paths(map_cfg_two_layers): ...
def test_map_to_surface_empty_layer(): ...
def test_build_map_validates_tool_origin(): ...
def test_surface_serializes_v1_envelope(chart_cfg): ...
# fixtures per spec §4: chart_cfg (stacked/trendline/axis labels/palette/color_by_sign),
# map_cfg_two_layers (marker_color/tooltip_template/label_field, viewport, query),
# rows_1500 (NaN/Timestamp/Decimal cells already canonicalised)
```

---

## Agent Instructions

1. Verify FEAT-470 is merged and TASK-2560 is in `sdd/tasks/completed/`.
2. Re-verify every **[470-wt]** contract line; update contract first if drifted.
3. Implement, test, move to completed, update index, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
