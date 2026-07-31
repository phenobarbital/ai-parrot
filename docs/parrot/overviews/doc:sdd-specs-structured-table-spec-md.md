---
type: Wiki Overview
title: 'Feature Specification: Structured Table Output Mode'
id: doc:sdd-specs-structured-table-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tabular agent results are delivered today either as **rendered HTML/Grid.js**
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Structured Table Output Mode

**Feature ID**: FEAT-218
**Date**: 2026-06-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor)

> Input: `sdd/proposals/structured-table.brainstorm.md` (Recommended Option C) and
> `docs/product-analysis/structured-table.analysis.md` (verdict: GO).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement
Tabular agent results are delivered today either as **rendered HTML/Grid.js**
(`OutputMode.TABLE`, `outputs/formats/table.py:52`) or as a **flat JSON string with no
column semantics and no provenance** (`OutputMode.JSON`, `outputs/formats/json.py:7`).

- HTML forces the frontend to parse, sanitize and re-style markup it didn't author, and
  couples output to Grid.js — it cannot be fed to AG Grid / TanStack / MUI DataGrid without
  scraping the DOM.
- Plain JSON gives rows but drops the two things a frontend actually needs: **per-column
  semantic typing** (a number to right-align/sum vs. an ID to leave alone) and the
  **explanation of how the table was derived** (the SQL/Pandas reasoning).

A new `OutputMode.STRUCTURED_TABLE` — the table sibling of `STRUCTURED_CHART` (FEAT-215) —
returns framework-agnostic structured data (`data` rows + `explanation` provenance + minimal
per-column directives) so any frontend renders the table with the table library it prefers.

### Goals
- Add `OutputMode.STRUCTURED_TABLE` **parallel to** `OutputMode.TABLE` (HTML), without
  breaking or replacing the HTML path.
- Emit a minimal, framework-agnostic per-column contract: `name` + `type` (storage) +
  `title` (label) + optional `format` hint.
- Produce data and base column types **deterministically** from the DataFrame/QueryResponse;
  let the LLM only **refine ambiguous columns**; on conflict, **deterministic wins**.
- Reuse provenance (`explanation`) from the producing data agents; never mint it fresh;
  best-effort (never block render).
- Emit **canonical machine values** (ISO-8601 UTC dates, plain numbers, big-ints-as-strings);
  leave locale formatting to the frontend.
- Support a **configurable row-limit** with a truncation signal.
- Ship **PandasAgent** and **DB/SQL agent** as reference producers in v1.
- Achieve **parity with STRUCTURED_CHART**: same envelope shape, `data` excluded from
  `output` and routed to `response.data`, explanation surfaced as `wrapped`, graceful
  degradation (never raise).

### Non-Goals (explicitly out of scope)
- Replacing or deprecating `OutputMode.TABLE` (HTML/Grid.js) — left intact.
- Rich grid behavior in the payload (sort/filter/width/conditional-format/pinned). Rejected
  in brainstorm as scope creep that couples the contract to one grid library.
- Backend-side locale formatting of values (currency symbols, decimal separators) — this
  lives in the frontend (`Intl`).
- LLM owning the row set/data (brainstorm Option A) — rejected; risks dropped/renamed
  columns and broken type fidelity. See `proposals/structured-table.brainstorm.md` Option A.

---

## 2. Architectural Design

### Overview
Mirror the FEAT-215 architecture, **inverting who fills the config** (brainstorm Option C):
the deterministic layer owns data + base schema; a narrow LLM pass only annotates ambiguous
columns.

1. The producing agent (PandasAgent or DB/SQL agent) sets `response.data` (DataFrame /
   dataset) and `response.response` / `QueryResponse.explanation` as it does today.
2. The `structured_table` renderer (dispatched via the formatter registry) extracts rows
   (`TableRenderer._extract_data`), applies the deterministic row-limit, derives base column
   types (`DatasetManager.categorize_columns` + a dtype→vocabulary map), and serializes
   values canonically.
3. A narrow, optional LLM-refine pass annotates ambiguous columns with finer `format` hints
   (currency/percent/id/code). Deterministic base types are immutable — conflicts resolve to
   deterministic; disagreements are recorded best-effort.
4. The renderer builds a `StructuredTableConfig`, returns `(output_without_data,
   explanation)`, routes rows to `response.data`, sets `response.output_mode`.

If the LLM-refine pass fails/times out, the renderer falls back to the deterministic-only
schema (equivalent to brainstorm Option B) and never raises — mirroring
`structured_chart.py`'s `(None, msg)` graceful degradation.

### Component Diagram
```
ProducingAgent (PandasAgent / DB-SQL agent)
   │ sets response.data (+ response.response / QueryResponse.explanation)
   ▼
OutputFormatter.format(STRUCTURED_TABLE)         (outputs/formatter.py:267)
   │ dispatch via _MODULE_MAP                     (outputs/formats/__init__.py:20)
   ▼
StructuredTableRenderer  (ai-parrot-visualizations)
   ├─→ TableRenderer._extract_data(response)      (rows)
   ├─→ DatasetManager.categorize_columns(df)      (base types) ──┐
   ├─→ dtype→vocabulary map + canonical serialize                │ deterministic wins
   ├─→ [optional] LLM-refine ambiguous columns  ─────────────────┘
   ├─→ apply row-limit → total_rows / truncated
   └─→ build StructuredTableConfig → (out_without_data, explanation); response.data = cfg.data
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `OutputMode` (`models/outputs.py:39`) | extends | add `STRUCTURED_TABLE = "structured_table"` |
| `StructuredChartConfig` (`models/outputs.py:309`) | mirrors | new `StructuredTableConfig` BaseModel |
| `_MODULE_MAP` (`outputs/formats/__init__.py:20`) | extends | add `OutputMode.STRUCTURED_TABLE: ('.structured_table',)` |
| `bots/data.py:1623-1629` override-guard | modifies | extend skip to also cover STRUCTURED_TABLE |
| `DatasetManager.categorize_columns` (`tools/dataset_manager/tool.py:625`) | uses (read-only) | deterministic dtype→category |
| `TableRenderer._extract_data` (`outputs/formats/table.py:57`) | uses (read-only) | row extraction |
| `StructuredChartRenderer` (`ai-parrot-visualizations/.../structured_chart.py`) | mirrors | renderer return/route/degradation contract |
| `QueryResponse` (`bots/database/models.py:276`) | uses (read-only) | provenance (`explanation`/`query`) |
| PandasAgent / DB-SQL agent | depends on | reference producers; provenance already emitted |
| `handlers/agent.py:2591-2626` | none | envelope already mode-agnostic |

### Data Models
```python
# parrot/models/outputs.py — new, mirrors StructuredChartConfig (:309-392)
class TableColumn(BaseModel):
    name: str          # column key (matches a key in data rows)
    type: str          # storage: string|integer|number|boolean|date|datetime|time|duration|any
    title: str         # human label (default: name as-is — NOT renamed by the LLM)
    format: str | None = None  # display hint: currency|percent|email|uri|enum (+ optional meta)

class StructuredTableConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    columns: list[TableColumn]
    data: list[dict]           # INPUT-ONLY — excluded from output dump; routed to response.data
    explanation: str | None = None
    total_rows: int | None = None
    truncated: bool = False
    # @model_validator(mode="after"): every column.name must exist in data[0].keys() when data non-empty
```

### New Public Interfaces
```python
# parrot/models/outputs.py
class OutputMode(str, Enum):
    ...
    STRUCTURED_TABLE = "structured_table"   # new

# ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py
@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=...)
class StructuredTableRenderer(BaseRenderer):  # or BaseChart-style base, mirroring structured_chart
    def render(self, response, **kwargs) -> tuple[dict | None, str | None]:
        ...  # returns (out_without_data, explanation); never raises
```

---

## 3. Module Breakdown

### Module 1: Contract — `StructuredTableConfig` + enum member
- **Path**: `packages/ai-parrot/src/parrot/models/outputs.py`
- **Responsibility**: Add `OutputMode.STRUCTURED_TABLE`; add `TableColumn` +
  `StructuredTableConfig` (data INPUT-ONLY/excluded on dump, `populate_by_name`,
  after-validator over column names, `total_rows`/`truncated`).
- **Depends on**: existing `StructuredChartConfig` pattern (mirror).

### Module 2: Deterministic dtype→vocabulary map
- **Path**: `packages/ai-parrot/src/parrot/outputs/formats/` (helper near the renderer, or a
  small util) — exact home decided in implementation.
- **Responsibility**: Map `DatasetManager.categorize_columns` output
  (`integer/float/datetime/boolean/categorical/text`) onto the storage vocabulary
  (`integer→integer`, `float→number`, `datetime→datetime`, `boolean→boolean`,
  `categorical/text→string`, unknown→`any`); canonical value serialization (ISO-8601 UTC
  dates, big-ints-as-strings, null/mixed→`any`).
- **Depends on**: `DatasetManager.categorize_columns` (read-only).

### Module 3: `StructuredTableRenderer` + dispatch wiring
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py`
  + one line in `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:_MODULE_MAP`.
- **Responsibility**: Extract rows, build base schema (Module 2), apply row-limit
  (`total_rows`/`truncated`), reuse `explanation`, optional LLM-refine of ambiguous columns
  (deterministic wins), build `StructuredTableConfig`, return `(out_without_data,
  explanation)`, route `response.data = cfg.data`, graceful `(None, msg)` on failure.
- **Depends on**: Module 1, Module 2; mirrors `structured_chart.py`.

### Module 4: data.py routing guard
- **Path**: `packages/ai-parrot/src/parrot/bots/data.py:1623-1629`
- **Responsibility**: Extend the FEAT-215 override-guard so data.py does NOT overwrite
  `response.data` with the raw tool-local DataFrame for STRUCTURED_TABLE (the renderer owns
  that via `cfg.data`).
- **Depends on**: Module 3.

### Module 5: Reference producers (PandasAgent + DB/SQL agent)
- **Path**: PandasAgent path (sets `response.response`/`response.data` already) and
  `packages/ai-parrot/src/parrot/bots/database/agent.py` (currently emits
  `OutputMode.SQL_ANALYSIS`).
- **Responsibility**: Honor `output_mode=STRUCTURED_TABLE` end-to-end. DB/SQL agent routes
  its `QueryDataset` + `QueryResponse.explanation`/`query` through the renderer when the
  caller selects STRUCTURED_TABLE. (Parallelizable: PandasAgent and DB agent independently.)
- **Depends on**: Module 3.

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/outputs/formats/test_structured_table.py`
- **Responsibility**: Clone `test_structured_chart.py` (521 lines): enum member,
  model/validator, dispatch resolution, system-prompt schema, data-exclusion + routing,
  explanation-as-wrapped, graceful degradation, envelope serialization; plus new cases for
  the dtype→vocabulary map, deterministic-wins conflict, and row-limit/truncation.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_output_mode_has_structured_table` | M1 | `OutputMode.STRUCTURED_TABLE == "structured_table"` |
| `test_config_excludes_data_on_dump` | M1 | `model_dump(by_alias=True, exclude={"data"})` omits rows |
| `test_config_validator_rejects_unknown_column` | M1 | column.name not in data[0] → ValidationError |
| `test_dtype_vocabulary_map` | M2 | float→number, int→integer, datetime→datetime, object→string, unknown→any |
| `test_canonical_serialization` | M2 | dates→ISO-8601 UTC, big ints→str, null/mixed→any |
| `test_renderer_routes_rows_to_response_data` | M3 | `response.data == cfg.data`; `output` excludes data |
| `test_renderer_reuses_explanation` | M3 | explanation taken from `response.response` / QueryResponse |
| `test_deterministic_wins_on_conflict` | M3 | LLM "date" over float64 column is ignored |
| `test_row_limit_and_truncated_signal` | M3 | cap applied; `total_rows`/`truncated` set |
| `test_graceful_degradation_on_bad_input` | M3 | returns `(None, msg)`, never raises |
| `test_llm_refine_failure_falls_back` | M3 | refine error → deterministic-only schema |
| `test_data_py_guard_skips_structured_table` | M4 | data.py does not overwrite `response.data` |

### Integration Tests
| Test | Description |
|---|---|
| `test_pandasagent_structured_table_end_to_end` | PandasAgent + `output_mode=STRUCTURED_TABLE` → valid payload, zero HTML |
| `test_db_agent_structured_table_end_to_end` | DB/SQL agent → STRUCTURED_TABLE with reused SQL provenance |
| `test_envelope_serialization_parity` | HTTP envelope mirrors STRUCTURED_CHART shape (`output`/`data`/`response`/`code`) |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_df():
    import pandas as pd
    return pd.DataFrame({
        "id": [1, 2], "amount": [10.5, 20.0],
        "created": pd.to_datetime(["2026-01-01", "2026-02-01"]),
    })
# Reuse satellite-availability skipif + sys.path wiring from test_structured_chart.py:16-27
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `OutputMode.STRUCTURED_TABLE` exists and is routable via the formatter registry.
- [ ] `StructuredTableConfig` excludes `data` from its output dump and routes rows to
      `response.data` (parity with STRUCTURED_CHART).
- [ ] Per-column contract is minimal: `name` + `type` (storage) + `title` + optional
      `format`; `currency`/`percent` are `format` hints, NOT top-level types.
- [ ] Data + base column types are derived deterministically; LLM only refines ambiguous
      columns; on conflict with a hard dtype, **deterministic wins**.
- [ ] Values are canonical (ISO-8601 UTC dates, plain numbers, big-ints-as-strings); no
      locale-formatted strings in the payload.
- [ ] `explanation` is reused from the producing agent and is best-effort (absent →
      omitted, never blocks render).
- [ ] Configurable row-limit (default 1000) with `total_rows` + `truncated` signal.
- [ ] `OutputMode.TABLE` (HTML) behavior is unchanged (no regression).
- [ ] Renderer never raises — returns `(None, msg)` on malformed input; LLM-refine failure
      falls back to deterministic-only schema.
- [ ] Both PandasAgent and DB/SQL agent emit STRUCTURED_TABLE end-to-end.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/outputs/formats/test_structured_table.py -v`).
- [ ] Integration tests pass; HTTP envelope parity with STRUCTURED_CHART verified.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified 2026-06-03 against the working tree.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # used at bots/data.py:28
# OutputMode is imported directly everywhere; NOT re-exported from parrot/models/__init__.py.
# Renderer registration pattern:
from parrot.outputs.formats import register_renderer  # outputs/formats/__init__.py:48
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):                       # :39
    JSON = "json"                                  # :42  (routable flat-JSON mode)
    TABLE = "table"                                # :63  (existing HTML/Grid.js — untouched)
    SQL_ANALYSIS = "sql_analysis"                  # :71
    STRUCTURED_CHART = "structured_chart"          # :72  (STRUCTURED_TABLE added adjacent)

class StructuredChartConfig(BaseModel):            # :309  (mirror target)
    model_config = ConfigDict(populate_by_name=True)
    # data: List[dict] is INPUT-ONLY, excluded from output dump; @model_validator(mode="after")
    # checks declared columns exist in data[0].keys() when data is non-empty.

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager:
    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]:   # :625
        # → integer | float | datetime | boolean | categorical | categorical_text | text

# packages/ai-parrot/src/parrot/outputs/formats/table.py
class TableRenderer(BaseRenderer):                 # :52
    def _extract_data(self, response: Any) -> pd.DataFrame:   # :57
        # handles PandasAgentResponse, to_dataframe, list/dict, response.data

# packages/ai-parrot/src/parrot/bots/database/models.py
class QueryResponse(BaseModel):                    # :276
    explanation: str = Field(...)                  # :279
    query: Optional[str] = Field(...)              # :282  (SQL artifact)
    # _dedupe_sql_from_explanation validator keeps explanation prose-only (:314-317)

# packages/ai-parrot/src/parrot/outputs/formatter.py
class OutputFormatter:                             # :129
    def format(...) -> tuple:                      # :267  (returns (content, wrapped))
    # .extract_data() reuses TableRenderer._extract_data (:340-359)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OutputMode.STRUCTURED_TABLE` | `OutputMode` enum | new member | `models/outputs.py:39-72` |
| `StructuredTableConfig` | `StructuredChartConfig` | mirror | `models/outputs.py:309-392` |
| `StructuredTableRenderer` | `register_renderer` | decorator | `outputs/formats/__init__.py:48` |
| dispatch | `_MODULE_MAP` | dict entry | `outputs/formats/__init__.py:20-29` |
| renderer | `DatasetManager.categorize_columns` | static call | `tools/dataset_manager/tool.py:625` |
| renderer | `TableRenderer._extract_data` | method call | `outputs/formats/table.py:57` |
| renderer route | `cfg.data → response.data` | mirror of FEAT-215 | `ai-parrot-visualizations/.../structured_chart.py:171-173` |
| data.py guard | `output_mode != OutputMode.STRUCTURED_TABLE` | add to guard | `bots/data.py:1629` |
| DB producer | `QueryResponse.explanation` / `.query` | read | `bots/database/models.py:279-282`; envelope `database/agent.py:585-595` |
| HTTP envelope | (no change) | generic serialize | `handlers/agent.py:2591-2626` |

### Does NOT Exist (Anti-Hallucination)
- ~~`OutputMode.DATAFRAME`~~ / ~~`OutputMode.JSON_DATA`~~ — only `OutputType.DATAFRAME`/`OutputType.JSON_DATA` exist (`outputs.py:26,35`), NOT routable. Routable JSON mode is `OutputMode.JSON` (`outputs/formats/json.py:7`).
- ~~`structured_table` renderer / `StructuredTableConfig` / `TableColumn` / `STRUCTURED_TABLE` member~~ — none exist yet.
- ~~dtype→`currency`/`percent`/`id`/`code` mapper~~ — `categorize_columns` stops at `integer/float/datetime/boolean/categorical/text`; finer vocabulary is new (LLM elevation + small static map).
- ~~`OutputMode` re-export from `parrot/models/__init__.py`~~ — not re-exported; direct import only.
- ~~`TableRenderer` at line 51~~ — the class is at `table.py:52` (brainstorm said 51).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `ai-parrot-visualizations/.../structured_chart.py` for renderer placement
  (satellite package, PEP 420 namespace), registration, `(out, explanation)` return,
  `response.data = cfg.data` routing, and graceful `(None, msg)` degradation.
- Clone `tests/outputs/formats/test_structured_chart.py` (satellite skipif + sys.path
  wiring at `:16-27`) as the test scaffold.
- Pydantic v2 (`ConfigDict(populate_by_name=True)`, `@model_validator(mode="after")`).
- Async-first; `self.logger`; strict types + Google docstrings; `uv` only; no LangChain.

### Known Risks / Gotchas
- **Type fidelity at the JSON boundary**: dates (no JSON date type), big ints (>2^53
  precision loss), null/mixed columns. Mitigate: ISO-8601 UTC strings, big-ints-as-strings,
  pandas-enforced column homogeneity, `any` fallback.
- **Large-table payloads**: array-of-objects repeats keys and can hit payload caps.
  Mitigate: configurable row-limit (default 1000) + `total_rows`/`truncated` from day one.
- **Scope creep into presentation**: pressure to embed locale-formatted strings or
  grid-specific config. Hold the line — semantic hints only (frontend formats via `Intl`).
- **LLM mislabels semantic type**: bounded by deterministic-wins — the LLM cannot change a
  hard dtype, only refine ambiguous (`object`/`int`) columns; disagreements recorded.
- **DB/SQL agent currently emits `SQL_ANALYSIS`**: routing it through STRUCTURED_TABLE must
  not regress the SQL_ANALYSIS path; the caller's `output_mode` selects which.
- **`pd.DataFrame` truthiness**: use explicit `if cfg.data:` carefully (mirror the warning
  comment in `structured_chart.py` about DataFrame ambiguity).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | `StructuredTableConfig` / `TableColumn` models (already core) |
| `pandas` | (existing) | dtype source; optional `build_table_schema` baseline (already core) |
| `ai-parrot-visualizations` | (existing satellite) | renderer home, like STRUCTURED_CHART |

_No new third-party dependencies._

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (all tasks sequential in one worktree).
- **Rationale**: Hard dependency chain — contract (M1) → dtype map (M2) → renderer +
  dispatch (M3) → data.py guard (M4) → producers (M5) → tests (M6). The only genuinely
  parallelizable work is the two reference producers in M5 (PandasAgent vs DB/SQL agent),
  which is small enough not to justify separate worktrees.
- **Cross-feature dependencies**: none must be merged first. Touches the same additive files
  as FEAT-215 (`models/outputs.py`, `outputs/formats/__init__.py`, `bots/data.py`); working
  tree shows only `generic-evaluation-harness` and `odoo-fieldservice-toolkit` specs in
  flight — no overlap. Low conflict risk (additive changes).

---

## 8. Open Questions

> Resolved items carried forward from the brainstorm; unresolved items remain `[ ]`.

- [x] Flow type & base branch — *Resolved in brainstorm*: `type=feature`, `base_branch=dev`.
- [x] Reference producer(s) — *Resolved in brainstorm*: both PandasAgent and DB/SQL agent in v1.
- [x] Type/format conflict policy — *Resolved in brainstorm*: deterministic wins; LLM only refines ambiguous columns; disagreement recorded best-effort.
- [x] currency/percent modeling — *Resolved in research*: `format` hint on a base type, NOT a top-level type (Frictionless / pandas `orient='table'` / W3C).
- [x] Renderer package placement — *Resolved in research*: ships from `ai-parrot-visualizations` (satellite), like STRUCTURED_CHART.
- [ ] Row-limit default & truncation field names — *Owner: Jesus Lara* (spec proposes default **1000** rows with `total_rows` + `truncated` fields; confirm during implementation).
- [ ] Is the LLM-refine pass worth it for v1, or does deterministic-only suffice? — *Owner: Jesus Lara* (spec builds Option C with deterministic-only fallback; validate via the cheapest experiment before committing the refine step).
- [ ] DB/SQL agent opt-in mechanism — *Owner: Jesus Lara* (spec assumes caller selects `STRUCTURED_TABLE` and the agent routes its `QueryDataset`/`QueryResponse` provenance through the renderer; "emit both modes" is the alternative if a caller needs SQL_ANALYSIS simultaneously).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-03 | Jesus Lara | Initial draft from brainstorm (Option C) + product analysis |
