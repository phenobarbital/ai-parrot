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
