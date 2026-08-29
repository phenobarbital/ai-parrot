---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: UI Agent Management — Admin UI Agent CRUD

**Feature ID**: FEAT-475
**Date**: 2026-08-30
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot-server 0.29.0

> Source brainstorm: `sdd/proposals/ui-agent-management.brainstorm.md`
> (Recommended Option B — Tabbed Wizard Interface). Second spec in the
> Admin UI series; builds on the FEAT-468 foundation
> (`sdd/specs/ui-server-backend.spec.md`), whose read-only agents module
> already absorbed this brainstorm's list-view design.
>
> **Re-anchoring note.** The brainstorm (2026-03-18) targeted the corporate
> SvelteKit app `navigator-frontend-next` (`/agents`, Flowbite, `$app/*`).
> FEAT-468 decided the open-source Admin UI is an embedded **Svelte 5 +
> Vite SPA** served at `/admin/` from `ai-parrot-server`, with vendored
> shadcn primitives and a hand-rolled router. Every brainstorm path and
> library reference below has been translated to that target; the
> feature intent (tabbed CRUD form over `BotModel`) is unchanged.

---

## 1. Motivation & Business Requirements

### Problem Statement

`ChatbotHandler` at `/api/v1/bots` can create, update and delete agents,
but there is no user interface to do it: agent creation today requires
direct API calls or database manipulation. FEAT-468 shipped a **read-only**
agents module (list + detail dialog) explicitly leaving create/edit/delete
to "the next spec". This is that spec: a complete CRUD experience for
database-backed `BotModel` agents inside the Admin UI.

**Who is affected:**
- **Admins & developers** — currently need an API client to configure
  bot behaviour, memory, tools and vector stores.
- **Open-source adopters** — get an Admin UI with FEAT-468 but still
  cannot manage agents from it.

### Goals

- **DB agents only**: create, edit and delete agents stored in the
  database (`source: "database"`). Registry agents stay read-only in the
  UI (brainstorm constraint carried verbatim).
- **Strictly CRUD**: a complete form covering every user-editable
  `BotModel` field; no live testing/preview.
- **Dedicated form page**, separate from the list: `/admin/agents/new`
  and `/admin/agents/<name>` (brainstorm constraint; identity is the
  agent **name**, see §2 — the backend addresses agents by name, not by
  `chatbot_id`).
- **Tabbed layout** (Option B): General · Behavior · AI · Capabilities ·
  Data & Memory · Advanced, with sticky Save/Cancel across tabs and a
  per-tab error indicator.
- Tools are selectable from the tools listing endpoint; Knowledge Bases,
  LLM providers and memory types come from a **server-owned catalog
  endpoint** instead of hardcoded UI lists (see §2 and §8 Q2).
- Advanced: `bot_class` is a plain text input; `permissions` (and every
  other JSONB field) uses a validated JSON editor component.
- Backend gaps that block a correct UI are closed **in the library**
  (not in the repo-root `app.py`): the tools listing route, a way to list
  disabled agents, and the catalog endpoint.
- All new API payloads get generated TypeScript types via the FEAT-468
  codegen pipeline (`scripts/generate_ts_types.py` → `pnpm generate`).

### Non-Goals (explicitly out of scope)

- Creating/editing/deleting **registry** (YAML/code) agents through the
  UI — the row/detail stays read-only for `source: "registry"`.
- A live chat/test panel on the form (brainstorm: "no Testing/Preview").
- Provisioning or browsing vector-store collections, uploading KB
  documents, or managing embedding models — the form only edits the
  configuration dicts the backend already accepts.
- A schema-driven auto-generated form from `BotModel` metadata
  (`ui_help`) — the form is hand-laid-out per tab; `ui_help` strings are
  copied into field hints where useful.
- Changing `ChatbotHandler`'s validation semantics (slugify/dedup on
  create, immutable `chatbot_id`/`created_at`/`created_by`) — the UI
  adapts to them.
- The `/api/v1/astudio/*` management API (`agentstudio-management`
  brainstorm) — this UI keeps consuming `/api/v1/bots`.
- Monolithic single-page form (brainstorm Option A) and accordion layout
  (Option C) — rejected in the brainstorm.

---

## 2. Architectural Design

### Overview

Two halves, mirroring FEAT-468:

**UI half** (`packages/ai-parrot-server/ui/`): a new `pages/agents/`
form module. `AgentForm.svelte` owns one centralized Svelte 5 rune-class
store (`AgentFormState`, `stores/agent-form.svelte.ts`) holding the full
`BotModel` payload as `$state`, plus dirty tracking, per-field validation
and per-tab error aggregation. Six tab panels render slices of that state;
Save/Cancel live in a sticky footer outside the tab panels. Two routes
wrap the form: `/admin/agents/new` (create) and `/admin/agents/:name`
(edit, loads `GET /api/v1/bots/<name>` on mount). The existing
`AgentsList.svelte` gains a **Create Agent** button, a per-row **Edit**
action for database rows, and a **Delete** confirmation dialog; the
existing `AgentDetail.svelte` gains an **Edit** button for database
agents. Registry rows keep no mutating affordances.

The hand-rolled `Router` (exact-path matching today) is extended with
**parameterized segments** (`:name`) and a `params` map, so the route
table can declare `/admin/agents/:name` without a router dependency.

Vendored shadcn primitives that the shell did not need are added
(**tabs, checkbox, switch, textarea, slider**) — copied from the
shadcn-svelte upstream generator output for bits-ui 2.x, byte-faithful
where possible, since the corporate copy-in source is no longer
available on disk (see §6).

**Python half** (`packages/ai-parrot-server/src/parrot/server/ui/` and
`parrot/handlers/bots.py`): three small backend enablers.

1. **Tools listing is library-owned.** `ToolList` (`handlers/bots.py`)
   is today registered only in the repo-root `app.py:151-155` at
   `/api/v1/agent_tools`; a `pip install ai-parrot-server` deployment does
   not have it. `BotManager.setup()` registers it (same site as
   `ChatbotHandler.configure`, `manager.py:1952`), guarded against double
   registration, and `app.py` drops its own registration.
2. **Disabled agents are listable.** `ChatbotHandler._get_db_agents()`
   filters `enabled=True` (`bots.py:463-473`), so an agent toggled off in
   the form vanishes from the list. `GET /api/v1/bots?include_disabled=true`
   returns all DB agents; default behaviour is unchanged.
3. **Catalog endpoint.** `GET /api/v1/admin/catalog` (`server/ui/catalog.py`,
   `@is_authenticated() @user_session()`) returns the option lists the
   form needs and the server already knows: LLM providers
   (`SUPPORTED_CLIENTS` keys, deduplicated by class), `operation_mode` and
   `memory_type` enums (mirroring `BotModel.__post_init__`), and the
   knowledge-base choices (`AbstractKnowledgeBase` subclasses importable
   from `parrot.stores.kb` — `RedisKnowledgeBase`, `LocalKB` — as
   `custom_kbs` class-path options; see §8 Q2). Registered from
   `setup_admin_ui()` alongside `/api/v1/admin/status`.

**Form ↔ API mapping** (from the brainstorm's Internal Behavior, corrected
against the handler):

| UI action | Request | Notes |
|---|---|---|
| Load for edit | `GET /api/v1/bots/{name}` | DB has priority; response is `_bot_model_to_dict()` + `source` |
| Create | `PUT /api/v1/bots` with `storage: "database"` | Backend slugifies/dedups `name`; **response `name` may differ** → navigate to `/admin/agents/<response.name>`; 201 |
| Update | `POST /api/v1/bots/{name}` | Body = changed fields only (dirty diff); `chatbot_id`/`created_at`/`created_by` never sent |
| Delete | `DELETE /api/v1/bots/{name}` | DB agents only; 403 for repo registry agents is surfaced, not retried |
| Tools list | `GET /api/v1/agent_tools` | `{"tools": {name: {tool_name, module_path, description?}}}` |
| Catalog | `GET /api/v1/admin/catalog` | new |

**Validation model**: client-side required-field checks (`name`, `goal`,
`backstory`, `rationale` — the `required=True` fields of `BotModel`),
range checks (`tool_threshold`, `context_score_threshold` ∈ [0,1];
`temperature` ≥ 0; integer fields), enum checks (`operation_mode`,
`memory_type`), and JSON-object checks for every JSONB field
(`model_config`, `prompt_config`, `vector_store_config`, `reranker_config`,
`parent_searcher_config`, `memory_config`, `permissions`). A tab whose
fields have errors shows a red indicator; Save is blocked until the form
is valid. Server-side errors (`{"message": ...}`, 400/409) are shown in
the sticky footer and never lose the user's input.

**Unsaved-changes guard**: `AgentFormState.dirty` gates both in-app
navigation (a `beforeNavigate` hook added to `Router`) and browser unload
(`beforeunload`), prompting with a confirm dialog.

### Component Diagram

```
 /admin/agents ─────────────── AgentsList.svelte (FEAT-468, extended)
   │  [Create Agent]  [row: Edit | Delete (database only)]
   │        │                     │
   ▼        ▼                     ▼
 /admin/agents/new        /admin/agents/:name      DeleteAgentDialog.svelte
   AgentFormPage.svelte ── AgentFormPage.svelte      └─ DELETE /api/v1/bots/{name}
            │
            ▼
   AgentForm.svelte ──── AgentFormState (rune class: payload, dirty, errors, tabErrors)
     ├─ TabsGeneral      (chatbot_id ro, name, description, avatar, enabled, timezone, language, disclaimer)
     ├─ TabsBehavior     (role, goal, backstory, rationale, capabilities, pre_instructions[], system/human prompt templates, prompt_config JSON)
     ├─ TabsAI           (llm ◄ catalog.providers, model, temperature, max_tokens, top_p/top_k → model_config)
     ├─ TabsCapabilities (tools_enabled, auto_tool_detection, tool_threshold, tools[] ◄ GET /api/v1/agent_tools, operation_mode,
     │                    use_kb, kb[] JSON, custom_kbs[] ◄ catalog.knowledge_bases)
     ├─ TabsDataMemory   (use_vector, vector_store_config JSON, reranker_config JSON, parent_searcher_config JSON,
     │                    context_search_limit, context_score_threshold, memory_type ◄ catalog.memory_types,
     │                    memory_config JSON, max_context_turns, use_conversation_history)
     ├─ TabsAdvanced     (bot_class text, permissions JSON)
     └─ FormFooter       (sticky: Save · Cancel · server error · dirty badge)
            │
            ▼ PUT /api/v1/bots (create)  |  POST /api/v1/bots/{name} (update)
 ┌────────────────────────── aiohttp Application ──────────────────────────┐
 │ ChatbotHandler (existing)  GET/PUT/POST/DELETE /api/v1/bots[/{id}]      │
 │   └─ GET ?include_disabled=true  (new query param)                      │
 │ ToolList (existing)        GET /api/v1/agent_tools  ← now registered by │
 │                                                       BotManager.setup()│
 │ AdminCatalogHandler (new)  GET /api/v1/admin/catalog ← setup_admin_ui() │
 └─────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ui/src/pages/agents/AgentsList.svelte` (FEAT-468) | modified | Create button, Edit/Delete row actions for `source === "database"`, `?include_disabled=true` fetch + "Show disabled" toggle |
| `ui/src/pages/agents/AgentDetail.svelte` (FEAT-468) | modified | Edit button for database agents (navigates to `/admin/agents/:name`) |
| `ui/src/App.svelte` route table | modified | adds `/admin/agents/new` and `/admin/agents/:name` (`requiresAuth: true`) |
| `ui/src/lib/router.svelte.ts` | extended | `:param` segment matching, `params` state, `beforeNavigate` guard hook — existing tests keep passing |
| `ui/src/lib/nav.ts` | unchanged | Agents entry already exists; sub-routes do not get sidebar entries |
| `ui/src/lib/api/http.ts` | consumed | `apiClient.get/put/post/delete`; `ApiError.message` carries the server `{"message"}` |
| `ui/src/lib/ui/internal/shadcn/ui/` | extended | new vendored families: `tabs`, `checkbox`, `switch`, `textarea`, `slider` |
| `parrot.handlers.bots.ChatbotHandler` | modified (minimal) | `_get_db_agents(include_disabled: bool)`; `_get_all` reads the query param |
| `parrot.handlers.bots.ToolList` | re-homed | registered by `BotManager.setup()`; removed from repo-root `app.py` |
| `parrot.server.ui.setup_admin_ui()` | modified | also registers `AdminCatalogHandler` at `/api/v1/admin/catalog` |
| `parrot.clients.factory.SUPPORTED_CLIENTS` | read | provider catalog source |
| `parrot.stores.kb` | read | KB class catalog source |
| `scripts/generate_ts_types.py` + `ui/schemas/` | extended | `AdminCatalog`, `ToolsListResponse`, `ToolInfo`, `BotWritePayload`, `BotMutationResponse` |
| `docs/admin-ui.md` (FEAT-468) | extended | agent CRUD section |

### Data Models

```python
# parrot/server/ui/catalog.py (new) — response model, also the TS-codegen source
class KnowledgeBaseOption(BaseModel):
    class_path: str            # e.g. "parrot.stores.kb.redis.RedisKnowledgeBase"
    name: str                  # class name
    description: str | None = None

class AdminCatalog(BaseModel):
    llm_providers: list[str]                     # sorted, deduplicated SUPPORTED_CLIENTS keys
    operation_modes: list[str]                   # ["conversational", "agentic", "adaptive"]
    memory_types: list[str]                      # ["memory", "file", "redis"]
    knowledge_bases: list[KnowledgeBaseOption]
    bot_class_default: str = "BasicBot"

# parrot/server/ui/models.py (extend) — codegen descriptors only, NOT imported by handlers
class ToolInfo(BaseModel):
    tool_name: str
    module_path: str
    description: str | None = None

class ToolsListResponse(BaseModel):
    tools: dict[str, ToolInfo]                   # GET /api/v1/agent_tools

class BotWritePayload(BaseModel):
    """Body accepted by PUT /api/v1/bots (create) and POST /api/v1/bots/{name} (update).
    Mirrors the user-editable BotModel fields; all optional except name on create."""
    model_config = ConfigDict(extra="forbid")
    storage: Literal["database"] | None = None   # create only
    name: str | None = None
    description: str | None = None
    avatar: str | None = None
    enabled: bool | None = None
    timezone: str | None = None
    language: str | None = None
    disclaimer: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    rationale: str | None = None
    capabilities: str | None = None
    system_prompt_template: str | None = None
    human_prompt_template: str | None = None
    pre_instructions: list[str] | None = None
    prompt_config: dict[str, Any] | None = None
    llm: str | None = None
    model_config_: dict[str, Any] | None = Field(default=None, alias="model_config")  # pydantic reserves model_config
    tools_enabled: bool | None = None
    auto_tool_detection: bool | None = None
    tool_threshold: float | None = None
    tools: list[str] | None = None
    operation_mode: Literal["conversational", "agentic", "adaptive"] | None = None
    use_kb: bool | None = None
    kb: list[dict[str, Any]] | None = None
    custom_kbs: list[str] | None = None
    use_vector: bool | None = None
    vector_store_config: dict[str, Any] | None = None
    reranker_config: dict[str, Any] | None = None
    parent_searcher_config: dict[str, Any] | None = None
    context_search_limit: int | None = None
    context_score_threshold: float | None = None
    memory_type: Literal["memory", "file", "redis"] | None = None
    memory_config: dict[str, Any] | None = None
    max_context_turns: int | None = None
    use_conversation_history: bool | None = None
    bot_class: str | None = None
    permissions: dict[str, Any] | list[dict[str, Any]] | None = None

class BotMutationResponse(BaseModel):
    message: str
    name: str
    source: str | None = None
    chatbot_id: str | None = None                # create only
    vector_store_status: str | None = None       # create only
    vector_store_error: str | None = None
```

```typescript
// ui/src/lib/stores/agent-form.svelte.ts (new, rune class — svelte5-structural)
export class AgentFormState {
  mode: "create" | "edit";
  original: BotWritePayload | null;          // snapshot loaded for edit
  values = $state<BotWritePayload>(defaults());
  errors = $state<Record<string, string>>({});
  serverError = $state<string | null>(null);
  saving = $state(false);
  readonly dirty = $derived(...);            // deep-compare values vs original
  readonly tabErrors = $derived<Record<TabId, number>>(...);  // FIELD_TAB map → count
  validate(): boolean;                       // fills errors, returns validity
  diff(): Partial<BotWritePayload>;          // changed fields only (edit)
  payload(): BotWritePayload;                // full + storage:"database" (create)
}
```

### New Public Interfaces

```python
# parrot/server/ui/catalog.py (new)
@is_authenticated()
@user_session()
class AdminCatalogHandler(BaseView):
    async def get(self) -> web.Response: ...   # GET /api/v1/admin/catalog → AdminCatalog

def build_catalog() -> AdminCatalog: ...       # pure, import-safe; unit-testable without aiohttp

# parrot/manager/manager.py — inside BotManager.setup(), next to ChatbotHandler.configure (:1952)
#   registers ToolList at '/api/v1/agent_tools' (name='tools_list') unless a route with that
#   name already exists (idempotent with any host app that still registers it).

# parrot/handlers/bots.py
class ChatbotHandler:
    async def _get_db_agents(self, include_disabled: bool = False) -> list[BotModel]: ...
    # _get_all(): include_disabled = query param 'include_disabled' in ('1','true','yes')
```

```typescript
// ui/src/lib/router.svelte.ts (extended)
export interface RouteDefinition { path: string; component; requiresAuth?: boolean }  // path may contain ":param"
class Router {
  params = $state<Record<string, string>>({});
  match(path?: string): RouteDefinition | undefined;   // now also fills params
  beforeNavigate: ((to: string) => boolean | Promise<boolean>) | null;  // false cancels
}

// ui/src/lib/api/agents.ts (new) — thin typed wrappers over apiClient
export async function listAgents(opts?: { includeDisabled?: boolean }): Promise<BotsListResponse>;
export async function getAgent(name: string): Promise<BotAgentItem>;
export async function createAgent(body: BotWritePayload): Promise<BotMutationResponse>;
export async function updateAgent(name: string, patch: Partial<BotWritePayload>): Promise<BotMutationResponse>;
export async function deleteAgent(name: string): Promise<BotMutationResponse>;
export async function listTools(): Promise<ToolsListResponse>;
export async function getCatalog(): Promise<AdminCatalog>;
```

---

## 3. Module Breakdown

### Module 1: backend-enablers
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/bots.py` (`_get_db_agents`, `_get_all`), `packages/ai-parrot-server/src/parrot/manager/manager.py` (`ToolList` registration), repo-root `app.py` (remove `ToolList` registration), `packages/ai-parrot-server/tests/test_bots_include_disabled.py`, `tests/test_tools_list_route.py`
- **Responsibility**: `GET /api/v1/bots?include_disabled=true`; library-owned `/api/v1/agent_tools`; no behaviour change for existing callers.
- **Depends on**: none.

### Module 2: admin-catalog-endpoint + codegen models
- **Path**: `packages/ai-parrot-server/src/parrot/server/ui/catalog.py` (new), `server/ui/models.py` (extend), `server/ui/serving.py` (register), `scripts/generate_ts_types.py` (add models), `ui/schemas/*.json` + `ui/src/lib/types/generated/*.d.ts` (regenerated), `tests/test_admin_catalog.py`
- **Responsibility**: `AdminCatalogHandler` + `build_catalog()`; `ToolInfo`, `ToolsListResponse`, `BotWritePayload`, `BotMutationResponse`, `AdminCatalog`, `KnowledgeBaseOption` exported to TS.
- **Depends on**: none (parallel with Module 1).

### Module 3: ui-router-params + vendored form primitives
- **Path**: `ui/src/lib/router.svelte.ts` (+ `router.test.ts`), `ui/src/lib/ui/internal/shadcn/ui/{tabs,checkbox,switch,textarea,slider}/`, `ui/src/lib/components/JsonEditor.svelte` (+ test), `ui/src/lib/components/StringListEditor.svelte` (+ test)
- **Responsibility**: `:param` routes with `params`, `beforeNavigate` hook; the primitives and two reusable form widgets (validated JSON textarea with parse-error display and pretty-print; add/remove/reorder list of strings for `pre_instructions`/`tools`/`custom_kbs`).
- **Depends on**: none (parallel with Modules 1–2).

### Module 4: ui-agent-form-state + api layer
- **Path**: `ui/src/lib/stores/agent-form.svelte.ts` (+ test), `ui/src/lib/api/agents.ts` (+ test), `ui/src/lib/agents/fields.ts` (defaults, FIELD_TAB map, validators)
- **Responsibility**: `AgentFormState` rune class (defaults from `BotModel` defaults, validation rules of §2, dirty diff, tab error aggregation); typed API wrappers.
- **Depends on**: Module 2 (generated types).

### Module 5: ui-agent-form-pages (tabs + routes)
- **Path**: `ui/src/pages/agents/AgentForm.svelte`, `pages/agents/form/{TabsGeneral,TabsBehavior,TabsAI,TabsCapabilities,TabsDataMemory,TabsAdvanced,FormFooter}.svelte`, `pages/agents/AgentFormPage.svelte`, `ui/src/App.svelte` (routes)
- **Responsibility**: the six tabs per §2 diagram, sticky footer, per-tab error badge, create → navigate to returned name, edit → load + diff-update, unsaved-changes guard (router hook + `beforeunload`), server error surfacing.
- **Depends on**: Modules 3, 4.

### Module 6: ui-agents-list-actions (create/edit/delete entry points)
- **Path**: `ui/src/pages/agents/AgentsList.svelte`, `AgentDetail.svelte`, `pages/agents/DeleteAgentDialog.svelte` (+ tests)
- **Responsibility**: Create button; Edit/Delete row actions and Edit-in-detail for database rows only; delete confirmation typed-name dialog; "Show disabled" toggle using `?include_disabled=true`; registry rows unchanged.
- **Depends on**: Modules 1, 3, 4.

### Module 7: e2e + docs
- **Path**: `packages/ai-parrot-server/tests/test_admin_ui_agent_crud.py`, `docs/admin-ui.md`
- **Responsibility**: aiohttp-level round-trip against `ChatbotHandler` with a stubbed DB connection (create → list incl. disabled → update → delete) validating the exact payload shapes the UI sends; docs section for agent management (field/tab mapping, name slugification caveat, registry read-only rule).
- **Depends on**: Modules 1, 2, 5, 6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_get_all_default_hides_disabled` | 1 | `enabled=False` DB agent absent without the param (regression guard) |
| `test_get_all_include_disabled` | 1 | `?include_disabled=true` returns it; `enabled` field present |
| `test_tools_list_registered_by_manager` | 1 | `BotManager.setup()` on a bare app yields a `tools_list` route; calling twice / pre-registered by host does not raise |
| `test_catalog_requires_auth` | 2 | unauthenticated GET → 401 (same harness as `test_admin_status.py`) |
| `test_catalog_shape` | 2 | providers sorted & unique, enums match `BotModel.__post_init__`, KB entries have importable `class_path` |
| `test_build_catalog_kb_import_failure_degrades` | 2 | `LocalKB` import failing (embeddings pkg absent) drops that entry, never raises |
| `test_generate_ts_types_includes_new_models` | 2 | schema files emitted for the six new models |
| `Router` param tests | 3 | `/admin/agents/:name` matches `/admin/agents/helpdesk` with `params.name`; static route wins over param; `beforeNavigate` returning false cancels navigation |
| `JsonEditor` tests | 3 | malformed JSON shows error and reports invalid; valid JSON emits parsed object; array vs object mode |
| `StringListEditor` tests | 3 | add/remove/reorder, trims blanks |
| `AgentFormState` tests | 4 | defaults equal `BotModel` defaults; required fields → errors on right tab; range/enum/JSON validators; `dirty` false after load, true after edit; `diff()` excludes immutable fields and unchanged ones; `payload()` adds `storage: "database"` |
| `agents.ts` tests | 4 | URL/method per operation; `include_disabled` param; error passthrough |
| `AgentForm` create flow | 5 | mocked `PUT` returning a slugified name → navigates to `/admin/agents/<returned>` |
| `AgentForm` edit flow | 5 | loads by name, sends only diff on save, shows 400 `{"message"}` in footer, keeps input |
| `AgentForm` tab error badge | 5 | empty `goal` → Behavior tab badge; Save disabled |
| `AgentForm` unsaved guard | 5 | dirty + navigate → confirm; cancel keeps route |
| `AgentsList` actions | 6 | Create button; Edit/Delete only on database rows; Show-disabled toggles fetch param |
| `DeleteAgentDialog` | 6 | typed-name confirmation; 403 message surfaced; success refreshes list |

### Integration Tests

| Test | Description |
|---|---|
| `test_admin_ui_agent_crud_roundtrip` | aiohttp test client + `ChatbotHandler` with monkeypatched `BotModel` persistence: `PUT` (name "My Bot" → `my-bot`), `GET ?include_disabled=true`, `POST` diff with `enabled:false`, `DELETE`; asserts response shapes match `BotMutationResponse` |
| `test_generated_types_in_sync` (FEAT-468, extended) | regenerating schemas produces no diff for the new models |

### Test Data / Fixtures

```python
@pytest.fixture
def db_agents(monkeypatch):
    """Patch ChatbotHandler._get_db_agents/_get_db_agent with an in-memory
    list of BotModel-shaped stand-ins (enabled and disabled)."""

@pytest.fixture
def app_with_bots(db_agents) -> web.Application:
    """aiohttp app: ChatbotHandler.configure(app, '/api/v1/bots') + stub
    bot_manager (registry.has → False, remove_bot no-op); auth short-circuit
    reused from tests/test_admin_status.py."""
```

```typescript
// ui vitest fixtures: dbAgentFull (all BotModel fields as returned by GET),
// catalogFixture (providers/enums/kbs), toolsFixture ({tools:{...}}).
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] From `/admin/agents`, **Create Agent** opens `/admin/agents/new`; a
  database row's **Edit** (row action or detail dialog) opens
  `/admin/agents/<name>`; registry rows expose **no** create/edit/delete
  affordance.
- [ ] The form is a six-tab layout — General, Behavior, AI, Capabilities,
  Data & Memory, Advanced — with Save/Cancel sticky across tabs; every
  user-editable `BotModel` field is reachable in exactly one tab;
  `chatbot_id` is shown read-only in edit mode.
- [ ] Create sends `PUT /api/v1/bots` with `storage: "database"`; on 201
  the UI navigates to the **name returned by the server** (slugified /
  deduplicated names round-trip correctly).
- [ ] Edit loads `GET /api/v1/bots/<name>`, sends `POST /api/v1/bots/<name>`
  with **only changed fields**, and never sends `chatbot_id`,
  `created_at`, `created_by`.
- [ ] Delete requires typed-name confirmation, calls
  `DELETE /api/v1/bots/<name>`, refreshes the list; a 403 for a repo
  registry agent is displayed verbatim.
- [ ] Missing required fields (`name`, `goal`, `backstory`, `rationale`)
  and invalid values (ranges, enums) block Save and mark the owning tab
  with a red indicator.
- [ ] Every JSONB field (`model_config`, `prompt_config`,
  `vector_store_config`, `reranker_config`, `parent_searcher_config`,
  `memory_config`, `permissions`) is edited through the JSON editor;
  malformed JSON blocks submission with an inline error.
- [ ] Tools are picked from `GET /api/v1/agent_tools`; that route is
  registered by `BotManager.setup()` (works on a wheel install) and is no
  longer registered by repo-root `app.py`.
- [ ] LLM provider, operation mode, memory type and KB class options come
  from `GET /api/v1/admin/catalog` (auth-required); the UI hardcodes none
  of them.
- [ ] `GET /api/v1/bots?include_disabled=true` lists disabled DB agents;
  without the param behaviour is byte-identical to today; the list view
  offers a "Show disabled" toggle.
- [ ] Navigating away (in-app or browser unload) with unsaved changes
  prompts for confirmation.
- [ ] Server errors (`{"message"}` 400/409/403) are shown in the footer
  without discarding user input.
- [ ] `bot_class` is a plain text input (default `BasicBot`);
  `permissions` uses the JSON editor.
- [ ] All new API payload types are generated (`pnpm generate`) from the
  Pydantic models in `parrot.server.ui`; no hand-written TS payload types.
- [ ] Python tests pass (`pytest packages/ai-parrot-server/tests/ -v`) and
  UI tests pass (`pnpm test` in `packages/ai-parrot-server/ui`); FEAT-468
  read-only tests still pass unmodified except where affordances were
  intentionally added.
- [ ] `docs/admin-ui.md` gains an "Agent management" section.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-30 against `dev` (`b988d2248`). Implementation agents
> MUST NOT reference imports, attributes, or methods not listed here
> without first verifying via `grep`/`read`. The brainstorm's Code Context
> referenced `navigator-frontend-next` paths that are **not** the target
> — see "Does NOT Exist".

### Verified Imports

```python
from parrot.server.ui import setup_admin_ui                       # server/ui/__init__.py; used by tests/test_admin_status.py:26
from parrot.server.ui.status import AdminStatusHandler, AdminStatus, AgentCounts, DependencyHealth  # server/ui/status.py
from parrot.server.ui.models import BotAgentItem, BotsListResponse  # server/ui/models.py:19,41
from parrot.handlers.bots import ChatbotHandler, ToolList           # handlers/bots.py:424, :1332
from parrot.handlers.models.bots import BotModel                    # handlers/models/bots.py:20  (asyncdb/datamodel Model, NOT pydantic)
from parrot.clients.factory import SUPPORTED_CLIENTS                # clients/factory.py:107 (dict provider-key → client class)
from parrot.stores.kb import AbstractKnowledgeBase, RedisKnowledgeBase  # stores/kb/__init__.py:3-4
from parrot.stores.kb import LocalKB                                # lazy __getattr__ (kb/__init__.py:17-22) — needs ai-parrot-embeddings; wrap in try/except
from parrot.utils.naming import slugify_name, deduplicate_name      # utils/naming.py:15, :42
from parrot.tools.discovery import discover_all                     # used at handlers/bots.py:37, :1346
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
```

### Existing Class Signatures

```python
# packages/ai-parrot-server/src/parrot/handlers/bots.py
class ChatbotHandler(_PBACHandlerMixin, AbstractModel):   # :424
    model = BotModel; pk = 'chatbot_id'                     # :438, :440
    def _agent_name_from_request(self) -> str | None       # :455 — match_info['id'] or ?name=
    async def _get_db_agents(self) -> list[BotModel]       # :463 — BotModel.filter(enabled=True)  ← the include_disabled change site
    async def _get_db_agent(self, name) -> BotModel | None # :475 — BotModel.get(name=name), NO enabled filter
    async def _check_duplicate(self, name) -> str | None   # :490
    def _bot_model_to_dict(self, agent) -> dict            # :605 — to_dict() + str(chatbot_id) + str(dates) + source='database'
    def _registry_agent_to_dict(self, name, meta) -> dict  # :618
    async def get(self)                                     # :640 → _get_one (:653) | _get_all (:702; response :751 {"agents","total"})
    async def put(self)                                     # :756 — pops 'storage' (default 'database'); requires name (:781);
                                                            #   slugify_name + deduplicate_name (:789-812); may prefix description
                                                            #   with "Display name: <original>." when renamed (:820-825)
    async def _put_database(self, payload)                  # :852 — reranker/parent_searcher must be dict (:855-860);
                                                            #   BotModel(**payload).insert(); registers into BotManager; 201 body :895-903
    async def post(self)                                    # :1072 — name from URL; DB first, then registry; 404 :1111
    async def _post_database(self, agent, payload)          # :1116 — skips chatbot_id/created_at/created_by (:1133);
                                                            #   agent.set(k, v) per key; updated_at=now; re-registers bot; body :1154-1158
    async def delete(self)                                  # :1247 — registry repo agents → 403 (:1289-1297); factory → deletes;
                                                            #   DB → delete + manager.remove_bot; 404 when absent (:1302)

@user_session()
class ToolList(_PBACHandlerMixin, BaseView):               # :1332
    async def get(self)                                     # :1343 — discover_all() → {"tools": {name: {tool_name, module_path[, description]}}} (:1388)
# ROUTE: registered ONLY in repo-root app.py:151-155 — app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')

# packages/ai-parrot-server/src/parrot/handlers/models/bots.py
class BotModel(Model):                                      # :20  (asyncdb datamodel; Field(required=..., default=..., ui_help=...))
    chatbot_id: uuid.UUID                                   # :96  pk, default uuid4
    name: str  (required)                                   # :104
    description, avatar: str; enabled: bool = True; timezone: str = "UTC"   # :105-108
    role = "AI Assistant"; goal (required); backstory (required); rationale (required); capabilities  # :111-136
    system_prompt_template, human_prompt_template: Optional[str]; pre_instructions: List[str]; prompt_config: dict  # :138-163
    llm: str = 'google'; model_config: dict  ('model'/'model_name','temperature','max_tokens','top_k','top_p')  # :165-175
    tools_enabled = True; auto_tool_detection = True; tool_threshold = 0.7; tools: List[str]; operation_mode = 'adaptive'  # :177-185
    use_kb = False; kb: List[dict]; custom_kbs: List[str] | None   # :188-198
    use_vector = False; vector_store_config, reranker_config, parent_searcher_config: dict  # :200-218
    context_search_limit = 10; context_score_threshold = 0.7      # :220-230
    memory_type = 'memory'; memory_config: dict; max_context_turns = 5; use_conversation_history = True  # :232-249
    bot_class: Optional[str] = 'BasicBot'                   # :251
    permissions: dict (see ui_help :258-275 — list-of-rules shape also accepted)
    language = 'en'; disclaimer: Optional[str]; created_at; created_by: Optional[int]; updated_at  # :277-298
    def __post_init__(self)                                 # :300 — validates operation_mode ∈ {conversational,agentic,adaptive} (:307),
                                                            #   memory_type ∈ {memory,file,redis} (:312), 0 ≤ tool_threshold ≤ 1 (:317)
    def to_bot_config(self) -> dict                         # :321
    class Meta: name = PARROT_BOTS_TABLE; schema = PARROT_SCHEMA   # :391-395

# packages/ai-parrot-server/src/parrot/server/ui/serving.py
def setup_admin_ui(app, *, prefix=DEFAULT_PREFIX) -> bool  # :156 — add_view('/api/v1/admin/status', AdminStatusHandler) at :195
                                                            #   (registers API even when dist absent) ← add catalog view here
# packages/ai-parrot-server/src/parrot/server/ui/models.py — BotAgentItem(extra="allow"; name, source) :19; BotsListResponse :41
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  def setup(self, app)                     # :1686; ChatbotHandler.configure(self.app, '/api/v1/bots') :1952;
                                                            #   setup_credentials_routes :2221, setup_mcp_helper_routes :2225, setup_admin_ui :2230
# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: dict[str, type]                          # :107 — keys include aliases (claude/anthropic, bedrock/anthropic-aws, xai/grok,
                                                            #   local/localllm/ollama, claude-agent/claude-code, codex-agent/openai-codex/codex-code…)
                                                            #   → catalog dedups by class, prefers first key
# packages/ai-parrot/src/parrot/stores/kb/
class AbstractKnowledgeBase(ABC)  __init__(self, name: str, ...)   # abstract.py:7,:12
class RedisKnowledgeBase(AbstractKnowledgeBase)  __init__(*, name, category, namespace, ...)  # redis.py:14,:22
class LocalKB(AbstractKnowledgeBase)  __init__(name, kb_directory: Path, ...)                 # local.py:17,:37
# Chatbot consumption: bots/chatbot.py:439-452 — use_kb → KnowledgeBaseStore; custom_kbs = list of class paths → import_kb_class + register_kb
# scripts/generate_ts_types.py — _models() mapping :45-63 (add new models); writes ui/schemas/<Name>.json; pnpm generate → src/lib/types/generated/
```

```typescript
// packages/ai-parrot-server/ui/src/lib/router.svelte.ts
export interface RouteDefinition { path: string; component: RouteComponentLoader; requiresAuth?: boolean }
class Router { path = $state(...); routes: RouteDefinition[]; navigate(to, {replace}); match(path?)  /* exact pathname match today */; guard(path?) }
export const router = new Router();
// packages/ai-parrot-server/ui/src/App.svelte — router.routes table (login/home/dashboard/agents); resolve() → guard → lazy component
// packages/ai-parrot-server/ui/src/lib/api/http.ts — default apiClient (axios); class ApiError { message; code; status; raw }; 401 → authStore.handle401()
// packages/ai-parrot-server/ui/src/lib/config.ts — config.basePath="/admin", loginPath, tokenStorageKey="ai_parrot_token"
// packages/ai-parrot-server/ui/src/pages/agents/AgentsList.svelte — apiClient.get<BotsListResponse>("/api/v1/bots"); Button/Badge/Card/Input/Skeleton; <AgentDetail agent bind:open>
// packages/ai-parrot-server/ui/src/pages/agents/AgentDetail.svelte — Dialog-based; props { agent: BotAgentItem|null; open = $bindable(false) }
// Vendored primitives present: avatar, badge, button, card, dialog, input, label, select, separator, skeleton (+ utils.ts cn())
// Test harness: vitest + @testing-library/svelte + jsdom; mocking pattern vi.spyOn(apiClient, "get") (AgentsList.test.ts:29-31)
// package.json scripts: dev / build (= pnpm generate && vite build) / test (vitest run) / generate (json2ts -i schemas -o src/lib/types/generated)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AdminCatalogHandler` | `setup_admin_ui()` | `app.router.add_view("/api/v1/admin/catalog", …)` next to status | `server/ui/serving.py:195` |
| `build_catalog()` | `SUPPORTED_CLIENTS`, `parrot.stores.kb`, `BotModel.__post_init__` enums | import + read | `clients/factory.py:107`, `stores/kb/__init__.py:10-22`, `handlers/models/bots.py:307-317` |
| `ToolList` registration | `BotManager.setup()` | `self.app.router.add_view('/api/v1/agent_tools', ToolList, name='tools_list')` | `manager/manager.py:1952` (pattern), `app.py:151-155` (current site to remove) |
| `include_disabled` | `ChatbotHandler._get_all` → `_get_db_agents` | `self.query_parameters(self.request)` (already used at `:459`) | `handlers/bots.py:463-473, :702-716` |
| `AgentFormPage` (create) | `ChatbotHandler.put` | `apiClient.put("/api/v1/bots", {storage:"database", …})` → 201 `{name}` | `handlers/bots.py:756-903` |
| `AgentFormPage` (edit) | `ChatbotHandler.get/post` | `GET /api/v1/bots/{name}`, `POST /api/v1/bots/{name}` | `handlers/bots.py:653-686, :1072-1158` |
| `DeleteAgentDialog` | `ChatbotHandler.delete` | `DELETE /api/v1/bots/{name}` | `handlers/bots.py:1247-1326` |
| `TabsCapabilities` tools picker | `ToolList.get` | `GET /api/v1/agent_tools` | `handlers/bots.py:1343-1388` |
| New routes | `App.svelte` route table + `Router.match` params | `{ path: "/admin/agents/:name", requiresAuth: true }` | `ui/src/App.svelte`, `ui/src/lib/router.svelte.ts` |
| Generated types | `scripts/generate_ts_types.py::_models()` | add 6 models | `scripts/generate_ts_types.py:45-63` |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator-frontend-next/src/routes/agents/...`, `AgentManagement.svelte`, Flowbite Svelte, `$app/navigation`, `$app/environment`, `$env/dynamic/public`~~ — brainstorm targets; this feature lives in `packages/ai-parrot-server/ui/` (plain Vite SPA, no SvelteKit). The corporate repo at `/home/jesuslara/proyectos/navigator-frontend-next` is **not present on disk** (TASK-2525 was blocked on it once — commit `c25495486`); vendor missing primitives from shadcn-svelte upstream, do not plan a copy-in.
- ~~`/api/v1/agent_tools` registered in the library~~ — only in repo-root `app.py`; wheel installs lack it until Module 1.
- ~~`GET /api/v1/admin/catalog`, `parrot/server/ui/catalog.py`~~ — new in this spec.
- ~~a providers/models/embeddings listing endpoint (`/api/v1/models`, `/api/v1/providers`, `/api/v1/embeddings`)~~ — none; grep hit zero.
- ~~a KB registry/list of KB *instances* (`KB_REGISTRY`, `list_kbs()`)~~ — `parrot.stores.kb` exposes classes only; `BotModel.kb` is a free-form `List[dict]` and `custom_kbs` a list of class paths.
- ~~`BotModel` as a Pydantic model / `model_json_schema()`~~ — it is an asyncdb datamodel `Model`; hence the codegen descriptor `BotWritePayload` in `server/ui/models.py`. Note `model_config` is a **column name** on `BotModel` and a **reserved attribute** on Pydantic — the descriptor must use an alias.
- ~~`GET /api/v1/bots` returning disabled agents / an `include_disabled` param~~ — new in Module 1.
- ~~a router library (`svelte-spa-router`, `tinro`, `@sveltejs/kit` routing) or `Router.params`/`beforeNavigate`~~ — router is hand-rolled; params/hook are new in Module 3.
- ~~vendored `tabs`, `checkbox`, `switch`, `textarea`, `slider` primitives, `JsonEditor`, `StringListEditor`, `ui/src/lib/api/agents.ts`, `stores/agent-form.svelte.ts`~~ — new.
- ~~`svelte-jsoneditor` / any JSON editor dependency~~ — not a dependency; the JSON editor is a validated textarea unless §8 Q1 decides otherwise.
- ~~`ChatbotHandler.patch()` / update by `chatbot_id`~~ — update is `POST /api/v1/bots/{name}`; all mutations key on `name`.
- ~~`BotModel.enabled` filtering in `_get_db_agent`/`get one`~~ — only the list filters `enabled=True`; single-agent GET/POST/DELETE find disabled agents fine.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Backend: `@is_authenticated() @user_session()` on a `BaseView`
  (precedent `server/ui/status.py`); Pydantic response models in
  `parrot.server.ui.*` are the single codegen source; `self.logger`,
  async throughout; `build_catalog()` must be import-safe when
  `ai-parrot-embeddings` is absent (wrap the `LocalKB` lazy import).
- `ToolList` registration in `BotManager.setup()` must be idempotent:
  check `app.router.named_resources()` for `tools_list` before adding, so
  a host app that still registers it does not crash.
- Keep `ChatbotHandler` changes surgical: one keyword parameter, one query
  read; do not touch validation/slugify paths.
- UI: svelte5-structural doctrine (`ui/docs/svelte5-structural/SKILL.md`)
  — rune class for `AgentFormState`, semantic tokens inside vendored
  primitives, scale tokens in pages; generated types are read-only;
  mocking via `vi.spyOn(apiClient, …)` as in existing tests. Avoid
  `$state` reads before the first `await` in fetch functions (see
  `AgentsList.svelte` comment) to prevent `$effect` self-retriggering.
- Tabs must keep all panels' state mounted (or fully in the store) so
  validation covers hidden tabs — the brainstorm's known Option B cost.
- Create/edit share one component; mode drives defaults vs load, `PUT`
  vs `POST`, full payload vs diff.
- Commit convention `sdd: <action> for ui-agent-management`; never commit
  `ui/dist/` or `node_modules/`.

### Known Risks / Gotchas

- **Name is the identity and the backend may change it on create**
  (`slugify_name` + `deduplicate_name`, `bots.py:789-825`) — always route
  to the returned `name`; show a notice when it differs from what the user
  typed. Renaming an existing agent via `POST {name: …}` changes its URL
  and re-registers the bot; the form treats `name` as read-only in edit
  mode (documented; renaming is out of scope for v1).
- **Disabled agents disappear from the default list** — Module 1 fixes
  listing; the list's "Show disabled" toggle defaults off to keep FEAT-468
  behaviour.
- **`POST` applies every key sent** (`agent.set(key, val)`) — sending the
  full payload would rewrite `updated_at`-adjacent fields and could clobber
  concurrent edits; send the diff only.
- **JSON validation must happen client-side** for every JSONB field
  (brainstorm edge case): the backend only checks `reranker_config` /
  `parent_searcher_config` are dicts and otherwise fails with a generic
  400 from `BotModel(**payload)`.
- **`permissions` shape is dual** (dict or list of rule dicts per
  `ui_help`); the JSON editor accepts both; the form does not validate
  rule semantics (backend `parse_bot_permissions` does at load).
- **`model_config` naming clash** with Pydantic — alias in the codegen
  descriptor; the generated TS keeps the wire name `model_config`.
- **Catalog provider aliases** — `SUPPORTED_CLIENTS` has many alias keys
  for the same class; dedup by class and keep the canonical (first) key,
  but accept any stored alias value when loading an existing agent (show
  it even if not in the list).
- **Unsaved-changes guard vs the 401 interceptor** — `handle401()`
  navigates to login; the guard must not block that redirect (bypass when
  the destination is `config.loginPath`).
- **Corporate copy-in source is gone** — new primitives come from
  shadcn-svelte upstream; keep the vendored style (semantic tokens, `cn()`),
  and run `pnpm test` in jsdom: bits-ui floating primitives (select) were
  already avoided in FEAT-468 tests for this reason — prefer native
  `<select>`-backed wrappers or the existing 3-way button pattern where
  option counts are small.
- **Vite/Svelte majors** — stay on the FEAT-468 pins (vite ^5.4, svelte
  ^5.55); do not bump as part of this feature.
- **Concurrent sessions on `dev`** — another session is committing to
  `dev` in this repo; worktree from `origin/dev` after `/sdd-task`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| *(Python)* | — | **no new Python dependencies** |
| `bits-ui` | `^2.18` (present) | tabs/checkbox/switch/slider primitives |
| `svelte`, `vite`, `vitest`, `@testing-library/svelte`, `jsdom` | present pins | no changes |
| `json-schema-to-typescript` | present | generated types for the 6 new models |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `feat-475-ui-agent-management` from `origin/dev`.
- **Parallelizable**: Modules 1, 2 and 3 are independent (backend
  enablers · catalog+codegen · router+primitives) and may be dispatched
  concurrently; Module 4 waits on 2; Modules 5–6 wait on 3–4; Module 7
  last.
- **Cross-feature dependencies**: FEAT-468 (`ui-server-backend`) is merged
  on `dev` (9/9 tasks done) — required. No dependency on
  `agentstudio-management`.

---

## 8. Open Questions

> Carried from the brainstorm (both unresolved there — the brainstorm's
> table had no `[x]` items). Neither blocks task decomposition; the spec
> fixes a recommendation and implementation follows it unless overridden.

- [ ] **Q1 — JSON editor: external library (`svelte-jsoneditor`) or a
  validated auto-resizing textarea?** — *Owner: Jesus Lara*. Spec
  recommendation: **validated textarea** (`JsonEditor.svelte`, Module 3)
  — zero dependencies, jsdom-testable, pretty-print button; a richer
  editor can replace it later behind the same props.
- [ ] **Q2 — Which KB IDs/names to hardcode in the UI?** — *Owner: Jesus
  Lara*. Spec recommendation: **hardcode none**; serve the importable
  `AbstractKnowledgeBase` classes (`RedisKnowledgeBase`, `LocalKB`) from
  `GET /api/v1/admin/catalog` as `custom_kbs` class-path options, and edit
  `kb` (free-form `List[dict]`) with the JSON editor. If specific
  deployment KB instances must be offered, add them to the catalog
  builder, not to the UI.
- [ ] **Q3 (new) — Should the edit form allow renaming (`name`) an
  existing DB agent?** — *Owner: Jesus Lara*. Spec default: **no** (name is
  the identity for URL, `BotManager` registration and formdesigner links);
  read-only in edit mode.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-30 | Jesus Lara | Initial draft from `ui-agent-management.brainstorm.md`, re-anchored on the FEAT-468 Admin UI |
