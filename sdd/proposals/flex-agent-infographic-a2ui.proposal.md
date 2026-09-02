---
id: FEAT-517
title: Compose a FlexDashboard agent (PandasAgent + InfographicAuthoringMixin + skills + kb) over six QuerySource slugs, reusing the deterministic A2UI recipe/refresh lane
slug: flex-agent-infographic-a2ui
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-01
  summary_oneline: New A2UI PandasAgent for Flex — KPI dashboards, /widget + /infographic skills, QuerySource-fed datasets, deterministic HTML refresh
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-517/
created: 2026-09-01
updated: 2026-09-01
---

# FEAT-517 — Flex A2UI Dashboard Agent (`agents/flex_dashboard.py`)

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-517/`](../state/FEAT-517/)

---

## 0. Origin

The original request, preserved verbatim (full text with all six sample rows at
`sdd/state/FEAT-517/source.md`):

> Crear un agente en `agents/flex_dashboard.py` basado en PandasAgent y con la
> infra de A2UI outputs and dashboards. Using QuerySource slugs y
> DatasSourceManager para consumir los siguientes slugs: `flex_msl_brian_bi`,
> `Finance_results_bi`, `flex_hours_query_pbi`, `flex_empolyees_brian_bi`,
> `fm_regions_avg_employees_html`, `fm_rep_utilization`. […] El PandasAgent
> será usado para responder por Payroll Contribution, Proximity Staffing y Rep
> Utilization […] Aprovechar la capacidad de generar Dashboards con
> refrescamiento determinista […] un botón de "refresh" […] un skill "/widget"
> […] Incorporar InfographicToolkit y un skill ("/infographic") […]
> WorkingMemoryToolkit […] y varios documentos de "kb" explicando cada uno de
> los KPIs.

**Initial signals** (extracted, not interpreted):
- Verbs: "crear", "incorporar", "aprovechar", "mostrar", "filtrar" → feature-shaped (enrichment)
- Named entities: PandasAgent, A2UI, QuerySource, DatasSourceManager, InfographicToolkit, WorkingMemoryToolkit, `/widget`, `/infographic`, kb, `flex_program_report`
- Components: six QuerySource slugs with sample rows; two example HTML dashboards
- Acceptance criteria provided: implicit (KPI list, filter list, refresh button, skills, kb docs)

---

## 1. Synthesis Summary

The request is to build a Flex-program analytics agent that both answers KPI
questions over six QuerySource datasets and publishes an interactive,
deterministically-refreshable A2UI dashboard. Every building block already
exists: `PandasAgent` (`packages/ai-parrot/src/parrot/bots/data.py`) natively
consumes QuerySource slugs through its internal `DatasetManager`
(`packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — this is what
the ticket calls "DatasSourceManager"); `agents/finance_reporter.py`
(FEAT-420) is the direct structural precedent for the mixin stack and recipe
publishing; and `examples/agents/a2ui/deterministic_refresh_dashboard.py`
(FEAT-324/326 × FEAT-469) demonstrates the exact refresh-button + in-dashboard
filter lane requested — its docstring even cites the standalone Flex Program
report as its lineage. `InfographicToolkit`, `WorkingMemoryToolkit`, skill
`/trigger` middleware, and the `kb=` plane on `AbstractBot` cover the remaining
requirements. The feature is therefore **pure composition** — a new agent
module, a flex transformer set, recipe descriptors, two skills, and kb docs —
with no core-package changes. Recommendation: proceed to `/sdd-spec FEAT-517`.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-517/findings/`. No fabricated
> paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/bots/data.py` | `PandasAgent` | 379-491 | Base class: `query=` slugs, internal `DatasetManager`, `add_query()`/`refresh_data()`, `output_routing` (FEAT-224) | F001 |
| 2 | `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | `DatasetManager.add_dataset` | 501, 966-1091 | Slug consumption: `add_dataset(query_slug=…)` → lazy `QuerySlugSource` with `permanent_filter` + `usage_guidance` | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/qsource.py` | `QSourceTool` | 62-437 | Ad-hoc LLM-facing QuerySource executor — optional here | F002 |
| 4 | `agents/finance_reporter.py` | `FinanceReporter` | 85-326 | FEAT-420 precedent: `NarrativeMixin + InfographicAuthoringMixin + PandasAgent`, `publish_recipe`, LayoutSpec v2 (`KPICard`/`DataTable`), `skill_paths` opt-in | F003 |
| 5 | `examples/agents/a2ui/deterministic_refresh_dashboard.py` | (worked example) | 1-764 | The requested refresh lane end-to-end: transformers with filter params, `RecipeRunner` byte-identical replay, `A2UIRuntime` `callAgentFunction → refresh_dashboard`, per-surface filter state | F004 |
| 6 | `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | `InfographicToolkit` | 180-899 | render/render_template/render_data_template + A2UI envelope builders | F005 |
| 7 | `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | `WorkingMemoryToolkit` | 44-650 | store / compute_and_store / merge / import_from_tool for intermediate data ops | F005 |
| 8 | `packages/ai-parrot/src/parrot/skills/mixin.py` | `SkillRegistryMixin` + `create_skill_trigger_middleware` | 142-188 | Deterministic `/trigger` activation for `/widget` and `/infographic` | F005 |
| 9 | `packages/ai-parrot/src/parrot/bots/abstract.py` | `AbstractBot(use_kb, local_kb, kb=[…])` / `register_kb` | 287-288, 554-562, 1172-1176 | kb attachment plane for KPI-definition docs | F005, F003 |
| 10 | `docs/flex_program_report (39).html` | (target layout) | 1-3064 | Concrete visual target: KPI hero row, Chart.js month charts, pay-code pie, map, multi-select filter bar with embedded data | F006 |

### 2.2 Constraints Discovered

- **Determinism rule (FEAT-324 G1).** Recipe numbers must come from registered
  `@infographic_transformer` functions over declared datasets, never from
  replaying LLM-generated code.
  *Implication*: every Flex KPI needs a named, registered transformer.
  *Evidence*: F004

- **Alias ↔ transformer-key 1:1.** `publish_recipe` forces
  `TransformStep.inputs` to equal the section's dataset alias, and transformers
  hard-code their input frame keys.
  *Implication*: DatasetManager aliases for the six slugs must exactly match
  what the flex transformers read.
  *Evidence*: F003

- **Dirty inputs.** `Finance_results_bi` currency columns arrive as formatted
  strings (`"$137,456.85"`); the three dataset families use three date-grain
  conventions (`month` month-end, `month_start`/`month_end`, `BOP/EOP Date`)
  and `fm_rep_utilization` has a `catagory` typo column.
  *Implication*: a deterministic normalization layer inside the transformers,
  pinned down by the kb docs.
  *Evidence*: F006

- **HTTP origin required.** The `interactive-html` renderer (ships from
  ai-parrot-visualizations, registers on import) breaks under `file://`.
  *Implication*: dashboards must be served, not just written to disk.
  *Evidence*: F004

- **Eager `template_dirs` validation.** `InfographicToolkit` validates every
  template directory at construction.
  *Implication*: any Flex HTML template must live in a repo-tracked/package
  directory, never a gitignored artifacts path.
  *Evidence*: F005, F003

- **Hot surface.** The A2UI v1 dialect (renderers, envelope routing,
  structured outputs) changed heavily in the last 60 days.
  *Implication*: pin to current LayoutSpec v2 conventions (`{"path"}` bindings,
  `metadata.extensions.parrot_optional`).
  *Evidence*: F006

### 2.3 Recent History (Relevant)

| Commit | Message | Touched |
|--------|---------|---------|
| `ff7728a2c` | feat(a2ui-v1-structured-outputs): TASK-2564 — echarts + folium renderer prop fidelity | `parrot/outputs/` |
| `9314cec4a` | TASK-2563 — satellite `_route_envelope` dual-emit + map per-layer payloads | `parrot/outputs/` |
| `32dfcf854` | feat(a2ui-v1-dialect): TASK-2544 — interactive-html, ECharts y Folium sobre primitivas v1.0 | `parrot/outputs/` |
| `69422348d` | wip: info agent | `bots/data.py` — **confirmed unrelated to this feature (U5)** |
| `051939fae` | TASK-2565 — agents + transport: artifact v2 call sites, non-stream envelope passthrough | `bots/data.py` |

*Evidence*: F006

---

## 3. Probable Scope *(mode = enrichment)*

### What's New

- **`agents/flex_dashboard.py`** — `FlexDashboard(InfographicAuthoringMixin, PandasAgent)`
  (optionally `NarrativeMixin` for narrative sections), registering the six
  slugs on its `DatasetManager` in `configure()`, with `WorkingMemoryToolkit`
  and `InfographicToolkit` attached and `output_routing` enabled.
- **Flex transformer module** — registered `@infographic_transformer` functions
  for Payroll Contribution (worked hours / payroll / revenue / payroll% by
  month, pay-code hours, pay-code allocation), Rep Utilization
  (region/type), and Proximity Staffing (per-store nearest-N employees via
  haversine, configurable radius, map layers + coverage table — per U4), each
  with declared filter params (month, flex_type, pay_code, cost_center).
- **Dashboard recipe descriptor(s)** — hero-card KPI row (Worked Hours,
  Payroll, P&L Revenue, Payroll % to Revenue) + monthly chart sections +
  pay-code sections; published via `publish_recipe`; refresh via the
  A2UIRuntime `refresh_dashboard` agent function; **per-section filters** (U1).
- **Skills** — `/widget` (export any KPI as an A2UI structured chart / map /
  hero-card envelope) and `/infographic` (InfographicToolkit descriptive
  infographic), file-based skills with deterministic triggers.
- **kb documents** — one markdown doc per KPI defining exact computation
  (currency parsing, month-grain alignment, utilization formula, proximity
  method), attached via file-based `kb=` (U2).
- **Example runner** mirroring `deterministic_refresh_dashboard.py` (synthetic
  seed for tests; live slugs behind lazy fetch) — plus server registration via
  the existing `infographic_recipes` handlers (U3: both lanes in this feature).

### What Changes

- Nothing in core packages. *Evidence*: F001-F005 (all required APIs exist).

### What's Untouched (Non-Goals)

- `packages/ai-parrot/src/parrot/bots/data.py` (PandasAgent core)
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
- `packages/ai-parrot/src/parrot/skills/mixin.py`
- The `wip: info agent` work (`69422348d`) — unrelated (U5)

### Patterns to Follow

- FinanceReporter composition + its in-file FEAT-420 review lessons (alias
  matching, `dataset_sql` for replay, eager template dirs, `skill_paths`).
  *Evidence*: F003
- deterministic_refresh_dashboard example: filter placeholders, FileRecipeStore,
  byte-identical replay, refresh RPC. *Evidence*: F004
- Porygon: per-agent skills directory + kb configuration. *Evidence*: F003, F005

### Integration Risks

- **Filter semantics across heterogeneous datasets** → resolved to per-section
  filters (U1); the spec must table which filter applies to which section.
  *Evidence*: F006
- **Prod-only slug data** (project convention: `ENV=prod` for data access) →
  synthetic seed frames for tests, like the example. *Evidence*: F004
- **A2UI v1 churn** → pin conventions at spec time; re-verify LayoutSpec
  details when tasks start. *Evidence*: F006

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | All named building blocks exist; feature is pure composition, no core changes | F001, F002, F004, F005 | high | each class/API located and its contract read |
| C2 | FinanceReporter is the correct structural template, incl. its documented pitfalls | F003 | high | same base, mixins, recipe machinery; in-file FEAT-420 rationale |
| C3 | Refresh button + filters map onto the FEAT-469 A2UIRuntime lane already demonstrated end-to-end | F004 | high | worked example implements precisely this and cites the Flex report as origin |
| C4 | The six slugs are consumed via `DatasetManager.add_dataset(query_slug=…)`, not ad-hoc QSourceTool | F002, F001 | high | direct API read; PandasAgent syncs the catalog automatically |
| C5 | `/widget` and `/infographic` work as file-based skills; `/widget` needs new per-KPI export glue (agent function or tool emitting the A2UI envelope) | F005, F004 | medium | trigger middleware verified; export glue is a new design choice |
| C6 | Ticket's `artifacts/a2ui_live/*` paths don't exist; real references are `docs/flex_program_report (39).html` + `documents/flex_program_report.html` | F006, F004 | high | filesystem checked; report ids match ticket vocabulary |
| C7 | KPI computation rules (currency parsing, date-grain alignment, utilization/proximity formulas) are the core ambiguity | F006 | medium | sample rows show shape, not business rules — hence the kb docs |
| C8 | The `wip: info agent` commit might overlap | F006 | low → **resolved** | user confirmed unrelated (U5) |

Distribution: **5** high, **2** medium, **1** low (resolved).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Filter scope: per-section or global cross-filter?** — *Resolved*:
  Per-section — each filter only affects sections whose dataset carries that
  column (matches the shipped flex_program_report behavior). *Resolves*: C7
- [x] **U2 — Where do the KPI kb documents live?** — *Resolved*: file-based
  `kb=` markdown documents shipped in the agent's directory (versioned with
  code, no DB dependency). *Resolves*: C7
- [x] **U3 — Deployment target?** — *Resolved*: Both — standalone example-style
  runner (FileRecipeStore) for dev/tests **and** server registration
  (`infographic_recipes` handlers) in the same feature. *Resolves*: C3
- [x] **U4 — Proximity Staffing definition?** — *Resolved*: map + coverage
  table — per-store nearest-N employees with haversine distance, configurable
  radius threshold, two map layers (stores/employees) plus a coverage table.
  *Resolves*: C7
- [x] **U5 — Is `wip: info agent` (69422348d) this feature?** — *Resolved*:
  Unrelated — proceed independently. *Resolves*: C8

### Unresolved (defer to spec / implementation)

- [ ] **Exact KPI formulas per kb doc** (e.g. Payroll % denominator: `Revenue`
  vs `Revenue + PC Revenue`; utilization definition vs the precomputed
  `Employee Utilization` column) — *Owner*: spec Q&A / kb authoring.
  *Blocks claims*: C7

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-517`** — *Rationale*: localization is high-confidence and the
architecture is predetermined by the FinanceReporter + deterministic-refresh
precedents; the remaining ambiguity (exact KPI formulas) is precisely what the
spec's acceptance criteria and the kb documents should pin down. No
architectural fork worth a brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-517`** — only if the /widget export-glue design
  (agent function vs skill-guided tool) deserves an options analysis.
- **`/sdd-task FEAT-517`** — not recommended; scope is multi-module (agent,
  transformers, recipes, skills, kb, example, server wiring).
- **Manual review** — not needed; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-517/state.json` |
| Source (raw) | `sdd/state/FEAT-517/source.md` |
| Research plan | `sdd/state/FEAT-517/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-517/findings/F001-*.md` … `F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-517/synthesis.json` |

**Budget consumed**:
- Files read: 6 / 40 (incl. partial/structural reads)
- Grep calls: 14 / 25
- Git calls: 2 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (feature-shaped verbs:
"crear", "incorporar", "aprovechar").

**Wiki**: unavailable this session (MCP + CLI timeout) — grep-first fallback,
declared before falling back.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jlara@trocglobal.com + Claude (Fable 5) |
