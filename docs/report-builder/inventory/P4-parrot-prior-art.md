# P4 — ai-parrot prior art for a Report Builder (SDD inventory)

Repo: `/home/jelitox/repos/trocglobal/ai-parrot`, branch `dev`, read-only survey on 2026-09-30.
Paths are relative to `sdd/` unless they say otherwise. "Tasks" comes from `sdd/tasks/index/<slug>.json` and reads done/total; completed_at.
"No idx" means the spec has no per-spec index; for those, the counts of tasks under `tasks/completed/` are listed instead.

**Takeaway.** ai-parrot already has most of the engine a report builder needs. It has the A2UI v1.0 wire with three catalogs, deterministic recipes (dataset → registered transformer → layout), a persisted, shareable and refreshable surface store (`navigator.ui_surfaces`), linked (live-data) surfaces, the HTML, PDF and Adaptive Card renderers, a design system, signed artifact URLs, scheduling, and notifications. The missing piece is the authoring side. Nothing yet describes a visual, user-driven builder (the "Canvas Builder") that edits surface or recipe layouts. That idea exists only as SPEC-B inside the FEAT-430 brainstorm and was never proposed or specced.

---

## 1. Inventory by domain

### 1.1 Infographic (legacy block model → recipes → A2UI)

| FEAT | Slug / file | Status | Tasks | Delivers (2 lines) | Meaning for a report builder |
|---|---|---|---|---|---|
| FEAT-094 | infographic-html-output · `specs/infographic-html-output.spec.md` | draft (implemented) | 4/4; 2026-04-10 | `InfographicHTMLRenderer`: `InfographicResponse` → self-contained HTML (inline CSS + ECharts) via `Accept` negotiation. Themes light/dark/corporate. | **Reusable**: the HTML lane for the legacy block model. Content negotiation (HTML vs JSON) is the established pattern. |
| FEAT-095 | get-infographic-handler · `specs/get-infographic-handler.spec.md` | approved | 4/4; 2026-04-10 | `InfographicTalk` HTTP handler, plus discovery and registration of templates (basic, executive, dashboard, comparison, timeline_report, minimal) and themes. | **Reusable**: template and theme catalog endpoints (`docs/infographic_handler_api.md`). |
| FEAT-102 | multi-tab-infographic · `specs/multi-tab-infographic.spec.md` (brainstorms `proposals/multi-tab-infographic.brainstorm.md`, `multi-tab-infographic.md`, `sdd-brainstorm-multi-tab-infographic.md`) | approved | 8/8; 2026-04-15 | Adds `TabViewBlock`, `AccordionBlock`, `ChecklistBlock` and a richer Table/BulletList to the block model, plus a `multi_tab` template and an LLM pre-pass that auto-detects the template. | **Constraint/legacy**: tabs exist only in the *legacy block model*. The A2UI catalog has no Tabs/Page component (gap). |
| FEAT-197 | infographictoolkit · `specs/infographictoolkit.spec.md` (brainstorm and proposal both recommend Option B) | approved | 10/10; 2026-05-28 | `InfographicToolkit` handles single-turn render from DataFrames, `InfographicTemplate` positional block contracts, HMAC-signed artifact URLs and CSP. | **Reusable**: `ArtifactStore` plus signed iframe URLs (`/api/v1/artifacts/public/{sig}/{id}.html`). Template = layout contract. |
| FEAT-301 | infographic-theme-catalog-a2ui · `specs/infographic-theme-catalog-a2ui.spec.md` (a copy also sits in `proposals/`) | approved | 9/9; 2026-08-19 | Raises block types 15→19 (chain, steps, code, card_grid). Adds ThemeConfig v2, a `petrol` theme, CSS variables, `I18nText` bilingual text, and document chrome (version bar, changelog, footer). | **Reusable**: theme tokens, i18n and doc chrome. **Gap**: the 4 new blocks lower to generic Card in A2UI; no dedicated components. |
| FEAT-308 | agentcrew-node-infographic · `specs/agentcrew-node-infographic.spec.md` | approved | 6/6; 2026-07-14 | `ResultAgent` builds a multi-tab infographic at the end of an AgentCrew run (summary, final result, one tab per agent). | Shows a report assembled automatically from run output. |
| FEAT-324 | infographic-builder · `specs/infographic-builder.spec.md` / `proposals/infographic-builder.brainstorm.md` | approved | 9/9; 2026-07-22 | **Recipe layer** (`parrot/outputs/a2ui/recipes/`): `InfographicRecipe` (data_sources, transforms, layout, render, schedule), `@infographic_transformer` registry, File/DB stores, `RecipeRunner`, chat/REST/scheduler triggers, `interactive-html` profile (Chart.js v4). | **Core reusable piece**: the "report definition" model already exists as a recipe. A builder would edit `LayoutSpec` and transforms and persist them as recipes. |
| FEAT-326 | dataagent-infographic · `specs/dataagent-infographic.spec.md` | approved | 6/6; 2026-07-24 | `InfographicAuthoringMixin` + `SectionDescriptor` (machine-enforced section → data contract), the data-splice template mode, ArtifactStore persistence, and `FinanceReporter`. | **Reusable**: the section→dataset contract with fail-fast validation, i.e. a "slot binding" model for templates. |
| FEAT-327 | infographic-render-endpoint · `specs/infographic-render-endpoint.spec.md` | approved | 5/5; 2026-07-24 | `POST /api/v1/agents/infographic/render`: deterministic, no LLM. Accepts datasets (JSON, split, Parquet/CSV), a pre-registered template and a descriptor. Sync or async (Redis job, 1-day TTL), 50 MB cap. | **Reusable**: render-as-a-service for any client. **Constraint**: inline template HTML is forbidden (stored XSS). |
| FEAT-420 | finance-reporter-tier2-narrative · `specs/finance-reporter-tier2-narrative.spec.md` | approved | 12/12; 2026-08-07 | Moves FinanceReporter to tier 2 (`publish_recipe` with registered transformers) and adds a narrative skill. Removes the tier-1 data-splice path. | **Decision**: tier 2 (recipes) is the blessed path, and data-splice templates are legacy. |
| FEAT-428 | agent-infographic-generation · `specs/agent-infographic-generation.spec.md` | **draft** | **no idx / 0 tasks** | DataAgent multi-tab dashboard: new `Dashboard`+`FilterBar` components, `DashboardRecipe`, `PythonCodeStep` (LLM pandas code stored in the recipe), Excel parquet snapshot, declarative dashboard templates in `BASE_DIR/templates/infographics/`. | **Gap/unbuilt**: `Dashboard` component, `PythonCodeStep` and file-snapshot sources do not exist in code (grep-verified). FilterBar was later delivered by FEAT-493. The *template library of parametrized A2UI layouts* idea is unbuilt. |
| FEAT-491 | flex-agent-infographic-a2ui · `specs/flex-agent-infographic-a2ui.spec.md` | approved | 7/7; 2026-09-01 | The `flex_dashboard` PandasAgent: an A2UI dashboard recipe with hero cards, monthly charts, per-section filters and a refresh button (`refresh_dashboard`), plus a `/widget` skill that exports a single KPI. | **Reference implementation** of a real dashboard report on recipes. Pure composition, no core changes. |
| FEAT-493 | html-renderer-design-system · `specs/html-renderer-design-system.spec.md` | approved | 11/11; 2026-09-02 | `DesignSystem` CSS composer shared by interactive-html, ssr-html and pdf. Two axes: theme × layout (`report`, `analytics`, `print`). Adds a rich DataTable, a KPI hero row and the `FilterBar` composite. | **Reusable**: theming and layout presets for report output. **Constraint**: no CDN, no Tailwind build, no `lower()` changes, no wire changes. |
| FEAT-522 | interactive-html-map-tailwind · `specs/interactive-html-map-tailwind.spec.md` | approved | 10/10; 2026-09-03 | Real Map rendering in interactive-html, plus Tailwind CSS coverage. | Map widget available in HTML reports. |
| FEAT-527 | infographic-a2ui-migration · `specs/infographic-a2ui-migration.spec.md` / `proposals/infographic-a2ui-migration.proposal.md` | approved | 14/14; 2026-09-05 | **Dual-emit**: every infographic render produces both HTML and an A2UI envelope. Adds the `HtmlDocument` component for Jinja output and a Svelte A2UI Infographic renderer in the bundled UI. | **Decision**: HTML is a permanent sibling, not deprecated. **Gap**: the 10 built-in templates were *not* re-expressed as recipes/LayoutSpecs (deferred). |
| FEAT-528 | pg-recipe-store-and-agent-package-importability · `specs/pg-recipe-store-and-agent-package-importability.spec.md` | approved | 5/5; 2026-09-05 | `PgRecipeStore` (relational, one row per recipe, next to `ui_surfaces`) and agent-package importability for host apps (FieldSync). | **Reusable**: recipes as editable DB rows, which is the natural persistence for a builder. Note that `DBRecipeStore` is actually Redis. |

### 1.2 A2UI core and surfaces

| FEAT | Slug / file | Status | Tasks | Delivers | Meaning for a report builder |
|---|---|---|---|---|---|
| FEAT-273 | a2ui-implementation · `specs/a2ui-implementation.spec.md` / `proposals/a2ui-implementation.brainstorm.md` | approved | 22/22; 2026-07-11 | `parrot.outputs.a2ui`: envelope models, catalog registry with `lower()`, builders, validate-retry producer, renderers (ssr-html, interactive-html, pdf, adaptive cards, echarts), `RenderedArtifact`, `deliver_artifact`, `DeepLinkService`. Kills `exec()` of LLM code. | **Foundation**. Invariants: no exec, one-way import rule (G8), catalog allowlist. |
| FEAT-470 | a2ui-v1-dialect · `specs/a2ui-v1-dialect.spec.md` | approved | 17/17; 2026-08-28 | Wire is 100% A2UI v1.0 (vendored schemas, jsonschema validation). Ships the basic catalog (18 primitives + 14 functions) and the parrot catalog via `$ref`. Card is renamed to `InfoCard`, Form becomes a composition, `migrate_layout()` handles schema_version 1→2. | **Constraint**: everything the builder emits must validate against v1.0 plus the catalogs. Presentation hints go in `metadata.extensions.parrot_*`. |
| FEAT-469 | a2ui-agent-functions · `specs/a2ui-agent-functions.spec.md` | approved | 11/11; 2026-08-29 | The v1.0 RPC leg: `callAgentFunction` → tool → response, `callRendererFunction`, `sendDataModel`, `A2UIHandler`, SSE stream, catalog `functions` declarations. | **Reusable**: deterministic drill-down and refresh from a rendered report without an LLM turn. |
| FEAT-473 | a2ui-v1-structured-outputs · `specs/a2ui-v1-structured-outputs.spec.md` | draft (implemented) | 7/7; 2026-08-29 | STRUCTURED_CHART, STRUCTURED_TABLE and STRUCTURED_MAP now emit A2UI v1.0 (Chart, DataTable, Map). | One chart/table/map contract shared by chat and reports. |
| FEAT-492 | a2ui-surface-rehydration · `specs/a2ui-surface-rehydration.spec.md` | approved | 6/6; 2026-09-01 | `navigator.ui_surfaces` (Pg). Routes: `GET /api/v1/ui/surfaces/{id}` (JSON or HTML), `POST .../refresh` via `recipe_ref`, `publish_surface` (agent) plus `POST /api/v1/ui/surfaces` (pin), opaque revocable share tokens. | **Core reusable piece**: the persisted, bookmarkable, shareable report instance. Non-goal: *editing components through the API* → **gap for a builder**. |
| FEAT-499 | a2ui-optional-binding-lowering · `specs/a2ui-optional-binding-lowering.spec.md` | approved | 4/4; 2026-09-02 | `parrot_optional` bindings actually reach the wire, so a missing optional path omits the component instead of aborting the run. | A builder can mark sections as optional. |
| FEAT-529 | a2ui-graph-component · `specs/a2ui-graph-component.spec.md` (umbrella `proposals/a2ui-rich-visualizations.brainstorm.md`, accepted) | approved | 11/11; 2026-09-06 | Shell of the `viz-core` catalog plus a `Graph` component (typed nodes and edges, mermaid codec, server-side layered layout), drawn natively in all four renderers. | **Reusable**: diagrams in reports. The umbrella planned 3 specs (graph → **viz-core charts** → **live workflow surface**); the last two **have no spec yet**. |
| FEAT-535 | ui-surfaces-tenant-visibility · `specs/ui-surfaces-tenant-visibility.spec.md` | approved | 5/5; 2026-09-07 | Surfaces gain `tenant`, `visibility` (private/tenant/groups) and `allowed_groups`. Adds `PATCH /api/v1/ui/surfaces/{id}`, a pluggable `SurfaceScopeResolver` and superuser views, and exposes recipe_name/params. | **Reusable**: publishing a report to a tenant or groups. **Constraint**: tenant never comes from the request body. Non-goal: per-user ACLs. |
| FEAT-544 | a2ui-form-output-renderer · `specs/a2ui-form-output-renderer.spec.md` | approved | 8/8; 2026-09-10 | Adds an `a2ui` render format for FormDesigner forms, with a full render → validate → submit → respond cycle over A2UI and no agent in the loop. | **Reusable**: parameter/filter input forms for reports (e.g. a "run report for month X" prompt). |
| FEAT-598 | a2ui-linked-surfaces · `specs/a2ui-linked-surfaces.spec.md` / `docs/outputs/a2ui-linked-surfaces.md` | approved | 29/29; 2026-09-26 | Data-source descriptors (`metadata.extensions.parrot_data_sources`) instead of baked rows. The renderer fetches QuerySource with the viewer's JWT, and a Python executor handles the server lane. A 10-operation transform DSL. Only TOOL-origin builders may emit descriptors. | **Core reusable piece** for live reports. **Constraint**: an LLM-origin envelope with descriptors fails validation. Open ledger bugs: `request.limit` dropped, empty snapshot vs KPI binding, fail-closed slug auth adapter (major). |
| FEAT-610 | a2ui-linked-e2e-test · `specs/a2ui-linked-e2e-test.spec.md` | approved | 13/13; 2026-09-28 | Self-contained E2E: an agent emits a multi-widget linked dashboard (4 KPIs, 2 bars, 1 pie, a paged grid) and a plain HTML5 client renders and refreshes it. | Proof that a plain client can render a report. |
| FEAT-611 | a2ui-linked-e2e-parallel · `specs/a2ui-linked-e2e-parallel.spec.md` | approved | **9/10** (TASK-3840 done-with-issues); 2026-09-29 | Staging E2E (Epson, querysource 5.1.2): server lane, share tokens, PBAC, join/union, FilterBar `parrot_param`, Python↔TS parity. | **Risk**: drift between the Svelte linked lane and Python, which the spec itself flags. The S4 checklist is manual. |
| FEAT-200 | `proposals/ai-parrot-visualizations.proposal.md` | accepted | — | Moves `parrot/outputs/formats` into the `ai-parrot-visualizations` package. | Renderers live in the satellite package. |
| — | `proposals/a2ui-outputs-brainstorm.md` | brainstorm-input | — | Original input for integrating A2UI into `parrot.outputs`. | Background only. |
| — | `proposals/output-mode-intent-router.brainstorm.md` | exploration (no spec) | — | LLM-driven choice between chart, map and table output. | Possible "auto-suggest widget" for a builder. Unbuilt. |

### 1.3 Dashboards / canvas / artifacts / publish / UI surfaces

| FEAT | Slug / file | Status | Tasks | Delivers | Meaning for a report builder |
|---|---|---|---|---|---|
| FEAT-430 | dashboard-scheduled-notifications-canvas · `proposals/dashboard-scheduled-notifications-canvas.proposal.md` + `state/FEAT-430/source.md` (the brainstorm, rev 2.1, by Javier) | proposal **review**; **no spec** | — | SPEC-A (PoC): scheduled refresh of a Navigator dashboard's HTML artifact → ArtifactStore signed URL → Teams Adaptive Card or email. SPEC-B: **"Artifact & Canvas Builder"**, a visual composition of catalog components in Navigator with self-service and advanced permission tiers, coexisting v1-html and v2-a2ui. | **The only prior art for a Canvas/Report Builder.** SPEC-B was never proposed or specced. Decisions D1–D4 and the coexistence discriminator `Dashboard.attributes.artifact_type` are reusable. Q5–Q10 are open. |
| FEAT-103 | agent-artifact-persistency · `specs/agent-artifact-persistency.spec.md` (+ `proposals/sdd-brainstorm-artifact-persistence.md`) | approved | no idx; 14 completed tasks | Persists artifacts (charts, canvas tabs, infographics, DataFrames) in DynamoDB and S3, with REST CRUD, and replaces DocumentDB. | **Reusable**: `ArtifactStore` (S3, always presigned). "Canvas tabs" are artifacts that already exist on the frontend. |
| FEAT-119 | navigator-dashboard-draft-publish-lifecycle · `specs/navigator-dashboard-draft-publish-lifecycle.spec.md` | approved | no idx; 3 completed tasks | Two-phase lifecycle for `nav_create_dashboard`: a private draft (`is_system=False`), then publish (ownership released, becomes a system dashboard). | **Reusable pattern**: draft → publish for builder-authored reports, on the Navigator dashboard entity. |
| FEAT-223 | structured-artifact-contract · `specs/structured-artifact-contract.spec.md` | approved | 5/5; 2026-06-04 | Brings the structured_* family under one contract where deterministic data wins. | **Decision**: the deterministic layer owns the data and the LLM only refines. |
| FEAT-215 / FEAT-221 | structured-chart-output / structured-map-output | approved | 4/4; 7/7 | Library-agnostic chart contract (`AppChartConfig`, LayerChart) and the GeoJSON map output. | Contract used by the navigator-frontend-next widgets. |
| FEAT-468 / FEAT-475 | ui-server-backend / ui-agent-management | approved | 9/9; 7/7 | Embedded Svelte 5 Admin UI (`packages/ai-parrot-server/ui`) with agent CRUD. | Host where an in-repo builder UI could live (the bundled UI already has an A2UI Infographic renderer from FEAT-527). |
| FEAT-097 | printpdf-helper-agenttalk | approved | no idx; 2 completed | `POST /api/v1/utilities/print2pdf` converts HTML to PDF. | PDF export (alongside the A2UI `pdf` renderer). |
| FEAT-417 | commcenter-notify | approved | 11/11; 2026-08-06 | Bulk templated sends (email, Teams, SMS) over NotifyWorker and async-notify. | Delivery channel for scheduled reports. |
| FEAT-423 | purge-matplotlib-renderer-libs | approved | 6/6 | Steers the LLM away from matplotlib and toward A2UI and structured outputs. | **Constraint**: no raster charts. |

### 1.4 Report-domain features

| FEAT | Slug | Status | Tasks | Delivers | Meaning |
|---|---|---|---|---|---|
| FEAT-011 | compliancereport-toolkit (`proposals/compliancereport.md`) | approved | no idx; 13 completed | Prowler, Trivy and Checkov toolkits plus SOC2/HIPAA/PCI compliance reports (`SecurityFinding`). | A domain report generator, not a builder. Tool-specific output. |
| FEAT-162 | security-report-catalog | approved | 14/14; 2026-05-12 | Cross-session report catalog (Postgres metadata + S3 body) with fractal summaries. | **Pattern**: a report catalog with metadata, storage and summaries that could be reused as a "report library". |
| FEAT-184 | agenttool-s3-readreports | approved | 3/3 (completed_at null) | Generic S3 report reader: compare and diff reports. | Report diff/compare idea. |
| FEAT-420 | finance-reporter-tier2-narrative | approved | 12/12 | (see 1.1) Recipes plus an LLM narrative section. | **Pattern**: deterministic data paired with an LLM narrative block. |
| FEAT-591 | speech-report-models | approved | 6/6; 2026-09-23 | Pluggable TTS backends for `speech_report()` (verbatim or scripted podcast). | An audio export of a report. |
| FEAT-180 | github-repo-weekly-activity-report | approved | 7/7 | Weekly scheduled report to Telegram. | Scheduled-report pattern. |
| FEAT-024 | finance-investment-memo-persistency | approved | no idx; 14 completed | Persists the InvestmentMemo artifact. | Peripheral. |
| — | `proposals/nav-7622-sms-analysis-report.brainstorm.md` | brainstorm | — | SMS analysis report. | Peripheral. |

### 1.5 Form designer / formbuilder (patterns for a "designer" product)

All of these are approved and fully implemented unless noted. The lines below give FEAT, slug, tasks, and what each offers a builder.

- **FEAT-076** form-abstraction-layer (16/16): `FormSchema` (Pydantic) is separated from `StyleSchema` (presentation), with JSON Schema export and pluggable renderers. → *Precedent for splitting the definition from its presentation and renderers.*
- **FEAT-079** formdesigner-package (8/8) and **FEAT-080** package-fixes (6/6): the separate `parrot-formdesigner` distribution with registry, storage, handlers and renderers. → *Precedent for shipping a "designer" as its own package.*
- **FEAT-078** formbuilder-database (4/4): imports form definitions from Postgres (`networkninja.forms`) into `FormSchema`.
- **FEAT-086** form-designer-edition (9/9) and **FEAT-169** formdesigner-edition-parts (3/3): an Edit API, then editing through toolkit tools (LLM-driven partial edits). → *Precedent for edit operations on a persisted definition, which a report builder lacks.*
- **FEAT-388** deterministic-creationformtool (4/4): structured input bypasses the LLM. → *Precedent: deterministic creation whenever the input is already structured.*
- **FEAT-457** formbuilder-formschema-persistency (15/15): each form chooses its own persistence target. **FEAT-459** formbuilder-custom-code (16/16): custom event code beyond the decorator registry. **FEAT-456** formbuilder-fieldtype-cardinality (7/7): Many2one, Many2many and One2many relational fields.
- **FEAT-433** form-version-history-repair (6/6): version history. **FEAT-389** form-uid-stable-identity (12/12) and **FEAT-393** field-uid (15/15): stable identity for definitions and elements. → *Builder needs: stable element ids and history (recipes have neither: overwrite + `updated_at` only).*
- **FEAT-183** formregistry-multi-tenancy (8/8), **FEAT-421** forms-tenant-in-url (10/10), **FEAT-241** public-forms (7/7), **FEAT-166** multi-origin (6/6), **FEAT-234** conditional-sections (10/10; completed_at null), **FEAT-188** lifecycle-events (9/9), **FEAT-186** partial-saves (6/6), **FEAT-551** msteams renderer (7/7), **FEAT-544** A2UI form renderer (see 1.2).
- Data hygiene: FEAT-183 is used twice (formregistry-multi-tenancy and formdesigner-clone-form). FEAT-224 is used both by formdesigner-audio-renderer and by the FEAT-224 artifact mirror referenced in the structured specs.

---

## 2. In-depth: `proposals/infographic-builder.brainstorm.md` (→ FEAT-324)

- **Problem.** The daily budget-variance infographic (`sdd/artifacts/daily_report.py`, `executive_summary.py`, `budget_variance_dashboard_Template.html`) needs a persisted, replayable recipe: datasets → domain transforms → fixed layout, regenerated daily without an LLM.
- **Options.**
  - **A**: a recipe layer over A2UI (transformer registry, recipe store, runner).
  - B: extend the FEAT-197 `InfographicTemplate` system.
  - C: a declarative transform DSL.
  - D: recipes as learned Skills, replayed by the LLM.
- **Recommendation: Option A.** It is the only option that meets all 7 user decisions:
  1. Deterministic, LLM-free replay (rules out D).
  2. Registered Python transformers, not a DSL (rules out C).
  3. Per-user file and DB persistence (rules out retrofitting B's registry).
  4. Native FEAT-273 alignment.
  5. Dual authorship: an LLM "freeze" from a session plus hand-written YAML/JSON.
  6. Three triggers sharing one runner: chat tool, REST, and scheduler.
  7. Fail fast on schema drift.

  Option D stays as a possible complement: an LLM skill that helps author recipes.
- **All 7 open questions were resolved** (owner: Jesús):
  1. Vendor Chart.js v4 alongside ECharts. The v1 behaviours are day tabs, metric toggle and column sort in vanilla JS driven by the embedded dataModel.
  2. Versioning is overwrite + `updated_at` + `schema_version`; history is a follow-up.
  3. Parameters use plain `{param}` substitution plus fixed resolvers (`current_month`, `previous_month`, `today`, `yesterday`, `first_of_month`). No expression language.
  4. PBAC: chat and REST run as the invoker. Scheduled runs use an explicit principal stored in the schedule config, and permissions are never elevated.
  5. The DB store lives in core (SkillRegistry precedent).
  6. Scheduling reuses the existing `AgentSchedulerManager` (APScheduler) and `SchedulerJobsHandler`. No new scheduler.
  7. LLM "repair" on drift is a fast-follow.
- **Spec non-goals (FEAT-324).**
  - LLM repair.
  - Version history.
  - A DSL or stored code.
  - A new scheduler.
  - Server-push interactivity.
  - Extending the legacy templates.
- Related template brainstorms:
  - `infographictoolkit.proposal.md` recommends **B**: toolkit + `return_direct` + OutputMode wrapper + signed frozen artifacts. Two items remain open there: the single-turn retry on slot mismatch, and the renderer location.
  - `multi-tab-infographic.brainstorm.md` recommends **A**: recursive `TabViewBlock` in the block model, plus a two-step LLM pre-pass that picks the template.
  - `a2ui-rich-visualizations.brainstorm.md` (accepted) recommends Option D, a `viz-core` grammar catalog with a tool-only `parrot_vendor` hint. Its open questions:
    - the catalog-id domain;
    - whether `Timeline` moves to viz-core;
    - the fate of the Parrot `Chart`/`KPICard`;
    - SSE live interactive-html;
    - animation defaults;
    - the graph node threshold;
    - `describe_flow_node` scope.

---

## 3. Docs relevant to a report builder

| Doc | Purpose (1 line) |
|---|---|
| `docs/outputs/infographic-recipes.md` (710L) | FEAT-324 recipe model, transformers, stores, runner, triggers: the main "report definition" reference. |
| `docs/outputs/a2ui-v1.md` (540L) | The A2UI v1.0 wire, catalogs, validation and migration (FEAT-470). |
| `docs/outputs/a2ui-agent-functions.md` | The RPC leg: callAgentFunction, refresh and drill-down (FEAT-469). |
| `docs/outputs/a2ui-linked-surfaces.md` | Data-source descriptors and the transform DSL for live surfaces (FEAT-598). |
| `docs/frontend/agentdashboard-a2ui-reference.md` (1101L) | Contract for navigator-frontend-next AgentDashboard rendering A2UI dashboards, infographics and widgets. |
| `docs/frontend/structured-artifacts-frontend-guide.md` | Frontend guide for STRUCTURED_TABLE/CHART/MAP (FEAT-223). |
| `docs/api/infographic_render.md` | Deterministic render endpoint (FEAT-327). |
| `docs/infographic_handler_api.md` | InfographicTalk plus template and theme discovery API (FEAT-095). |
| `docs/interactive_artifacts_api.md` | Interactive HTML artifacts frontend API (PR #962). |
| `docs/toolkits/infographic_toolkit.md` / `infographic_authoring.md` | InfographicToolkit (FEAT-197) and the authoring mixin with SectionDescriptor (FEAT-326). |
| `docs/operations/infographic_csp_and_signed_urls.md` | CSP plus HMAC-signed artifact URL operations. |
| `docs/design-system.md` | Backend HTML DesignSystem, theme × layout (FEAT-493). |
| `docs/migration/feat-273-a2ui-deprecations.md`, `feat-473-structured-a2ui.md`, `feat-223-structured-artifact-contract.md` | Migration guides from legacy output modes to A2UI. |
| `docs/admin-ui.md` | Bundled Svelte Admin UI (FEAT-468), a possible builder host. |
| `docs/voice/speech-report-tts-backends.md` | speech_report TTS export. |
| `docs/outputs.md` | Legacy Smart OutputFormatter (pre-A2UI). |
| `docs/postman/a2ui-agentdashboard.postman_collection.json` | Postman collection for the A2UI dashboard endpoints. |

---

## 4. Decisions already made / constraints

1. **No executable code in report definitions.** Recipes are data. Transforms are registered Python transformers referenced by name. A DSL and stored code were rejected (`specs/infographic-builder.spec.md` G1, non-goals). Linked surfaces allow only a 10-operation declarative DSL, plus `transform.ref` to catalogued, signed modules (`specs/a2ui-linked-surfaces.spec.md` G7). FEAT-428's `PythonCodeStep` contradicts this and was never built.
2. **A2UI v1.0 is the wire.** Everything must validate against the vendored v1.0 schemas and the basic, parrot and viz-core catalogs. Presentation semantics go in `metadata.extensions.parrot_*`. `CreateSurface` is `extra="forbid"` (`specs/a2ui-v1-dialect.spec.md` G1–G4; `specs/html-renderer-design-system.spec.md` non-goals).
3. **Deterministic replay, no LLM in refresh** (FEAT-324 G3, FEAT-327, FEAT-469 drill-down, FEAT-492 refresh).
4. **Fail-fast on schema drift**, with a structured `RecipeRunError` (FEAT-324 G4; FEAT-326 descriptor validation).
5. **Origin gating.** Only TOOL-origin builders may emit linked data-source descriptors. LLM-origin envelopes are allowlisted and action-gated (`a2ui-linked-surfaces` G5; `a2ui-v1-dialect` G7).
6. **Permissions.** Chat and REST run as the invoker. Scheduled runs use an explicit stored principal. A share token grants read + refresh under the owner's context. The tenant never comes from a request body. Visibility is private, tenant or groups (FEAT-324 G8, FEAT-492 G5, FEAT-535).
7. **Self-contained HTML.** No CDN, no Tailwind build, system fonts, vendored Chart.js and ECharts. Interactivity is baked client-side (FEAT-324 G7, FEAT-493 non-goals).
8. **Dual-emit is permanent.** HTML is a sibling of A2UI, not deprecated (FEAT-527 G1). v1-html and v2-a2ui coexist through a discriminator, with no forced migration (FEAT-430 §3.3).
9. **Reuse, don't rebuild:** the scheduler (`AgentSchedulerManager`), notifications (`NotificationMixin`, `build_teams_card`, `deliver_artifact`), storage (`ArtifactStore` S3 presigned plus HMAC signed URLs) and deep links (FEAT-324, FEAT-430 D1–D4).
10. **Delivery is card + URL only.** No attachments, and `public=True` (the world-readable STATIC_DIR) is forbidden for dashboards. The link targets `/share/dashboard/<id>` (singular, server-backed), not `/share/dashboards/<snapshotId>` (FEAT-430 §2.4, §3.5).
11. **No inline template HTML** in render requests; templates are pre-registered only (FEAT-327 G-5).
12. **Tier 2 (recipes) is the blessed authoring path.** Tier-1 data-splice is legacy (FEAT-420, FEAT-491 non-goals).
13. **Recipe versioning** is overwrite + `updated_at` + `schema_version`. Surfaces refresh in place, with no history (FEAT-324 G5, FEAT-492 non-goals).
14. **Import rule.** `parrot.outputs.a2ui` never imports agents, DatasetManager or LLM clients. Runners live outside the core package (FEAT-273 G8).
15. **Viz vocabulary.** viz-core is a separate catalog id. The Parrot `Chart`/`KPICard` remain for recipes and navigator-frontend-next, and renderers dispatch on (catalogId, name) (`proposals/a2ui-rich-visualizations.brainstorm.md` rev 2).

## 5. Not yet done / open

1. **No Canvas/Report Builder spec.** SPEC-B ("Artifact & Canvas Builder") exists only in `state/FEAT-430/source.md` §5:
   - two permission tiers;
   - composition from catalog components;
   - a knowledge-transfer deliverable;
   - A2UI → sendable rendering for the share target.

   The FEAT-430 proposal is in `review` and covers SPEC-A only. It says SPEC-B needs its own proposal.
2. **FEAT-430 open questions Q5–Q10** (`proposals/dashboard-scheduled-notifications-canvas.proposal.md` §5):
   - Q5: where the iframe widget and its artifact URL are persisted on the backend;
   - Q6: how to extract the ETL generation step;
   - Q7: which email entry point to use;
   - Q8: signature TTL and the re-request flow;
   - Q9: a FEAT-ID for navigator-svelte;
   - Q10: navigator-api has no SDD home.
3. **No component-editing API for surfaces.** FEAT-492 explicitly excludes editing components. Recipes can be saved or overwritten but have no element-level edit operations, stable element ids or history. FormDesigner has all three (FEAT-086/169, 389/393, 433).
4. **No layout container vocabulary in A2UI.** There is no `Dashboard`, Tabs, Page or Grid component in `catalog/parrot/` (current components: chart, datatable, filterbar, form, htmldocument, infocard, infographic, kpicard, map, report, timeline). Tabs exist only in the legacy block model (FEAT-102). FEAT-428's `Dashboard` component remains unbuilt (spec draft, 0 tasks).
5. **No template library on recipes.** The 10 built-in `InfographicTemplate`s were not re-expressed as recipes or `LayoutSpec`s (FEAT-527 non-goal, deferred). The parametrized dashboard templates proposed in FEAT-428 G8 are unbuilt.
6. **FEAT-301's 4 new blocks** (chain, steps, code, card_grid) lower to a generic Card, with no dedicated A2UI components.
7. **viz-core follow-ups have no spec yet:** charts on the viz-core grammar (Stat.gauge, Treemap, polar), and the live workflow surface. Several open questions remain in `a2ui-rich-visualizations.brainstorm.md`.
8. **Linked surfaces still have defects.** Open major ledger items for FEAT-598: `request.limit` is discarded, an empty snapshot breaks KPI scalar bindings, and the slug authorization adapter does not fail closed. FEAT-611 has TASK-3840 done-with-issues, a manual S4 checklist, and noted TS↔Python drift. `QSPrincipal` on the agent-tool lane is a follow-up.
9. **FEAT-324 fast-follows:** LLM-assisted repair on schema drift, and recipe version history.
10. **Spec non-goals deferred to follow-ups:** an HTTP handler for `refresh_dashboard` (FEAT-428), and an MCP tool transport for the render endpoint (FEAT-327).
11. **Frontend scope lives elsewhere.** navigator-frontend-next and navigator-svelte run their own flows. The bundled UI renders only the display-only Infographic subtree (FEAT-527 G4).
12. **Two infographictoolkit questions were never closed:** the single-turn retry on slot mismatch, and the renderer location (`proposals/infographictoolkit.proposal.md`).
