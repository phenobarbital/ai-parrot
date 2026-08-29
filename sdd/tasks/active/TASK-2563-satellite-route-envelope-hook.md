# TASK-2563: Satellite hook — `_route_envelope` dual-emit + map per-layer payloads

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2561
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the single hook point (G4). Every STRUCTURED_* render path
(PandasAgent, DatabaseAgent, direct `render()`) flows through
`StructuredOutputBase._route_envelope` in the ai-parrot-visualizations
satellite. After the existing dump/`response.data` routing, the hook mints a
surface id, calls the TASK-2561 core adapter, and dual-emits: config in
`response.output` (+`surfaceId`), envelope in `response.a2ui_envelope`.
The helper keeps its "never raises" contract.

---

## Scope

- Modify `_route_envelope` in `structured_base.py`: after the existing dump +
  `response.data` routing —
  - mint `surface_id = f"{mode}-{uuid4().hex[:8]}"` (FEAT-224 pattern);
  - call `chart_to_surface` / `table_to_surface` / `map_to_surface` with the
    **capped** rows (`canonical_records`) or per-layer payloads, passing the
    renderer's `row_limit`;
  - set `response.a2ui_envelope = serialize(surface)`;
  - inject `out["surfaceId"] = surface_id`; set `response.artifact_id = surface_id`;
  - wrap the whole addition in try/except: log at `warning`, leave
    `a2ui_envelope` unset (`None`), return `(out, explanation)` — no exception
    escapes; `response.output_mode` untouched.
- Modify `structured_map.py`: expose the per-layer feature lists it already
  builds in `_build_rows_payload` to the base so `map_to_surface` receives
  `list[list[dict]]` ordered as `cfg.layers` (never `SpatialResult`).
- Unit tests (spec §4 Module-4 rows) incl. the parity assertion:
  `out` minus `surfaceId` equals the pre-feature dump.

**NOT in scope**: adapter internals (TASK-2561), artifacts[] minting
(TASK-2562/2565), echarts/folium props (TASK-2564).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py` | MODIFY | dual-emit in `_route_envelope` |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py` | MODIFY | hand per-layer feature lists to the base |
| `packages/ai-parrot-visualizations/tests/formats/test_structured_envelope.py` | CREATE | hook + never-raises + parity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# satellite dev @ 8b40e0c — packages/ai-parrot-visualizations/src/parrot/outputs/formats/
from parrot.outputs.formats.structured_base import StructuredOutputBase   # structured_base.py:26
from parrot.outputs.formats.structured_table import DEFAULT_ROW_LIMIT     # structured_table.py:39 (=1000)
from parrot.outputs.formats.table_types import canonical_records          # core formats/table_types.py
# from this feature (TASK-2561, core):
from parrot.outputs.a2ui.adapters.structured import chart_to_surface, table_to_surface, map_to_surface
from parrot.outputs.a2ui.serialization import serialize
```

### Existing Signatures to Use
```python
# satellite structured_base.py (dev @ 8b40e0c)
class StructuredOutputBase:                                                    # :26
    def _extract_rows(self, response: Any) -> Optional[pd.DataFrame]          # :39  (never raises)
    def _route_envelope(self, response: Any, cfg: Any, explanation: Optional[str]
                        ) -> tuple[Optional[dict], Optional[str]]             # :64  (never raises; warning log :96)
        # out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"}); if cfg.data: response.data = cfg.data
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]                     # :100

# satellite structured_chart.py / structured_table.py / structured_map.py (dev)
class StructuredChartRenderer(StructuredOutputBase, BaseChart):               # chart :80; render :98
class StructuredTableRenderer(StructuredOutputBase, BaseChart):               # table :88; __init__(row_limit=DEFAULT_ROW_LIMIT) :105; render :117
class StructuredMapRenderer(StructuredOutputBase, BaseChart):                 # map :177; render :208
    def _build_rows_payload(...)   # :505 — already builds per-layer feature lists
    def _build_tabular_rows(...)   # :539
    # render() step 8 (~:400-403): cfg.data is [] by design; calls _route_envelope then wraps explanation

# core models/responses.py: AIMessage.artifact_id :214, .a2ui_envelope :222
```

### Does NOT Exist
- ~~`response.a2ui_envelope` set on STRUCTURED_* responses today~~ — this task introduces it.
- ~~`out["surfaceId"]`~~ — new; the ONLY change to `response.output` (AC-2).
- ~~any A2UI-specific row-cap setting~~ — reuse the renderer's `row_limit`.
- ~~`emission.finalize_a2ui_response` for this path~~ — FORBIDDEN: it flips `output_mode` to `A2UI` (spec §7).
- ~~`SpatialResult` handed to the adapter~~ — pass plain per-layer dicts only (D4).

---

## Implementation Notes

### Key Constraints
- "Never raises" is load-bearing (AC-5): a raising adapter must yield
  `(out, explanation)` with `a2ui_envelope is None` + one `warning` log.
- `response.data` keeps the FULL row set; only `dataModel` is capped (AC-4).
- Empty/`None` rows still build the envelope (`rows: []`, `totalRows: 0`).
- Multi-dataset maps: `datasets` is input-only → dropped; layers ordered as `cfg.layers`.
- `output_mode` must remain the STRUCTURED_* value — it is the routing signal
  for `_STRUCTURED_OUTPUT_ROUTER` (bots/data.py:329-350).

### References in Codebase
- `structured_base.py:64-97` — the exact function body being extended
- `structured_map.py:505` — `_build_rows_payload`, source of per-layer features

---

## Acceptance Criteria

- [ ] After `render()` on each STRUCTURED_* renderer, `response.a2ui_envelope` is a valid v1.0 envelope (`validate_message` + `validate_envelope(TOOL)`), `out["surfaceId"]` and `response.artifact_id` set (AC-1)
- [ ] `out` minus `surfaceId` byte-equal to the pre-feature dump; `response.data` unchanged — FEAT-215/218/221/224 parity suites pass (AC-2)
- [ ] Adapter monkeypatched to raise → `(out, explanation)` returned, envelope `None`, warning logged (AC-5)
- [ ] Multi-dataset map → N layers in `dataModel`, each bound at `/layers/<i>/features` (AC-4)
- [ ] Tests pass: `pytest packages/ai-parrot-visualizations/tests/formats/ -k structured -v` and existing `tests/outputs/formats/test_structured_*`; ruff clean

---

## Test Specification

```python
# packages/ai-parrot-visualizations/tests/formats/test_structured_envelope.py
async def test_route_envelope_sets_a2ui_envelope(): ...
async def test_route_envelope_never_raises(monkeypatch): ...
async def test_output_unchanged_except_surface_id(): ...
async def test_structured_map_multi_layer_envelope(): ...
```

---

## Agent Instructions

1. Verify TASK-2561 is in `sdd/tasks/completed/` (FEAT-470 merged transitively).
2. Re-verify contract lines; update contract first if drifted.
3. Implement, run tests (incl. existing structured parity suites), move to completed, update index, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
