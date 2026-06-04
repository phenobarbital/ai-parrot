---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Structured Artifact Contract — homologate the `structured_` family

**Feature ID**: FEAT-221
**Date**: 2026-06-03
**Author**: Juan Ruffato
**Status**: draft
**Target version**: 1.x
**Brainstorm**: `sdd/proposals/structured-artifact-contract.brainstorm.md`

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
- **Add `map`** as a structured artifact (`ArtifactType.MAP` + `STRUCTURED_MAP`) mirroring the chart contract.

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
# - StructuredChartConfig (:310): data becomes informational-only (rows come deterministically);
#   x/y validated against real columns by the renderer, not the LLM.
# - NEW StructuredMapConfig: mirrors the chart/table contract (geo + value columns + presentation).
# - OutputMode (:39): add STRUCTURED_MAP = "structured_map".

# parrot/storage/models.py
# - ArtifactType (:244): add MAP = "map".
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

### Module 4: `map` structured artifact
Add `ArtifactType.MAP`, `OutputMode.STRUCTURED_MAP`, `StructuredMapConfig`, and a
`StructuredMapRenderer` conforming to Module 1.

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
- [ ] `ArtifactType.MAP` + `OutputMode.STRUCTURED_MAP` + `StructuredMapConfig` + renderer exist and round-trip.
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
# parrot/models/outputs.py
class OutputMode(str, Enum):                 # :39
    STRUCTURED_CHART = "structured_chart"    # :72
    STRUCTURED_TABLE = "structured_table"    # :73
class StructuredChartConfig(BaseModel): ...  # :310 (type, x, y, data, palette, colorBySign, dataVariable, ...)
class TableColumn(BaseModel): ...            # :472 (name, type, title, format)
class StructuredTableConfig(BaseModel): ...  # :509 (columns, data, explanation, total_rows, truncated)

# parrot/storage/models.py
class ArtifactType(str, Enum):               # :244  CHART, CANVAS, INFOGRAPHIC, DATAFRAME, EXPORT  (no MAP)

# parrot/outputs/formats/table.py
class TableRenderer:
    def _extract_data(self, response: Any) -> pd.DataFrame: ...   # :57  (deterministic row extraction)

# parrot/tools/dataset_manager/tool.py
class DatasetManager:
    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]: ...  # :633

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py
class StructuredTableRenderer(BaseChart):    # :88  — THE deterministic pattern to mirror
    async def render(self, response, *, environment="html", **kwargs): ...  # :117
    # uses self._table_renderer._extract_data(response); sets response.data = cfg.data

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py
class StructuredChartRenderer(BaseChart): ...  # current LLM-owns-data renderer (to refactor)
```

### Integration Points
- Chart renderer MUST obtain rows via `TableRenderer._extract_data` (same call `StructuredTableRenderer`
  uses), not from `cfg.data` nor a tool variable.
- Renderers register via the formats registry `_MODULE_MAP` (`outputs/formats/__init__.py`).
- Envelope writeback unchanged in `bots/data.py` (formatter call) and `handlers/agent.py`.

### Does NOT Exist (Anti-Hallucination)
- No `ArtifactType.MAP`, no `OutputMode.STRUCTURED_MAP`, no `StructuredMapConfig` yet.
- No `StructuredOutputBase` / shared mixin yet (logic currently lives inside `StructuredTableRenderer`).
- No single shared chart config — three shapes exist (FEAT-215 config, Artifact echarts-spec, infographic ChartBlock).
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
