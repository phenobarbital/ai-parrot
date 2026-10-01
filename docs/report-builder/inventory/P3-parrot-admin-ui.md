# P3 — parrot-admin-ui inventory (canvases / A2UI / infographic / builders)

Repo: `/home/jelitox/repos/trocglobal/ai-parrot/packages/ai-parrot-server/ui` (branch `dev`). All paths below are relative to `ui/src/` unless absolute.
Nature: **plain Vite + Svelte 5 SPA (NOT SvelteKit)**, served by aiohttp at `/admin` (`vite.config.ts` base `/admin/`, build -> `../src/parrot/server/ui/dist`). Tailwind 4 + shadcn-svelte (vendored, bits-ui). 394 files under `src/`.

**Provenance (important for porting):** the whole AgentChat + canvas closure is *vendored from navigator* ("navigator-frontend-next"): see `lib/shims/environment.ts:1-13`, `lib/shims/env-public.ts`, `lib/api/http.ts:3`, `lib/api/auth-headers.ts:5`, `lib/stores/agentchat-layout.svelte.ts:24` ("set by Program.svelte"). SvelteKit specifiers (`$app/environment`, `$app/navigation`, `$env/dynamic/public`) are kept verbatim and aliased to shims in `vite.config.ts` `resolve.alias`. Files tagged `ai-parrot (FEAT-xxx)` are parrot-side additions (A2UI stack, linked lane, feature flags). => Porting back to navigator-svelte is mostly a reverse diff; the A2UI/linked/infographic-a2ui pieces are the genuinely new code.

---

## 1. Routes / pages

Router: hand-rolled history router `lib/router.svelte.ts` (`Router` class, `routes`, `match()`, `guard()`, `beforeNavigate` hook, `:param` segments, exact-length match). Route table in `App.svelte:17-50`; auth pages wrapped in `lib/components/AppShell.svelte` (Sidebar/Topbar). Nav entries: `lib/nav.ts`.

| Route | Page | Notes |
|---|---|---|
| `/admin/login` | `pages/Login.svelte` | full-screen, no shell |
| `/admin/home` | `pages/Home.svelte` | GET `/api/v1/admin/status` + nav cards |
| `/admin/dashboard` | `pages/Dashboard.svelte` | **status dashboard only** (AdminStatus, HealthBadge, StatusTile) — not a widget dashboard |
| `/admin/agents` | `pages/Agents.svelte` -> `pages/agents/AgentsList.svelte` | list/delete (`DeleteAgentDialog.svelte`) |
| `/admin/agents/new`, `/admin/agents/:name` | `pages/agents/AgentFormPage.svelte` -> `AgentForm.svelte` + `form/Tabs*.svelte` | agent builder (see §5) |
| `/admin/agents/:name/chat` | `pages/agents/AgentChatPage.svelte` -> `lib/components/agents/AgentChat.svelte` (2722 lines) | **the only host of the canvas** |

No report/canvas/page/notebook route exists. `AgentDetail.svelte` is a detail view used by the list.

## 2. Canvas system (`lib/components/agents/canvas/`)

| File | Role / key APIs |
|---|---|
| `canvas-tab-manager.svelte.ts` | **Module-level runes singleton** (one canvas per app). `CanvasTabType = markdown|chart|spreadsheet|infographic|audio|interactive` (:6-12). `CanvasTab {id,type,title,data:unknown,closable}` (:14-20). `MAIN_CANVAS_ID="main-canvas"` non-closable markdown tab with `data: CanvasBlock[]` (:22-38). API: `initCanvas` :52, `addTab(type,title,data)->id` (uuid, activates) :56, `removeTab` :67 (activates neighbour), `setActiveTab` :81, `updateTabData` :87, `updateTabTitle` :94, `resetCanvas` :101, getters `getTabs/getActiveTabId/getActiveTab`. Sentinel `data === "__loading__"` used for async tabs. |
| `canvas-registry.ts` | `Map<CanvasTabType, Component<{data, previewMode?, agentId?}>>`; markdown+chart -> `BlockCanvas`, infographic -> `InfographicCanvas`, audio -> `AudioCanvas`, spreadsheet -> `SpreadsheetCanvas`, interactive -> `InteractiveArtifactCanvas`. `registerCanvasComponent` :70, `getCanvasComponent` :81. Extension point for a "report" tab type. |
| `CanvasPanel.svelte` (448) | Panel chrome: header buttons New Canvas (:121), Duplicate (:127, deep-clones blocks w/ new uuids; spreadsheet -> table block), Export menu (HTML :147 / Print-PDF :157 / Export All :166), "Infographic" (:73 serializes main canvas via `serializeBlocksForInfographic` -> new infographic tab), "Listen This" (:88 audio report), Edit/Preview toggle for block tabs (:310), swap/maximize/close (:328-356) via layout store. Tab bar (:361) with close buttons; "+" add-tab menu (:195 `tabTypes`, interactive excluded). Renders `<ActiveComponent data previewMode agentId/>` (:431). |
| `canvas-persistence.svelte.ts` | **@deprecated / unused (FEAT-042)** — Dexie `canvas_state` table keyed by session_id, debounced save, `saveCanvasState/loadCanvasState/initCanvasPersistence`. Disabled due to Svelte-5 effect races. => **Canvas tabs are NOT persisted** (in-memory only, lost on reload). Comment says to be repurposed for backend (DocumentDB) persistence. |
| `canvas-block-types.ts` | `CanvasBlockType` (14): markdown, chart, image, table, html, map, interactive, title, hero_card, summary, quote, callout, divider, bullet_list (:11-25). Per-type data interfaces (:29-130). `CanvasBlock {id,type,data,meta?{title,collapsed}}` :134. `createBlock` :163, `isCanvasBlockArray` :178, legacy migrators :196/:205. |
| `BlockCanvas.svelte` (314) | "Main Canvas" block editor. Managed mode (reads active tab) or standalone (data is `CanvasBlock[]`). CRUD: `addBlock(type,data,afterId)` :88, `removeBlock` :104, `moveBlockUp/Down` :108/:117 (**buttons, no DnD**), `updateBlockData` :126. Renders `blocks/*Block.svelte`. |
| `blocks/` | `BlockToolbar` (move/remove), `BlockInsertHandle` (insert menu), `MarkdownBlock`(+`MarkdownToolbar`, resizable), `ChartBlock` (lazy `DataChart`, gated `features.charts`), `TableBlock` (lazy `@revolist/svelte-datagrid`), `MapBlock` (lazy `DataMap`/leaflet), `ImageBlock`, `HtmlBlock`, `InteractiveBlock`, `TitleBlock`, `HeroCardBlock`, `SummaryBlock`, `QuoteBlock`, `CalloutBlock`, `DividerBlock`, `BulletListBlock`. Most are inline-editable (`onUpdate`). |
| `canvas-block-exporter.ts` | `exportBlocksToHtml(blocks,title)` :251, `exportAllTabsToHtml(tabs)` :292, `downloadHtml` :368, `printHtml` :382 — self-contained HTML/print, no lib. |
| `InfographicCanvas.svelte` (524) | infographic tab; see §4. |
| `InteractiveArtifactCanvas.svelte` | iframe (`srcdoc` html_inline preferred, else `html_url`), `sandbox="allow-scripts allow-forms allow-modals allow-popups"`. Tab data `InteractiveArtifactTabData` (`lib/types/agent.ts`). |
| `SpreadsheetCanvas.svelte` | wraps `lib/components/grid/ResultGrid.svelte` (RevoGrid, 1489 lines: sort, roll-up formulas `grid/formulas.ts`, export csv/json/xlsx via exceljs). |
| `AudioCanvas.svelte` | podcast/script player from speech_report. |
| `ChartCanvas.svelte`, `MarkdownCanvas.svelte` | **orphaned legacy** (not registered/imported). |
| `infographic-tab-builder.ts` | pure `buildInfographicTabData(message, features)` :45 — routing table: linked surface (any mode) or `output_mode infographic|a2ui` + Infographic/Report root + `features.a2ui` -> `mode:'a2ui'` (+`persistedSurfaceId` from `metadata.a2ui_surface_id`); else HTML inline/url fallback; widget-only a2ui -> null. |

**Layout store** `lib/stores/agentchat-layout.svelte.ts`: 3 panes [History | Chat | Canvas]. `canvasOpen` :11, `canvasExpanded` :14 (hides chat), `canvasPrimary` :18 (swap sizes, FEAT-611; mutually exclusive with expanded :100-116). `openCanvas` :84 (closes history), `closeCanvas` :89 resets both. Global-nav collapse hooks `registerGlobalNavControl` :27 (navigator Program.svelte leftover). Consumed in `AgentChat.svelte:432-435, 2567-2590` (canvas pane width / flex-1, lazy `import("./canvas/CanvasPanel.svelte")` gated by `features.canvas`).

**How tabs get created** (all in `AgentChat.svelte`): `handleExplain` :1688 (markdown, `__loading__` then result), `handleOpenSpreadsheet` :1733, `handleMoveToCanvas` :1739 / `handleMoveTableDataToCanvas` :1757 / `handleCopyChartToCanvas` :1777 (append block to main-canvas), `handleCopyChartToChartCanvas` :1800 (reuse/create "chart" tab), `handleCreateInfographic` :1823 (`mode:'json'` + query), `maybeOpenInfographicCanvas` :1854 (auto on assistant message), `maybeOpenInteractiveArtifactCanvas` :1873 (`output_mode === 'interactive'`). Closing: tab "x" -> `removeTab`; panel close -> `chatLayout.closeCanvas()`. Persistence: none.

## 3. A2UI rendering stack (`canvas/a2ui/`)

| File | Role / key APIs |
|---|---|
| `a2ui-types.ts` | `A2UIEnvelope {version:"v1.0", createSurface}` :86; `CreateSurface {surfaceId, catalogId?, components: WireComponent[], dataModel?, metadata.extensions}` :74; `WireComponent {id, component, catalogId?, child?, children?: string[]|{componentId,path}, ...props}` :28 (flat adjacency list); `SectionDescriptor`, `InfographicSection {heading,text,components}`; `Binding {path}` (JSON Pointer); `VIZ_CORE_CATALOG_ID` :23; `WIRE_INDEX_CONTEXT` :47. |
| `a2ui-kind.ts` | `inferSurfaceKind` -> widget/infographic/dashboard (:19-27); `hasInfographicRoot` (Infographic/Report) ; `isLinkedSurface` (has `parrot_data_sources`). |
| `a2ui-binding.ts` | `isBinding`, JSON-pointer `resolveBinding(value, dataModel)`, `resolveProps`. |
| `a2ui-format.ts` | `formatA2UIValue(value, format: percent|currency|number, unit)` :38. |
| `a2ui-chart-adapter.ts` | `toChartBlockData(properties, dataModel)` :46 — A2UI `Chart {type,x,y[],data(binding),palette,title,xAxisLabel,stacked,showLegend,layout,colorBySign...}` -> infographic `ChartBlockData {chart_type, labels, series[]}`. |
| `A2UISurface.svelte` (259) | Root. Props `{envelope, persistedSurfaceId?, transformsBase?}` :34. Stateful `baseDataModel` (cloned from envelope :51), local `activeFilters` -> derived filtered `dataModel` (:69-93, filter applies only to root keys whose rows contain the column). Contexts set at init: `LINKED_LANE_CONTEXT` (stable proxy :104-112), `FILTER_CONTEXT` :114-122, `WIRE_INDEX_CONTEXT` :126-129. Effect creates `createLinkedLane(sources, {baseUrl: querySourceBaseUrl, headers, transformsBase: ${apiBaseUrl}/static/a2ui/transforms, onUpdate})` :131-162 -> patches `dataModel[key]={rows}`. `serverRefresh()` :164 -> **POST `/api/v1/ui/surfaces/{persistedSurfaceId}/refresh`** `{params}`, reads `X-Parrot-Refresh-Warnings`. Renders Infographic/Report root via `A2UIInfographic`, else `A2UINode`; per-source status notices + Refresh/Refresh all buttons (:224-257). |
| `A2UIInfographic.svelte` | title/subtitle + sections; >1 section -> `AppTabs` (bits-ui) tabs, 1 -> stacked; `groupByLayout` pairs consecutive `layout:"half"` into 2-col grid (:31-51). |
| `A2UINode.svelte` (326) | Recursive dispatcher. **Supported components:** `KPICard` (-> InfographicHeroCardBlock) :214, `Chart` (-> InfographicChartBlock via adapter) :224, `DataTable` (columns{name,title,format}) :231, `Timeline` :233, `InfoCard` :235, `Graph` (only when catalog = viz-core -> `A2UIGraph`) :243, `HtmlDocument` (sandboxed iframe srcdoc/srcUrl) :250, `Text`, `Image`, `Divider`, `CheckBox` (read-only), **FilterBar** (raw `filters[]` or lowered `Row{parrot_variant:"filter-bar"}` of `ChoicePicker`) :286, `List`/`Row`/`Column` (children by id via wire index) :307, `Tabs` (rendered stacked, not real tabs) :313; else "not supported" placeholder. |
| `A2UIGraph.svelte` (246) | viz-core `Graph` (nodes/edges/groups/state) -> ECharts `graph` series via module-level pure builder; renders `lib/components/visualizations/ECharts.svelte`. |
| FilterBar logic (in A2UINode :47-156) | Normalizes filters, checkbox UI, `toggleOption`: with `param{source,name}` -> `lane.setParam` (re-fetch one source); without -> `filterCtl.setFilter` (local filtering). Only checkbox UI (no date range/select). |
| `linked/index.ts` (281) | `createLinkedLane(sources, opts)` :149 -> `LinkedLane {start, stop, setParam, refreshAll, getParams, refreshSource}` :54; `currentParams` :145; dependency ordering for join/union, `locked` params. Contexts `LINKED_LANE_CONTEXT` :21, `FILTER_CONTEXT` :31; `SourceUpdate {key, rows|null, status: loading|ready|unavailable|error, snapshotAt}`. |
| `linked/fetch.ts` | `fetchSource(src, conditions, {baseUrl, headers, maxFetchRows})` :61, cap `DEFAULT_MAX_FETCH_ROWS=5000`, multi-output frame selection, `SourceUnavailable` on 404. |
| `linked/dsl.ts` (560) | `applyTransform(rows, spec, frames)` :32 — ops: select, rename, filter (eq/ne/gt/ge/lt/le/in/contains), sort, limit, derive (+-*/ expr), group_by (sum...), pivot, join, union. Mirror of Python `parrot/outputs/a2ui/linked/dsl.py` (golden-fixture parity test). |
| `linked/conditions.ts` | `deriveConditions` (params -> QuerySource conditions). |
| `linked/scheduler.ts` | `RefreshScheduler`, `MIN_INTERVAL_SECONDS=30`. |
| `linked/ref.ts` | `loadRef` (external JS row-transform module with SRI `sriOf`) from `transformsBase`. |
| `linked/types.ts` | re-exports generated `LinkedSources` types (`lib/types/generated/LinkedSources.d.ts` from `ui/schemas/LinkedSources.json`); `DATA_SOURCES_EXTENSION='parrot_data_sources'`, `getDataSources(surface)` :43. |
| `lib/api/querysource.ts` | `querySourceBaseUrl` (PUBLIC_QUERYSOURCE_URL or apiBaseUrl), `queryUrl` -> **POST `/api/v2/services/queries/{slug}`** (default, plain QS), **`/api/v3/queries/{slug}`** only when `is_multiquery` (MultiQS), or **`/api/v1/{tenant}/queries/{slug}`** when a tenant is set; native fetch + bearer (`getAuthHeaders`). Browser calls QuerySource directly. |

## 4. Infographic UI (`canvas/infographic/` + `InfographicCanvas.svelte`)

- **Tab data** `InfographicTabData {mode: json|html|a2ui, html?, url?, infographic?: InfographicData, query?, template?, theme?, envelope?, persistedSurfaceId?}` (`infographic-types.ts:245`).
- **Block model** (`infographic-types.ts`): `InfographicBlock` union :166 of 12 types — title, hero_card, summary, chart (`ChartType` 12: bar,line,pie,donut,area,scatter,radar,heatmap,treemap,funnel,gauge,waterfall :25), bullet_list, table, image, quote, callout, divider, timeline, progress. Plus template/theme API types (`TemplateItem`, `ThemeItem`, detail responses :203-240).
- **Registry** `infographic-registry.ts` (type -> `blocks/Infographic*Block.svelte`; `registerInfographicBlock`). Blocks: Title, HeroCard, Summary, Chart (AppChart/layerchart; unsupported types fall back; gated `features.charts`), Table, BulletList, Image, Quote, Callout, Divider, Timeline, Progress. **Render-only** (no inline editing in infographic blocks).
- `InfographicBlockCanvas.svelte` (230): renders blocks, groups consecutive blocks into grids (`groupConsecutiveBlocks` :79), move up/down/remove/insert (`InfographicInsertHandle.svelte` palette of 12 block factories); emits `onBlocksChange`.
- `InfographicToolbar.svelte` (248): template + theme pickers (`fetchTemplates(true)`, `fetchThemes(true)` :65) and "Create" -> `generateInfographicFromApi({query, template, theme})`.
- `InfographicCanvas.svelte` modes: JSON/"Visual Blocks" (toolbar + block canvas), **A2UI** (Rendered via `A2UISurface` / HTML iframe toggle `a2uiView` :84), URL (iframe src), HTML (edit/preview toggle :81; edit = `InfographicEditor` if `features.richEditor` else textarea; preview = sandboxed iframe). `loadDemo()` :216 (`demo-financial-variance.ts`).
- **Save flow** `handleSave` :128: **download only** — JSON -> `exportBlocksToHtml(blocks, collectChartImages(...))`; HTML -> raw html; a2ui without html -> opens signed `url`. Blob download `infographic-<ts>.html`. **No server save/persist.** Print :153 via hidden iframe.
- `InfographicEditor.svelte` (158): TipTap (StarterKit+Link+Underline) WYSIWYG over the **body of a backend-generated HTML infographic**, preserving `<head>`; emits merged HTML via `onUpdate`.
- `infographic-html-export.ts`: `collectChartImages` :34, `exportBlocksToHtml` :425 (self-contained HTML, grid layout). **Likely bug:** `collectChartImages` queries `.echarts-container` (only emitted by `visualizations/ECharts.svelte:298`) but `InfographicChartBlock` now renders via `AppChart` (layerchart) => chart images probably missing in exported/printed JSON infographics.
- Endpoints (`lib/api/infographic.ts`, base `/api/v1/agents/infographic` :601): GET `/templates` :607, GET `/themes` :621, GET `/templates/{name}` :634, GET `/themes/{name}` :646, POST `/{agentId}` :664 (json or html response). Legacy `generateInfographic` :173 (chat with design-system prompt). Helpers `serializeBlocksForInfographic` :121, `sanitizeInfographicHtml` :153.
- Themes for the app shell: `lib/stores/theme.svelte.ts` (light/dark), `lib/styles/themes/{_tokens,_schema,light,dark}.css` (shadcn CSS vars, `--chart-N`).

## 5. Builder / editor UIs

| UI | Files | Notes |
|---|---|---|
| Agent form (builder) | `pages/agents/AgentForm.svelte`, `form/TabsGeneral/AI/Behavior/Capabilities/DataMemory/Tools/Advanced.svelte`, `FormFooter`, `AgentMcpPanel`, `ToolkitDrawer`; store `lib/stores/agent-form.svelte.ts` (`AgentFormState` class :77, create/edit modes, dirty tracking + router `beforeNavigate`); `lib/agents/fields.ts` | Tabbed form with unsaved-changes guard — reusable pattern for a report metadata form. |
| Schema form | `lib/components/schema-form/SchemaForm.svelte` (284) | JSON-Schema -> widgets: switch/number/text/password/multi-select/string-list/oneof/oneof-array; `x-secret`, `x-server-managed`, `x-user-overridable`, `x-options` (async `optionsLoader`), recursive. Good candidate for **widget property panels**. |
| Tools tab | `form/TabsTools.svelte`, `ToolkitDrawer.svelte`, `agents/MyToolkitSettings.svelte` | toolkit config via `api/studio.ts`. |
| Prompt library | `agents/PromptLibraryModal.svelte`, `PromptPills`, `StarterPromptBubbles`; store `lib/stores/prompt-library.svelte.ts` (load/add/update/remove, starter prompts); `api/prompt-library.ts`, `api/user-prompts.ts`; `utils/prompt-placeholders.ts` | |
| JSON / list editors | `lib/components/JsonEditor.svelte`, `StringListEditor.svelte` | |
| Rich text | `lib/ui/components/AppTextEditor.svelte` (650, TipTap full), `AppTextEditorLite.svelte` (339) | |
| Chart config | `agents/ChartConfigPanel.svelte`, `chart-types.ts`, `DataChart.svelte` (AppChart), `DataMap`/`StructuredMap` (leaflet), `charts/AppChart.svelte` (671, layerchart; `chart-contract.ts` `AppChartConfig`), `AppChartGeo.svelte` (d3-geo/topojson), `visualizations/ECharts.svelte` (300, tree-shaken echarts/core) | Chart-config UI exists for chat data -> reusable for widget editing. |
| Datasets | `DatasetTab`, `DatasetConfigModal`, `DatasetCreatePane`, `DatasetInlinePreview`, `DataManagementModal` | `features.datasets`. |
| Notebooks | — | **none** |
| Dashboard | `pages/Dashboard.svelte` | admin status only, not a layout dashboard. |
| UI kit | `lib/ui/components/*` (AppTabs, AppDialog, AppSheet, AppDropdown, AppCommand, AppToggle, AppTooltip, SimpleTable, LlmModelPicker) + `lib/ui/internal/shadcn/ui/*` | |

## 6. API clients (`lib/api/*`) — axios `apiClient` from `http.ts` (bearer from localStorage `config.tokenStorageKey`, 401 -> logout) unless noted

| Module | Endpoints |
|---|---|
| `http.ts` | `createApiClient(baseURL)` :179, interceptors :110, `extractServerMessage` :80, `ApiError` |
| `auth-headers.ts` | `getAuthHeaders()` -> `{Authorization: Bearer}` (for native fetch) |
| `agents.ts` | GET `/api/v1/bots[?include_disabled=true]`; GET/POST?/DELETE `/api/v1/bots/{name}` (update :58); PUT `/api/v1/bots` (create); GET `/api/v1/agent_tools`; GET `/api/v1/admin/catalog` |
| `agent.ts` | POST `/api/v1/agents/chat/{agent}`; POST `/api/v1/agents/chat/{agent}/{method}`; PATCH/PUT `/api/v1/agents/chat/{agent}` (session/upload/slug); GET `/api/v1/agents/chat/{agent}/mcp_servers`; POST/HEAD `/api/v1/agents/voice/{agent}`; POST `/api/v1/bot_feedback`; GET/PATCH/PUT/POST/DELETE `/api/v1/agents/datasets/{agentId}` |
| `stream.ts` | native fetch streaming POST `/api/v1/agents/chat/{agent}`, POST `/api/v1/chat/{chatbotId}` |
| `botChat.ts` | POST `/api/v1/chat/{chatbotId}` |
| `chatInteraction.ts` | GET/POST `/api/v1/chat/interactions`; GET/PUT/DELETE/PATCH `/api/v1/chat/interactions/{sessionId}` |
| `infographic.ts` | GET `/api/v1/agents/infographic/templates[/{name}]`, `/themes[/{name}]`; POST `/api/v1/agents/infographic/{agentId}` |
| `speechReport.ts` | POST `/api/v1/agents/chat/{agentId}/speech_report` |
| `querysource.ts` | POST `/api/v2/services/queries/{slug}` (default), `/api/v3/queries/{slug}` (is_multiquery only) or `/api/v1/{tenant}/queries/{slug}` (native fetch) |
| (inline in `A2UISurface.svelte:169`) | POST `/api/v1/ui/surfaces/{id}/refresh`; GET `${apiBaseUrl}/static/a2ui/transforms/*` (ref transforms) |
| `studio.ts` (base `/api/v1/astudio`) | GET `/toolkits/{slug}/schema`; GET `/agents/{n}/toolkit-config`; PUT/DELETE `/agents/{n}/toolkits/{slug}`; GET `/agents/{n}/toolkits/{slug}/options/{param}`; GET/PUT `/agents/{n}/mcp-servers`; POST `/agents/{n}/reload`; GET/PUT/DELETE `/agents/{n}/toolkits/{slug}/me` |
| `prompt-library.ts` | GET/PUT `/api/v1/prompt_library`; POST/DELETE `/api/v1/prompt_library/{id}` |
| `user-prompts.ts` | GET/PUT `/api/v1/agents/user_prompts`; POST/DELETE `/api/v1/agents/user_prompts/{id}` |
| `integrations.ts` | `/api/v1/agents/integrations/{agentId}` GET list; POST `/{provider}/connect`, `/{provider}/enable`; DELETE `/{provider}` |
| `llm.ts` | GET `/api/v1/ai/clients`, GET `/api/v1/ai/clients/models` |
| `avatar.ts` | POST `/api/v1/agents/avatar/{id}/start|stop`, voice-native start, POST `/api/v1/avatar/{id}/viewers` |
| Pages | GET `/api/v1/admin/status` (Home, Dashboard) |

No client exists for **saving surfaces/reports/templates** (no `ui/surfaces` CRUD client; only `/refresh`).

## 7. Stores (`lib/stores/*`, all Svelte 5 runes)

| Store | Relevance |
|---|---|
| `agentchat-layout.svelte.ts` | canvas open/expanded/primary + history (see §2) |
| `canvas/canvas-tab-manager.svelte.ts` | tab state (module singleton) |
| `agent-form.svelte.ts` | form state class w/ dirty tracking — pattern for report editor |
| `prompt-library.svelte.ts` | prompt CRUD cache |
| `theme.svelte.ts` | light/dark, `init()` |
| `toast.svelte.ts`, `notifications.svelte.ts` | `toastStore` used across canvas |
| `auth.svelte.ts`, `client.svelte.ts`, `avatar.svelte.ts` | infra |
| `lib/services/chat-db.ts` | Dexie DB (v3 adds `canvas_state` table, unused) |
| `lib/features.ts` | build-time flags `voice, avatar, maps, charts, canvas, infographic, datasets, richEditor, a2ui` (`__AGENTCHAT_*__` defines from `PUBLIC_AGENTCHAT_*`) |

## 8. Dependencies (package.json) relevant

| Dep | Used by |
|---|---|
| `echarts ^5` | `visualizations/ECharts.svelte` only (-> A2UIGraph) |
| `layerchart 2.0.0-next.64`, `d3-scale`, `d3-geo`, `topojson-client`, `world-atlas` | `charts/AppChart.svelte`, `AppChartGeo.svelte` (DataChart, InfographicChartBlock) |
| `@revolist/svelte-datagrid` | `grid/ResultGrid.svelte`, `blocks/TableBlock.svelte` |
| `exceljs` | ResultGrid xlsx export |
| `@tiptap/*` (core, starter-kit, link, underline, text-align, text-style, typography) v3 | `InfographicEditor`, `AppTextEditor`, `AppTextEditorLite` |
| `leaflet` | DataMap, StructuredMap |
| `bits-ui`, `tailwind-variants`, `tailwind-merge`, `clsx`, `tw-animate-css` | shadcn UI kit |
| `dexie` | chat-db |
| `marked`, `dompurify`, `highlight.js` | markdown rendering |
| `uuid` | tab/block ids |
| `@iconify/svelte` + iconify-json sets (mdi, lucide, ph, tabler) | icons everywhere |
| `livekit-client` | avatar |
| **absent** | no grid-layout lib (gridstack/svelte-grid), no DnD lib (svelte-dnd-action), no monaco/codemirror, no html2canvas/jspdf/pdf export (print = browser print), no svelte-kit |

## 9. Test coverage (vitest + @testing-library/svelte + jsdom + fake-indexeddb)

| Area | Tests (it/test count) |
|---|---|
| A2UI core | `a2ui-binding.test.ts`(9), `a2ui-chart-adapter.test.ts`(7), `a2ui-format.test.ts`(6), `a2ui-kind.test.ts`(11), `A2UINode.test.ts`(15), `A2UISurface.test.ts`(7), `A2UISurface.linked.test.ts`(14), `A2UIGraph.test.ts`(5) |
| Linked lane | `linked/index.test.ts`(5), `dsl.test.ts`(fixture-driven), `parity.test.ts`(fixture parity w/ Python), `fetch.test.ts`(14), `scheduler.test.ts`(6), `conditions.test.ts`(3), `ref.test.ts`(7), `types.test.ts`(4) |
| Infographic | `InfographicCanvas.a2ui.test.ts`(6), `infographic-tab-builder.test.ts`(9) — **no tests for InfographicBlockCanvas/blocks/Toolbar/Editor/html-export** |
| Canvas/tabs | `stores/agentchat-layout.test.ts`(3), `AgentChat.a2ui-canvas.test.ts`, `AgentChat.test.ts`, `features-gating.test.ts` — **no tests for canvas-tab-manager, CanvasPanel, BlockCanvas, blocks, block exporter, ResultGrid** |
| Builders | `SchemaForm.test.ts`, `JsonEditor.test.ts`, `StringListEditor.test.ts`, `agent-form.test.ts`, `pages/agents/*.test.ts`, `form/TabsTools.test.ts`, `MyToolkitSettings.test.ts` |
| Infra | `router.test.ts`, `api/{agents,agent,http,stream}.test.ts`, `services/{chat-db,websocket-service}.test.ts`, shims, config, features, icons, App/Home/Login/Dashboard |

---

## Portability notes (-> navigator-svelte / SvelteKit)

| Piece | Portability | Deps / coupling |
|---|---|---|
| `a2ui/a2ui-types.ts`, `a2ui-binding.ts`, `a2ui-format.ts`, `a2ui-kind.ts`, `a2ui-chart-adapter.ts` | **High** — pure TS | `a2ui-kind` -> `linked/types` -> generated `LinkedSources.d.ts` (copy schema + `json2ts` script); adapter -> `infographic-types` |
| `a2ui/linked/*` (lane, dsl, fetch, scheduler, conditions, ref) | **High** — plain TS, no Svelte | `fetch.ts` -> `$lib/api/querysource` (native fetch + `getAuthHeaders` + `config.apiBaseUrl`); swap to navigator's auth headers / QuerySource base. Bring `contract/fixtures/dsl` for parity tests. |
| `A2UISurface/A2UINode/A2UIInfographic/A2UIGraph.svelte` | **Medium-high** | Svelte 5 runes + contexts; imports `$lib/config`, `$lib/api/*`, `$lib/ui/components/AppTabs` (bits-ui), infographic blocks, `visualizations/ECharts.svelte`, `$app/environment` (native in SvelteKit). Tailwind/shadcn token classes (`text-muted-foreground`, `border-border`) — navigator must have same tokens. |
| `infographic/*` (types, registry, blocks, BlockCanvas, InsertHandle, Toolbar, html-export) | **Medium** | blocks depend on `charts/AppChart.svelte` + `chart-contract.ts` (layerchart/d3) and `$lib/features`; Toolbar depends on `api/infographic.ts` (agent infographic endpoints). |
| `canvas-tab-manager`, `canvas-registry`, `canvas-block-types`, `canvas-block-exporter`, `CanvasPanel`, `BlockCanvas`, `blocks/*` | **Medium** — originally from navigator, so likely near-identical upstream | module-level singleton (one canvas per app; SSR-unsafe in SvelteKit: module `$state` is shared across requests — must be client-only or converted to context-scoped class); CanvasPanel couples to `agentchat-layout`, `toastStore`, `api/infographic`, `api/speechReport`. |
| `agentchat-layout.svelte.ts` | High (trivial) | expects navigator `Program.svelte` global-nav hook |
| `SchemaForm`, `JsonEditor`, `StringListEditor` | High | shadcn primitives under `$lib/ui/internal/shadcn/ui/*` |
| `grid/ResultGrid` | Medium | RevoGrid + exceljs + `revogrid-theme.css` |
| Feature flags (`$lib/features`, `__AGENTCHAT_*__` defines) | Drop or replace with navigator config; every gated block reads `features.x`. |
| Shims (`lib/shims/*`) | Not needed in SvelteKit (real modules) — they exist only because this is a Vite SPA. |
| Router (`router.svelte.ts`) | Not portable/needed (SvelteKit routing). |

## Gaps for a report builder

1. **No persistence**: canvas tabs are in-memory; `canvas-persistence` deprecated (Dexie races); no client for saving/listing/loading surfaces/reports (`/api/v1/ui/surfaces` only `/refresh` is used). Need CRUD client + save/load UI + versioning.
2. **No page management**: no report/page entity, no page list/rename/reorder; tabs are ad-hoc session artefacts; A2UI multi-section renders as tabs but not editable.
3. **No grid/free layout editing**: layouts are linear block lists (+ auto-pairing `layout:"half"`, `groupConsecutiveBlocks`); no resize/position model, no grid-layout lib.
4. **No drag-and-drop**: reorder = up/down buttons only (BlockCanvas, InfographicBlockCanvas); no DnD lib.
5. **A2UI is render-only**: no A2UI editor (cannot add/edit components, bindings, data sources, FilterBar from UI); no reverse mapping block -> A2UI wire.
6. **Widget toolbox**: insert palettes exist (`BlockInsertHandle`, `InfographicInsertHandle` 12 factories) but no data-bound widget creation (pick QuerySource slug, map x/y, pick chart type) — `ChartConfigPanel` + `SchemaForm` are the nearest building blocks.
7. **Template save UI**: templates/themes are read-only pickers (GET only); no create/save-as-template, no theme editor.
8. **Two parallel block models** (`CanvasBlock` 14 types vs `InfographicBlock` 12 types vs A2UI components) — needs one canonical report model (A2UI v1.0 wire is the natural candidate given linked lane + server refresh).
9. **FilterBar limited**: checkbox-only, no date range/select/search; `Tabs` component rendered stacked.
10. **Export**: HTML download + browser print only; no PDF/PNG/PPTX; probable bug — JSON infographic export looks for `.echarts-container` but charts render via layerchart, so chart images likely dropped.
11. **Tests**: tab manager, CanvasPanel, BlockCanvas/blocks, infographic block canvas/export have no unit tests.
12. Charting is split (layerchart for charts, echarts only for Graph); a report builder should pick one (ECharts covers heatmap/treemap/funnel/gauge/waterfall that AppChart falls back on).
