---
type: Wiki Overview
title: 'Brainstorm: Structured Table Output Mode'
id: doc:sdd-proposals-structured-table-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tabular agent results are delivered today either as **rendered HTML/Grid.js**
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Structured Table Output Mode

**Date**: 2026-06-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: C

> Upstream input: `docs/product-analysis/structured-table.analysis.md` (verdict: GO).
> This brainstorm carries forward its verified Code Context and resolved decisions.

---

## Problem Statement

Tabular agent results are delivered today either as **rendered HTML/Grid.js**
(`OutputMode.TABLE`, `outputs/formats/table.py:51`) or as a **flat JSON string with no
column semantics and no provenance** (`OutputMode.JSON`, `outputs/formats/json.py:7`).

- HTML forces the frontend to parse, sanitize and re-style markup it didn't author, and
  couples output to Grid.js — it cannot be fed to AG Grid / TanStack / MUI DataGrid
  without scraping the DOM.
- Plain JSON gives rows but drops the two things a frontend actually needs: **per-column
  semantic typing** (number to right-align/sum vs. an ID to leave alone) and the
  **explanation of how the table was derived** (the SQL/Pandas reasoning).

**Who is affected**: primarily frontend developers consuming AI-Parrot agent responses;
secondarily bot/agent developers who set the output mode. **Why now**: FEAT-215 just
shipped `STRUCTURED_CHART` — the same data/metadata-split pattern, renderer dispatch, and
test scaffold already exist, so giving tables the same treatment is cheap and closes the
consistency gap (charts are library-agnostic; tables are not).

## Constraints & Requirements

- **New mode PARALLEL to `OutputMode.TABLE`** — do not replace or break the HTML path.
- **Minimal per-column directives**: `name` (key) + `type` (storage) + `title` (label).
  `currency`/`percent`/`id`/`code` are **`format` hints layered on a base type, NOT
  top-level types** (Frictionless / pandas `orient='table'` / W3C i18n consensus).
- **Canonical values, frontend formats**: backend emits ISO-8601 UTC dates, plain numbers,
  big-ints-as-strings; locale formatting lives in the frontend (`Intl`). No pre-formatted
  strings in the payload.
- **Hybrid producer, deterministic wins**: data + base types derived deterministically from
  the DataFrame/QueryResponse; the LLM only *elevates ambiguous* columns. On conflict with
  a hard dtype, **deterministic wins**.
- **Reuse provenance**: `explanation` comes from the data agents
  (`response.response` for PandasAgent; `QueryResponse.explanation`/`.query` for DB/SQL) —
  never minted fresh; best-effort (never blocks render).
- **Configurable row-limit** with a truncation signal (`total_rows` + `truncated`).
- **Reference producers**: both **PandasAgent** and **DB/SQL agent** end-to-end in v1.
- **Paridad with STRUCTURED_CHART**: same envelope shape, `data` excluded from `output`
  and routed to `response.data`, explanation surfaced as `wrapped`, graceful degradation
  (never raise).
- Conventions: `uv`, async-first, Pydantic, strict types, no LangChain.

---

## Options Explored

### Option A: Verbatim clone of STRUCTURED_CHART (LLM emits the full config)

The LLM is prompted to emit a `StructuredTableConfig` (columns + data + explanation) into
`response.code`, exactly as STRUCTURED_CHART does. The renderer reads the config, excludes
`data` from `output`, and routes rows to `response.data`. Hybrid typing is achieved purely
through the system prompt instructing the LLM to derive types.

✅ **Pros:**
- Maximum consistency with FEAT-215 — same mental model, same plumbing, least new code.
- The renderer is a near-literal copy of `structured_chart.py`.

❌ **Cons:**
- The LLM owns the whole payload, including **rows and column set** → risk of dropped /
  renamed / hallucinated columns and silently mangled data. Contradicts "deterministic
  wins" and the minimal-reliable spirit.
- Type fidelity (dates, big ints, nulls) is at the mercy of LLM serialization.
- Token cost scales with table size (the LLM re-emits all rows).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `StructuredTableConfig` model | already core |
| (none new) | — | reuses FEAT-215 machinery |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` — renderer blueprint.
- `packages/ai-parrot/src/parrot/models/outputs.py:309-392` — `StructuredChartConfig` pattern.

---

### Option B: Deterministic-only (pandas `orient='table'`, no LLM in the loop)

Build the payload entirely from the DataFrame via Frictionless Table Schema
(`df.to_json(orient='table')` / `build_table_schema`) plus the reused `explanation`. No LLM
elevation — column types are exactly the pandas dtype mapping.

✅ **Pros:**
- Most reliable and cheapest — zero hallucination surface, zero extra tokens.
- The contract is literally a published standard (Frictionless / pandas), round-trips to a
  typed DataFrame on a Python consumer.

❌ **Cons:**
- **No semantic elevation** — an `object` column that is really currency, or an `int64`
  that is really an ID, stays `string`/`integer`. Loses the `currency/percent/id/code`
  intent that motivated "presentation directives".
- Diverges from the STRUCTURED_CHART pattern (no LLM config in `response.code`).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` | `build_table_schema` / `to_json(orient='table')` | already core |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:625-670` — `categorize_columns`.
- `packages/ai-parrot/src/parrot/outputs/formats/table.py:57-97` — `TableRenderer._extract_data`.

---

### Option C: Deterministic-builds + LLM-refines (recommended)

The **deterministic layer owns data and the base schema**: `TableRenderer._extract_data`
pulls rows, `categorize_columns` + a small dtype→vocabulary map produces base column types,
and the row-limit/truncation is applied deterministically. A **focused, narrow LLM pass**
then refines *only the ambiguous columns* to the finer vocabulary (elevate `object`/`int`
to `currency/percent/id/code` via `format` hints) and the `explanation` is reused, not
generated. On any conflict with a hard dtype, **deterministic wins** (the LLM cannot change
`number`→`date`); disagreements are recorded best-effort. Reuses the FEAT-215 enum / config
/ renderer / dispatch scaffolding, but **inverts who fills the config**: the renderer builds
it from the DataFrame; the LLM only annotates.

✅ **Pros:**
- Matches the resolved decisions exactly: hybrid, deterministic-wins, minimal directives.
- Data and column set are never at the LLM's mercy → no dropped/renamed columns, type
  fidelity preserved (ISO dates, big-ints-as-strings handled deterministically).
- Still gets semantic elevation (currency/id/code) where it adds value.
- Token cost is bounded — the LLM sees column names + dtype + a sample, not all rows.

❌ **Cons:**
- Slightly more new code than A: the dtype→vocabulary map and the merge/refine step are
  genuinely new (no STRUCTURED_CHART precedent for deterministic truncation either).
- The LLM-refine pass is an extra, narrow call (or a structured sub-prompt) — needs an
  opt-out for "deterministic-only" callers.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `StructuredTableConfig` | core |
| `pandas` | dtype source / optional `build_table_schema` baseline | core |
| (none new) | — | reuses categorize_columns + renderer scaffolding |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:625-670` — deterministic dtype→category.
- `packages/ai-parrot/src/parrot/outputs/formats/table.py:57-97` — row extraction.
- `packages/ai-parrot-visualizations/.../structured_chart.py` — renderer return/route/degradation contract.
- `packages/ai-parrot/src/parrot/bots/database/models.py:276-325` — `QueryResponse` provenance.

---

## Recommendation

**Option C** is recommended. It is the only option that honors all four resolved
decisions — *hybrid producer*, *deterministic wins on conflict*, *minimal directives*, and
*reused provenance* — without the data-integrity risk of Option A (LLM owning the rows) or
the semantic poverty of Option B (no currency/id/code elevation).

The tradeoff is a **Medium** effort vs. A's **Low**: C adds a dtype→vocabulary mapping and
a narrow LLM-refine/merge step that have no direct FEAT-215 precedent. That cost is
acceptable because it buys the thing that actually makes this feature trustworthy — the
frontend never receives a table whose columns or values the LLM silently altered. C still
reuses ~80% of the STRUCTURED_CHART scaffolding (enum, config shape, renderer
return/route/degradation contract, dispatch wiring, test scaffold), so the new surface is
contained. Option B remains the clean fallback if the LLM-refine pass proves low-value in
the cheapest-experiment (see Open Questions).

---

## Feature Description

### User-Facing Behavior
A caller selects `output_mode=OutputMode.STRUCTURED_TABLE`. The agent response carries:
- `data`: list of row dicts (canonical machine values — ISO-8601 UTC dates, plain numbers,
  big-ints-as-strings), capped at the configured row-limit.
- `columns`: per-column `{ name, type, title, format? }` — `type` is a small storage enum
  (`string|integer|number|boolean|date|datetime|time|duration|any`); `format` is an
  optional display hint (`currency`+ISO-4217, `percent`, `email`, `uri`, `enum`).
- `explanation`: prose provenance reused from the producing agent.
- `total_rows` + `truncated`: signal when the table was capped.

The frontend renders with any grid (AG Grid / TanStack / MUI), applying locale formatting
itself. No HTML to parse, no column semantics to re-derive.

### Internal Behavior
1. The producing agent (PandasAgent or DB/SQL agent) sets `response.data` (DataFrame /
   dataset) and `response.response` / `QueryResponse.explanation` as it does today.
2. The `structured_table` renderer (dispatched via the formatter registry) extracts rows
   (`_extract_data`), applies the deterministic row-limit, derives base column types
   (`categorize_columns` + dtype→vocabulary map), and serializes values canonically.
3. A narrow LLM-refine pass annotates ambiguous columns with finer `format` hints;
   deterministic types are immutable (conflicts → deterministic, disagreement recorded).
4. The renderer builds a `StructuredTableConfig`, returns `(output_without_data,
   explanation)`, routes rows to `response.data`, sets `response.output_mode`.

### Edge Cases & Error Handling
- **Large tables**: deterministic cap + `truncated=true` + `total_rows`.
- **Missing explanation**: omit it; never block render.
- **Type fidelity**: dates→ISO-8601 UTC strings; integers >2^53→strings; null/mixed
  columns→`any` fallback; pandas enforces per-column homogeneity.
- **LLM-refine failure/timeout**: fall back to deterministic-only schema (degrade to
  Option B behavior), never raise — mirror `structured_chart.py` `(None, msg)` degradation.
- **Non-tabular response**: renderer returns `(None, message)` gracefully.

---

## Capabilities

### New Capabilities
- `structured-table`: a framework-agnostic `OutputMode.STRUCTURED_TABLE` that returns
  rows + minimal per-column directives + reused provenance for frontend-side rendering.

### Modified Capabilities
- (none — `OutputMode.TABLE` is left intact by design)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/models/outputs.py` | extends | new `OutputMode.STRUCTURED_TABLE` + `StructuredTableConfig` model |
| `parrot/outputs/formats/__init__.py` | extends | one `_MODULE_MAP` line for `.structured_table` |
| `ai-parrot-visualizations` (new `structured_table.py`) | adds | renderer cloned from `structured_chart.py` |
| `parrot/bots/data.py:1623-1629` | modifies | extend override-guard to also skip for STRUCTURED_TABLE |
| `parrot/tools/dataset_manager/tool.py` | depends on | reuse `categorize_columns` (read-only) |
| `parrot/outputs/formats/table.py` | depends on | reuse `_extract_data` (read-only) |
| PandasAgent + DB/SQL agent | depends on | reference producers; provenance already emitted |
| `parrot/handlers/agent.py:2591-2626` | none | envelope already mode-agnostic |

---

## Code Context

### User-Provided Code
_None — idea described in prose; all references below were verified during research._

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/models/outputs.py:72
class OutputMode(str, Enum):
    ...
    STRUCTURED_CHART = "structured_chart"   # :72  (STRUCTURED_TABLE to be added here)
    TABLE = "table"                         # :63  (existing HTML/Grid.js mode — untouched)
    JSON = "json"                           # :42  (routable flat-JSON mode)
    SQL_ANALYSIS = "sql_analysis"           # :71

# packages/ai-parrot/src/parrot/models/outputs.py:309-392
class StructuredChartConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)          # :332
    x: str                                                    # :335
    y: List[str]                                              # :336
    data: List[dict]  # INPUT-ONLY, excluded from output dump # :366-372
    @model_validator(mode="after")                            # :374-392 (column-presence check)

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:625-670
class DatasetManager:
    @staticmethod
    def categorize_columns(df) -> Dict[str, str]:  # integer/float/datetime/boolean/categorical/text

# packages/ai-parrot/src/parrot/outputs/formats/table.py:51,57-97
class TableRenderer(BaseRenderer):
    def _extract_data(self, response) -> "pd.DataFrame":  # :57-97 (handles PandasAgentResponse, to_dataframe, list/dict, response.data)

# packages/ai-parrot/src/parrot/bots/database/models.py:276-325
class QueryResponse(...):
    explanation: str            # :279
    query: Optional[str]        # :282  (SQL artifact)
    data: Optional[QueryDataset]  # :286 (QueryDataset carries columns/row_count/dtypes :271-273)
```

#### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # used at bots/data.py:28
# OutputMode is imported directly everywhere (e.g. outputs/formats/__init__.py:7)
```

#### Key Attributes & Constants
- `OutputFormatter` → `packages/ai-parrot/src/parrot/outputs/formatter.py:129`; `.format()` `:267-338`; `.extract_data()` reuses `TableRenderer._extract_data` `:340-359`.
- Renderer dispatch `_MODULE_MAP` → `outputs/formats/__init__.py:20-45` (STRUCTURED_CHART at `:29`); `@register_renderer` `:48-61`.
- STRUCTURED_CHART renderer contract → `ai-parrot-visualizations/.../structured_chart.py`: `@register_renderer` `:56`; explanation capture `:118`; output excludes data `:161`; `response.data = cfg.data` `:171-173`; returns `(out, explanation)` `:182`; graceful `(None, msg)` `:135-138,184-187`.
- data.py override-guard (extend) → `bots/data.py:1623-1629`; generic prompt-inject `:1411-1418`; formatter call `:1773-1776`; envelope writeback `:1786-1789`.
- DB-agent envelope → `bots/database/agent.py:585-595` (sets `response.response`, `response.data`, `OutputMode.SQL_ANALYSIS`).
- Test scaffold to clone → `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` (521 lines).

### Does NOT Exist (Anti-Hallucination)
- ~~`OutputMode.DATAFRAME`~~ / ~~`OutputMode.JSON_DATA`~~ — only `OutputType.DATAFRAME`/`OutputType.JSON_DATA` exist (`outputs.py:26,35`) and are NOT routable through the formatter. The routable JSON mode is `OutputMode.JSON` (`json.py:7`).
- ~~`structured_table` renderer / config / enum member~~ — does not exist anywhere yet.
- ~~dtype→`currency`/`percent`/`id`/`code` mapper~~ — `categorize_columns` stops at `integer/float/datetime/boolean/categorical/text`; the finer vocabulary is new (LLM elevation + small static map).
- ~~`OutputMode` re-export from `parrot/models/__init__.py`~~ — not re-exported; direct import only (no export plumbing needed).

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The contract (enum + `StructuredTableConfig` in
  core), the renderer (in `ai-parrot-visualizations`), and the producer wiring (PandasAgent
  + DB/SQL agent) are separable, but the renderer depends on the contract and the producers
  depend on the renderer behavior — so most tasks are sequential with a short fan-out at
  the end (the two reference producers can be done in parallel once the renderer lands).
- **Cross-feature independence**: Touches `parrot/models/outputs.py`,
  `outputs/formats/__init__.py`, and `bots/data.py` — the same files FEAT-215 touched. No
  in-flight spec currently edits these (working tree shows only `generic-evaluation-harness`
  and `odoo-fieldservice-toolkit` specs modified). Low conflict risk; additive changes.
- **Recommended isolation**: `per-spec` (one worktree, tasks sequential), with the two
  reference-producer tasks optionally split at the tail.
- **Rationale**: The hard dependency chain (contract → renderer → producers) and the shared
  additive edits to FEAT-215 files make a single sequential worktree the safest; the only
  genuinely parallel work (two producers) is small enough not to justify extra worktrees.

---

## Open Questions

- [x] Flow type & base branch — *Owner: Jesus Lara*: `type=feature`, `base_branch=dev`.
- [x] Reference producer(s) — *Owner: Jesus Lara*: both PandasAgent and DB/SQL agent in v1.
- [x] Type/format conflict policy — *Owner: Jesus Lara*: deterministic wins; LLM only refines ambiguous columns; disagreement recorded best-effort.
- [x] currency/percent modeling — *Owner: research*: `format` hint on a base type, NOT a top-level type (Frictionless/pandas/W3C).
- [x] Package placement — *Owner: research*: renderer ships from `ai-parrot-visualizations` (satellite), like STRUCTURED_CHART.
- [ ] Row-limit default value and exact truncation signal field names (`total_rows`/`truncated` vs. inside `explanation`) — *Owner: Jesus Lara* (spec decision; proposed default ~1000 rows).
- [ ] Is the LLM-refine pass worth it, or does deterministic-only (Option B) suffice for v1? Validate via the cheapest experiment before committing the refine step — *Owner: Jesus Lara*.
- [ ] How does the DB/SQL agent (currently `OutputMode.SQL_ANALYSIS`) opt into STRUCTURED_TABLE — switch mode, or emit both? — *Owner: Jesus Lara*.
