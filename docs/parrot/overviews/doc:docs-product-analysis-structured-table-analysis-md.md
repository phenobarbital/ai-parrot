---
type: Wiki Overview
title: Product Analysis — Structured Table Output Mode
id: doc:docs-product-analysis-structured-table-analysis-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Add `OutputMode.STRUCTURED_TABLE` — the table sibling of `STRUCTURED_CHART`
  (FEAT-215) —
---

# Product Analysis — Structured Table Output Mode

> Status: analysis · Date: 2026-06-03 · Verdict: **GO**

## 1. Idea in One Line
Add `OutputMode.STRUCTURED_TABLE` — the table sibling of `STRUCTURED_CHART` (FEAT-215) —
that returns framework-agnostic structured data (`data` rows + `explanation` provenance +
minimal per-column directives) instead of pre-rendered HTML, so any frontend can paint the
table with the table library it prefers.

## 2. Problem & Opportunity
Today, tabular agent results are delivered either as **rendered HTML/Grid.js**
(`OutputMode.TABLE`, `outputs/formats/table.py:51`) or as a **flat JSON string with no
column semantics and no provenance** (`OutputMode.JSON`, `outputs/formats/json.py:7`).

- HTML forces the frontend to **parse, sanitize and re-style** markup it didn't author,
  and couples the rendered output to Grid.js. It can't be fed to AG Grid / TanStack / MUI
  DataGrid without scraping the DOM.
- Plain JSON gives rows but **drops the two things a frontend actually needs**: per-column
  semantic typing (is this column a number to right-align and sum, or an ID to leave
  alone?) and the explanation of *how the table was derived* (the SQL/Pandas reasoning).

**Why now**: FEAT-215 just shipped `STRUCTURED_CHART` — the exact data/metadata-split
pattern, renderer dispatch, and test scaffold already exist. The marginal cost of giving
tables the same treatment is now small, and it closes the consistency gap (charts are
library-agnostic; tables are not).

## 3. Target Users & Jobs-to-be-Done
- **Primary — frontend developers** consuming AI-Parrot agent responses. JTBD: *"When an
  agent returns tabular data, give me render-ready rows + column types + provenance so I
  can paint a table with my own grid, without parsing HTML or re-deriving column
  semantics."*
- **Secondary — bot/agent developers** who set the output mode. JTBD: *"Let me opt a
  data agent into a structured table contract that's consistent with how I already consume
  structured charts."*
- **Not a target**: end-users of the agent (they see whatever the frontend paints).

## 4. How It Should Be Realized  (strategy — no code)
Mirror the FEAT-215 architecture **verbatim**, swapping chart encodings for column
directives. Placement follows the existing satellite layout.

| Layer | What | Mirror of |
|---|---|---|
| Enum | `OutputMode.STRUCTURED_TABLE = "structured_table"` | `outputs.py:72` |
| Contract | `StructuredTableConfig(BaseModel)` — `columns[]` (name/type/title[/format]), `data` rows (INPUT-ONLY, excluded on dump), `explanation` | `StructuredChartConfig` `outputs.py:309-392` |
| Renderer | `structured_table.py` in `ai-parrot-visualizations`, `@register_renderer`, returns `(out, explanation)`, routes rows via `response.data = cfg.data`, never raises | `structured_chart.py` |
| Dispatch | one line in `formats/__init__.py:_MODULE_MAP` | `formats/__init__.py:29` |
| Routing | extend the FEAT-215 override-guard so it also skips for STRUCTURED_TABLE | `data.py:1629` |

**Hybrid producer** (per discovery): the deterministic half is **already built** —
`DatasetManager.categorize_columns()` (`dataset_manager/tool.py:625-670`) maps dtypes to
`integer/float/datetime/boolean/categorical/text`, and `TableRenderer._extract_data()`
(`table.py:57-97`) pulls rows out of any agent response. The LLM's only job is to (a)
**elevate ambiguous columns** to the finer vocabulary and (b) the `explanation` is
**reused, not minted** — from `response.response` (PandasAgent) or
`QueryResponse.explanation`/`.query` (`database/models.py:279-285`).

**Integration path**: internal output-mode plumbing — **not** A2A/MCP/OpenAPI. The HTTP
envelope (`handlers/agent.py:2591-2626`) is already mode-agnostic; no handler change.

## 5. Potential Impact  (value prop, differentiation, metrics)
- **Pain relieved**: frontend no longer parses/sanitizes HTML; no re-deriving column
  semantics; provenance travels with the data.
- **Gain created**: one contract renders in AG Grid, TanStack, MUI DataGrid (all need ≤
  `name + type + label`; AG Grid & MUI even auto-infer type — see §Appendix).
- **Differentiation**: tables become as portable as charts — a coherent "structured
  output" story across the framework.
- **Success metrics** (paridad-with-STRUCTURED_CHART framing):
  - Frontend renders a table from the payload with **zero HTML parsing** (binary: yes/no).
  - Contract serialization parity with STRUCTURED_CHART (same envelope shape, data excluded
    from `output`, routed to `response.data`) — covered by a cloned test file.
  - Adoption: ≥1 data agent (PandasAgent or DB agent) emits STRUCTURED_TABLE end-to-end.

## 6. Feasibility  (approach, effort, dependencies, readiness, RICE/ICE)
- **Approach**: clone FEAT-215 (enum + config + renderer + dispatch line + 1-line guard +
  copied test), add a thin `categorize_columns → {string,integer,number,boolean,date,
  datetime,...}` mapping, and the hybrid merge (deterministic types + LLM elevation +
  conflict policy).
- **Codebase readiness**: **high.** Reusable, verified: `StructuredChartConfig` pattern
  (`outputs.py:309-392`), `StructuredChartRenderer` (`ai-parrot-visualizations/.../
  structured_chart.py`), `categorize_columns` (`dataset_manager/tool.py:625-670`),
  `TableRenderer._extract_data` (`table.py:57-97`), provenance via `QueryResponse`
  (`database/models.py:276-325`) and `response.response`, test scaffold
  (`tests/outputs/formats/test_structured_chart.py`, 521 lines).
- **External readiness**: **high.** The contract is a de facto standard — pandas
  `to_json(orient='table')` = Frictionless Table Schema + records; Vega-Lite validates the
  data/typed-field split as the chart analogue.
- **Effort: S–M.** S for the mechanical clone; M for the two genuinely new bits — the
  hybrid type-merge + conflict policy, and the configurable row-limit/truncation signal
  (no STRUCTURED_CHART precedent for deterministic truncation).
- **RICE/ICE**: Reach = all table-returning agents × all frontends (high). Impact = medium
  (DX + portability, not a new capability). Confidence = high (precedent + standard).
  Effort = low. → **High priority, low risk.**

## 7. Hidden Assumptions
| # | Assumption | Why assumed | How to validate | Risk if wrong |
|---|---|---|---|---|
| 1 | `currency`/`percent` belong as column **types** | Stated in discovery framing | Frictionless/pandas/W3C all model these as `format` over `number`, not types | **Already shown false** — bake `format` (optional, on `number`) vs `type` (storage) into the contract from day one, or rework later |
| 2 | Formatting (separators, currency symbol, date display) is a backend concern | Implied by "presentation directives" | W3C i18n / `Intl` guidance | Backend-formatted strings break i18n + downstream parsing → ship **canonical values** (ISO-8601 UTC, plain numbers), frontend formats |
| 3 | The LLM can reliably elevate ambiguous columns to semantic types | Hybrid design choice | Eval on real agent tables; measure mislabel rate | Wrong types → wrong sort/align/format. Mitigate: deterministic dtype is the floor, LLM only refines, conflicts resolve to deterministic |
| 4 | Whole table fits in one payload | "data carries the rows" | Test with large agent results; check payload caps (~6 MB) | Oversized payloads → need pagination/`total_rows` + truncation signal (already chose "configurable row-limit") |
| 5 | The reused `explanation` is always present & table-relevant | "reuse data-agent provenance" | Inspect PandasAgent vs DB-agent vs generic-agent paths | Missing/irrelevant explanation → make it best-effort/optional, never block render |
| 6 | Frontends want minimal directives, not grid behavior | Discovery choice | Confirm with the consuming frontend team | If they want sort/filter/width, contract under-delivers — but standards say over-specifying couples to one grid (hold the line) |
| 7 | Type fidelity survives JSON | Implicit | Test dates, big ints (>2^53), nulls, mixed columns | Precision loss / unparseable dates → ISO-8601 strings, big-ints-as-strings, pandas-enforced column homogeneity |

## 8. Opportunities & Adjacencies
- **Unified "structured output" family**: STRUCTURED_CHART + STRUCTURED_TABLE → a
  consistent contract style; a future STRUCTURED_* (cards, KPIs) follows the same mold.
- **Round-trip with pandas**: emitting `orient='table'`-compatible payloads means a Python
  consumer can reconstruct a typed DataFrame for free.
- **Frontend component library**: a single `<StructuredTable>` adapter per grid, reused
  across every AI-Parrot-backed app.
- **Provenance UX**: surfacing `explanation` (the SQL/Pandas reasoning) next to the table
  is a trust/observability win that HTML output can't carry cleanly.

## 9. Risks & Mitigations
- **Type fidelity at the JSON boundary** (dates/big-ints/nulls/mixed) → ISO-8601 UTC,
  big-ints-as-strings, pandas column homogeneity, fall back to `any`. *(Assumption 7)*
- **Large-table payloads** → configurable row-limit (chosen) + `total_rows`/truncation
  flag in the contract from day one, not bolted on. *(Assumption 4)*
- **Scope creep into presentation** (locale strings, grid-specific config) → hold the
  "semantic hints only" line; couples to one frontend otherwise. *(Assumptions 2, 6)*
- **Pre-mortem — "it shipped and nobody used it"**: if the frontend already post-processes
  `OutputMode.JSON`, adoption stalls. Mitigate by landing one real agent + one real
  frontend consumer in the first iteration (the success metric), not just the plumbing.

## 10. Open Questions
1. **Contract shape for currency/percent**: confirm `type` (storage) + optional `format`
   (display intent) split — this overrides the Round-1 "semantic types" framing.
2. **Conflict policy** when the LLM's elevated type disagrees with the deterministic dtype
   — default to deterministic? flag the disagreement?
3. **Row-limit default** value and where truncation is signaled (in `explanation`? a
   dedicated `total_rows`/`truncated` field?).
4. **Which agent(s)** ship first as the reference producer — PandasAgent or DB agent?
5. **Package placement**: confirm STRUCTURED_TABLE renderer ships from
   `ai-parrot-visualizations` (satellite), matching STRUCTURED_CHART.

## 11. Recommendation & Next Steps
**GO** — high-value, low-risk. The architecture is a near-verbatim clone of a shipped
feature, the deterministic half already exists in the codebase, and the contract is an
established external standard. The only real design work is the type/format split, the
hybrid conflict policy, and truncation signaling.

**Cheapest de-risking experiment**: take one real PandasAgent table result, run it through
`categorize_columns` + a hand-written `StructuredTableConfig`, and confirm a frontend grid
(AG Grid/TanStack) renders it from the JSON with zero HTML parsing. One afternoon; proves
the contract end-to-end before any renderer plumbing.

→ Proceed to **`/sdd-brainstorm structured-table`** — this analysis feeds Problem (§2),
Users (§3), Impact+Feasibility constraints (§5/§6), the realization approach (§4), and the
verified Code Context below.

---

## Appendix — Code Context (verified)

### Reuse / integration points
- `OutputMode` enum + `StructuredChartConfig` pattern — `packages/ai-parrot/src/parrot/models/outputs.py:72`, `:309-392` (clone for STRUCTURED_TABLE; `data` is INPUT-ONLY, excluded on dump; `populate_by_name`; after-validator over columns).
- STRUCTURED_CHART renderer (blueprint) — `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` (`@register_renderer` `:56`; `(out, explanation)`; `response.data = cfg.data` `:171-173`; graceful degradation `:135-138,184-187`).
- Renderer dispatch — `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:_MODULE_MAP` (`:20-45`, STRUCTURED_CHART at `:29`); `OutputFormatter` `formatter.py:129`, `format()` `:267-338`.
- Routing override-guard to extend — `packages/ai-parrot/src/parrot/bots/data.py:1623-1629`; generic prompt-inject `:1411-1418`, formatter call `:1773-1776`, envelope writeback `:1786-1789`.
- Existing HTML TABLE (stays untouched) + reusable extractor — `packages/ai-parrot/src/parrot/outputs/formats/table.py:51`, `_extract_data` `:57-97`; reused by `OutputFormatter.extract_data` `formatter.py:340-359`.
- Deterministic dtype→semantic-category — `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:625-670` (`categorize_columns`, `@staticmethod`).
- Provenance — `QueryResponse` `packages/ai-parrot/src/parrot/bots/database/models.py:276-325` (`explanation` `:279`, `query` `:282`); DB-agent envelope `database/agent.py:585-595` (`OutputMode.SQL_ANALYSIS`); PandasAgent sets `response.response` + `response.data`.
- Mode-agnostic HTTP envelope (no change needed) — `packages/ai-parrot-server/src/parrot/handlers/agent.py:2591-2626`.
- Test scaffold to clone — `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` (521 lines; data-exclusion, routing, explanation-as-wrapped, graceful degradation, envelope serialization).

### Does NOT exist (verified)
- No `OutputMode.DATAFRAME` / `OutputMode.JSON_DATA` — only `OutputType.DATAFRAME`/`JSON_DATA` (`outputs.py:26,35`), which are NOT routable through the formatter. The routable JSON mode is `OutputMode.JSON` (`json.py:7`). *(Corrects the Round-2 pre-mortem framing — delta still holds vs `OutputMode.JSON`.)*
- No `structured_table` renderer / config / enum member anywhere.
- No existing dtype→`currency/percent/id/code` mapper — `categorize_columns` stops at `integer/float/datetime/boolean/categorical/text`; finer vocabulary is the LLM elevation + a small static mapping table (the only genuinely new deterministic code).
- No re-export of `OutputMode` from `models/__init__.py` (direct import only — no export plumbing needed).

### External sources cited
- Frictionless Table Schema — https://specs.frictionlessdata.io//table-schema/
- pandas `build_table_schema` / `orient='table'` — https://pandas.pydata.org/docs/reference/api/pandas.io.json.build_table_schema.html ; PDEP-12 — https://pandas.pydata.org/pdeps/0012-compact-and-reversible-JSON-interface.html
- Vega-Lite type/encoding (chart analogue) — https://vega.github.io/vega-lite/docs/type.html
- Grid column defs — AG Grid https://www.ag-grid.com/javascript-data-grid/cell-data-types/ · TanStack https://tanstack.com/table/v8/docs/api/core/column-def · MUI https://mui.com/x/api/data-grid/grid-col-def/
- W3C number/currency formatting (frontend-side) — https://w3c.github.io/i18n-drafts/questions/qa-number-format.en.html ; MDN Intl.NumberFormat — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/NumberFormat
- JSON date best practices (ISO 8601) — https://jsoneditoronline.org/indepth/parse/json-date-format/
