# ai-parrot server — Admin / Bots / Studio / misc endpoint inventory

Repo: `/home/jelitox/repos/trocglobal/ai-parrot` (read-only survey, 2026-09-30).
All paths below are relative to `packages/ai-parrot-server/src/parrot/` unless prefixed `app.py` (repo root).

Legend — Auth: `IA` = `@is_authenticated()`, `US` = `@user_session()`, `MW` = no class decorator (relies on global navigator-auth middleware only), `PBAC(x)` = `_pbac_gate`/evaluator check on action `x` (fail-open when no PDP), `own` = owner check with superuser bypass, `EAA` = `BotManager.get_bot(..., request=)` → `enforce_agent_access` (manager/manager.py:744-772).
ModelView/FormModel/AbstractModel `.configure(app, path)` auto-registers `path`, `path/{id}` (+ `path{meta}`) and exposes GET/POST/PUT/PATCH/DELETE generic CRUD.

## 0. Where routes are mounted

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

### Mount check (grep over packages/, app.py, appauto.py)
- **handlers/threads.py (`ThreadListView`, `ThreadDetailView`) — NOT MOUNTED anywhere.** Only artifacts sub-routes `/api/v1/threads/{session_id}/artifacts[...]` exist (app.py:236-245, handlers/artifacts.py). Its docstring routes (`/api/v1/threads`, `/api/v1/threads/{session_id}`) are dead code.
- **handlers/user_objects.py (`UserObjectsHandler`) — not an HTTP handler** (plain class); used internally by handlers/agent.py:45,143 and handlers/datasets.py:33,159 to build session-scoped ToolManager/DatasetManager.
- **handlers/scheduler.py — MOUNTED** by scheduler/manager.py:1812-1827 (lazy import inside `AgentSchedulerManager.setup`).
- handlers/jobs/* — JobManager + RedisJobStore (prefix `parrot:jobs`, TTL 86400; jobs/worker.py:15). Consumed by video_reel, flow_authoring, stores, crew execution; no routes of its own.

---

## 1. Agent Studio — `/api/v1/astudio/*` (handlers/studio/, registered handlers/studio/__init__.py:26-145)

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

## 2. Admin UI — server/ui/serving.py (`setup_admin_ui`, called manager/manager.py:2575)

| METHOD | PATH | Handler file:line | Purpose | Response | Auth |
|---|---|---|---|---|---|
| GET | /api/v1/admin/status | ui/status.py:247 `AdminStatusHandler` (reg serving.py:196) | server health | `AdminStatus{name,version,uptime_seconds,agents{database,registry,loaded},crews,dependencies{postgres,redis,vector_store: {status,detail,latency_ms}}}` (status.py:34-60) | IA+US |
| GET | /api/v1/admin/catalog | ui/catalog.py:134 `AdminCatalogHandler` (reg serving.py:197) | option lists for agent form | `AdminCatalog{llm_providers[],operation_modes[],memory_types[],knowledge_bases[{class_path,...}],bot_class_default}` (catalog.py:34) | IA+US |
| GET | /admin, /admin/{tail:.*} | serving.py:237-238 `_spa_fallback` | Svelte SPA shell (history fallback), only if `ui/dist/index.html` exists | index.html (no-cache) | auth-excluded (registered on_startup, serving.py:88) |
| GET | /admin/assets/* | serving.py:221 static | hashed assets, immutable cache | files | auth-excluded |

ui/models.py `BotsListResponse` is a codegen-only descriptor for `GET /api/v1/bots` (not used at runtime). ui/chat_models.py similar.

## 3. handlers/bots.py

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

## 4. handlers/chat.py

| METHOD | PATH | Handler file:line | Purpose | Request | Response | Auth |
|---|---|---|---|---|---|---|
| GET | /api/v1/chats | `ChatHandler.get` chat.py:118 (class :41; reg manager.py:2313) | welcome msg | — | `{message}` | IA+US |
| GET | /api/v1/chat/{chatbot_name} | chat.py:118 | bot info | — | `{chatbot,description,role,embedding_model,llm,temperature,config_file}` | IA+US |
| POST | /api/v1/chat/{chatbot_name} | `ChatHandler.post` chat.py:215 | RAG ask (JSON or SSE) | body `{query, session_id?, search_type='similarity', return_sources=True, return_context, stream}`; `?llm=&model=` override | AIMessage JSON or `text/event-stream` | IA+US + PBAC chatbot access (chat.py:47, :389) |
| POST | /api/v1/chat/{chatbot_name}/{method_name} | chat.py:215 (`_check_methods` :190) | invoke a public bot method with body params | method kwargs | method result | same; `_`-prefixed/forbidden blocked |
| PUT | /api/v1/chatbots[/{name}] | `BotHandler.put` chat.py:630 (class :594; reg manager.py:2518-2519) | create bot from config + insert BotModel | `{name, ...BotModel}` | `{message}` (202 if exists) | IA+US (no GET defined) |
| GET | /api/v1/bot_management[/{bot}] | `BotManagement.get` chat.py:708 (class :703; app.py:149) | list bots + vector store info | — | list | IA+US |
| PUT | /api/v1/bot_management/{bot} | chat.py:816 | multipart upload docs into bot vector store (loader per ext) | multipart files / form | load result | IA+US; writes vector table (default = bot name) |

## 5. Other handlers in scope

### 5a. Agent config / testing / user agents / catalog / prompt / knowledge / chat persistence

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

### 5b. WebSocket
| PROTO | PATH | Handler | Purpose | Messages | Auth | Persistence |
|---|---|---|---|---|---|---|
| WS | /ws/userinfo | `UserSocketManager` handlers/user.py:28 (navigator `WebSocketManager`; instantiated app.py:197) | user presence / channel pub-sub / notifications | in: `auth{token}`, `location`, `message`, `broadcast`, `direct{target,content}`, `subscribe`, `unsubscribe`, `get_users` (user.py:531-645); out: `auth_success`, `subscribed`, `users_list`, `direct`, `error`... ; server push `notify_channel()` (user.py:694) | in-band bearer token (`_validate_token` :179); path auth-excluded unless SaaS mode (:91) | Redis `user_socket:{username}` hash TTL 1d; default channels information/following |

### 5c. Scheduler (handlers/scheduler.py, mounted scheduler/manager.py:1818-1827) — **all MW only (no decorators, no owner scoping)**

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

### 5d. Peripheral (one line each)

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

## Report-builder relevance (summary)

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
