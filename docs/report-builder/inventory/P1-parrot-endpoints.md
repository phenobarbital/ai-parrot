# P1 — ai-parrot HTTP/WS endpoint inventory (report-builder lens)

Repo `ai-parrot` @ `dev`. Paths: `S=packages/ai-parrot-server/src/parrot`, `C=packages/ai-parrot/src/parrot`, `FD=packages/parrot-formdesigner/src/parrot_formdesigner`.
Wiring roots: `BotManager.setup()` `S/manager/manager.py:2239-2596` and the host app `app.py:87-352` (repo root). Host order: `QuerySource.setup` (`app.py:109`) → `BotManager.setup` (`app.py:113`) → scheduler (`app.py:126-129`) → misc views (`app.py:134-250`) → formdesigner (`app.py:257-290`) → `AuthHandler.setup` + exclude list (`app.py:296-332`) → PBAC (`app.py:337-351`).

**Auth legend**
- **AU** = class decorated `@is_authenticated()` + `@user_session()` (navigator_auth).
- **MW** = no decorator; only navigator-auth's global auth middleware applies (it gates everything not in the exclude list, `app.py:303-332`; see `S/handlers/stream.py:66-85` docstring confirming global-middleware model). No per-user ownership checks unless noted.
- **PBAC(x)** = `AgentTalk._check_pbac_agent_access(agent_id, action=x)` `S/handlers/agent.py:150-200` — fails OPEN when PBAC/`app['security']`/`app['abac']` absent.
- **SCOPE** = ui_surfaces access order owner → tenant/group/superuser scope → share token → 404 (`S/handlers/ui_surfaces.py:167-216`, `S/handlers/ui_surfaces_scope.py:42-171`).
- **PUB** = excluded from auth (`app.py:303-332`).

---

## 1. A2UI surfaces (persistent "boards/widgets") — `UISurfacesHandler` (AU + SCOPE)

Handler `S/handlers/ui_surfaces.py:313-840`; routes `S/manager/manager.py:2339-2343`. Store `PgUISurfaceStore` (`S/handlers/models/ui_surfaces.py:457`) → Postgres `navigator.ui_surfaces` (`:110`) + `navigator.ui_surface_shares` (`:132`), auto-DDL. Record `UISurfaceRecord` (`:64-82`): `surface_id, kind∈{dashboard,infographic,widget} (:42-47), title, envelope (A2UI CreateSurface JSON), catalog_id, agent_id, user_id, session_id, recipe_name, recipe_owner, recipe_params, tenant, visibility∈{private,tenant,groups} (:50-61), allowed_groups, created_at, updated_at`.

| Method | Path | Handler (file:line) | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/ui/surfaces` | `get`→`_get_list` `ui_surfaces.py:393,466` | List surfaces visible (owner ∪ tenant ∪ group ∪ superuser) ∪ token-claimed shares, deduped & tagged `access∈{owner,tenant,shared}` | query `kind?` | `{status,count,surfaces:[metadata+access]}` (metadata = `_surface_metadata` `:148-165`; **no envelope**) | AU+SCOPE | `list_visible` + `list_shared_with` |
| POST | `/api/v1/ui/surfaces` | `post`→`_pin_save` `:402,508-613` | Pin/save a surface from an inline envelope OR copy from an ArtifactStore artifact; linked (data-source) envelopes get a snapshot via `LinkedSurfaceService.ensure_snapshot` | `PublishSurfaceRequest` `:69-93`: `kind,title, envelope XOR source_artifact_id(+agent_id,session_id), recipe_name, recipe_owner, recipe_params, visibility, allowed_groups` (tenant server-set) | 201 `{status,surface_id}`; 400/403/404/422/503 | AU; visibility≠private needs tenant scope (`:528`) | INSERT `navigator.ui_surfaces` |
| GET | `/api/v1/ui/surfaces/{surface_id}` | `_get_one` `:457` + `SurfaceNegotiationService` `:218-310` | Fetch one surface; content negotiation `?format=json|html` > Accept > JSON | query `share?`, `format?` | JSON `{status,envelope,metadata}` or `text/html` rendered on the fly by `InteractiveHTMLRenderer` (501 if ai-parrot-visualizations missing, 422 on render fail) | AU+SCOPE/share (410 bad token) | read |
| PATCH | `/api/v1/ui/surfaces/{surface_id}` | `patch`→`_patch_visibility` `:411,738-783` | Owner-only visibility/group change | `PatchVisibilityRequest` `:109-113`: `visibility, allowed_groups` | `{status,metadata}` | AU owner (SQL-enforced) | `update_visibility` |
| DELETE | `/api/v1/ui/surfaces/{surface_id}` | `_delete_surface` `:821-828` | Delete owned surface | – | `{status}` / 404 | AU owner | DELETE |
| POST | `/api/v1/ui/surfaces/{surface_id}/refresh` | `_refresh` `:617-686`, `_refresh_linked` `:688-736` | **Re-run data** for a surface: recipe-backed → `RecipeRunner.run(recipe, merged params, owner pctx)`; linked (`parrot_data_sources`) → `LinkedSurfaceService.refresh` with optimistic concurrency (409 "stale refresh") | `RefreshSurfaceRequest` `:96-99`: `params{}`; query `share?`, `format?` | negotiated JSON/HTML of updated surface; header `X-Parrot-Refresh-Warnings`; 409 if not refreshable; 502/422 recipe errors; 403 data-plane guard | AU+SCOPE/share; runs as **owner** pctx (`:643`) | `update_envelope` (+`expected_updated_at`) |
| POST | `/api/v1/ui/surfaces/{surface_id}/share` | `_mint_share` `:787-818` | Mint share token (read+refresh) | `MintShareRequest` `:102-106`: `expires_at?, ttl:bool` | 201 `{token,expires_at,permissions}` | AU owner | `navigator.ui_surface_shares` |
| DELETE | `/api/v1/ui/surfaces/{surface_id}/share/{token}` | `_revoke_share` `:830-840` | Revoke token | – | `{status}` | AU owner | shares |

Notes: there is **no PUT/PATCH of envelope/title** (store has `save(overwrite=True)` upsert `models/ui_surfaces.py:503-510`, unexposed); no versions/history; refresh is whole-surface (no per-component refresh).

## 2. A2UI agent runtime, mirror, deep-link (`A2UIHandler`, AU; extends AgentTalk)

Handler `S/handlers/a2ui.py:83-344`; routes `manager.py:2326-2331`.

| Method | Path | Handler | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/agents/{agent_id}/a2ui/capabilities` | `_get_capabilities` `a2ui.py:240-242` | Agent A2UI capabilities doc | – | `{"v1.0":{supportedCatalogIds:[parrot, basic],acceptsInlineCatalogs:false}}` (`C/outputs/a2ui/catalog/export.py:195-212`) | AU | – |
| GET | `/api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` | `_get_surface` `:266-301` | Mirror of ui_surfaces GET (same negotiation + `resolve_surface_access`) | query `share?,format?,user_id?,session_id?` | same as §1 GET one | AU+SCOPE | `ui_surfaces` |
| POST | `/api/v1/agents/{agent_id}/a2ui` | `post` `:155-224` | Dispatch renderer→agent envelopes (JSONL / list / single) through `A2UIRuntime`; may trigger an `agent.ask` user turn with `a2ui_surface_state` | raw A2UI v1.0 envelopes (`extra=forbid`); query `user_id,session_id,agent_name` (`:101-119`) | single envelope as `application/a2ui…` (`A2UI_MEDIA_TYPE`) or `{messages:[...]}`; error envelopes 400 | AU + `build_principal_context` (roles empty → role-gated PBAC denies) `:187` | surface state in agent `conversation_memory` (`ConversationMemorySurfaceStore` `:150-153`) |
| GET | `/api/v1/agents/{agent_id}/a2ui` | `_get_stream` `:303-344` | SSE stream of pending `callRendererFunction` envelopes; 15 s keepalive | query `session_id` | `text/event-stream` `data: {...}` | AU | marks delivered in conversation memory |
| GET | `/api/v1/a2ui/resume/web` | `DeepLinkResumeHandler.landing` `S/handlers/deeplink.py:165`; reg `:181-220`, mounted by `manager.py:1667-1691` only if `app['redis']` | Confirm page for single-use deep-link (prescanner-safe) | query `token` | HTML | MW (token-based) | Redis `DeepLinkService` |
| POST | `/api/v1/a2ui/resume/web` | `resume` `deeplink.py:174-178` | Consume token → `A2UIRuntime.dispatch(transport="deeplink")` → inject structured user message into original session | query `token` | JSON `{...}`, friendly "session expired" on replay | MW | Redis (single-use) |

Static: `STATIC_DIR/a2ui/transforms/*.js` + signed `manifest.json` published by `publish_transforms` (`S/handlers/a2ui_transforms.py:1-5`, `C/outputs/a2ui/linked/manifest.py:66-69`) and served anonymously via the framework `/static/` mount (`app.py:66-73`, `enable_static=True`). **No HTTP endpoint exposes the A2UI component catalog definition** — `export_catalog_definition` (`C/outputs/a2ui/catalog/export.py:215`) is only used by a file writer (`:300-310`). ECharts/Chart.js bundles are **inlined** by renderers (`packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py:6`, `interactive_html.py:4`), not served by a route.

## 3. Infographics — generate, deterministic render, templates/themes (`InfographicTalk`, AU; extends AgentTalk)

Handler `S/handlers/infographic.py:70-839`; routes `manager.py:2429-2461` (literal resources before `{agent_id}`).

| Method | Path | Handler | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| POST | `/api/v1/agents/infographic/{agent_id}` | `_generate_infographic` `infographic.py:158-265` | LLM-driven `bot.get_infographic()` | JSON `{query, template="basic", theme?, use_vector_context=true, use_conversation_history=false, session_id?, user_id?, …extra kwargs}`; `?format=html|json` / Accept (default HTML) `:819-839` | `text/html` or `{infographic:{...}}` | AU (+agent resolution) | fire-and-forget `ArtifactStore.save_artifact` type `infographic` (`:267-329`) |
| POST | `/api/v1/agents/infographic/render` | `_render_infographic_deterministic` `:331-437` | **LLM-free** template render from datasets + `SectionDescriptor` | `RenderRequest` `S/handlers/infographic_render.py:119-150`: `datasets{alias: InlineDataset{orient: records|split, data} | null}` (null ⇒ multipart part `dataset:<alias>` CSV/Parquet), `template` (registered only), `descriptor: SectionDescriptor` (`C/tools/infographic_sections.py:80`; `template, mode∈{jinja,data-splice}, sections[{name,target,datasets,columns,shape,hint}], params, dataset_sql, layout, narrative`), `theme?, marker_id, agent_id?, session_id?, persist=true, public=false, async=false`; JSON or multipart; 50 MB cap (`:63`) | HTML (`X-Artifact-Persisted`) or `RenderResponse` `:153-180` `{artifact_id,url,url_note,template,sections_validated,persisted,timings}`; `async=true` → 202 `{job_id}` | AU | ArtifactStore (awaited) ; `public=true` also writes `STATIC_DIR` → `/static/<file>` (`infographic_render.py:632-664`) |
| GET | `/api/v1/agents/infographic/render/jobs/{job_id}` | `_get_render_job_status` `:655-670` | Poll async render | – | `RenderJob` `{job_id,status∈pending|running|done|failed,result?,error?,created_at,deadline}` (`infographic_render.py:182-199`) | AU | Redis `RenderJobStore` (`S/handlers/render_jobs.py:70`), 1-day TTL on terminal |
| GET | `/api/v1/agents/infographic/templates` | `_handle_templates_get` `:671-692` | List templates | `?detailed=true` | names or `[{name,description}]` | AU | in-process `infographic_registry` (`C/models/infographic_templates.py:512`) |
| GET | `/api/v1/agents/infographic/templates/{template_name}` | same | Template def | – | `InfographicTemplate` (`name, description, block_specs[{block_type,required,min/max_items,constraints}], default_theme, js_bundles`) `C/models/infographic_templates.py:21-60` | AU | in-memory |
| POST | `/api/v1/agents/infographic/templates` | `_handle_templates_register` `:717-765` | Register template (global only; `scope=session` → 403) | `{template: InfographicTemplate, scope?}` | 201 | AU + PBAC(`agent:configure`, agent `*`) | **in-memory only** (`C/helpers/infographics.py:50-75`) — lost on restart |
| GET | `/api/v1/agents/infographic/themes[/{theme_name}]` | `_handle_themes_get` `:694-715` | List/get themes | `?detailed=true` | names / `ThemeConfig` | AU | in-memory `theme_registry` |
| POST | `/api/v1/agents/infographic/themes` | `_handle_themes_register` `:767-817` | Register theme | `{theme: ThemeConfig, scope?}` | 201 | AU + PBAC(`agent:configure`) | in-memory |
| GET | `/api/v1/agents/infographic/{agent_id}` | `get` `:119-156` | Endpoint info | – | JSON | AU | – |

No PUT/DELETE for templates/themes.

## 4. Infographic recipes (replayable report definitions) — `RecipeHandler` (AU)

Handler `S/handlers/infographic_recipes.py:153-320`; routes `manager.py:2496-2498`. **Requires** `register_recipe_routes(app, recipe_store=…, dataset_manager=…)` (`:78-125`) — **not called anywhere in `app.py`/manager** ⇒ endpoints return 500 "recipe_store is not configured" in the stock host (`manager.py:2490-2495` comment). Store: `FileRecipeStore` (`C/outputs/a2ui/recipes/store.py:230`) or `DBRecipeStore` (`:304`, actually Redis w/ in-memory fallback). Model `InfographicRecipe` (`C/outputs/a2ui/recipes/models.py:235`): `schema_version, name, title, description, owner, params[RecipeParam{name,default,description}], data_sources[DataSourceSpec{dataset,alias,sql,conditions,force_refresh}], transforms[TransformStep{transformer,inputs,params,output_key}], layout: LayoutSpec{component,child,children,metadata}, render: RenderSpec{profile="interactive-html",theme,layout,delivery}, schedule?: ScheduleSpec{principal,tenant_id,roles}, narrative?, section_descriptor?, updated_at`.

| Method | Path | Handler | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/infographic_recipes` | `get` `:180-205` | List caller's recipes | – | `{status,count,recipes}` | AU (owner-scoped) | recipe store |
| GET | `/api/v1/infographic_recipes/{name}` | `get` | Full recipe | – | `{status,recipe}` | AU owner | " |
| PUT | `/api/v1/infographic_recipes/{name}` | `put` `:207-246` | Create/overwrite (owner defaulted from session) | `InfographicRecipe` JSON | 200/422 | AU | " |
| DELETE | `/api/v1/infographic_recipes/{name}` | `delete` `:248-264` | Delete | – | `{status}` | AU owner | " |
| POST | `/api/v1/infographic_recipes/{name}/run` | `post` `:266-320` | Replay recipe (fresh data → render) | `{params?}` | `{status, artifact:{artifact_id,filename,mime_type,size,storage_ref}}`; 422 `RecipeRunException` | AU; pctx=owner (`:295`) | ArtifactStore (via runner) |

Scheduler hook: callback `run_infographic_recipe` (`RunInfographicRecipeCallback` `:323-388`) on `CALLBACK_REGISTRY`, runs as `schedule.principal` — usable from the scheduler API (§9).

## 5. Artifacts (per-thread charts / tables / maps / canvas / infographic / interactive / export)

Handlers `S/handlers/artifacts.py`; mounted by **host** `app.py:236-250`. Store `ArtifactStore` (`C/storage/artifacts.py:27-235`) created in `BotManager.on_startup` (`manager.py:2746-2756`) over `build_conversation_backend()` (DynamoDB/Mongo/Postgres/SQLite backends `C/storage/backends/`) + S3 overflow (`definition_ref`). Model `Artifact` (`C/storage/models.py:275-293`): `artifact_id, artifact_type∈{chart,map,table,canvas,infographic,interactive,dataframe,export} (:244-253), title, created_at, updated_at, source_turn_id, created_by∈{user,agent,system}, definition{}, definition_ref`. A `CanvasDefinition{tab_id,title,blocks[CanvasBlock{block_id,block_type∈markdown|heading|chart_ref|data_table|agent_response|infographic_ref|note|code|image|divider, content, artifact_ref, source_turn_id, display_options, position}], layout="vertical", export_config}` exists (`C/storage/models.py:404-435`) but **no endpoint validates against it** (definition is free-form).

| Method | Path | Handler | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/threads/{session_id}/artifacts` | `ArtifactListView.get` `artifacts.py:117-158` | List artifacts of a thread | query `agent_id` | `{artifacts:[ArtifactSummary{id,type,title,created_at,updated_at}],count}` | AU (user from session) | ArtifactStore |
| POST | `/api/v1/threads/{session_id}/artifacts` | `ArtifactListView.post` `:160-247` | Save artifact (e.g. canvas tab, user chart) | `{artifact_id, artifact_type, title, agent_id, definition, source_turn_id?, created_by?}` | 201 `{artifact_id,…}` | AU | save (overflow to S3) |
| GET | `/api/v1/threads/{session_id}/artifacts/{artifact_id}` | `ArtifactDetailView.get` `:291-372` | Get artifact; `Accept: text/html` / `?format=html` / `?download=1` → self-contained HTML w/ CSP | query `agent_id, format, download` | `{artifact}` or HTML (attachment on download) | AU | read |
| PUT | `/api/v1/threads/{session_id}/artifacts/{artifact_id}` | `.put` `:374-433` | Replace `definition` | `{agent_id, definition}` | `{message,artifact_id}` | AU | update (old overflow deleted) |
| DELETE | `/api/v1/threads/{session_id}/artifacts/{artifact_id}` | `.delete` `:435-528` | Delete | query `agent_id` | JSON | AU | delete |
| GET | `/api/v1/artifacts/public/{signature}/{artifact_id}.html` | `ArtifactPublicHTMLView.get` `:530-684` | HMAC-signed frozen HTML for `<iframe>` embed (`INFOGRAPHIC_SIGNING_KEY`, CSP `frame-ancestors`) | path sig `{expiry}.{hmac}`; query `agent_id,session_id,user_id` | `text/html` | PUB (`app.py:304`) | read |

Artifacts are also auto-saved by AgentTalk structured outputs (`S/handlers/agent.py:~2963-3058`) and InfographicTalk.

## 6. Agent chat & output modes (AgentTalk, AU + PBAC)

Handler `S/handlers/agent.py:114-3318`; routes `manager.py:2317-2318`.

| Method | Path | Handler | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| POST | `/api/v1/agents/chat/{agent_id}` | `post` `agent.py:1523-2047` | Main chat; multipart (attachments) or JSON | `{query, session_id?, user_id?, agent_name?, stream=false, background=false, output_mode, output_format?, format_kwargs, search_type, return_sources, use_vector_context, use_conversation_history, message_id, turn_id, data, hitl_response, llm, ws_channel_id, avatar_bifurcate, method_name?}` (pops at `:1634-1708`). `output_mode` ∈ `OutputMode` (`C/models/outputs.py:26-55`): default,text,json,terminal,markdown,yaml,html,jinja2,jupyter,notebook,template_report,application,chart,code,map,image,echarts,table,card,telegram,msteams,whatsapp,slack,**infographic,interactive**,sql_analysis,**structured_chart,structured_table,structured_map,a2ui**. infographic/interactive force non-stream (`:1692-1696`) | JSON `{input,output,data,response,output_mode,code,metadata{model,provider,session_id,turn_id,user_id,response_time,usage,…},sources,tool_calls, a2ui_envelope?, artifact_id?}` (`:2797-2925`); A2UI mode special envelope (`:2800-2826`); infographic envelope `{output:<html_url|inline>, artifact_id, data:[DatasetResult], metadata{html_url,template_name,…}}` (`:3134-3228`); panel dashboards served as HTML (`:3230`); `stream=true` → chunked text + `\n\x00` + JSON tail | AU + PBAC(`agent:chat`) `:1580-1586` | chat history (ChatStorage), artifact auto-save |
| POST | `/api/v1/agents/chat/{agent_id}/{method_name}` | `post` (method invocation) | Invoke a public bot method (e.g. `refresh_data`) — denylist `_check_methods` `:711-741` | as above | method result | AU + PBAC | – |
| PATCH | `/api/v1/agents/chat/{agent_id}` | `patch` `:2049-2156` | Session-scoped tools/MCP config, data refresh | `{tools?, mcp_servers?[...], …}` | JSON | AU + PBAC(`agent:configure`) | navigator_session (`{agent}_tool_manager`) |
| PUT | `/api/v1/agents/chat/{agent_id}` | `put` `:2158-2238` | Upload Excel / add query slug to agent | multipart / JSON | JSON | AU | session DatasetManager |
| GET | `/api/v1/agents/chat/{agent_id}[/debug]` | `get` `:2240-2480` | Endpoint info / `debug` | – | JSON | AU | – |

Related: `AgentVoiceTalk` `/api/v1/agents/voice/{agent_id}` & `/api/v1/agents/transcribe/{agent_id}` (`manager.py:1796-1832`, optional); `/ws/voice` (`manager.py:1834-1866`); avatar & OpenAI-compat routes (`manager.py:2112-2222`).

## 7. Streaming & websockets

| Method | Path | Handler | Purpose | Auth |
|---|---|---|---|---|
| POST | `/bots/{bot_id}/stream/sse` | `StreamHandler.stream_sse` `S/handlers/stream.py:114`; reg `:505` via `manager.py:2522` | SSE token stream (+`tool_event` frames) | MW |
| POST | `/bots/{bot_id}/stream/ndjson` | `stream_ndjson` `:189` | NDJSON `{type:content|ai_message}` | MW |
| POST | `/bots/{bot_id}/stream/chunked` | `stream_chunked` `:245` | chunked text | MW |
| GET (WS) | `/bots/{bot_id}/stream/ws` | `stream_websocket` `:287-475` | WS: msgs `auth`, `stream`/prompt, `ping`; server `connection, stream_start, content, ai_message, stream_complete, error, pong` | MW + `Sec-WebSocket-Protocol: jwt,<token>` preauth middleware `:513-518` |
| GET (WS) | `/ws/userinfo…` | `UserSocketManager` `S/handlers/user.py`, mounted `app.py:197-203` | per-user push channels (`information`,`following`); used by web HITL | see `_admin_bots` section |
| GET (SSE) | `/api/v1/agents/{agent_id}/a2ui` | see §2 | renderer-function push | AU |

## 8. Datasets & data access exposed by parrot

`DatasetManagerHandler` (AU) `S/handlers/datasets.py:139-599`, routes `manager.py:2488-2489`. **Session-scoped** DatasetManager (navigator_session key `{agent}_dataset_manager`, cloned from agent catalog `:162-177`); not durable.

| Method | Path | Handler | Purpose | Request | Response |
|---|---|---|---|---|---|
| GET | `/api/v1/agents/datasets/{agent_id}` | `get` `datasets.py:179-257` | List datasets | – | `DatasetListResponse{datasets[],total,active_count}` (`C/models/datasets.py:83-93`) |
| GET | `/api/v1/agents/datasets/{agent_id}/{dataset_id}` | `get` | Describe one dataset (schema, optional sample rows) | `?samples=true` | metadata JSON |
| PATCH | `/api/v1/agents/datasets/{agent_id}` | `patch` `:259-309` | activate/deactivate | `DatasetPatchRequest{dataset_name, action}` | JSON |
| PUT | `/api/v1/agents/datasets/{agent_id}` | `put` `:311-381` | Upload Excel/CSV (≤50 MB) | multipart | 201 `DatasetUploadResponse{name,rows,columns,columns_list}` |
| POST | `/api/v1/agents/datasets/{agent_id}` | `post` `:383-561` | Add dataset: `DatasetQueryRequest{name, query?, query_slug?, description?, datasource{type∈query_slug|sql|table|airtable|smartsheet|dataframe,…}}` (`C/models/datasets.py:38-80`) | 201 |
| DELETE | `/api/v1/agents/datasets/{agent_id}` | `delete` `:563-599` | Remove | `?name=` | `DatasetDeleteResponse` |

**Unmounted library handlers** (documented `app.router.add_route(...)` usage only in docstrings, no caller): `DatasetFilterHandler` `/api/v1/filters/{agent_id}[/schema|/values/{name}]` (`C/handlers/dataset_filter_handler.py:1-30`) — filter schema/values/apply across datasets; `SpatialFilterHandler` `/api/v1/spatial/{agent_id}[/manifest]` (`C/handlers/spatial_filter_handler.py:20-22`).

**QuerySource (mounted by host `app.py:109-110`, external lib `.venv/.../querysource/services.py:172-356`)** — the real data plane for refreshable widgets: `GET|POST /api/v2/services/queries/{slug}` (run slug), `PATCH|HEAD …/{slug}` (columns), `GET /api/v2/services/queries` (multi), `POST /api/v1/queries/run|test|schema`, `GET /api/v1/queries/describe`, `/api/v1/queries/{slug}/describe|columns`, `/api/v1/queries/vocabulary`, tenant variants `/api/v1/{tenant}/queries/...`, `/api/v1/management/queries[/{slug}]` (slug CRUD, `QueryManager`), `/api/v3/queries[/{slug}]{meta}` (GET/POST/…), `/api/v3/qs/components`, `POST /api/v3/qs/validate`, `/api/v2/queries/{driver}/{source}/{attribute}[/{var}]`, `/api/v1/datasources*` (DatasourceView CRUD, drivers list/test), `/api/v2/qs/variables[/{program}]`, `/api/v1/qs/audit_log`, `/api/v1/services/qsurl/{path}`, Airtable OAuth.

## 9. Dashboards (legacy Mongo boards with tabs + widgets) — **gated `ENABLE_DASHBOARDS` (default False, `C/conf.py:95`)**

`DashboardHandler` / `DashboardTabHandler` `S/handlers/dashboard_handler.py:74-634`; routes `manager.py:2560-2564`; indexes `_ensure_dashboard_indexes` `:37-71` (startup `manager.py:2784-2785`). Persistence: DocumentDB/Mongo collections `dashboards`, `dashboard_tabs` (`:33-34`). **Auth: MW only — no decorator, no ownership check; `user_id` may come from body or `request['user_id']`** (`:89-91,186`).

| Method | Path | Handler | Purpose | Request | Response |
|---|---|---|---|---|---|
| GET | `/api/v1/dashboards` | `get`→`_get_list` `:99,138-162` | List | `?module_id,&user_id` | list |
| GET | `/api/v1/dashboards/{dashboard_id}` | `_get_one` `:111-136` | Dashboard + its tabs | – | doc + tabs |
| POST | `/api/v1/dashboards` | `post` `:164-206` | Create | `{title*, dashboard_id?, module_id, user_id?, attributes{}}` | 201 |
| PUT / PATCH | `/api/v1/dashboards/{dashboard_id}` | `put` `:208-257` / `patch` `:259-310` | Replace / partial | doc fields | JSON |
| DELETE | `/api/v1/dashboards/{dashboard_id}` | `delete` `:312-338` | Delete + cascade tabs | – | JSON |
| GET | `/api/v1/dashboards/{dashboard_id}/tabs[/{tab_id}]` | `DashboardTabHandler.get` `:367-416` | List/get tabs | – | list/doc |
| POST | `/api/v1/dashboards/{dashboard_id}/tabs` | `post` `:418-493` | Create tab = **page** | `{title*, tab_id?, icon, index, layout_mode="grid", grid_mode="flexible", template="default", pane_size=300, closable, component, widgets:[...], module_id, user_id}` | 201 `{tab_id}` |
| PUT / PATCH / DELETE | `/api/v1/dashboards/{dashboard_id}/tabs/{tab_id}` | `put` `:495-550` / `patch` `:552-605` / `delete` `:607-634` | Update/partial/delete tab | tab fields | JSON |

## 10. Export / render utilities

| Method | Path | Handler | Purpose | Auth |
|---|---|---|---|---|
| POST | `/api/v1/utilities/print2pdf` | `PrintPDFHandler.post` `S/handlers/print_pdf.py:40-116`; reg `manager.py:2508` | HTML → PDF (weasyprint). `text/html` body or JSON `{html, filename, disposition}` → `application/pdf` | AU |
| GET | `/api/v1/threads/{sid}/artifacts/{id}?download=1` | §5 | self-contained HTML download | AU |
| GET | `/api/v1/{tenant}/forms/{uid}/render/{format}` | formdesigner | html/adaptive/xml/pdf/audio/a2ui | see §12 |
| GET | `/api/v1/thales/{run_id}/artifacts` | `ThalesArtifactsHandler` `S/handlers/thales.py:262` | research-run artifacts (slides/report) | see admin section |

---

## 11. ai-parrot server — Admin / Bots / Studio / misc endpoint inventory

Repo: `/home/jelitox/repos/trocglobal/ai-parrot` (read-only survey, 2026-09-30).
All paths below are relative to `packages/ai-parrot-server/src/parrot/` unless prefixed `app.py` (repo root).

Legend — Auth: `IA` = `@is_authenticated()`, `US` = `@user_session()`, `MW` = no class decorator (relies on global navigator-auth middleware only), `PBAC(x)` = `_pbac_gate`/evaluator check on action `x` (fail-open when no PDP), `own` = owner check with superuser bypass, `EAA` = `BotManager.get_bot(..., request=)` → `enforce_agent_access` (manager/manager.py:744-772).
ModelView/FormModel/AbstractModel `.configure(app, path)` auto-registers `path`, `path/{id}` (+ `path{meta}`) and exposes GET/POST/PUT/PATCH/DELETE generic CRUD.

### 0. Where routes are mounted

| Mount point | What |
|---|---|
| manager/manager.py:2313-2315 | ChatHandler `/api/v1/chats`, `/api/v1/chat/{chatbot_name}[/{method_name}]` |
| manager/manager.py:2348-2349 | AgentKnowledgeHandler |
| manager/manager.py:2380-2417 | UserAgentHandler, EphemeralUserAgentHandler, ToolCatalogHandler, PromptTunerHandler |
| manager/manager.py:2510 | `ChatbotHandler.configure(app, "/api/v1/bots")` |
| manager/manager.py:2516 | ToolList `/api/v1/agent_tools` (name `tools_list`, idempotent) |
| manager/manager.py:2518-2519 | BotHandler `/api/v1/chatbots[/{name}]` |
| manager/manager.py:2529-2540 | Crew routes (only if `ENABLE_CREWS`, default False — ai-parrot/src/parrot/conf.py:96) |
| manager/manager.py:2543 | FlowCheckpointHandler `/api/v1/flows/checkpoints` |
| manager/manager.py:2552-2558 | BotConfigHandler, BotConfigTestHandler, ChatInteractionHandler |
| manager/manager.py:2566-2577 | credentials, `setup_studio_routes`, mcp_helper, thales, `setup_admin_ui`, CommCenter |
| scheduler/manager.py:1818-1827 | Scheduler REST (via `AgentSchedulerManager.setup`, called at app.py:129) |
| app.py:134-149 | FeedbackType, ChatbotFeedback, PromptLibrary, UserPrompts, ChatbotUsage, SharingQuestion, BotManagement |
| app.py:197 | `UserSocketManager(route_prefix="/ws/userinfo")` |
| app.py:211-215 | VideoReelHandler, FlowAuthoringHandler, VectorStoreHandler `.setup()` |
| app.py:131 | `configure_job_manager(app, use_redis=True)` (handlers/jobs — infra only, **no HTTP routes**) |

#### Mount check (grep over packages/, app.py, appauto.py)
- **handlers/threads.py (`ThreadListView`, `ThreadDetailView`) — NOT MOUNTED anywhere.** Only artifacts sub-routes `/api/v1/threads/{session_id}/artifacts[...]` exist (app.py:236-245, handlers/artifacts.py). Its docstring routes (`/api/v1/threads`, `/api/v1/threads/{session_id}`) are dead code.
- **handlers/user_objects.py (`UserObjectsHandler`) — not an HTTP handler** (plain class); used internally by handlers/agent.py:45,143 and handlers/datasets.py:33,159 to build session-scoped ToolManager/DatasetManager.
- **handlers/scheduler.py — MOUNTED** by scheduler/manager.py:1812-1827 (lazy import inside `AgentSchedulerManager.setup`).
- handlers/jobs/* — JobManager + RedisJobStore (prefix `parrot:jobs`, TTL 86400; jobs/worker.py:15). Consumed by video_reel, flow_authoring, stores, crew execution; no routes of its own.

---

### 1. Agent Studio — `/api/v1/astudio/*` (handlers/studio/, registered handlers/studio/__init__.py:26-145)

Every view: `IA`+`US`, subclass of `StudioBaseView` (_base.py:121); PBAC namespace `astudio:<area>` via `_pbac_gate` (_base.py:308, fail-open); `_require_owner` (_base.py:230, superuser group bypass _base.py:44). Errors: `StudioError{message,code,details}` (models.py:23). Plain `add_view` (no `{id:.*}` catch-all).

| METHOD | PATH | Handler file:line | Purpose | Request | Response | Auth extra | Persistence |
|---|---|---|---|---|---|---|---|
| GET | /astudio/agents | agents.py:175 (`StudioAgentsHandler`, reg __init__:46) | list agents (DB + registry) | — | `{agents[],count}` | — | `navigator.ai_bots` + AgentRegistry |
| GET | /astudio/agents/{name} | agents.py:175 (reg :47) | one agent | — | agent dict (origin, enabled, class_name, module, owner) | — | same |
| POST | /astudio/agents | agents.py:209 | create live agent, opt. persist YAML | `CreateAgentRequest{name,bot_class,llm,description,persist,category,config}` models.py:38 | agent dict | PBAC astudio:agents:create | runtime registry; YAML under `AGENTS_DIR/agents/<category>/` if persist |
| DELETE | /astudio/agents/{name} | agents.py:373 | delete factory/YAML agent | — | `{deleted}` | PBAC agents:delete, own | unlinks YAML |
| POST | /astudio/agents/{name}/reload | agents.py:450 (`StudioAgentReloadHandler`, reg :48) | hot-reload agent | — | `ReloadResult` | PBAC agents:reload | — |
| GET | /astudio/drafts[/{name}] | drafts.py:162 (reg :53-54) | list/read Python agent drafts | — | draft dict(s) + validation_report | — | `navigator.studio_drafts` (models/studio_drafts.py:41) + `AGENTS_DIR/_drafts/*.py` |
| POST | /astudio/drafts | drafts.py:181 | save + static-validate draft | `SaveDraftRequest{name,source}` drafts.py:32 | draft + `DraftValidationReport{passed,errors[]}` | PBAC drafts:create | same |
| DELETE | /astudio/drafts/{name} | drafts.py:243 | delete draft | — | `{deleted}` | PBAC drafts:delete, own | same |
| POST | /astudio/drafts/{name}/activate | drafts.py:279 (`StudioDraftActivateHandler`, reg :55) | move draft into AGENTS_DIR & import | `ActivateDraftRequest{replace}` drafts.py:39 | activation result | PBAC drafts:activate, own | file move + `activated_at` |
| GET | /astudio/agents/{name}/files/{kind}[/{filename}] | files.py:170 (reg :60-61) | list/read agent asset files; kind ∈ identity/kb/skills (files.py:26) | — | list / file content | — | `AGENTS_DIR/<agent>/<kind>/` |
| PUT | /astudio/agents/{name}/files/{kind}/{filename} | files.py:216 | write file | raw body | `{path,kind,reload_required:true}` | PBAC files:write, own | filesystem |
| DELETE | same | files.py:280 | delete file | — | `{deleted,reload_required}` | PBAC files:delete, own | filesystem |
| GET | /astudio/skills[?category&owner] | skills_catalog.py:276 (reg :75) | org-wide skills catalog | query `category`,`owner` | list of entries | — | `navigator.ai_skills_catalog` (SkillCatalogEntry: skill_id,name,description,category,owner,triggers,body,**version**,status,search_index_stale) |
| GET | /astudio/skills/{id} | skills_catalog.py:276 (reg :81) | one skill + **versions** (registry `get_skill_versions`, :323) | — | entry + `versions[]` | — | PG + SkillRegistry (git-like versions) |
| POST | /astudio/skills | skills_catalog.py:333 | publish skill | `SkillPublishRequest{name,description,category,triggers[],body}` models.py:78 | entry | PBAC skills:publish | PG first, registry dual-write best-effort |
| PUT | /astudio/skills/{id} | skills_catalog.py:397 | update skill (new version) | same | entry | PBAC skills:update, own | same |
| DELETE | /astudio/skills/{id} | skills_catalog.py:442 | delete | — | — | PBAC skills:delete, own | same |
| POST | /astudio/skills/resync | skills_catalog.py:602 (reg :80) | repair stale index rows | — | counts | PBAC skills:resync + superuser only | same |
| POST | /astudio/agents/{name}/skills/import/{id} | skills_catalog.py:527 (reg :82) | copy catalog skill into agent skills/ | — | file info | PBAC skills:import | filesystem |
| GET | /astudio/keys | byok.py:99 (reg :93) | masked BYOK keys list | — | masked list | — | DocumentDB `user_llm_keys` (byok.py:31) |
| POST | /astudio/keys | byok.py:144 | store LLM API key (AES-GCM vault) | `ByokKeyRequest{provider,api_key:SecretStr}` models.py:97 | masked | PBAC keys:store | session vault + DocumentDB |
| DELETE | /astudio/keys/{provider} | byok.py:231 (reg :94) | delete key | — | — | PBAC keys:delete | same |
| POST | /astudio/agents/{name}/test[/ask] | testing.py:235 (reg :104-105) | ask session-scoped test clone | `TestAskRequest{query,use_byok}` testing.py:55 | AI response | PBAC testing:ask + EAA | session key (testing.py:178) |
| DELETE | /astudio/agents/{name}/test | testing.py:312 | drop test clone | — | — | — | session |
| POST | /astudio/tools/{slug}/execute | testing.py:344 (reg :106) | deterministic tool exec | `ToolExecuteRequest{args}` testing.py:72 | tool result | PBAC testing:execute | — |
| POST | /astudio/agents/{name}/tools | testing.py:408 (reg :107) | assign tools/toolkits | `ToolAssignRequest{tools[],toolkits[{slug,params}]}` testing.py:85 | result | PBAC agents:assign_tools, own | runtime |
| GET | /astudio/toolkits/{slug}/schema | toolkits.py:237 (reg :113) | toolkit config JSON schema | — | schema | — | — |
| POST | /astudio/agents/{name}/toolkits | toolkits.py:281 (reg :114) | attach toolkit to live agent | `ToolkitAssignRequest{slug,params}` toolkits.py:65 | `{reload_required:false}` | PBAC toolkits:assign, own | runtime |
| GET | /astudio/agents/{name}/toolkit-config | toolkit_config.py:71 (reg :125) | persisted toolkit specs (masked) | — | `AgentToolkitsResponse{agent,editable,reason,toolkits[],unavailable[]}` | PBAC+own (:38-45) | `ai_bots.toolkit_config` or agent YAML (tooling_store.py:292) |
| PUT/DELETE | /astudio/agents/{name}/toolkits/{slug} | toolkit_config.py:93/115 (reg :126) | persist/remove toolkit spec; secrets → vault | `ToolkitConfigPutRequest{params,user_overridable[]}` models.py:112 | `ToolkitPersistResponse{agent,slug,reload_required,persisted}` | PBAC+own | DB row / YAML + vault |
| GET | /astudio/agents/{name}/toolkits/{slug}/options/{param} | toolkit_config.py:135 (reg :127) | dynamic option list for a param | — | `ToolkitOptionsResponse{options[]}` | PBAC+own | — |
| GET/PUT | /astudio/agents/{name}/mcp-servers | toolkit_config.py:179/194 (reg :130) | persisted MCP servers (replace list) | `AgentMcpServersPutRequest{servers[]}` | `AgentMcpServersResponse` | PBAC+own | `ai_bots.mcp_servers` / YAML + vault |
| GET/PUT/DELETE | /astudio/agents/{name}/toolkits/{slug}/me | toolkit_overrides.py:93/127/189 (reg :134) | caller's per-user toolkit override | params dict | override | PBAC toolkits:override (no owner check) | vault `toolkit_{slug}_{name}_user` |
| GET | /astudio/catalog/{kind} | catalog.py:203 (reg :140) | reference catalogs: base-classes, llm-clients, tools, vector-stores | — | list | — | process cache |
| POST | /astudio/assistant | meta_agent.py:77 (reg :145) | AgentStudio meta-agent chat | `AssistantAskRequest{query,use_byok}` meta_agent.py:36 | AI response | PBAC assistant:ask | per-app cache + session |
| DELETE | /astudio/assistant | meta_agent.py:123 | reset assistant session | — | — | — | session |

### 2. Admin UI — server/ui/serving.py (`setup_admin_ui`, called manager/manager.py:2575)

| METHOD | PATH | Handler file:line | Purpose | Response | Auth |
|---|---|---|---|---|---|
| GET | /api/v1/admin/status | ui/status.py:247 `AdminStatusHandler` (reg serving.py:196) | server health | `AdminStatus{name,version,uptime_seconds,agents{database,registry,loaded},crews,dependencies{postgres,redis,vector_store: {status,detail,latency_ms}}}` (status.py:34-60) | IA+US |
| GET | /api/v1/admin/catalog | ui/catalog.py:134 `AdminCatalogHandler` (reg serving.py:197) | option lists for agent form | `AdminCatalog{llm_providers[],operation_modes[],memory_types[],knowledge_bases[{class_path,...}],bot_class_default}` (catalog.py:34) | IA+US |
| GET | /admin, /admin/{tail:.*} | serving.py:237-238 `_spa_fallback` | Svelte SPA shell (history fallback), only if `ui/dist/index.html` exists | index.html (no-cache) | auth-excluded (registered on_startup, serving.py:88) |
| GET | /admin/assets/* | serving.py:221 static | hashed assets, immutable cache | files | auth-excluded |

ui/models.py `BotsListResponse` is a codegen-only descriptor for `GET /api/v1/bots` (not used at runtime). ui/chat_models.py similar.

### 3. handlers/bots.py

| METHOD | PATH | Handler file:line | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | /api/v1/bots[?include_disabled] | `ChatbotHandler.get` bots.py:578 (configure manager.py:2510) | list agents DB+registry | query include_disabled | `{agents[{name,source:database|registry,...BotModel}]}` | session; PBAC `agent:list` `filter_resources` (bots.py:597-603, list ~:663) | `navigator.ai_bots` (BotModel; PARROT_BOTS_TABLE) + registry |
| GET | /api/v1/bots/{id} | bots.py:578 | one agent by name | — | BotModel dict / registry dict | PBAC `agent:list` check_access | same |
| PUT | /api/v1/bots | bots.py:689 | create DB agent, configure, register; eager pgvector table | BotModel fields (name, llm, model_config, vector_store_config, tools, ...) | agent dict | session only (sets created_by) — **no PBAC on write** | ai_bots (+ pgvector table) |
| POST | /api/v1/bots/{id} | bots.py:958 / `_post_database` :990 | update agent (name, chatbot_id, created_* immutable) | partial BotModel | agent dict | session | ai_bots / registry YAML |
| DELETE | /api/v1/bots/{id} | bots.py:1116 | delete DB agent (or factory-origin YAML) | — | msg | session | ai_bots |
| GET | /api/v1/agent_tools | `ToolList.get` bots.py:1208 (class :1197) | registered tools | — | `{tools:{name:{tool_name,...}}}` | US; PBAC `tool:list` filter | registry |
| CRUD | /api/v1/chatbots/prompt_library[/{prompt_id}] | `PromptLibraryManagement` bots.py:83 (get :99; app.py:140) | shared prompt library; GET filters `chatbot_id` (UUID) **or** `agent_id` (slug) | PromptLibrary{prompt_id,chatbot_id,agent_id,title,query,description,prompt_category,prompt_tags,created_by...} | rows | ModelView session | `navigator.prompt_library` |
| CRUD | /api/v1/agents/user_prompts[/{prompt_id}] | `UserPromptsManagement` bots.py:142 (get :164; app.py:141) | per-user saved prompts; user_id forced from session | UserPrompts{prompt_id,user_id,chatbot_id,title,query,description,prompt_category,prompt_tags,**is_public**} | rows | session (explicit) | `navigator.users_prompts` |
| CRUD/POST | /api/v1/chatbots_usage[/{sid}] | `ChatbotUsageHandler` bots.py:178 (post :197; app.py:143) | log Q/A usage event | ChatbotUsage{chatbot_id,user_id,sid,source_path,platform,origin,user_agent,question,response,used_at} | row | ModelView | **BigQuery** `navigator.chatbots_usage` |
| GET | /api/v1/chatbots/questions/{sid} | `ChatbotSharingQuestion.get` bots.py:269 (app.py:144) | public-ish share of a Q/A by sid | — | `{chatbot,question,answer,at}` | MW | BigQuery chatbots_usage |
| GET | /api/v1/feedback_types/{feedback_type} | `FeedbackTypeHandler.get` bots.py:300 (app.py:134) | feedback reason enum list | path good/bad | `{feedback[]}` | MW | enum |
| POST | /api/v1/bot_feedback | `ChatbotFeedbackHandler.post` bots.py:324 (FormModel; app.py:138) | thumbs/feedback on a turn | ChatbotFeedback{chatbot_id,session_id,turn_id,user_id,rating,like,dislike,feedback_type,feedback} | row | FormModel | BigQuery `navigator.chatbots_feedback` |

### 4. handlers/chat.py

| METHOD | PATH | Handler file:line | Purpose | Request | Response | Auth |
|---|---|---|---|---|---|---|
| GET | /api/v1/chats | `ChatHandler.get` chat.py:118 (class :41; reg manager.py:2313) | welcome msg | — | `{message}` | IA+US |
| GET | /api/v1/chat/{chatbot_name} | chat.py:118 | bot info | — | `{chatbot,description,role,embedding_model,llm,temperature,config_file}` | IA+US |
| POST | /api/v1/chat/{chatbot_name} | `ChatHandler.post` chat.py:215 | RAG ask (JSON or SSE) | body `{query, session_id?, search_type='similarity', return_sources=True, return_context, stream}`; `?llm=&model=` override | AIMessage JSON or `text/event-stream` | IA+US + PBAC chatbot access (chat.py:47, :389) |
| POST | /api/v1/chat/{chatbot_name}/{method_name} | chat.py:215 (`_check_methods` :190) | invoke a public bot method with body params | method kwargs | method result | same; `_`-prefixed/forbidden blocked |
| PUT | /api/v1/chatbots[/{name}] | `BotHandler.put` chat.py:630 (class :594; reg manager.py:2518-2519) | create bot from config + insert BotModel | `{name, ...BotModel}` | `{message}` (202 if exists) | IA+US (no GET defined) |
| GET | /api/v1/bot_management[/{bot}] | `BotManagement.get` chat.py:708 (class :703; app.py:149) | list bots + vector store info | — | list | IA+US |
| PUT | /api/v1/bot_management/{bot} | chat.py:816 | multipart upload docs into bot vector store (loader per ext) | multipart files / form | load result | IA+US; writes vector table (default = bot name) |

### 5. Other handlers in scope

#### 5a. Agent config / testing / user agents / catalog / prompt / knowledge / chat persistence

| METHOD | PATH | Handler file:line | Purpose | Request / Response | Auth | Persistence |
|---|---|---|---|---|---|---|
| GET | /api/v1/agents/config[/{agent_name}][?category] | config_handler.py:102 (`BotConfigHandler` :31; reg manager.py:2552-2553) | list/get BotConfigs | → config dict(s) with `source` (registry/redis) | **MW only** | Redis `BotConfigStorage` + registry |
| PUT | /api/v1/agents/config | config_handler.py:256 | insert new BotConfig + register | BotConfig body | MW | Redis |
| POST | /api/v1/agents/config/{agent_name}[?persist=file] | config_handler.py:181 | full update (Redis or YAML) | BotConfig | MW | Redis / YAML |
| PATCH | /api/v1/agents/config/{agent_name} | config_handler.py:366 | partial update (Redis only) | fields | MW | Redis |
| DELETE | /api/v1/agents/config/{agent_name} | config_handler.py:325 | delete Redis config | — | MW | Redis |
| PUT/POST/DELETE | /api/v1/agents/test/{agent_name} | testing_handler.py:76/128/228 (`BotConfigTestHandler` :29; reg manager.py:2555) | start / ask / end test session clone | POST `{query,...}` | MW (navigator_session) | session key `_test_agent_<name>` |
| PUT | /api/v1/user_agents | agents/users.py:458 (`UserAgentHandler` :161; reg manager.py:2380) | create user bot (JSON or multipart config+files[]) | UserBotModel{name,role,goal,backstory,llm,model_config,use_vector,vector_config,documents,mcp_config(enc),tools_config(enc),operation_mode,memory_*,**permissions**,...} | IA+US | `navigator.users_bots` (AES-GCM blobs) + S3 `users_bots/{user_id}/{chatbot_id}` |
| PATCH/GET/DELETE | /api/v1/user_agents[/{chatbot_id}] | users.py:530/631/656 (reg :2381) | update / list `{bots[]}` / get / delete (+S3) | creds redacted on GET | IA+US, scoped to session user_id | same |
| POST | /api/v1/agents/user | agents/ephemeral.py:165 (reg manager.py:2385) | create in-memory ephemeral user agent | JSON/multipart → 201 `{chatbot_id,status:"creating"}` | IA+US | EphemeralRegistry (TTL) |
| GET | /api/v1/agents/user/{chatbot_id}/status | ephemeral.py:214 (reg :2389) | warm-up status | → EphemeralAgentStatus | IA+US | memory |
| PUT | /api/v1/agents/user/{chatbot_id} | ephemeral.py:253 (reg :2393) | promote to persisted user bot | → UserBotModel | IA+US | users_bots |
| DELETE | /api/v1/agents/user/{chatbot_id} | ephemeral.py:310 | discard | — | IA+US | memory |
| GET | /api/v1/tools/catalog | tools_catalog.py:99 (`ToolCatalogHandler` :86; reg manager.py:2398) | TOOL_REGISTRY catalog | → `[{slug,dotted_path,description}]` | IA+US | process cache |
| GET | /api/v1/agents/prompt/{agent_name} | prompt.py:364 (`PromptTunerHandler` :122; reg manager.py:2405-2417) | live prompt parts + rendered prompt + draft | → fields, layers, rendered, draft | IA+US | in-memory; draft in session |
| PATCH | /api/v1/agents/prompt/{agent_name} | prompt.py:400 | merge edits into session draft | `{fields:{},layers:{}}` | IA+US | session |
| POST | /api/v1/agents/prompt/{agent_name}/{suggest\|test\|save} | prompt.py:441 | LLM suggestions / test on clone / apply to live bot (in-memory only, lost on restart) | suggest/test `{query?}` | IA+US | memory |
| DELETE | /api/v1/agents/prompt/{agent_name} | prompt.py:588 | discard draft + clone | — | IA+US | session |
| GET | /api/v1/agents/knowledge/{agent_id}[/status\|/search\|/ask] | knowledge.py:119 (`AgentKnowledgeHandler` :49; reg manager.py:2348-2349) | index status / search JSON / ask_stream chunked; `?index=pageindex\|graphindex&tree=` | — | IA (no US) + EAA (knowledge.py:76) | PageIndex / GraphIndex |
| PUT/POST/DELETE | /api/v1/agents/knowledge/{agent_id} | knowledge.py:207/299/344 | upload files / edit node / delete node(`?node_id`) or tree (GraphIndex edit/delete → 501) | multipart / JSON | IA + EAA | same |
| GET | /api/v1/chat/interactions[?agent_id&limit&since] | chat_interaction.py:76 (`ChatInteractionHandler` :19; reg manager.py:2557) | list user conversations | → conversations[] | IA+US | ChatStorage (Redis + DocumentDB) |
| GET | /api/v1/chat/interactions/{session_id}[?agent_id&limit] | chat_interaction.py:76 (reg :2558) | load messages + metadata | → messages, metadata | IA+US | same |
| POST | /api/v1/chat/interactions | chat_interaction.py:153 | create conversation | `{session_id,agent_id,title}` | IA+US | same |
| PUT | /api/v1/chat/interactions/{session_id} | chat_interaction.py:201 | rename (title) | `{title}` | IA+US | same |
| DELETE | /api/v1/chat/interactions/{session_id} | chat_interaction.py:277 | delete conversation | — | IA+US | same |
| PATCH | /api/v1/chat/interactions/{session_id} | chat_interaction.py:330 | delete a turn | `{action,turn_id}` | IA+US | same |

#### 5b. WebSocket
| PROTO | PATH | Handler | Purpose | Messages | Auth | Persistence |
|---|---|---|---|---|---|---|
| WS | /ws/userinfo | `UserSocketManager` handlers/user.py:28 (navigator `WebSocketManager`; instantiated app.py:197) | user presence / channel pub-sub / notifications | in: `auth{token}`, `location`, `message`, `broadcast`, `direct{target,content}`, `subscribe`, `unsubscribe`, `get_users` (user.py:531-645); out: `auth_success`, `subscribed`, `users_list`, `direct`, `error`... ; server push `notify_channel()` (user.py:694) | in-band bearer token (`_validate_token` :179); path auth-excluded unless SaaS mode (:91) | Redis `user_socket:{username}` hash TTL 1d; default channels information/following |

#### 5c. Scheduler (handlers/scheduler.py, mounted scheduler/manager.py:1818-1827) — **all MW only (no decorators, no owner scoping)**

| METHOD | PATH | Handler file:line | Purpose | Request | Response |
|---|---|---|---|---|---|
| GET | /api/v1/parrot/scheduler/schedules[/{schedule_id}] | `SchedulerJobsHandler.get` scheduler.py:73 (class :55) | list / one schedule (+ APScheduler next run) | — | `{status,count,schedules[]}` / `{schedule}` |
| POST | /api/v1/parrot/scheduler/schedules | scheduler.py:93 | create schedule | `{agent_name*, schedule_type* (once/daily/weekly/monthly/interval/cron/crontab — scheduler/manager.py:62), schedule_config*, prompt, method_name, created_by, created_email, metadata, agent_id, is_crew, send_result, scheduler_type, callbacks[]}` | schedule |
| PATCH | /api/v1/parrot/scheduler/schedules/{schedule_id} | scheduler.py:127 | `action`: pause / resume / **run_now** (409 if running) / update (editable fields scheduler/manager.py:1446) | `{action, ...fields}` | schedule |
| DELETE | /api/v1/parrot/scheduler/schedules/{schedule_id} | scheduler.py:160 | delete | — | msg |
| GET | /api/v1/parrot/scheduler/schedules/{schedule_id}/last-result | `SchedulerLastResultHandler.get` scheduler.py:198 (class :172) | last execution output | — | `{status, ...result}` |
| GET | /api/v1/parrot/scheduler/callbacks | `SchedulerCallbacksHandler.get` scheduler.py:45 (class :36) | callbacks + jobstore types | — | `{callbacks[], schedule_types[]}` |
| POST | /api/v1/parrot/scheduler/restart | `AgentSchedulerManager.restart_handler` (scheduler/manager.py:1827) | restart scheduler | — | — |

Persistence: `navigator.agents_scheduler` (scheduler/manager.py:1252) + APScheduler jobstores. Callbacks (scheduler/functions/__init__.py): `send_email_report` (:69; recipients, subject, message, **as_pdf** → WeasyPrint PDF of markdown), `create_file` (:117; markdown file, output_dir/filename), `saving_data` (:131; CSV via DataFrame, optional email_to), `send_notify_report` (:169).

#### 5d. Peripheral (one line each)

| METHOD | PATH | Handler file:line | Note (auth / store) |
|---|---|---|---|
| GET/POST | /api/v1/users/credentials | credentials.py:152/229 (`CredentialsHandler` :59; reg :512) | list/create user DB credentials — IA+US, DocumentDB `user_credentials` + session vault |
| GET/PUT/DELETE | /api/v1/users/credentials/{name} | credentials.py:152/330/436 (reg :513) | one credential — same |
| GET/POST | /api/v1/agents/chat/{agent_id}/mcp-servers | mcp_helper.py:127/138 (reg :439-440) | MCP catalog / activate for session agent — IA+US |
| GET | /api/v1/agents/chat/{agent_id}/mcp-servers/active | mcp_helper.py:315 (reg :443) | active MCP servers — IA+US |
| DELETE | /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name} | mcp_helper.py:346 (reg :446) | deactivate — IA+US |
| POST/GET | /api/v1/comm_center/sender | comm_center.py:281/415 (reg :853-854; mounted manager.py:2577) | bulk notification send / list batches — IA (method-level); `navigator.notification_batch_recipients` |
| GET | /api/v1/comm_center/sender/{batch_id} | comm_center.py:378 (reg :855) | batch detail (aggregated) — IA |
| POST | /api/v1/comm_center/sender/{batch_id}/retry | comm_center.py:396 (reg :856) | retry failed recipients — IA |
| POST | /api/v1/comm_center/message | comm_center.py:542 (reg :861) | single send — IA |
| GET/POST | /api/v1/comm_center/templates | comm_center.py:688/736 (reg :862,864) | **message templates** list/create — IA; `notification_templates{template_id,name,template_string,subject,provider,description,tags,is_active,created_by,updated_by}` |
| GET/PUT/PATCH/DELETE | /api/v1/comm_center/templates/{template_id} | comm_center.py:720/779/827 (reg :863-875) | template CRUD — IA |
| GET | /api/v1/comm_center/placeholders | comm_center.py:533 (reg :876) | **placeholder catalog** (recipient fields, computed date resolvers, reserved names; comm_center_placeholders.py) — IA |
| GET | /api/v1/crew/tools, /api/v1/crew/special_nodes | crew/tool_catalog.py:241, crew/special_nodes.py:84 (manager.py:2530-2533) | crew designer catalogs — IA+US; ENABLE_CREWS |
| GET/POST/DELETE | /api/v1/crew/executions[/{execution_id}[/{replay\|schedule}]] | crew/execution_history_handler.py:177/188/221 (manager.py:2538) | saved crew executions: list (ExecutionFilter crew_name,method,date_from,date_to), detail, replay, **schedule** (ScheduleRequest{schedule_type,schedule_config,created_by,created_email,metadata,callbacks}) — IA+US; result storage backend |
| PUT/GET/DELETE | /api/v1/crew[/{id}] | crew/handler.py:272/379/472 (manager.py:2539; `{id:.*}` catch-all, handler.py:84-85) | crew definition CRUD — IA+US; Redis-synced |
| GET/PATCH/PUT/POST | /api/v1/crews[/{job_id}/{crew_id}[/{agent_id}\|/{ask\|summary}]] | crew/execution_handler.py:123/277/571/642 (manager.py:2540) | execute crew (POST async job), job status, ask/summary — IA+US; JobManager |
| GET/POST/DELETE | /api/v1/flows/checkpoints[/{flow_id}[/resume]] | flows/checkpoints.py:106/114/124 (reg :92-100; manager.py:2543) | list recoverable flows, history, resume (202), delete — IA+US; CheckpointStore |
| POST | /api/v1/thales | thales.py:119 (reg :260) | start research run `{thesis, num_decks>=10}` → 202 `{run_id}` — IA |
| GET | /api/v1/thales/{run_id}, /{run_id}/artifacts | thales.py:195/226 (reg :261-262) | status / produced artifacts (decks) — IA; in-memory RunRegistry |
| POST/GET | /api/v1/google/generation/video_reel[/{job_id}[/artifacts/{artifact_id}]] | video_reel.py:499/642 (setup :108-113; app.py:211) | submit job (202), poll, fetch artifact (signed URL redirect), GET bare = JSON schema — session-checked in code (no decorators), owner-only jobs |
| POST/GET | /api/v1/flows/authoring[/{job_id}] | flow_authoring.py:112/189 (setup :80-89; app.py:213) | NL → Crew/Flow definition (202 job, progress polling; bare GET = request schema) — IA+US; JobManager |
| GET/POST/PATCH/PUT | /api/v1/ai/stores, /api/v1/ai/stores/jobs/{job_id} | stores/handler.py:248/347/440/529 (setup :65-66; app.py:215) | vector store helper (`?resource=`), create collection, test search, load data (multipart/JSON/URLs, bg jobs) — IA+US |

---

### Report-builder relevance (summary)

**Directly reusable**
- **Scheduling + delivery**: `/api/v1/parrot/scheduler/*` already supports cron/interval/once schedules for an agent prompt or method, `run_now`, `last-result`, and post-run callbacks `send_email_report` (markdown or **PDF**), `create_file`, `saving_data` (**CSV**), `send_notify_report`. Missing: no auth decorators / owner scoping on these handlers (MW only), no per-user listing filter. Crew executions also have `/schedule` and `/replay`.
- **Templates with placeholders**: CommCenter `notification_templates` CRUD + `/placeholders` catalog (Jinja-style `{{field}}`, date resolvers from `parrot.outputs.a2ui.recipes.params`) — a ready pattern for report text templates; plain CRUD, no versioning.
- **Saved prompts with sharing flag**: `users_prompts.is_public` + shared `prompt_library` (per chatbot_id/agent_id, categories/tags) — can back "saved report questions".
- **Versioning precedent**: Studio skills catalog — PG row with `version` + SkillRegistry git-like `get_skill_versions` (skills_catalog.py:323). Only versioned store in this area.
- **Draft → validate → activate lifecycle**: Studio drafts (`studio_drafts` table + files) — pattern for draft/published report definitions.
- **Sharing**: only `ChatbotSharingQuestion` (`/api/v1/chatbots/questions/{sid}`, BigQuery usage row, no auth decorator) and `is_public` on user prompts. (UI surfaces share tokens `/api/v1/ui/surfaces/{id}/share/{token}`, dashboards `/api/v1/dashboards[/{id}/tabs]` (ENABLE_DASHBOARDS), artifacts public signed HTML `/api/v1/artifacts/public/...`, infographic templates/themes/render and `infographic_recipes/{name}/run` live outside this scope but are the most report-like surfaces — manager.py:2339-2343, 2429-2458, 2496-2498, 2561-2564; app.py:236-245.)
- **Export**: PDF only via scheduler callback (WeasyPrint) and `/api/v1/utilities/print2pdf` (manager.py:2508, out of scope); CSV via `saving_data` callback.
- **Conversation persistence**: `/api/v1/chat/interactions` (Redis+DocumentDB) for sourcing Q/A into reports; `threads.py` (pinned/tags metadata, DynamoDB) is **unmounted**.
- **Async job pattern**: JobManager (Redis `parrot:jobs`) + 202/poll used by video_reel, flow_authoring, stores, crews — reusable for long report renders.

**Gaps / cautions**
- No layout/page/report-definition model anywhere in this scope.
- config_handler, testing_handler, scheduler, FeedbackType, SharingQuestion have no handler-level auth decorators (global middleware only).
- `ChatbotHandler` writes (PUT/POST/DELETE `/api/v1/bots`) are session-only, no PBAC; reads are PBAC-filtered.
- PromptTuner changes are in-memory only (lost on restart).

---

## 12. parrot-formdesigner — HTTP/WS endpoint inventory

Repo: `ai-parrot` · package root `packages/parrot-formdesigner/src/parrot_formdesigner` (paths below are relative to it unless prefixed).
Host wiring: `app.py:257-290` — `PostgresFormStorage(schema="navigator", table_name="form_schemas", tenant=None)` → `FormRegistry(app, storage)`; `setup_form_api(app, registry, client=LLMFactory.create("google"), base_path="/api/v1", transcriber=FasterWhisperBackend(...), token_validator=TokenValidator())`; `setup_form_ui(app, registry, base_path="", protect_pages=False)`.
**Not passed by app.py** (so these stay `None`): `submission_storage`, `forwarder`, `partial_store`, `blob_storage`, `resolver`, `synthesizer`, `org_graph_service`, `project_service`, `rbac_service`, `workday_adapter`, `venue_service`, `alias_registry`, `public_base_url`/`teams_renderer`; `rbac_enforcing=False` (default, `api/routes.py:211`).

### Auth model (legend for the "Auth" column)

| Code | Meaning | Source |
|---|---|---|
| **A+T** | `_wrap_auth(tenant="required")`: navigator-auth `is_authenticated(content_type="application/json")` + `user_session()` + `requires_tenant(public=False)` → 400 `tenant_not_declared` if `{tenant}` empty, 404 if tenant is a reserved literal segment, 403 `tenant_forbidden` unless `tenant ∈ session["session"]["programs"]` or `superuser` | `api/routes.py:84-125`, `api/tenant.py:76-160`, `api/errors.py:27,55,82` |
| **A+Tp** | `_wrap_auth(tenant="public")`: same auth decorators, tenant declared but membership NOT checked at decorator; handler then calls `enforce_membership_unless_public()` (skips if `form.is_public`). When `form.is_public=True` the 5 paths are added to navigator-auth exclude list (`services/public_forms.py:13-53`, wired `api/routes.py:556-657`) so they become anonymous | `api/routes.py:385-421`, `api/tenant.py:190-218` |
| **A** | `_wrap_auth(tenant="none")`: auth decorators only, no tenant layer; tenant inferred from `session.programs[0]` or registry default (`_session_tenant`, `api/handlers.py:297-321`) | `api/routes.py:426-429, 519-554` |
| **RBACs** | `_rbac_shadow_gate(codename)` — no-op when `rbac_service is None` (true in app.py); log-only when `rbac_enforcing=False` | `api/handlers.py:2291-2356` |
| **T-only** | UI `_page_wrap(protect=False)`: **no navigator-auth**; `requires_tenant(public=True)` (declare-only, no membership). `protect_pages=False` in app.py ⇒ all UI HTML pages are anonymous | `ui/routes.py:80-144` |
| **WS-JWT** | Not wrapped. JWT from `Sec-WebSocket-Protocol` subprotocol or first `{"type":"auth","token":...}` msg (10 s timeout), validated by `TokenValidator`; tenant only checked non-empty + `form.tenant == {tenant}`; **no program-membership check** | `api/audio_ws.py:173-340`, `api/audio_ws.py:~457-483` |

All `/{tenant}/forms/{form_uid}` handlers parse `form_uid` as UUID (400 otherwise, `api/handlers.py:39-62`) and do tenant-scoped `registry.get(form_uid, tenant)` + `_assert_form_tenant` (404, `api/handlers.py:323-354`).

### A. JSON REST API — `setup_form_api` (`api/routes.py:192-696`), mounted at `/api/v1`

`tp = /api/v1/{tenant}` (`api/routes.py:372`).

#### A1. Form CRUD / authoring

| Method | Full path | Handler (file:line) · reg line | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/{tenant}/forms` | `FormAPIHandler.list_forms` `api/handlers.py:724` · reg `routes.py:375` | List forms (memory ∪ storage); `?slug=` filter via `get_by_slug` | query `slug?` | `{"forms":[{form_uid,form_id,title,description,version,source:"memory"\|"db",created_at}]}` sorted by form_id | A+T | reads registry + `PostgresFormStorage.list_forms(tenant)` |
| POST | `/api/v1/{tenant}/forms` | `create_form` `handlers.py:1135` · `routes.py:376` | LLM (NL prompt) form generation via `CreateFormTool` | `{"prompt": str}` | `{form_uid,form_id,title,url:"{ui_prefix}/{tenant}/forms/{uid}"}`; 503 if no LLM | A+T, RBACs(`create_form`) | `persist=True` → registry + storage |
| POST | `/api/v1/{tenant}/forms/from-db` | `load_from_db` `handlers.py:1970` · `routes.py:377` | Import legacy form definition (default service `networkninja`) via `DatabaseFormTool` | `{"formid":int,"orgid":int? (else session org),"service":str="networkninja"}` | `{form_uid,form_id,title,url}`; stores `ImportDiffReport` in-memory | A+T | `persist=True`; import report only in handler dict `_import_reports[(tenant,uid)]` (`handlers.py:2043-2047`, non-durable) |
| POST | `/api/v1/{tenant}/forms/blank` | `create_blank_form` `handlers.py:1075` · `routes.py:381` | Create empty form without LLM | `{"title": LocalizedString, "form_id"?: slug, "tenant"?: cross-check}` | 201 `{form_uid,form_id,title,url}`; 409 slug exists | A+T | `registry.register(persist=has_storage, overwrite=False)` |
| GET | `/api/v1/{tenant}/forms/{form_uid}` | `get_form` `handlers.py:847` · `routes.py:385` | Full `FormSchema` JSON; fires `onBeforeOpen` lifecycle | – | `FormSchema.model_dump(exclude_none)`; header `X-Form-CSRF-Token` if any `events.*.remote` binding | A+Tp (public-form glob) | registry read |
| PUT | `/api/v1/{tenant}/forms/{form_uid}` | `update_form` `handlers.py:1329` · `routes.py:389` | Full replace (may rename slug); bumps `version`; `published_version` forced to existing; tenant stamped from URL | full `FormSchema` body; `form_uid` must match URL | updated `FormSchema`; 422 validation / `check_schema`; 409 slug clash | A+T, RBACs(`update_form`) | `register(overwrite=True)` → UPSERT `ON CONFLICT (form_uid, version)` (`services/storage.py:179-199`) |
| PATCH | `/api/v1/{tenant}/forms/{form_uid}` | `patch_form` `handlers.py:1396` · `routes.py:390` | RFC 7396 merge-patch (arrays replaced wholesale); form_uid/form_id immutable; bumps version | partial `FormSchema` dict | updated `FormSchema` | A+T, RBACs(`patch_form`) | same UPSERT |
| DELETE | `/api/v1/{tenant}/forms/{form_uid}` | `delete_form` `handlers.py:1456` · `routes.py:391` | Remove form; guarded by `FormVersionService.can_delete` (has_responses hook — none wired ⇒ always allowed, `services/form_version.py:572-588`) | – | 204; 409 if has responses | A+T, RBACs(`delete_form`) | `registry.unregister` + `storage.delete(form_uid, tenant)` |
| POST | `/api/v1/{tenant}/forms/{form_uid}/edit` | `edit_form` `handlers.py:1190` · `routes.py:394` | NL-prompt edit (LLM refine of existing form) | `{"prompt": str}` | `{form_uid,form_id,title,url}` | A+T, RBACs(`edit_form`) | `persist=True` |
| POST | `/api/v1/{tenant}/forms/{form_uid}/clone` | `clone_form` `handlers.py:1261` · `routes.py:397` | Deep copy under new slug + new uid, optional merge-patch (de-facto "template" mechanism) | `{"new_form_id": str, "patch"?: dict, "tenant"?: cross-check}` | 201 full cloned `FormSchema`; 404/409/422 | A+T | `registry.clone_form` (persists) |
| PATCH | `/api/v1/{tenant}/forms/{form_uid}/operations` | `handle_operations` `api/operations.py:521` · `routes.py:432` | Atomic batched structural edits (layout/sections/fields), optimistic concurrency via `If-Match: <version>` (412) | `OperationsEnvelope{operations:[Operation]}` (`operations.py:183`); discriminated by `op`: `add_section{section,position?}` (:61), `add_field{section_uid,field,position?}` (:69), `move_field{from:{section_uid,field_uid},to:{section_uid,position}}` (:89), `remove_field{section_uid,field_uid}` (:108), `update_field{section_uid,field_uid,patch}` (:121), `update_section_meta{section_uid,patch}` (:139), `update_form_meta{patch}` (:152), `duplicate_field{from,as_field_id}` (:159) | 200 `{"form": FormSchema}`; 422 `{"errors":[{index,op,message}]}` | A+T | bumps version; `register(persist=True, overwrite=True)` (`operations.py:645`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/schema` | `get_schema` `handlers.py:884` · `routes.py:401` | Structural JSON Schema (`JsonSchemaRenderer`), `onSchemaLoaded` may apply `schema_overrides` | – | JSON Schema (`application/schema+json` content from `renderers/jsonschema.py:392`, served as JSON) | A+Tp | – |
| GET | `/api/v1/{tenant}/forms/{form_uid}/style` | `get_style` `handlers.py:916` · `routes.py:405` | Style schema = `form.meta["style"]` | – | `StyleSchema` dict or `{}` | A+T | – |
| GET | `/api/v1/form-controls` | `controls.handle_form_controls` `api/controls.py:20` · `routes.py:426` | Toolbar catalog of field-type controls (widget palette) | – | `{"controls":[FieldControlMetadata]}` (seeded by `controls/builtin.py`) | A (no tenant) | static |

#### A2. Rendering, validation, submissions, uploads, partials, events

| Method | Full path | Handler · reg | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/{tenant}/forms/{form_uid}/render/{format}` | `render.handle_render` `api/render.py:165` · `routes.py:408` | Render dispatcher. Formats seeded `render.py:42-88`: `html` (HTML5Renderer, text/html), `adaptive` (AdaptiveCardRenderer, JSON), `xml` (XFormsRenderer, application/xml), `pdf` (PdfRenderer, application/pdf), `audio` (AudioFormRenderer manifest, JSON), `a2ui` (A2UIFormRenderer, only if `parrot.outputs.a2ui` importable), `teams` (only if `public_base_url`/`FORMDESIGNER_PUBLIC_URL` set — not set in app.py, `render.py:117-147`) | query `locale=en`, `with_meta=true` (JSON envelope `{content, content_type, content_encoding:"base64"?, warnings, metadata}`) | raw rendered body w/ renderer content-type; 415 `{"supported":[...]}` unknown format; 400 renderer refusal | A+Tp | – |
| POST | `/api/v1/{tenant}/forms/{form_uid}/validate` | `validate` `handlers.py:1004` · `routes.py:414` | Dry-run validation; dual-wire legacy JSON or A2UI v1.0 action envelope (`api/a2ui_wire.py`) | answers dict `{field_id: value, "visit_context"?: {...}}` or A2UI `action` | 200/422 `{"is_valid", "errors"}` (reject policy → `errors.__unknown__`); A2UI: `{"messages":[]}` / VALIDATION_FAILED envelopes; 413 oversize | A+Tp | none |
| POST | `/api/v1/{tenant}/forms/{form_uid}/data` | `submit_data` `handlers.py:1498` · `routes.py:418` | Submission pipeline: optional `?merge_partials=true` → `onBeforeSubmit` → `FormValidator.validate` → `unknown_fields` policy (drop/keep/reject) → metadata enrichment → persist → forward (`submit.action_type=="endpoint"`) → `onAfterSubmit` | answers dict (+ `visit_context`) or A2UI action; query `merge_partials` | 200 `{submission_id, is_valid:true, forwarded, forward_status, forward_error}`; 422 `{is_valid:false, errors}`; 503/422/501 sink errors | A+Tp | builds `FormSubmission` (`services/submissions.py:~97`). If `form.persistence` set → per-form sink via `SinkFactory` (inactive: no `alias_registry` ⇒ 503 `SinkUnavailableError`, `handlers.py:1846-1864`). Else `submission_storage.store()` → `PostgresSubmissionStorage` default `navigator.form_data` (`services/submissions.py:31-32`) — **but app.py passes none ⇒ submission is validated and NOT stored** (`handlers.py:1871-1877`) |
| POST | `/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/upload` | `uploads.handle_rest_upload` `api/uploads.py:145` · `routes.py:438` | REST-field (FieldType.REST) multipart upload → blob → `RestFieldResolver` callback | multipart `file` (+ additional_args); header `X-Parrot-Prior-Blob-Ref` | `{success, answer, raw_value, blob_ref, display, warnings, error}` (`uploads.py:343-354`); 404/413/415 | A+T | blob storage: `app["blob_storage"]` else lazy `TempBlobStorage` (process-local temp dir, `uploads.py:113-140`) — app.py wires none |
| POST | `/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload` | `file_upload.handle_file_upload` `api/file_upload.py:132` · `routes.py:444` | Raw FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD upload; SHA-256, inline `data_url` ≤ max_inline, thumbnails; basic chunking (`X-Parrot-Upload-Id/Offset/Length` → 202 per chunk) | multipart `file` part(s) or raw chunk; `X-Parrot-Prior-Blob-Ref`, `X-Parrot-Tenant` | `FileEnvelope{filename, content_type, size, blob_ref, data_url, thumbnail_url, checksum}` or list (`file_upload.py:550-558`) | A+T | same blob storage (`TempBlobStorage` default, `file_upload.py:79-100`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/thumbnail` | `file_upload.handle_get_thumbnail` `file_upload.py:560` · `routes.py:450` | Stream thumbnail by blob ref | query `ref` (URL-encoded blob_ref) | `image/webp` bytes | A+T | blob read (unsigned) |
| POST | `/api/v1/{tenant}/forms/{form_uid}/partial` | `save_partial` `handlers.py:541` · `routes.py:456` | Merge & per-field-validate draft answers | `{"answers": {field_id: value}}` | `PartialFormData` `{form_uid/form_id, session_id, data, field_errors}`; **503 since no partial_store** | A+T | Redis `PartialSaveStore` (TTL 3600 s, keyed form_uid+session_id, data keyed by field_uid) — not wired |
| GET | `/api/v1/{tenant}/forms/{form_uid}/partial` | `get_partial` `handlers.py:650` · `routes.py:457` | Read draft | – | `PartialFormData` / 404; 503 (not wired) | A+T | Redis |
| DELETE | `/api/v1/{tenant}/forms/{form_uid}/partial` | `delete_partial` `handlers.py:692` · `routes.py:458` | Clear draft | – | 204; 503 (not wired) | A+T | Redis |
| POST | `/api/v1/{tenant}/forms/{form_uid}/events/{event_name}` | `remote_event` `handlers.py:927` · `routes.py:461` | Remote lifecycle bridge for bindings with `remote:true` (event must be in `FormEventName` Literal) | header `X-CSRF-Token`/`X-Form-CSRF-Token` (issued by GET form); body `{payload?, schema_dump?}` | `EventResolution` JSON; 403 CSRF; status from `FormEventAbort` | A+T + per-session CSRF | – |

#### A3. Versioning / question bank / import report (FEAT-300/433)

| Method | Full path | Handler · reg | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| POST | `/api/v1/{tenant}/forms/{form_uid}/publish` | `publish_form` `handlers.py:2116` · `routes.py:501` | Promote CURRENT live version to published (immutable, in place — no bump) | – | `{form_uid, version}`; 404; 409 already published | A+T | `FormVersionService` → `storage.promote()` guarded UPDATE on same `form_schemas` row (`services/form_version.py:716-760`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/versions` | `list_versions` `handlers.py:2187` · `routes.py:504` | Version history (all stored rows, draft+published) | – | `{form_uid, versions:[{version, published_at, published_by:null, is_current, is_published}]}` | A+T | `storage.list_versions` (one row per `(form_uid, version)`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/versions/{version}` | `get_version` `handlers.py:2237` · `routes.py:505` | Fetch stored snapshot (draft or published) | – | full `FormSchema` / 404 | A+T | storage |
| GET | `/api/v1/{tenant}/forms/{form_uid}/import-report` | `get_import_report` `handlers.py:2264` · `routes.py:509` | Last `ImportDiffReport` from `/from-db` | – | `ImportDiffReport` / 404 | A+T | in-process dict only (lost on restart) |
| GET | `/api/v1/{tenant}/fields` | `list_fields` `handlers.py:2146` · `routes.py:502` | Question bank — reusable fields | – | `{"fields":[ReusableField]}` | A+T | `QuestionBankService(storage=registry.storage, tenant)` (`services/question_bank.py`) |
| POST | `/api/v1/{tenant}/fields` | `create_field` `handlers.py:2160` · `routes.py:503` | Add reusable field | `FormField` JSON | 201 `ReusableField`; 422 | A+T | question bank |

#### A4. Audio WebSocket (conditional)

| Method | Full path | Handler · reg | Purpose | Protocol | Auth | Persistence |
|---|---|---|---|---|---|---|
| GET (WS upgrade) | `/api/v1/{tenant}/forms/{form_uid}/audio/ws` | `AudioFormWSHandler.handle_websocket` `api/audio_ws.py:173` · reg `routes.py:479-496` (**only if** `synthesizer or transcriber or token_validator` — true in app.py) | Voice Q&A form session (max 10 questions, `audio_ws.py:58`), TTS (SuperTonic→Google→text) + Whisper STT | Client JSON `type`: `start_session` (config: locale, tts_backend, tts_voice, tts_mime_format, auto_advance, enumerate_options, stt_confirm_threshold), `answer_text`, `answer_selection`, `answer_payload`, `confirm_answer`, `skip_question`, `go_back`, `repeat_question`, `end_session`, `ping`, `auth` (`audio_ws.py:368-378`); binary frames = audio. Server: `session_started`, questions, `form_complete{submission_id, answers}`, errors | WS-JWT | `_finish_session` stores `FormSubmission` via `submission_storage` (None in app.py ⇒ not stored; also uses `registry.get(..., tenant=None)` and hard-coded `form_version="1"`, `audio_ws.py:1115-1160`) |

#### A5. `/org/*` (FEAT-302/330) — mounted unconditionally, all return 501 in app.py (services not wired)

| Method | Full path | Handler (handlers.py) · reg (routes.py) | Purpose / body | Auth | Backend |
|---|---|---|---|---|---|
| GET | `/api/v1/org/graph` | `get_org_graph` :2362 · :519 | Org graph for session org | A | `OrgGraphService` (None ⇒ 501) |
| POST | `/api/v1/org/projects` | `create_project` :2394 · :520 | `{accounting_code, name?, client_id}` (org_id from session) | A | `ProjectService` (None ⇒ 501) |
| POST | `/api/v1/org/cost-centers/{project_id}/workday-map` | `map_project_workday` :2462 · :521 | `{workday_code}` | A | ProjectService |
| POST | `/api/v1/org/users/{user_id}/assign` | `assign_user_role` :2511 · :525 | `{codename, scope:RBACScope, program_id}`; always enforces `manage_roles`; writes `fieldsync.auth_policies` | A + hard RBAC | `RBACService` |
| POST | `/api/v1/org/sync/workday` | `sync_workday_identities` :2605 · :529 | `{user_id, action:provision\|deprovision, org_id}` → 202 stub | A | `WorkdayIdentitySyncAdapter` |
| GET | `/api/v1/org/stores/{store_id}/sites` | `list_sites` :2654 · :535 | list `Site` | A | `VenueService` |
| POST | `/api/v1/org/stores/{store_id}/sites` | `create_site` :2682 · :539 | `{client_id, name}` | A | VenueService |
| GET | `/api/v1/org/sites/{site_id}/locations` | `list_locations` :2741 · :543 | list `Location` | A | VenueService |
| POST | `/api/v1/org/sites/{site_id}/locations` | `create_location` :2771 · :547 | `{client_id, name, location_type="kiosk", latitude, longitude, geofence_radius_m}` | A | VenueService |
| GET | `/api/v1/org/locations/{location_id}` | `get_location` :2846 · :551 | one `Location` | A | VenueService |

### B. HTML / Telegram UI — `setup_form_ui` (`ui/routes.py:147-236`), mounted at `""` (root), `protect_pages=False`

| Method | Full path | Handler · reg | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/{tenant}/` | `FormPageHandler.index` `ui/handlers.py:58` · `ui/routes.py:183` | Builder landing page (prompt box + DB loader; JS calls the API) | – | HTML (`ui/templates.py`) | T-only (anonymous) | – |
| GET | `/{tenant}/gallery` | `gallery` `ui/handlers.py:86` · `routes.py:184` | List tenant forms with Open/Schema links | – | HTML | T-only | registry read |
| GET | `/{tenant}/forms/{form_uid}/schema` | `view_schema` `ui/handlers.py:197` · `routes.py:187` | Pretty JSON Schema + Style schema page | – | HTML | T-only | – |
| GET | `/{tenant}/forms/{form_uid}` | `render_form` `ui/handlers.py:139` · `routes.py:191` | Render form via `HTML5Renderer` with `?layout=` (`LayoutType`: single_column, two_column, wizard, accordion, tabs, inline — `core/style.py:16-24`) | query `layout` | HTML page, `<form action=... method=post>` | T-only | – |
| POST | `/{tenant}/forms/{form_uid}` | `submit_form` `ui/handlers.py:253` · `routes.py:195` | Validate urlencoded POST and show result / re-render with errors | form-urlencoded | HTML | T-only | **none** (validation only) |
| GET | `/{tenant}/forms/{form_uid}/telegram` | `TelegramWebAppHandler.serve_webapp` `ui/telegram.py:49` · `routes.py:207` | Form as Telegram WebApp (Jinja `telegram_webapp.html.j2`) | – | HTML | T-only (by design) | – |
| POST | `/api/v1/{tenant}/forms/{form_uid}/telegram-submit` | `rest_fallback` `ui/telegram.py:90` · `routes.py:212` | REST fallback for WebApp payloads > 4 KB | JSON answers (`_form_uid` stripped) | `{is_valid, errors}` 200/422 | T-only (anonymous) | **none** (validation only) |

Note: UI handlers use `request.match_info["form_uid"]` raw (no UUID parse) and do NOT call `_assert_form_tenant`/membership; telegram uses `declared_tenant` (`ui/telegram.py:61,102`).

### C. Persistence summary

| Store | Location | Used by | Wired in app.py? |
|---|---|---|---|
| `PostgresFormStorage` | table `form_schemas`; schema = **tenant slug** when tenant given (`_resolve_schema`, `services/storage.py:135-148`), else `navigator`. Columns `id, form_uid UUID, form_id, version, schema_json JSONB, style_json JSONB, tenant, created_at, updated_at, created_by`, `UNIQUE(form_uid,version)`, `UNIQUE(tenant,form_id,version)` (`storage.py:159-176`). UPSERT on `(form_uid,version)` (`:179-199`); `promote()` for publish (`:447`); `list_versions` (`:703`) | registry save/load/delete, versions, question bank | Yes (`app.py:257-263`). Registry `default_tenant="navigator"` (`services/registry.py:280`) and `register()` saves with `tenant=resolved` (`registry.py:662`) ⇒ forms for tenant `X` land in **`X.form_schemas`**, only default-tenant forms in `navigator.form_schemas`; schema must pre-exist |
| `PostgresSubmissionStorage` | default `navigator.form_data` (tenant overrides schema) (`services/submissions.py:31-32,123-155`) | `/data`, audio WS finish | **No** ⇒ submissions not persisted |
| Per-form sinks (FEAT-457) | `services/sinks/*` (postgres_table, asyncdb_store), mapped via `sinks/mapper.py` | `/data` when `form.persistence` set | **No** (`alias_registry` absent ⇒ 503) |
| `PartialSaveStore` (Redis) | `services/partial_saves.py:24` TTL 3600 s | `/partial` | **No** ⇒ 503 |
| Blob storage | `app["blob_storage"]`, lazy `TempBlobStorage` fallback (S3/GCS/Local available in `services/blob_storage.py`) | uploads/thumbnail | **No** ⇒ process-local temp (lost on restart) |
| Import reports | in-memory dict on handler | `/from-db`, `/import-report` | n/a (non-durable) |
| Forwarder | `services/forwarder.py` | `/data` when `submit.action_type=="endpoint"` | **No** ⇒ never forwarded |

### D. Domain notes (templates, versioning, layout, formats, export)

- **Form model** `FormSchema` (`core/schema.py:401`): `form_uid` (immutable UUID), `form_id` (slug), `version` ("1.0", auto-bumped on PUT/PATCH/operations), `title`/`description` (LocalizedString), `sections: list[FormSection]`, `submit: SubmitAction` (`:300`), `meta` (holds `style`), `tenant`, `metadata` (enrichment fields), `events` (lifecycle bindings), `form_type` (SIMPLE/PRODUCT/SURVEY, `:33`), `product_bindings`, `published_version`, `is_public`, `persistence`, `unknown_fields` (drop/keep/reject). `FormSection` (`:229`): `section_uid, section_id, title, description, fields: list[FormField|FormSubsection]` (`SectionItem`, `:226`), `depends_on`, `meta`. `FormField` at `:65`.
- **Layout / widgets**: `StyleSchema`/`LayoutType` (`core/style.py:16,52`); widget palette via `GET /form-controls` (`controls/builtin.py`); structural editing via `/operations`.
- **Templates**: no dedicated template endpoint. Reuse = `/clone` (+patch) and question bank `/fields`. (`ui/templates.py` is only HTML page chrome.)
- **Versioning**: draft rows per `(form_uid, version)`; `publish` freezes current version in place (409 on re-publish); `published_version` immutable via API (`handlers.py:1359-1362, 1432`); delete guarded only if a `has_responses` hook exists (none).
- **Render formats / export**: html, adaptive (Adaptive Cards), xml (XForms), pdf, audio (manifest), a2ui (optional), teams (conditional); JSON Schema via `/schema`. PDF/XML = the export paths; `?with_meta=true` base64-wraps binary. No submissions export / list / read endpoint exists.
- **Lifecycle events**: `onBeforeOpen`, `onSchemaLoaded`, `onBeforeSubmit`, `onAfterSubmit`, `onError` dispatched in handlers; remote bridge via `/events/{event_name}`.

### E. Gaps / risks spotted

1. **Audio WS auth-exclude path mismatch**: `app.py:310` excludes `/api/v1/forms/*/audio/ws`, but the real route is `/api/v1/{tenant}/forms/{form_uid}/audio/ws` (`routes.py:493`). If the navigator-auth middleware enforces on non-excluded paths, the WS upgrade from a browser (no Authorization header) may be rejected before reaching `AudioFormWSHandler`. Also `app.py:268` comment shows the stale path.
2. Audio WS has **no tenant membership check** (any valid JWT + any tenant whose form uid is known) and `_finish_session` re-resolves the form with `tenant=None` (`audio_ws.py:1137`) and hard-codes `form_version="1"`.
3. `protect_pages=False` ⇒ UI pages (`/{tenant}/...`) are fully anonymous and declare-only for tenant: any form (public or not) of any tenant is renderable/validatable by UUID; gallery lists all forms of any tenant.
4. Root-mounted `/{tenant}/` and `/{tenant}/gallery` capture every 1-segment path of the host app (tenant collisions with literal routes → 404 via reserved-segment guard, `api/tenant.py:150-156`).
5. Submissions, partials, blob durability, forwarding, RBAC and per-form sinks are all **inactive** in this host (nothing wired); `/data` returns 200 with a `submission_id` that is never stored.
6. RBAC on create/update/patch/delete/edit is shadow-only and no-op (no `rbac_service`).
7. Per-tenant physical schema: tenant slug becomes the Postgres schema for `form_schemas` (must pre-exist), not `navigator`.

---

## 13. Peripheral routes (not report-builder relevant; listed for completeness)

| Area | Paths | Where |
|---|---|---|
| A2A protocol | `/.well-known/agent(-card).json`, `{bp}/message/send|stream`, `{bp}/message:send|:stream`, `{bp}/tasks[/{id}][/cancel|/subscribe]`, `{bp}/rpc` (bp default `/a2a`, PUB `app.py:330-332`) | `S/a2a/server.py:266-326` |
| MCP | helper `/api/v1/mcp…` GET/POST, `/active`, `DELETE /{server_name}`; transports sse/http/ws/streamable; OAuth server; FEAT-477 agent mount | `S/handlers/mcp_helper.py:439-446`, `S/mcp/transports/*`, `S/mcp/oauth_server.py`, `manager.py:2598-2629` |
| Credentials | `/api/v1/users/credentials[...]` | `S/handlers/credentials.py:512-513` |
| Voice / avatar / broadcast | `/api/v1/agents/voice|transcribe/{agent_id}`, `/ws/voice`, avatar + fullmode + `/api/v1/agents/{agent_id}/voice-broadcasts`, OpenAI-compat | `manager.py:1770-2222`, `S/handlers/voice_broadcast.py`, `S/handlers/avatar*.py`, `S/handlers/openai_compat.py` |
| Integrations | Telegram/Teams/Slack/WhatsApp/MSAgentSDK webhooks, OAuth2 callbacks, `/telegram/` static | `packages/ai-parrot-integrations/...`, `app.py:93-101,122` |
| Media / pipelines | `/api/v1/google/understanding`, `/api/v1/google/media`, `/api/v1/google/generation[/music]`, video reel jobs, planogram compliance jobs (+`/sse`), `/api/v1/ai/client(s)…`, `/api/v1/ai/stores[/jobs/{id}]` | `app.py:153-228`, handlers cited in §11 |
| Ontology (library, **unmounted**) | concept catalog CRUD+transitions, schema overlays | `C/knowledge/ontology/concept_catalog/http.py:379-391`, `.../schema_overlay/http.py:214-218` (no caller) |
| PBAC admin | `/api/v1/abac/*` added by `PDP.setup` | `manager.py:2296-2306` comment, `S/auth/pbac` |
| Swagger | `/api/docs`, `/api/docs/redoc|rapidoc|swagger.json` (if `enable_swagger_api`) | `manager.py:2578-2590` |

---

## 14. Gaps for a report builder (observations grounded in the code above)

1. **No report/page/template entity.** Nearest things: `ui_surfaces` (single A2UI envelope per row, kinds `dashboard|infographic|widget`, `S/handlers/models/ui_surfaces.py:42-82`), legacy `dashboards`+`dashboard_tabs` with free-form `widgets[]`/`layout_mode`/`template` (`S/handlers/dashboard_handler.py:418-493`), and `InfographicRecipe` (data→transform→layout→render, `C/outputs/a2ui/recipes/models.py:235`). None models a canvas → pages → widget tree with per-widget data bindings as first-class rows.
2. **ui_surfaces cannot be edited.** No PUT/PATCH for `envelope`/`title` (only visibility PATCH, `ui_surfaces.py:738`); the store's `save(overwrite=True)` upsert is unexposed (`models/ui_surfaces.py:503-510`). No duplicate/clone and no "save as template".
3. **No versioning/history** for surfaces, artifacts, dashboards, recipes or infographic templates. `update_envelope` overwrites in place, guarded only by `expected_updated_at` on linked refresh (`ui_surfaces.py:712-728`). The only versioning precedents are formdesigner `publish`/`versions` (§12 A3) and the Studio skills catalog (§11).
4. **Refresh only at the whole-surface level.** `POST /ui/surfaces/{id}/refresh` re-runs the full recipe or every linked source (`ui_surfaces.py:617-736`). There is no endpoint to refresh or re-query one component or data source, and no partial-envelope (dataModel delta) response. Dashboards have no refresh at all.
5. **Infographic templates and themes are not persisted.** `POST /agents/infographic/templates|themes` writes to an in-process registry (`C/helpers/infographics.py:50-75`), so it is lost on restart, inconsistent across workers, and has no PUT/DELETE and no tenant/owner scoping. Only global scope is allowed; session scope returns 403 (`infographic.py:742-747`).
6. **Recipes are not wired in the stock host.** `register_recipe_routes` is never called (`manager.py:2490-2495`; no caller in `app.py`), so `/api/v1/infographic_recipes*` return 500. Surface refresh for recipe-backed surfaces also has no runner (`ui_surfaces.py:651-662`).
7. **Component catalog is not discoverable over HTTP.** `/a2ui/capabilities` returns only catalog IDs (`C/outputs/a2ui/catalog/export.py:195-212`). `export_catalog_definition` (`:215`) has no route, so a builder palette can't list A2UI components and their props. Formdesigner has an analogous `GET /api/v1/form-controls`.
8. **Dashboards are insecure and off by default.** They are behind `ENABLE_DASHBOARDS=False` (`C/conf.py:95`). There is no auth decorator and no owner check, and `user_id` is accepted from the body (`dashboard_handler.py:89-91,186`).
9. **Artifacts are thread-scoped only.** The key is `(user_id, agent_id, session_id, artifact_id)`, so there is no cross-thread library, search or sharing endpoint, apart from the signed public HTML (`artifacts.py:530`). `CanvasDefinition` exists (`C/storage/models.py:404-435`) but isn't validated on POST/PUT (definition is a free dict, `artifacts.py:204-233`).
10. **Export is fragmented.** Available paths: HTML→PDF via `print2pdf` (caller supplies the HTML); artifact `?download=1` HTML; infographic render `public=true` → `/static/`; formdesigner pdf/xml; scheduler `send_email_report` PDF (§11). There is no surface→PDF/PNG/XLSX/PPTX export endpoint, and no export job API (ui_surfaces HTML is rendered on the fly only).
11. **Datasets are session-scoped and not durable** (`datasets.py:162-177`). The filter-schema/values handlers that a builder's global filters would need exist but are unmounted (`C/handlers/dataset_filter_handler.py:1-30`). Durable data access goes through QuerySource slugs (`/api/v2/services/queries/{slug}`, `/api/v1/management/queries`).
12. **Scheduling isn't linked to surfaces.** The scheduler API exists (§11, `navigator.agents_scheduler`) and a `run_infographic_recipe` callback exists (`infographic_recipes.py:323`), but there is no "schedule this surface/report" or delivery-subscription endpoint, and the scheduler handlers have no owner scoping (§11).
13. **No collaborative or real-time editing channel for boards.** The streaming WS (`/bots/{id}/stream/ws`) and A2UI SSE are chat/renderer-function oriented. The `/ws/userinfo` push could carry notifications but has no surface-change topic.
14. **Thread metadata API is dead code.** `handlers/threads.py` (pinned/tags/archive) is unmounted (§11), so there is no "my reports" organisation (folders, tags, pins) on any entity. ui_surfaces list supports only `?kind=` (`ui_surfaces.py:466-484`).
