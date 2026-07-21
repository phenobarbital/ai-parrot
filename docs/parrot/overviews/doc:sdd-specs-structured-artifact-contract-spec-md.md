---
type: Wiki Overview
title: 'Feature Specification: Structured Artifact Contract — homologate the `structured_`
  family'
id: doc:sdd-specs-structured-artifact-contract-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `structured_` output family is inconsistent. `STRUCTURED_TABLE` (FEAT-218)
  is built on a
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Structured Artifact Contract — homologate the `structured_` family

**Feature ID**: FEAT-223
**Date**: 2026-06-03
**Author**: Juan Ruffato
**Status**: approved
**Target version**: 1.x
**Brainstorm**: `sdd/proposals/structured-artifact-contract.brainstorm.md`

> **Reassigned FEAT-221 → FEAT-223** (2026-06-03): `FEAT-221` is already owned by the
> completed `structured-map-output` spec (Jesus Lara). This spec is the **homologation
> umbrella**; the per-leaf features below are **completed dependencies**:
> - **FEAT-215** `structured-chart-output` — `STRUCTURED_CHART` (LLM-owns-data; refactored here).
> - **FEAT-218** `structured-table` — the `STRUCTURED_TABLE` deterministic pattern (the contract to extract).
> - **FEAT-221** `structured-map-output` — `STRUCTURED_MAP` + `StructuredMapConfig` +
>   `StructuredMapRenderer` already shipped. This FEAT only adds `ArtifactType.MAP` and
>   retrofits that renderer onto the shared base.

---

## 1. Motivation & Business Requirements

### Problem Statement

The `structured_` output family is inconsistent. `STRUCTURED_TABLE` (FEAT-218) is built on a
**deterministic-data** pattern — the deterministic layer owns rows + base column types, the LLM
only refines ambiguous columns ("on conflict, deterministic wins"). `STRUCTURED_CHART`
(FEAT-215) took the opposite, LLM-owns-the-data path that FEAT-218 explicitly **rejected**, and
in production it produced exactly the failures FEAT-218 predicted: invented columns, `data: [{}]`,
`{columns, rows}` orientations, "No data", sign flips — patched reactively with column
reconciliation, orientation normalization, and a `chart_data` convention.

Separately, a "chart" is represented **three** incompatible ways: `StructuredChartConfig`
(FEAT-215) / frontend `AppChartConfig`, the `Artifact` CHART `definition` (echarts-style spec,
FEAT-103), and the infographic `ChartBlock`. And `ArtifactType` has no `map`.

### Goals

- Establish a **homologated `structured_` contract**: one shared pattern that every
  `structured_*` renderer conforms to — deterministic layer owns rows; LLM owns *presentation*
  only; shared envelope (`data` excluded from `output`, routed to `response.data`; explanation as
  `wrapped`; graceful degradation, never raises). This is Jesus's decision (Q1): *"if we
  homologate all the `structured_` outputs it will be easier to incorporate new ones."*
- **Realign `STRUCTURED_CHART`** to that pattern: rows extracted deterministically from the
  agent's DataFrame (reusing the table layer); the LLM only chooses chart `type` and which
  **existing** columns are `x`/`y` (+ palette/colorBySign). Retire the reactive patches.
- **Converge the chart config** onto the single agnostic `AppChartConfig`/`StructuredChartConfig`
  shape, used by `STRUCTURED_CHART`, the infographic `ChartBlock`, and `Artifact` CHART definition.
- **Complete the `map` artifact**: `OutputMode.STRUCTURED_MAP`, `StructuredMapConfig`, and
  `StructuredMapRenderer` already shipped under FEAT-221 (`structured-map-output`). This FEAT only adds
  the missing `ArtifactType.MAP` and retrofits the existing renderer onto the shared base.

### Non-Goals (explicitly out of scope)

- **Output-side artifact/kind selector** (agent proposes `kind` / router validates) — deferred to
  a unified-artifact follow-up (Option C). Distinct from the input-side FEAT-070 Intent Router.
- **Removing or deprecating the library-specific `OutputMode`s** (echarts/plotly/vega/matplotlib/…).
  Per Jesus (Q5) they stay for backward compatibility now and are retired in the next release.
- `summary` / `document` as standalone structured kinds (document already = Canvas; summary already
  an infographic block). Folded into the homologated base so they plug in later; not built here.
- Changing the HTTP envelope (`handlers/agent.py`) — already mode-agnostic.

---

## 2. Architectural Design

### Overview

Extract the contract that `StructuredTableRenderer` already embodies into a shared
**structured-output base** (mixin/base class) and make every `structured_*` renderer use it:
deterministic row extraction (`TableRenderer._extract_data`), envelope routing (`data` out of
`output` → `response.data`; explanation → `wrapped`), and graceful degradation. `STRUCTURED_CHART`
is rebuilt on this base; the LLM contributes only presentation. `map` is a new conformer.

### Component Diagram

```
Producing agent → response.data (DataFrame/QueryResponse) + explanation
        │
StructuredOutputBase (NEW shared contract)
   ├── _extract_rows()  ── reuse ──▶ TableRenderer._extract_data (table.py:57)
   ├── _route_envelope() (data out of output → response.data; explanation → wrapped; never raises)
   │
   ├── StructuredTableRenderer  → columns via categorize_columns; LLM refines column format
   ├── StructuredChartRenderer  → presentation only (type + x/y from real cols + palette); rows deterministic
   └── StructuredMapRenderer (NEW) → presentation (map type + geo/value cols)
        │
        ▼
   envelope: output(config w/o data) / data(rows) / response(explanation) / output_mode   [unchanged]
        ▼
   frontend AppChart / table / map render the agnostic config
```

### Integration Points

- Reuses the FEAT-218 deterministic layer (`TableRenderer._extract_data`,
  `DatasetManager.categorize_columns`) — read-only.
- `Artifact` CHART/`MAP` `definition` (FEAT-103, `storage/models.py`) carries the converged config.
- Frontend `AppChart` already consumes the agnostic config — minimal change; it becomes the canonical shape.

### Data Models

```
# parrot/models/outputs.py
# - StructuredChartConfig (:309): `data` is ALREADY input-only; the renderer must STOP using
#   cfg.data as a row source and extract rows deterministically instead; x/y validated against
#   real columns by the renderer, not the LLM. (Today the LLM still owns rows via
#   _resolve_rows / _reconcile_columns — Module 2 removes those.)
# - OutputMode (:37): STRUCTURED_MAP = "structured_map" — ALREADY EXISTS (:72, FEAT-221). No change.
# - StructuredMapConfig (:711) — ALREADY EXISTS (FEAT-221). No change.

# parrot/storage/models.py
# - ArtifactType (:244): add MAP = "map"  — the ONLY missing enum member.
```

### New Public Interfaces

```
# parrot/outputs/formats/structured_base.py (or a mixin)
class StructuredOutputBase:
    def _extract_rows(self, response) -> list[dict]: ...        # deterministic, reuses TableRenderer
    def _route_envelope(self, response, out, rows, explanation): ...  # data→response.data; wrapped=explanation
```

---

## 3. Module Breakdown

### Module 1: `StructuredOutputBase` (shared contract)
Extract the deterministic-extraction + envelope-routing + graceful-degradation logic that
`StructuredTableRenderer` already implements into a reusable base/mixin. Table renderer refactored
to use it (behavior unchanged).

### Module 2: `STRUCTURED_CHART` deterministic refactor
Rebuild `StructuredChartRenderer` on Module 1: rows come from `_extract_rows`; the LLM emits only
presentation (`type`, `x`, `y[]` chosen from the real column set, palette/colorBySign). Remove the
now-unnecessary reactive patches (`_reconcile_columns` heuristics, orientation normalization,
`chart_data` inference) — keep a thin guard for safety. `StructuredChartConfig.data` becomes
input-only/ignored as a source.

### Module 3: Chart-config convergence
Make the infographic `ChartBlock` and `Artifact` CHART `definition` use the single agnostic config
(`AppChartConfig`/`StructuredChartConfig`) instead of their own shapes.

### Module 4: `map` structured artifact (complete + conform)
`OutputMode.STRUCTURED_MAP`, `StructuredMapConfig`, and `StructuredMapRenderer` already shipped
under FEAT-221 (`structured-map-output`). This module only: (a) adds the missing `ArtifactType.MAP`
enum member, and (b) retrofits the existing `StructuredMapRenderer` onto the Module 1 base (envelope
routing + graceful degradation) so it conforms to the homologated contract. No new config or renderer
is created.

### Module 5: Tests + migration
Update/extend tests; document that library-specific modes remain (retire next release).

---

## 4. Test Specification

### Unit Tests
- `StructuredOutputBase._extract_rows` returns deterministic rows for DataFrame / list / dict / QueryResponse inputs.
- Chart renderer: given a DataFrame in `response.data` and an LLM presentation (`type`, `x`, `y`),
  emits config whose x/y ∈ real columns; rows come from the DataFrame, NOT the LLM; never raises.
- Chart renderer: LLM picks an absent x/y → deterministic fallback (first categorical = x, numeric = y).
- Map renderer: geo/value columns routed; config excludes data.
- `ArtifactType.MAP` and `OutputMode.STRUCTURED_MAP` exist.

### Integration Tests
- chart and table share the same envelope shape (parity test).
- infographic `ChartBlock` + `Artifact` CHART definition serialize the converged config.

### Test Data / Fixtures
- Reuse `test_structured_chart.py` / `test_structured_table.py` patterns; placeholder data only
  (`cat`/`val`, no real client figures).

---

## 5. Acceptance Criteria

- [ ] A `StructuredOutputBase` is shared by table + chart (+ map); table behavior unchanged.
- [ ] `STRUCTURED_CHART` rows are deterministic (from the agent DataFrame); the LLM never owns the row set.
- [ ] The chart x/y always reference real columns; "No data"/column-mismatch failures cannot occur for valid data.
- [ ] One chart config shape used by `STRUCTURED_CHART`, infographic `ChartBlock`, and `Artifact` CHART definition.
- [ ] `ArtifactType.MAP` added; the pre-existing `OutputMode.STRUCTURED_MAP` / `StructuredMapConfig` /
      `StructuredMapRenderer` (FEAT-221) now conform to `StructuredOutputBase` and round-trip.
- [ ] Library-specific `OutputMode`s remain functional (no removal this FEAT).
- [ ] All `structured_*` tests pass; no real client data in fixtures/prompts.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredChartConfig, StructuredTableConfig, TableColumn
from parrot.storage.models import ArtifactType
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):                 # :37
    STRUCTURED_CHART = "structured_chart"    # :70
    STRUCTURED_TABLE = "structured_table"    # :71
    STRUCTURED_MAP   = "structured_map"      # :72  (FEAT-221 — already exists)
class StructuredChartConfig(BaseModel): ...  # :309 (type, x, y, data[input-only], palette, colorBySign, dataVariable, ...)
class TableColumn(BaseModel): ...            # :471 (name, type, title, format)
class StructuredTableConfig(BaseModel): ...  # :508 (columns, data, explanation, total_rows, truncated)
class StructuredMapConfig(BaseModel): ...    # :711 (layers, data[input-only], viewport, query, ...) — FEAT-221

# packages/ai-parrot/src/parrot/storage/models.py
class ArtifactType(str, Enum):               # :244  CHART, CANVAS, INFOGRAPHIC, DATAFRAME, EXPORT  (MAP still missing)
class Artifact(BaseModel):                   # :272  definition: Optional[Dict[str, Any]] (:287) — CHART carries echarts-style spec

# packages/ai-parrot/src/parrot/outputs/formats/base.py
class BaseRenderer(ABC): ...                 # :54   (_get_content :69)
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/chart.py
class BaseChart(BaseRenderer): ...           # :20   — shared by ALL three structured renderers today

# packages/ai-parrot/src/parrot/outputs/formats/table.py
class TableRenderer(BaseRenderer):           # :52
    def _extract_data(self, response: Any) -> pd.DataFrame: ...   # :57  (deterministic row extraction)

# packages/ai-parrot/src/parrot/outputs/formats/table_types.py
def base_column_types(df: pd.DataFrame) -> dict[str, str]: ...    # :42  (deterministic dtype→vocabulary)
def canonical_records(df, row_limit=None): ...                    # :70  (flat list[dict] + count + truncated)

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):       # :500
    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]: ...  # :633

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py
class StructuredTableRenderer(BaseChart):    # :88  — THE deterministic pattern to EXTRACT into the base
    async def render(self, response, *, environment="html", row_limit=None, **kwargs): ...  # :117
    # _extract_data → base_column_types → canonical_records → TableColumn list → _apply_llm_refine;
    # output excludes data (model_dump exclude={"data"}); routes response.data = cfg.data

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py
@register_renderer(OutputMode.STRUCTURED_CHART, ...)              # :75
class StructuredChartRenderer(BaseChart):    # :76  — CURRENT LLM-owns-data renderer (to refactor onto base)
    # reactive patches to REMOVE: _resolve_rows (:226), _reconcile_columns (:256);
    # output already excludes data (:180)

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py
@register_renderer(OutputMode.STRUCTURED_MAP, ...)               # :96
class StructuredMapRenderer(BaseChart):      # :97  — FEAT-221, already deterministic; retrofit onto base only

# Dispatch: packages/ai-parrot/src/parrot/outputs/formats/__init__.py
#   _MODULE_MAP (:20) wires STRUCTURED_CHART/TABLE/MAP; register_renderer (:50)
```

### Integration Points
- Chart renderer MUST obtain rows via `TableRenderer._extract_data` (same call `StructuredTableRenderer`
  uses), not from `cfg.data` nor a tool variable.
- Renderers register via the formats registry `_MODULE_MAP` (`outputs/formats/__init__.py`).
- Envelope writeback unchanged in `bots/data.py` (formatter call) and `handlers/agent.py`.

### Does NOT Exist (Anti-Hallucination)
- No `ArtifactType.MAP` yet — this is the ONLY missing map symbol.
- `OutputMode.STRUCTURED_MAP` (:72), `StructuredMapConfig` (:711) and `StructuredMapRenderer`
  DO exist (shipped by FEAT-221, `structured-map-output`). **Do NOT recreate them.**
- No `StructuredOutputBase` / shared structured base or mixin yet — the three renderers inherit
  `BaseChart` directly and each reimplements envelope routing + JSON extraction. The deterministic
  pattern currently lives inside `StructuredTableRenderer`.
- No single shared chart config — three shapes exist (FEAT-215 `StructuredChartConfig`,
  `Artifact.definition` echarts-spec, infographic `ChartBlock`).
- `StructuredChartRenderer` is NOT yet deterministic — it still uses `_resolve_rows` /
  `_reconcile_columns` (LLM-owns-data with reactive healing). Module 2 removes these.
- No output-side `kind` selector (FEAT-070 is input-side routing).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `StructuredTableRenderer` exactly for the deterministic-data + envelope contract.
- Keep the frontend `AppChart` agnostic config as the canonical chart shape.

### Known Risks / Gotchas
- The chart refactor changes data ownership — must verify pie/bar/horizontalBar/radar/line still
  render (positive & negative values) after rows become deterministic.
- The LLM still picks x/y; constrain it to the real column set (provided from the extracted schema).
- Don't break other ai-parrot consumers relying on library-specific modes.

### External Dependencies
- None new (reuses existing pandas / dataset_manager / table renderer).

---

## 8. Open Questions

- **Q4 (deferred, Option C):** output-side artifact/kind selector — design with FEAT-070/FEAT-103
  in a follow-up; not part of this FEAT.
- **Impl-1:** `StructuredOutputBase` as a base class vs a mixin — decide during Module 1.
- **Impl-2:** Does the converged chart config need any field the infographic `ChartBlock` has that
  `AppChartConfig` lacks? Audit during Module 3.

---

## Revision History
- 2026-06-03 — draft created from accepted brainstorm `structured-artifact-contract` (Juan Ruffato).
- 2026-06-03 — approved (Juan Ruffato). Open items are non-blocking: Q4 deferred to Option C;
  Impl-1/Impl-2 resolved during Module 1/3 implementation.
- 2026-06-03 — **reassigned FEAT-221 → FEAT-223** (FEAT-221 owned by the completed
  `structured-map-output` spec). Reconciled Module 4 + Codebase Contract with current reality:
  `STRUCTURED_MAP` / `StructuredMapConfig` / `StructuredMapRenderer` already shipped — only
  `ArtifactType.MAP` + base-conformance remain. FEAT-215 / FEAT-218 / FEAT-221 noted as completed
  dependencies (Juan Ruffato).
