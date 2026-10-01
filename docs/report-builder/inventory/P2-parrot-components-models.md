# P2 — ai-parrot (Python) UI components, models, renderers, persistence — inventory for a REPORT BUILDER

Repo: `/home/jelitox/repos/trocglobal/ai-parrot` (branch `dev`). Read-only survey. Paths are relative to `packages/`.
Abbreviations: `A2UI` = `ai-parrot/src/parrot/outputs/a2ui`, `VIZ` = `ai-parrot-visualizations/src/parrot/outputs`, `SRV` = `ai-parrot-server/src/parrot`, `TOOLS` = `ai-parrot-tools/src/parrot_tools`, `FD` = `parrot-formdesigner/src/parrot_formdesigner`.

---

## 1. A2UI catalogs, wire model, validation, builders

### 1.1 Catalog registry (core)
| Item | Location | Notes |
|---|---|---|
| Registry `_CATALOG: dict[(catalog_id,name)] -> RegisteredComponent` | `A2UI/catalog/__init__.py:101` | keyed by (catalog, name) since FEAT-529; `register_component` :114, `unregister_component` :196, `get_component` :209 (ambiguity error if name in >1 catalog), `list_components(catalog_id)` :253, `register_function`/`get_function` :267/:277, `catalog_instructions(catalog_ids)` :314 (aggregates per-component LLM instructions), `resolve_catalog` :345 |
| `ComponentDefinition` | `A2UI/catalog/base.py:234` | `name, catalog_id, schema, instructions, requires_actions, is_primitive, allowed_parents, allowed_children, tool_only` |
| `FunctionDefinition` | `A2UI/catalog/base.py:269` | `allowed_callers` rendererOnly/agentOnly/rendererOrAgent, `requires_user_activation` |
| `BasicNode` (lowered, nested tree) / `TabSpec` / `to_components()` flattener | `A2UI/catalog/base.py:111/155/174` | `lower()` output; flattened to wire list with ids `blk-n` |
| Contract: non-primitive must implement `lower()` | `A2UI/catalog/__init__.py:160-167` (`ComponentContractError`) | |
| `ProducerOrigin` {TOOL, LLM} | `A2UI/catalog/base.py:99` | drives gates |
| Catalog-definition export (A2UI `catalog_definition.json`, agent capabilities) | `A2UI/catalog/export.py:195,215,299` | `export_catalog_definition`, `write_catalog_definition` |
| Catalog ids | `DEFAULT_CATALOG_ID="https://parrot.dev/catalogs/v1"` (`base.py:53`); `BASIC_CATALOG_ID="https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"` (`basic/__init__.py:44`); `VIZ_CORE_CATALOG_ID="https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json"` (`viz_core/__init__.py`) | |

### 1.2 Every registered component
Parrot catalog (`https://parrot.dev/catalogs/v1`) — registered via `catalog/parrot/__init__.py:13-24` (Form intentionally NOT registered).

| Component | File:line | Key props (schema) | Linkable to data (binding) | Lowering → Basic | Flags |
|---|---|---|---|---|---|
| `Chart` | `catalog/parrot/chart.py:54` | schema **derived** from `StructuredChartConfig` (`models/outputs.py:332`) via `_derive.derive_schema`; req `type,x,y`; `type` bar/line/area/scatter/pie/donut/radar/horizontalBar/gauge/funnel/waterfall/heatmap/treemap; `seriesTypes`,`seriesAxes`,`stacked`,`splitSeries`,`trendline`,`showLegend`,`xAxisMode`,`palette`,`colorBySign`,`xAxisLabel/yAxisLabel(s)`,`layout` full/half,`mapName`,`title`,`description`,`dataVariable` | YES `data:{"path"}` (inline rows forbidden for LLM) | `Card{Column}` data summary (title/type/axis/series text) | display-only |
| `DataTable` | `catalog/parrot/datatable.py:51` | derived from `StructuredTableConfig` (`models/outputs.py:589`): `columns[{name,type,title,format}]` (req), `totalRows`,`truncated`,`explanation`, `style` default/striped/bordered/compact/comparison | YES `data` | `Card` + row `ChildTemplate` (one Text per column, relative path) expanded by bake | |
| `KPICard` | `catalog/parrot/kpicard.py:118` | `label,value,unit,delta,trend(up/down/flat),icon,color,comparisonPeriod,higherIsBetter(true/false/null),format(percent/currency/number)` | `value`/`delta` may be bindings; linked builder maps `value` to aggregate column | `Card{Column}` of Text | |
| `Map` | `catalog/parrot/map.py:71` | derived from `StructuredMapConfig` (`models/outputs.py:793`): `layers[MapLayer]` (req), `viewport`,`query`,`baseLayer`,`title`,`description` | YES `data`/`datasets`, per-layer `layers[i].data` | `Card{Column}` title + layer summary | |
| `FilterBar` | `catalog/parrot/filterbar.py:127` | `title`, `filters[{column,label,options[{label,value}]}]` | filters apply to data-model column; validated against linked source params (`_validate_filter_params` `catalog/__init__.py:521`) | `Row` of `ChoicePicker` tagged `parrot_role:"filter"` | |
| `Infographic` | `catalog/parrot/infographic.py:203` | `title`(req),`subtitle`,`theme`,`sections[{heading,text,components[{component,properties}]}]`(req) | via nested components | multiple sections → `Tabs` (one per section); single → `Column`; nested children lowered via registry, primitives passthrough; `properties.layout="half"` pairs side-by-side | `allowed_parents=[root,Column]` |
| `Report` | `catalog/parrot/report.py:110` | `title`(req),`reportMetadata`,`summary`,`sections[{heading,text,components[]}]`(req) | via nested components | `Card` → sections as `Tabs` (>1) or `Column` | `allowed_parents=[root,Column]` |
| `Timeline` | `catalog/parrot/timeline.py:43` | `title`, `events[{timestamp,title(req),description}]` | no | `Column` | |
| `InfoCard` | `catalog/parrot/infocard.py:37` | `title`(req),`subtitle`,`body`,`image`,`badge`,`footer` | `image` may be binding | `Card{Column}` | renamed from pre-v1 `Card` |
| `HtmlDocument` | `catalog/parrot/htmldocument.py:60` | `title`(req), `html` XOR `srcUrl`, `theme` (no-op) | no | title Text + placeholder (raw HTML never lowered) | **tool_only=True**, `allowed_parents=[root,Column]` |
| (`Form` retired) | `catalog/parrot/form.py:119` `build_form()` | `FormField`/`FormSubmit` → composition helper over Basic inputs | — | — | not registered |

Basic Catalog (official A2UI v1.0, `is_primitive=True`, no lowering) — registered `basic/__init__.py:182-202`; classes in `basic/media.py`, `basic/layout.py`, `basic/inputs.py`; vendored spec `basic/spec/catalog.json`:
`Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Modal, Divider, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput` (18).
Functions (14, `basic/functions.py`, registered `basic/__init__.py:221-250`): `required, regex, length, numeric, email, formatString, formatNumber, formatCurrency, formatDate, pluralize, openUrl, and, or, not`.

viz-core catalog — `catalog/viz_core/__init__.py` (header instructions = 9 viz rules), `viz_core/graph.py:63`:
| Component | Props | Notes |
|---|---|---|
| `Graph` | derived from `GraphSpec` (`A2UI/graph/models.py:179`): `kind` flowchart/state/sequence/dag, `direction`, `nodes[{id,label,shape,state,icon,meta}]`, `edges[{from,to,label,kind,condition}]`, `accessibleDescription`, `data` binding, `action` ($ref common Action, TOOL only) | lowering via mermaid/layout (`graph/mermaid.py:206`, `graph/layout.py`); ONLY component registered in viz-core |
| `Chart`, `Series`, `Stat` | present in vendored `viz_core/spec/catalog.json` | **NOT registered in Python** (spec-only draft) |

### 1.3 Wire model (A2UI v1.0) — `A2UI/models.py`
| Model | Line | Fields |
|---|---|---|
| `DataBinding` / `FunctionCall` / `ChildTemplate` | 155/174/212 | `{path}`, `{call,args,catalogId}`, `{componentId,path}` |
| `Action`(event/functionCall), `CheckRule`, `AccessibilityAttributes`, `Extensions`, `ComponentMetadata` | 250/272/313/341/364 | `metadata.extensions.parrot_*` is the extension point (`parrot_theme`, `parrot_layout`, `parrot_role`, `parrot_optional`, `parrot_data_sources`) |
| `SurfaceMetadata = ComponentMetadata` | 378 | |
| `Component` | 400 | flat adjacency list: `id, component, catalogId, child, children, weight, accessibility, checks, action, metadata` + extra props top-level |
| Agent→renderer: `CreateSurface`(surfaceId, catalogId, sendDataModel, components, dataModel, metadata), `UpdateComponents`, `UpdateDataModel`(path,value), `DeleteSurface`, `CallRendererFunction`, `AgentFunctionResponse` | 446/473/490/509/521/575 | envelope `A2UIAgentMessage` :695 (`version: Literal["v1.0"]`) |
| Renderer→agent: `ActionMessage`, `CallAgentFunction`, `RendererFunctionResponse`, `ErrorMessage` | 585/619/636/648 | envelope `A2UIRendererMessage` :740 |

Serialization: `A2UI/serialization.py` — sole owner of `version`; `serialize` :104, `deserialize` :155 (legacy auto-normalized via `compat.py:201 normalize_legacy` + DeprecationWarning), `to_jsonl` :201, `iter_jsonl` :215. Legacy `$bind` dialect → `{"path"}` (`compat.py`).

### 1.4 Validation
`validate_envelope(envelope, origin, surface_catalog_id)` — `A2UI/catalog/__init__.py:689`. Aggregates all issues (`CatalogValidationError.issues`). Codes (`base.py:61-96`): `MISSING_ROOT, DUPLICATE_ID, DANGLING_CHILD, CATALOG_UNRESOLVED, UNKNOWN_COMPONENT, UNALLOWED_PARENT/CHILD, ACTION_NOT_ALLOWED_FOR_LLM, TOOL_ONLY_NOT_ALLOWED_FOR_LLM, INLINE_DATA_NOT_ALLOWED_FOR_LLM (Chart/DataTable/Map + Map layers), DATA_SOURCES_NOT_ALLOWED_FOR_LLM, DATA_SOURCE_INVALID, TRANSFORM_REF_UNKNOWN, FILTER_PARAM_UNKNOWN_SOURCE/UNDECLARED`. Linked-source structural validation `_validate_linked_sources` :580 (CreateSurface only). JSON-schema message validation `validate_message` :458. Note: component **prop schemas are not JSON-schema-validated** inside `validate_envelope` (only structure/registry/gates).

### 1.5 Builders / producers / emission
| Function | Location | Purpose |
|---|---|---|
| `build_surface(component, properties, surface_id, …, origin=LLM)` | `A2UI/builders.py:77` | single-component validated surface |
| `build_chart` / `build_kpicard` / `build_card` / `build_datatable` / `build_map` | `builders.py:128/149/169/191/215` | per-component helpers |
| `build_infographic(title, sections, subtitle, theme, …)` | `builders.py:247` | Infographic root |
| `build_html_document` | `builders.py:276` | TOOL-only HtmlDocument (html XOR srcUrl, 50 KB inline cap) |
| `build_graph` | `builders.py:328` | Graph |
| `build_linked_surface(components, sources, frames, surface_id, snapshot, max_snapshot_rows=500, catalog_id)` | `builders.py:513` | TOOL-origin linked surface; validates axes vs frames (`_validate_axes` :476), writes `dataModel[key]={"rows":…}`, stamps `snapshot_at/snapshot_truncated`, puts sources in `metadata.extensions.parrot_data_sources` (`_LINKED_SOURCES_KEY` :456) |
| (no `build_report`) | — | `Report` has no Python builder |
| Adapters: `chart_to_surface`/`table_to_surface`/`map_to_surface` | `A2UI/adapters/structured.py:176/207/264` | STRUCTURED_* output → surface (TOOL origin, inline rows allowed) |
| `infographic_response_to_envelope` | `A2UI/adapters/infographic.py:642` | `InfographicResponse` blocks → `Infographic` composite (mapping table at file top: hero_card→KPICard, chart→Chart, table→DataTable, timeline→Timeline, progress→KPICard×n, summary→text/InfoCard, bullet_list→List, checklist→List of CheckBox, accordion/tab_view→Tabs, divider→Divider, card_grid→Row of InfoCard, callout/quote→InfoCard, image→Image) |
| `flow_definition_to_graph` | `A2UI/adapters/flow.py:63` | AgentsFlow → Graph |
| LLM producer `generate_envelope` (validate-retry 3x, degrade to text) | `A2UI/producer.py:191` | **not called anywhere** outside module (grep) |
| `finalize_a2ui_response(response)` | `A2UI/emission.py:18` | OutputMode.A2UI bypasses formatter; wraps bare CreateSurface as `{"version":"v1.0","createSurface":…}`; called at `bots/base.py:1659`, `bots/data.py:1896,1976` |
| `attach_structured_artifact` | `A2UI/artifacts.py:108` | STRUCTURED_* → artifact entry (used by `bots/data.py`, `bots/database/agent.py`) |
| Bake: `bake_envelope` | `A2UI/baking.py:356` | resolves all `path`/`call`, expands ChildTemplates → static flat list |
| `persist_envelope(envelope, store, …)` | `baking.py:399` | saves source envelope to ArtifactStore (>200KB → S3 `definition_ref`) |
| `RenderedArtifact` / `DeepLink` | `A2UI/artifacts.py:54/36` | content XOR path; `surface`, `source_envelope_ref`, `deep_links`, `metadata.degraded` |
| `deliver_artifact` | `A2UI/delivery.py:86` | notification delivery of a RenderedArtifact |
| `DeepLinkService` / `ResumePayload` | `A2UI/deeplink.py:92/53` | degraded actions on static surfaces |
| Runtime: `A2UIRuntime` (dispatch of actions/function calls), `ToolManagerExecutor`, `ConversationMemorySurfaceStore`, `SurfaceState` | `A2UI/runtime/dispatch.py:76`, `runtime/adapters.py:44/145`, `runtime/models.py:139` | per-conversation surface state (in conversation memory), HTTP via `SRV/handlers/a2ui.py:85` (`/api/v1/agents/{agent_id}/a2ui[...]`) |

---

## 2. Linked data (FEAT-598) — `A2UI/linked/`

| Item | Location | Detail |
|---|---|---|
| `LinkedDataSource` | `linked/models.py:192` | `kind="query_slug"`, `slug`, `tenant`, `is_multiquery`, `multi_output`, `conditions` (derived payload), `request: SourceRequest`, `params: {name: ParamSpec}`, `locked[]`, `transform: TransformSpec`, `target` (JSON pointer), `snapshot_at`, `snapshot_truncated`, `refresh: RefreshPolicy`; `extra=forbid` |
| `SourceRequest` | `models.py` (~:29) | `placeholders, filter, fields, ordering, grouping, limit, offset` (QS grammar) |
| `ParamSpec` | `models.py` | `type, default, required, editable, accepts_keywords` |
| `RefreshPolicy` | `models.py` | `on_mount`/`manual`/`interval` (min 30 s) |
| `TransformSpec` | `models.py` | XOR `ops[]` / `ref: TransformRef{name "<id>@semver", integrity "sha384-…"}` |
| DSL ops | `models.py` + impl `linked/dsl.py:167-357` | `select, rename, filter(eq,ne,gt,ge,lt,le,in,contains), group_by(sum,avg,count,min,max), sort, limit, derive(+-*/ tree), pivot, join(inner/left, with sibling source), union`; `apply_transform` :144, `frame_to_records` :97 |
| Conditions | `linked/conditions.py:17 derive_conditions`, `:40 locked_values` | deterministic QS payload; locked values win |
| Executor | `linked/executor.py:180 execute_sources` | sibling-first order (`_execution_order` :97), per-source failure isolation, `QuerySlugSource` + `AuthorizingDataSource` (data-plane guard), `max_fetch_rows=5000`; error mapping `map_query_error` :71 |
| Service | `linked/service.py:67 LinkedSurfaceService` | fail-closed without guard; `validate_for_persistence` :109, `ensure_snapshot` :119, `refresh(envelope, params, owner_pctx)` :152 (per-source vs broadcast params, patches dataModel, never persists) |
| Manifest (transform.ref) | `linked/manifest.py` | `TransformManifest{version, entries{id:{file,integrity,deprecated}}, signature}` HMAC-SHA256 with env `PARROT_A2UI_MANIFEST_KEY`, file `STATIC_DIR/a2ui/transforms/manifest.json`; `resolve_ref` :101 |
| JSON-schema export + contract fixtures | `linked/schema.py`, `linked/contract/schema.json` (765 lines), fixtures `contract/fixtures/{dsl,conditions,envelopes,parity}` (e.g. `linked_epson_dashboard.json`) | cross-language (TS) parity contract |
| Builders using it | `build_linked_surface` (above); `TOOLS/querysource/toolkit.py:347 qs_build_linked_surface`, `:407 qs_build_linked_dashboard` | dashboard layout reserved ids `root,title,row_kpis,row_charts` (`toolkit.py:69`); widget = `DashboardWidget{key,slug,component(Chart|DataTable|KPICard),request,tenant,section(kpis/charts/table),refresh}` (`TOOLS/querysource/models.py:127`) |

---

## 3. Renderers

Core ABC/registry: `A2UI/renderers/__init__.py` — `RendererCapabilities{interactive, supports_actions, supports_updates, output(mime), supported_catalog_ids, supported_components}` :51; `AbstractA2UIRenderer.render(envelope, bake=True)` :78; `register_a2ui_renderer` :108; `get_a2ui_renderer(name)` :141 (lazy import of satellite, error names pip extra `ai-parrot-visualizations[a2ui]` / `[a2ui-pdf]`). Degradation: `renderers/degrade.py` (visible Text placeholder + `metadata.degraded`).

| Renderer name | File:line | Output | Components natively handled | Notes |
|---|---|---|---|---|
| `interactive-html` | `VIZ/a2ui_renderers/interactive_html.py:867` | `text/html` single self-contained doc (vendored Chart.js v4 + vanilla JS; dataModel embedded as `<script id="report-data">`) | all 18 primitives + `Chart, DataTable, Infographic, Map, Graph`; intercepts `{Chart, DataTable, Infographic, Map, HtmlDocument}` (:136) before lowering; FilterBar client-side filtering (:683, :1179); KPICard/Chart grouping grids (:1605); HtmlDocument sandboxed iframe (:1650) | theme/layout via `DesignSystem.resolve` (:954); `Report`, `KPICard`, `Timeline`, `InfoCard` go through lowering (Report NOT intercepted) |
| `ssr_html` | `VIZ/a2ui_renderers/ssr_html.py:149` | `text/html` static, no JS | 18 primitives + `Graph` (inline SVG `_graph_svg.py`); composites lowered; FilterBar degraded to static summary (:626); HtmlDocument degraded (:533) | |
| `pdf` | `VIZ/a2ui_renderers/pdf.py:86` | `application/pdf` (weasyprint) | SSR set minus Video/AudioPlayer; charts pre-rendered as static SVG | layout `print`; for email attachment |
| `echarts` | `VIZ/a2ui_renderers/echarts.py:96` | `application/json` ECharts option (+ optional HTML wrap with vendored echarts.min.js) | `Chart, Graph` | |
| `folium_map` | `VIZ/a2ui_renderers/folium_map.py:262` | `text/html` folium | `Map` (per-layer FeatureGroups) | offline vendored assets `_map_vendor.py` |
| `adaptive_cards` | `VIZ/a2ui_renderers/adaptive_cards.py:212` | `application/vnd.microsoft.card.adaptive` | Text, Image, Row, Column, Card, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput, Button (real inputs/actions) | `supports_actions=True` |

Export formats available: HTML (interactive/static), PDF, ECharts JSON, Adaptive Card JSON, folium HTML. **No PNG/image export** in A2UI renderers (grep: no png). Legacy `ChartTool generate_chart` (`TOOLS/chart.py:164`, altair/plotly images) is separate.

Design system: `VIZ/formats/assets/design_system/__init__.py:91 DesignSystem` — `LAYOUTS={report, analytics, print}`, default theme `light`, resolves `metadata.extensions.parrot_theme/parrot_layout` (or Infographic `theme` prop), themes from `ThemeRegistry`; CSS assets `base.css, components.css, editorial.css, layout-*.css, print-media.css, tailwind.generated.css`.

Legacy `OutputMode` formatters (`register_renderer(OutputMode.X)`): core `ai-parrot/src/parrot/outputs/formats/{json,text,yaml,html,table}.py`; VIZ `formats/{jinja2,infographic,infographic_html,structured_table,structured_chart,structured_map,application,card,map,markdown,echarts,template_report}.py` (+ `slack`, `whatsapp`, generators panel/streamlit/terminal).

---

## 4. Infographic system

| Item | Location | Detail |
|---|---|---|
| `BlockType` (19) | `ai-parrot/src/parrot/models/infographic.py:79` | title, hero_card, summary, chart, bullet_list, table, image, quote, callout, divider, timeline, progress, accordion, checklist, tab_view, chain, steps, code, card_grid |
| Block models | `models/infographic.py:316-1022` | `TitleBlock`:316, `HeroCardBlock`:327, `SummaryBlock`:480, `ChartBlock`:511, `BulletListBlock`:727, `TableBlock`:749, `ImageBlock`:823, `QuoteBlock`:834, `CalloutBlock`:843, `DividerBlock`:868, `TimelineBlock`:893, `ProgressBlock`:916, `AccordionBlock`:924, `ChecklistBlock`:933, `TabViewBlock`:944 (`tabs[TabPane{id,label,icon,blocks}]`, style pills/underline/boxed), `ChainBlock`:953, `StepsBlock`:962, `CodeBlock`:971, `CardGridBlock`:981 |
| `InfographicResponse` (root) | `models/infographic.py:1044` | `template, theme, blocks[discriminated by type], metadata, document_meta` (flat block list, no sections/layout grid) |
| `ThemeConfig` / `ThemeRegistry` / `theme_registry` | `models/infographic.py:1307/1518/1580` | color tokens (primary*, accent_*, neutral_*, body_bg, font_family…); built-ins `light, dark, corporate, midnight, petrol`; **in-memory** dict |
| `InfographicTemplate` / `BlockSpec` | `models/infographic_templates.py:47/21` | `name, description, block_specs[{block_type, required, description, min_items, max_items, constraints}], default_theme, js_bundles`; `to_prompt_instruction()` |
| Built-in templates | `infographic_templates.py:168-482` | `basic, executive, dashboard, comparison, timeline, minimal, financial_variance, multi_tab, crew_report` |
| `InfographicTemplateRegistry` / `infographic_registry` | `infographic_templates.py:512/587` | `register/get/list_templates(_detailed)` — **in-memory only, no persistence, no versioning** |
| Register helpers | `ai-parrot/src/parrot/helpers/infographics.py:50 register_template`, `:115 register_theme` | used by REST `POST /api/v1/agents/infographic/{templates,themes}` (`SRV/handlers/infographic.py:717/767`) — process-local |
| Multi-tab | `TEMPLATE_MULTI_TAB` (:452, TITLE + TAB_VIEW 3-7) → adapter maps to `Tabs`; template detection `bots/abstract.py:4626 _detect_infographic_template`, `get_infographic` :4664, `enhance_infographic` :4773 | |
| A2UI Report root | `Report` component (above); UI `SRV/ui/src/lib/components/agents/canvas/a2ui/a2ui-kind.ts:19` treats `Infographic`/`Report` roots as infographic-like | no Python producer emits `Report` |
| `InfographicToolkit` | `ai-parrot/src/parrot/tools/infographic_toolkit.py:197` | tools (prefix `infographic_`): `render` :430, `render_template` :555 (trusted Jinja HTML), `render_data_template` :666 (data-splice), `list_templates` :1141, `get_template_contract` :1155, `validate_blocks` :1193, `build_block` :1226 (non-terminal); recipe tools (only with recipe_store) `save_recipe` :1332, `list_recipes` :1430, `run_recipe` :1446, `get_recipe_contract` :1486. `add_template(name, source)` :358 (in-memory Jinja). Dual-emit HTML artifact + A2UI envelope (`_build_a2ui_envelope` :871, `_build_html_document_envelope` :924, `_build_a2ui_envelope_from_layout` :976). Persists `Artifact(type=INFOGRAPHIC)` (`_persist` :2003, `_persist_template` :1093) |
| Section descriptors | `tools/infographic_sections.py` | `SectionSpec`:42 (`name,target,datasets,columns,shape,hint`), `SectionDescriptor`:80 (`template, mode jinja/data-splice, splice_marker_id, sections, params, dataset_sql, layout: LayoutSpec, narrative`), `ProvenanceDescriptor`:152, `GapReport`:196 |
| `InfographicAuthoringMixin` | `ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:58` | `generate_infographic` :122 (tier-1 one-shot + provenance), `publish_recipe` :283 (tier-2 → InfographicRecipe), `publish_surface(kind,title,envelope,recipe_*,overwrite)` :442 → `PgUISurfaceStore` via `LinkedSurfaceService` |
| Recipes models | `A2UI/recipes/models.py` | `InfographicRecipe`:235 (`schema_version=2, name, title, description, owner, params[RecipeParam], data_sources[DataSourceSpec{dataset,alias,sql,conditions}], transforms[TransformStep{transformer,inputs,params,output_key}], layout: LayoutSpec (single root component, top-level props + path bindings), render: RenderSpec{profile="interactive-html", theme, layout, delivery}, schedule: ScheduleSpec{principal,tenant_id,roles}, updated_at, section_descriptor, narrative: NarrativeSpec{skill,facts_key,output_key}`); `TransformerManifest`:313; `RecipeRunError`:331 |
| Params | `A2UI/recipes/params.py` | date resolvers, `{placeholder}` substitution |
| Transformers | `A2UI/recipes/transformers.py:61 TransformerRegistry`; built-ins `recipes/library.py`: `day_totals, division_breakdown, variance_analysis, top_movers, narrative_facts, groupby_aggregate, pivot, latest_vs_baseline` | in-process Python registry |
| Migration | `A2UI/recipes/migrate.py` (`migrate_layout`, `migrate_store`) | schema v1→v2 |
| Recipe stores | `A2UI/recipes/store.py`: `AbstractRecipeStore`:175 (save/get/list/delete by (name, owner)), `FileRecipeStore`:230 (JSON files), `DBRecipeStore`:304 (Redis); `SRV/handlers/models/recipes.py:128 PgRecipeStore` | see §5 |
| Runner | `ai-parrot/src/parrot/tools/infographic_recipes/runner.py` (`RecipeRunner`; renders via `get_a2ui_renderer(recipe.render.profile)` :652; delivery :687), `freeze.py` (`freeze_session_envelope`), `loader.py`, `narrator.py`, `figure_guard.py` | deterministic replay, no LLM |
| Interactive (free-form HTML) | `ai-parrot/src/parrot/tools/interactive_toolkit.py:74 InteractiveToolkit` — `interactive_render` :236, `list_templates` :152, `list_libraries` :171, `get_scaffold` :189; scaffolds `tools/interactive/catalog/templates/{dashboard,diagram,grid,report,wizard}.html + .meta.yaml` (name, description, default_theme, allowed_bundles); `InteractiveCatalogRegistry` `tools/interactive/catalog_registry.py:168` | Artifact type INTERACTIVE; LLM-authored HTML under SRI/CSP |
| Dead/legacy | `ai-parrot/src/parrot/outputs/templates/__init__.py` `ReportTemplate`/`TemplateSection`/`TemplateRegistry` (Jinja report templates with fillable sections) | **no usages** outside the module |

---

## 5. Persistence models

| Store / table | Location | Columns / shape | Notes |
|---|---|---|---|
| `navigator.ui_surfaces` (`PgUISurfaceStore`) | `SRV/handlers/models/ui_surfaces.py:106-153 DDL`, class :457 | `surface_id UUID PK, kind VARCHAR(32) (UISurfaceKind: dashboard/infographic/widget :42), title, envelope JSONB, catalog_id, agent_id, user_id, session_id, recipe_name, recipe_owner, recipe_params JSONB, tenant VARCHAR(63), visibility (private/tenant/groups :50), allowed_groups JSONB, created_at, updated_at`; idx (user_id), (user_id,kind), (tenant,visibility) | methods `save(overwrite)`:503, `get`:553, `list(user,kind)`:564, `list_shared_with`:575, `list_visible(scope,kind)`:583, `update_visibility`:624, `update_envelope` (optimistic `WHERE updated_at=$4` :258) :656, `delete`:686, shares :697-768. **No version history** (update overwrites envelope). `UISurfaceRecord.refreshable` :85 |
| `navigator.ui_surface_shares` | same file :132 | `token PK, surface_id FK cascade, permissions 'read+refresh', expires_at, revoked, claimed_by, claimed_at, created_at` | |
| REST `/api/v1/ui/surfaces[/{id}[/refresh|/share[/{token}]]]` | `SRV/handlers/ui_surfaces.py:315 UISurfacesHandler` (GET list/one with JSON/HTML negotiation `SurfaceNegotiationService` :226-275, POST pin/save :508, refresh :617 / linked :688, PATCH visibility :738, share :787, DELETE :821/830); routes `SRV/manager/manager.py:2339-2343` | HTML negotiation renders server-side |
| `{schema}.infographic_recipes` (`PgRecipeStore`) | `SRV/handlers/models/recipes.py:50-64`, class :128 | `name, owner, schema_version, title, description, recipe JSONB, created_at, updated_at, PK(name, owner)` | REST `/api/v1/infographic_recipes[/{name}[/run]]` (`SRV/handlers/infographic_recipes.py:155 RecipeHandler`, GET/PUT/DELETE/POST); upsert overwrites — **no version rows** |
| Scheduler → recipe | `SRV/handlers/infographic_recipes.py:323 RunInfographicRecipeCallback(BaseSchedulerCallback)` | runs a recipe from scheduler with `recipe.schedule.principal` |
| `navigator.agents_scheduler` (`AgentSchedule`) | `SRV/scheduler/models.py:7` | `schedule_id, agent_id, agent_name, prompt, method_name, schedule_type, schedule_config, enabled, …, send_result, callbacks` — no direct surface/recipe FK |
| Artifacts (`ArtifactStore`) | `ai-parrot/src/parrot/storage/artifacts.py:27` (DynamoDB/`ConversationBackend` + S3 overflow), model `storage/models.py:275 Artifact{artifact_id, artifact_type, title, created_at, updated_at, source_turn_id, created_by, definition, definition_ref}`; `ArtifactType` :244 = chart, map, table, canvas, infographic, interactive, dataframe, export | thread/session-scoped; REST `/api/v1/threads/{session_id}/artifacts[...]` + public signed HTML `/api/v1/artifacts/public/{signature}/{id}.html` (`SRV/handlers/artifacts.py`); protocol `interfaces/artifact_store.py:152` |
| Dashboards (DocumentDB/Mongo) | `SRV/handlers/dashboard_handler.py:74/341`; collections `dashboards` {dashboard_id, title, module_id, user_id, attributes}, `dashboard_tabs` {tab_id, dashboard_id, title, icon, index, layout_mode "grid", grid_mode "flexible", template, pane_size, closable, component, **widgets[] (opaque)**, module_id, user_id}; routes `manager.py:2561-2564` (behind `ENABLE_DASHBOARDS`) | not linked to A2UI envelopes/ui_surfaces |
| A2UI runtime state | `A2UI/runtime/adapters.py:145 ConversationMemorySurfaceStore` | in conversation history (ephemeral) |
| Recipe store alternates | `FileRecipeStore`, `DBRecipeStore`(Redis) | |
| Navigator dashboard tools | `TOOLS/navigator/schemas.py:209-312` (`DashboardCreateInput/UpdateInput/CloneDashboardInput/PublishDashboardInput`) | Navigator (external) dashboards, not A2UI |

No tables found for: surface templates, component library/presets, theme persistence, infographic template persistence, per-widget rows.

---

## 6. Agent tools that create/update components or templates

| Tool name | Module | Produces |
|---|---|---|
| `publish_surface` | `TOOLS/ui_surfaces.py:65` (args :35) → delegates to `InfographicAuthoringMixin.publish_surface` | row in `ui_surfaces` |
| `qs_build_linked_surface` | `TOOLS/querysource/toolkit.py:347` | linked CreateSurface (single component) |
| `qs_build_linked_dashboard` | `TOOLS/querysource/toolkit.py:407` | linked dashboard surface (KPI/Chart/Table rows) |
| `qs_list_components` | `toolkit.py:584` | component docs (`ComponentDoc`) for authoring |
| `qs_validate_pipeline`, `qs_run_multiquery`, `qs_save_multiquery`, `qs_describe_slug`, `qs_execute_slug`, `qs_list_slugs`, `qs_get_dialect_reference` | `toolkit.py:640/678/722/218/249/166/160` | data side |
| `infographic_render`, `infographic_render_template`, `infographic_render_data_template`, `infographic_list_templates`, `infographic_get_template_contract`, `infographic_validate_blocks`, `infographic_build_block`, `infographic_save_recipe`, `infographic_list_recipes`, `infographic_run_recipe`, `infographic_get_recipe_contract` | `ai-parrot/src/parrot/tools/infographic_toolkit.py` (see §4) | HTML artifact + A2UI envelope; recipes |
| `interactive_render`, `interactive_list_templates`, `interactive_list_libraries`, `interactive_get_scaffold` | `ai-parrot/src/parrot/tools/interactive_toolkit.py` | free-form HTML artifact |
| `generate_chart` | `TOOLS/chart.py:164` | image chart (altair/plotly) |
| `eda_report`, `compliance_report` | `TOOLS/edareport.py:118`, `TOOLS/security/compliance_report_toolkit.py:74` | domain reports (HTML) |
| `create_form`, `request_form`, `database_form`, `EditToolkit` (get_form_summary, add/update/remove_field, add/update_section, move_field, dependencies, update_form_meta/title/description, done) | `FD/tools/create_form.py:364`, `request_form.py:102`, `database_form.py:90`, `edit_toolkit.py:63` | FormSchema |
| Programmatic (not LLM tools): `InfographicAuthoringMixin.generate_infographic/publish_recipe/publish_surface` | `bots/mixins/infographic_authoring.py` | |

`OutputMode` (`ai-parrot/src/parrot/models/outputs.py:23`): `default, text, json, terminal, markdown, yaml, html, jupyter, notebook, template_report, application, chart, code, map, image, echarts, table, card, telegram, msteams, whatsapp, slack, infographic, interactive, sql_analysis, structured_chart, structured_table, structured_map, a2ui`. Formatters: JSON/TEXT/YAML/HTML/TABLE (core `outputs/formats`), INFOGRAPHIC (two registrations: `infographic.py:138` and `infographic_html.py:223`), STRUCTURED_TABLE/CHART/MAP, APPLICATION, CARD, MAP (folium), MARKDOWN, ECHARTS, TEMPLATE_REPORT (VIZ `outputs/formats`). Note: `VIZ/formats/jinja2.py:11` registers `OutputMode.JINJA2`, which does not exist in the enum (dead or broken module); `A2UI` bypasses formatter (`finalize_a2ui_response`). Structured config models: `StructuredChartConfig`:332, `StructuredTableConfig`:589, `StructuredMapConfig`:793 (also source of A2UI schemas).

---

## 7. Form designer (`packages/parrot-formdesigner`) — builder prior art

| Aspect | Location | Detail |
|---|---|---|
| Schema | `FD/core/schema.py:401 FormSchema` | `form_uid (UUID, immutable), form_id (slug), version "1.0", title/description (LocalizedString), sections[FormSection:229 → subsections:195, fields FormField:65], submit SubmitAction:300, cancel_allowed, meta, created_at, tenant, metadata[FormMetadataField], events, form_type, product_bindings, published_version, is_public, persistence, unknown_fields`; `RenderedForm`:671, `RenderWarning`:650 |
| Field types | `FD/core/types.py:16 FieldType` | text, text_area, number, integer, boolean, date, datetime, time, select, multi_select, file, image, color, url, email, phone, password, hidden, group, array, signature, dynamic_select, transfer_list, remote_response, availability, location, tags, nps, likert, ranking, rest, audio, formula, search, masked, color_picker, emoji, cron, tree_select, signature_pad |
| Style / layout | `FD/core/style.py` | `LayoutType` single_column/two_column/wizard/accordion/tabs/inline; `FieldSizeHint`, `FieldStyleHint`, `StyleSchema` (stored separately `style_json`) |
| Controls registry | `FD/controls/registry.py`, `controls/builtin.py` | pluggable field controls |
| Extractors | `FD/extractors/{pydantic,jsonschema,yaml,tool}.py` | build forms from models/schemas/tools |
| Renderers | `FD/renderers/`: `html5.py:131`, `a2ui.py:294 A2UIFormRenderer` (+`A2UIFieldLowering`:154), `adaptive_card.py:121`, `teams.py:88`, `pdf.py:115`, `jsonschema.py:301`, `xforms.py:185`, `audio.py:242`, `telegram/renderer.py:153`; base `AbstractFormRenderer` `renderers/base.py:57` | one schema → many targets |
| Storage | `FD/services/storage.py:69 PostgresFormStorage` (table per tenant: `id, form_uid, form_id, version, schema_json, style_json, tenant, created_at, updated_at, created_by, UNIQUE(form_uid,version), UNIQUE(tenant,form_id,version)`), abstract `FormStorage` `services/registry.py:63` (save/load/delete/list_forms/list_versions/promote) | **row-per-version** |
| Versioning / publish | `FD/services/form_version.py:251 FormVersionService` (`publish` :306 in-place promote, `get_published` :431, `list_versions` :480, `can_delete`/`safe_delete`, `backfill_published`); `VersionMeta` :35 | draft vs published, frozen published snapshots |
| Registry | `FD/services/registry.py:240 FormRegistry` (register, clone_form :833, get/get_by_slug, list, load_from_directory/storage, tenants) | |
| REST | `FD/api/routes.py` — `{tp}/forms`, `/forms/blank`, `/forms/{uid}`, `/clone`, `/edit`, `/partial`, `/publish`, `/style`, `/versions`, `/forms/from-db`, `{tp}/fields`; `FD/api/a2ui_wire.py` | |
| Other | submissions, sinks (postgres_table/asyncdb/csv/gsheet), rbac, question_bank, snippets (sandboxed rules), events, partial saves | |

---

## 8. Gaps for a REPORT BUILDER (evidence-based)

| # | Gap | Evidence |
|---|---|---|
| G1 | **No surface/report template entity** (reusable, parameterized layout distinct from a saved instance). Surfaces are concrete envelopes; recipes are the closest thing but are single-owner, single-root-layout, data-pipeline-centric | `ui_surfaces` columns (§5); `LayoutSpec` doc "single-node recipe layout" `recipes/models.py:109-146`; no template tables |
| G2 | **No versioning** for surfaces, recipes, infographic templates or themes (overwrite in place; optimistic concurrency only) | `_UPDATE_ENVELOPE_SQL` `ui_surfaces.py:251-263`; `infographic_recipes PK(name,owner)` `recipes.py:52-61`; registries in-memory `infographic_templates.py:512`, `infographic.py:1518`. Contrast form designer row-per-version + publish (`FD/services/form_version.py:306`) |
| G3 | **Infographic templates/themes are process-local**: REST POST registers into in-memory registries; lost on restart, not tenant-scoped | `helpers/infographics.py:50,115`; `SRV/handlers/infographic.py:717-767` |
| G4 | **No page/board model with explicit layout grid**: A2UI layout = Row/Column/Tabs nesting + `layout: full/half` hint; DesignSystem layouts are CSS presets (report/analytics/print); qs dashboard layout hardcoded (`root,title,row_kpis,row_charts`). No positions/sizes/breakpoints/pages/page-breaks | `chart.py` instructions; `design_system/__init__.py:99`; `querysource/toolkit.py:69` |
| G5 | **No widget-level persistence**: a widget is either a whole `ui_surfaces` row (`kind=widget`) or opaque JSON inside Mongo `dashboard_tabs.widgets[]`; Mongo dashboards are disconnected from A2UI/linked sources | `ui_surfaces.py:42`; `dashboard_handler.py` tab doc |
| G6 | **No component authoring/editing API** (add/move/update component in an envelope). Only whole-envelope build/publish; `UpdateComponents` message exists on wire but no server CRUD over components. Form designer has granular `EditToolkit` ops — direct prior art | `models.py:473`; `FD/tools/edit_toolkit.py:157-1057` |
| G7 | **Report composite is half-wired**: registered, but no `build_report`, no adapter emits it, interactive-html does not intercept it (lowers to Tabs), no pagination/TOC/header-footer/page numbering | `report.py:110`; `builders.py` list; `interactive_html.py:136` |
| G8 | **Prop schemas not enforced** at validation (structure/gates only); builder UIs need per-component JSON Schema validation + defaults | `validate_envelope` `catalog/__init__.py:689-919` |
| G9 | **viz-core catalog incomplete**: `Chart/Series/Stat` in vendored spec but unregistered; only `Graph` | `viz_core/spec/catalog.json`; `viz_core/__init__.py` docstring |
| G10 | **No PNG/image export** from A2UI renderers; PDF only via weasyprint (static SVG charts) | renderer table §3 |
| G11 | **Linked data limited to `query_slug`** sources; per-source params exist but no report-level parameter/filter model shared across widgets beyond FilterBar + broadcast refresh params | `LinkedDataSource.kind` `linked/models.py:192`; `service.py:152` |
| G12 | **Scheduling/delivery tied to recipes only**, not to surfaces; `AgentSchedule` has no surface FK; `RenderSpec.delivery` is free dict | `RunInfographicRecipeCallback` `infographic_recipes.py:323`; `scheduler/models.py:7`; `recipes/models.py:158` |
| G13 | **Several parallel "template" concepts, none unified**: InfographicTemplate (block slots), Jinja HTML templates (`render_template`, in-memory `add_template`), interactive scaffolds (yaml+html files), dead `outputs/templates ReportTemplate`, Mongo tab `template` string | §4 rows |
| G14 | **LLM producer not wired**: `generate_envelope` (validate-retry) unused; LLM authoring of envelopes goes through tools/adapters instead | `producer.py:191` (no callers) |
| G15 | **No component library / presets / saved-widget gallery** (e.g. reusable KPI definitions) and no theme CRUD with persistence (only 5 built-ins + in-memory register) | `infographic.py:1580-1672` |
| G16 | **Ownership/sharing model exists only for surfaces** (visibility + share tokens); recipes are (name, owner) only; templates have none | `ui_surfaces.py:50,132`; `recipes.py` |

Reusable foundations for a builder: catalog registry + `ComponentDefinition.schema/instructions` (palette metadata), `export_catalog_definition` (`catalog/export.py:215`), linked data DSL/executor/service (data binding + refresh), `ui_surfaces` (instances, visibility, shares), renderers (HTML/PDF/AC), DesignSystem/ThemeConfig (theming), RecipeRunner (scheduled re-render + delivery), form-designer patterns (row-per-version storage, publish, granular edit toolkit, multi-renderer).
