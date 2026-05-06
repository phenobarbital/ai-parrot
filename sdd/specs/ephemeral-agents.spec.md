---
type: feature
base_branch: dev
---

# Feature Specification: Ephemeral User Agents

**Feature ID**: FEAT-149
**Date**: 2026-05-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: tbd

---

## 1. Motivation & Business Requirements

### Problem Statement

Today users can only create bots through the existing `UserAgentHandler`
(`PUT /api/v1/user_agents`), which **persists to `navigator.users_bots`
synchronously and instantiates lazily on first chat**. There is no way
to:

1. Create an agent that lives **only in memory** (BotManager) for a
   trial session, with no DB row, and discard it cheaply.
2. Wait for the agent to be **warm** (LLM client ready, `ToolManager`
   synchronized, MCP handshakes done, RAG index built) before the user
   sends the first message.
3. **Promote** an ephemeral session-scoped agent into a persisted
   `users_bots` row only when the user is satisfied with it.
4. Expose a **catalog of available tools** to the frontend so the user
   can pick from `TOOL_REGISTRY` instead of guessing tool names.
5. Use a **lightweight, file-backed FAISS** store for RAG on uploaded
   files instead of provisioning a `pgvector` collection per trial.

### Goals

- Add a per-user ephemeral lifecycle on top of the existing
  `UserAgentHandler` / `UserBotModel` machinery without forking the
  data model.
- Reuse `BotManager.add_agent` / `get_user_bot` / `save_agent` and the
  encrypted-fields helpers — no duplicate persistence layer.
- Make warm-up observable: `POST` returns immediately with a
  `chatbot_id` and a `status` of `creating`; clients poll until
  `ready`.
- Default ephemeral TTL: **24 h** (override via env), with the same
  background cleanup hook BotManager already runs.
- Once an ephemeral agent is "saved", it stops being ephemeral —
  removed from the in-memory ephemeral registry, available through the
  normal user-bot resolution path.
- AgentTalk (`POST /api/v1/agents/chat/{agent_id}`) keeps working with
  no API change — `_resolve_bot` already checks BotManager first.

### Non-Goals

- Replacing or deprecating `PUT /api/v1/user_agents` (the synchronous
  DB-first flow) — both flows coexist.
- Multi-tenant bot sharing **other than** the explicit "share key"
  follow-up listed in §8 (Open Questions). Ephemeral agents are
  per-user by default.
- Adding stdio/local MCP server support to the runtime attach flow —
  HTTP-only for now (§7).
- Redesigning the tool registry; we expose `TOOL_REGISTRY` as-is
  through a read-only catalog endpoint.

---

## 2. Architectural Design

### Overview

A user POSTs an agent definition (LLM, prompt, selected tools, MCP
HTTP servers, optional documents, optional vector mode) to
`POST /api/v1/agents/user/`. The handler:

1. Persists nothing in DB.
2. Uploads any documents to S3 via the existing `FileManagerToolkit`
   (same path used today by `_ingest_uploads`).
3. Constructs a `UserBotModel` *in memory only* and uses the existing
   instantiation pipeline to build an `AbstractBot` instance.
4. Schedules `await agent.configure(app)` as a background task and
   tracks its progress in a per-bot `EphemeralAgentStatus`.
5. Registers the bot via `BotManager.add_agent(agent)` (memory-only,
   keyed by `str(chatbot_id)`).
6. Returns `201` with `{chatbot_id, status: "creating"}`.

The client then polls `GET /api/v1/agents/user/{chatbot_id}/status`
until `status == "ready"`.

`PUT /api/v1/agents/user/{chatbot_id}` promotes the ephemeral bot:
the in-memory `UserBotModel` is INSERTed into `navigator.users_bots`,
documents stay in S3 (their paths are already in `documents`), and the
FAISS index — if the agent uses Vector RAG — is dumped to S3 and its
location stored in `vector_config['faiss_persist_path']`. The agent is
then removed from the ephemeral registry (it remains accessible via
the normal `BotManager.get_user_bot` DB-resolution path).

`DELETE /api/v1/agents/user/{chatbot_id}` works for both ephemeral
and persisted agents (in the persisted case it delegates to the
existing DELETE `/api/v1/user_agents/{chatbot_id}` cleanup, including
S3 doc removal).

### Component Diagram

```
Client
  │
  ├─ POST /api/v1/agents/user/ (multipart: config + files[])
  │         │
  │         ▼
  │   EphemeralUserAgentHandler
  │         │
  │         ├─ _ingest_uploads() ──────► S3 (FileManagerToolkit)
  │         ├─ build UserBotModel in-memory
  │         ├─ instantiate AbstractBot
  │         ├─ BotManager.add_agent(bot)  (ephemeral registry)
  │         └─ asyncio.create_task(_warm_up(bot))
  │                  │
  │                  ├─ await bot.configure(app)
  │                  │     ├─ ToolManager sync
  │                  │     ├─ MCP HTTP handshake (validate)
  │                  │     └─ Vector RAG build (FAISS) OR PageIndex build
  │                  └─ EphemeralAgentStatus → ready / error(detail)
  │
  ├─ GET /api/v1/agents/user/{id}/status   →  {status, progress?, error?}
  ├─ PUT /api/v1/agents/user/{id}          →  promote (insert users_bots)
  ├─ DELETE /api/v1/agents/user/{id}       →  drop ephemeral OR delete persisted
  │
  └─ GET /api/v1/tools/catalog             →  TOOL_REGISTRY readout
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `UserBotModel` (`parrot/handlers/models/users_bots.py:26`) | reuses | Built in-memory for ephemerals; INSERTed on promote. |
| `UserAgentHandler` (`parrot/handlers/agents/users.py:161`) | extends | New `EphemeralUserAgentHandler` shares its `_parse_request`, `_ingest_uploads`, and `_resolve_user_id` helpers (refactored to a shared mixin if needed). |
| `BotManager` (`parrot/manager/manager.py:81`) | extends | New methods `create_ephemeral_user_bot`, `promote_user_bot`, `get_ephemeral_status`. Reuses `add_agent` (line 809), `save_agent` (line 817), `get_user_bot` (line 737), `_cleanup_expired_bots` background task. |
| `FAISSStore` (`parrot/stores/faiss_store.py:32`) | extends | Add `dump_to_s3()` / `load_from_s3()` for promote/load lifecycle. |
| `parrot.pageindex` (`parrot/pageindex/builder.py`) | uses | Selected when `vector_config['rag_mode'] == 'pageindex'`. |
| `FileManagerToolkit` (used in `users.py:300+`) | uses | S3 upload of original docs (already implemented), and new `dump_to_s3` payload for FAISS. |
| `TOOL_REGISTRY` (`parrot_tools` package, used in `parrot/tools/__init__.py:184`) | reads | Exposed read-only via `GET /api/v1/tools/catalog`. |
| `MCPClient` (`parrot/mcp/`) | uses | `await client.connect()` invoked during warm-up to validate HTTP handshake before the agent is marked `ready`. |
| AgentTalk `_resolve_bot` (`parrot/handlers/agent.py:932`) | unchanged | Already prefers `BotManager.get_user_bot` → falls back to `get_bot`; ephemeral agents are reachable as-is. |

### Data Models

```python
# parrot/manager/ephemeral.py  (NEW)
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

EphemeralPhase = Literal["creating", "warming", "ready", "error"]

class EphemeralAgentStatus(BaseModel):
    """Live warm-up state for an ephemeral user bot."""
    chatbot_id: str
    user_id: int
    phase: EphemeralPhase
    progress: dict = {}      # {"tools": "ready", "mcp": "ready", "rag": "building"}
    error: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    rag_mode: Optional[Literal["pageindex", "vector"]] = None
```

`UserBotModel` is reused unchanged. The existing
`vector_config: dict` carries `rag_mode` (`"pageindex"` or `"vector"`)
and, on promote, `faiss_persist_path` for vector mode.

### New Public Interfaces

```python
# parrot/manager/manager.py — added to BotManager
async def create_ephemeral_user_bot(
    self,
    user_id: int,
    config: dict,
    uploaded_paths: list[tuple[str, str]],   # [(s3_path, original_name), ...]
    *,
    ttl_seconds: int = 86400,
) -> EphemeralAgentStatus: ...

async def promote_user_bot(
    self,
    chatbot_id: str,
    user_id: int,
) -> UserBotModel: ...

async def save_user_bot(
    self,
    model: UserBotModel,
) -> UserBotModel:
    """INSERT (or UPSERT) into navigator.users_bots via UserBotModel.

    Distinct from save_agent (which targets navigator.ai_bots). Used
    by promote_user_bot and reusable for any future flow that needs
    to write to users_bots from BotManager.
    """

def get_ephemeral_status(
    self,
    chatbot_id: str,
    user_id: int,
) -> Optional[EphemeralAgentStatus]: ...

async def discard_ephemeral_user_bot(
    self,
    chatbot_id: str,
    user_id: int,
) -> bool: ...
```

```python
# parrot/handlers/agents/ephemeral.py  (NEW)
class EphemeralUserAgentHandler(BaseView):
    """POST /api/v1/agents/user/                — create ephemeral
    GET  /api/v1/agents/user/{id}/status   — warm-up polling
    PUT  /api/v1/agents/user/{id}          — promote to persisted
    DELETE /api/v1/agents/user/{id}        — discard ephemeral or delete persisted
    """
```

```python
# parrot/handlers/tools_catalog.py  (NEW)
class ToolCatalogHandler(BaseView):
    """GET /api/v1/tools/catalog — read-only TOOL_REGISTRY surface."""
```

---

## 3. Module Breakdown

### Module 1: `EphemeralAgentStatus` & in-memory registry
- **Path**: `packages/ai-parrot/src/parrot/manager/ephemeral.py` (new)
- **Responsibility**: Pydantic model + per-`BotManager` dict
  `_ephemeral_status: dict[str, EphemeralAgentStatus]` keyed by
  `chatbot_id`, with TTL/expiration helpers that piggyback on
  `BotManager._cleanup_expired_bots`.
- **Depends on**: existing BotManager.

### Module 2: BotManager ephemeral methods + `save_user_bot`
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py`
- **Responsibility**: implement `create_ephemeral_user_bot`,
  `promote_user_bot`, `get_ephemeral_status`,
  `discard_ephemeral_user_bot`, and a NEW
  `save_user_bot(model: UserBotModel) -> UserBotModel` that INSERTs
  into `navigator.users_bots` via `UserBotModel` (the existing
  `save_agent` writes `navigator.ai_bots` via `BotModel` and is NOT
  reusable here). Builds the `UserBotModel` in-memory for ephemerals,
  invokes the same instantiation path used by `get_user_bot`, and
  schedules warm-up via `asyncio.create_task`. `promote_user_bot`
  delegates the actual DB write to `save_user_bot`.
- **Depends on**: Module 1; existing `add_agent`, encrypted-fields
  helpers in `_encrypted_field.py`. Does **not** call `save_agent`.

### Module 3: Warm-up coroutine (`_warm_up`)
- **Path**: `packages/ai-parrot/src/parrot/manager/ephemeral.py`
- **Responsibility**: drives `await agent.configure(app)`, runs MCP
  HTTP handshake validation per server, builds the RAG index
  (FAISS or PageIndex) over the uploaded docs, and updates
  `EphemeralAgentStatus.phase` / `progress`. Catches and records
  exceptions in `error`.
- **Depends on**: Module 2; FAISS / PageIndex builders; `MCPClient`.

### Module 4: `EphemeralUserAgentHandler`
- **Path**: `packages/ai-parrot/src/parrot/handlers/agents/ephemeral.py` (new)
- **Responsibility**: HTTP surface for the four routes. Reuses
  `_parse_request`, `_ingest_uploads`, `_resolve_user_id` from
  `UserAgentHandler` (refactored into a `_UserAgentRequestMixin` if
  needed to avoid duplication).
- **Depends on**: Module 2; existing `UserAgentHandler` helpers.

### Module 5: Route registration
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py` (around
  line 1042 where `/api/v1/user_agents` routes are added today)
- **Responsibility**: register the four new ephemeral routes and the
  tools catalog route on the aiohttp app.
- **Depends on**: Modules 4, 7.

### Module 6: FAISS persistence to S3
- **Path**: `packages/ai-parrot/src/parrot/stores/faiss_store.py`
- **Responsibility**: add `async def dump_to_s3(self, key: str) -> str`
  and `classmethod async def load_from_s3(cls, key: str, **kwargs)
  -> FAISSStore`. Dumps the in-memory index + docstore to a tarball
  and uploads via `FileManagerToolkit`.
- **Depends on**: existing `FAISSStore`, `FileManagerToolkit`.

### Module 7: `ToolCatalogHandler`
- **Path**: `packages/ai-parrot/src/parrot/handlers/tools_catalog.py` (new)
- **Responsibility**: returns `TOOL_REGISTRY` as JSON
  `[{slug, dotted_path, description?}, ...]`. Read-only, no auth
  required beyond the standard session check.
- **Depends on**: `parrot_tools.TOOL_REGISTRY` (verified import path
  in §6).

### Module 8: MCP HTTP handshake validator
- **Path**: `packages/ai-parrot/src/parrot/mcp/integration.py`
- **Responsibility**: a small `async def validate_mcp_http(config:
  MCPServerConfig) -> None` helper that opens a connection, lists
  tools once, and either returns or raises a typed error so the
  warm-up can record it in `EphemeralAgentStatus.error`.
- **Depends on**: existing `MCPClient`.

### Module 9: Sharing scaffold (deferred)
- **Path**: `packages/ai-parrot/src/parrot/handlers/agents/sharing.py` (new, stub only)
- **Responsibility**: stub module + open question (§8) for
  share-key / per-user-grant scheme. Implementation deferred to a
  follow-up FEAT.
- **Depends on**: post-FEAT-149 design.

### Module 10: Frontend integration handoff document
- **Path**: `docs/api/feat-149-ephemeral-agents-api.md` (new, in this repo)
- **Responsibility**: single Markdown document that fully describes the
  HTTP surface introduced by FEAT-149 so the `navigator-frontend-next`
  team can run `/sdd-proposal` (and then `/sdd-spec`) on their side
  without having to re-read this repo. It is **not** an OpenAPI YAML —
  it is a self-contained handoff brief written for a frontend
  brainstorm. See §7 "Frontend Handoff Document" for required
  contents. The file is generated as the last task of the feature,
  after the routes stabilize, and is committed alongside the code on
  `dev`.
- **Depends on**: Modules 4, 5, 7 (routes must be wired and stable
  before this is finalized).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_ephemeral_status_lifecycle` | Module 1 | phase transitions creating → warming → ready, expiration math. |
| `test_create_ephemeral_persists_nothing` | Module 2 | After `create_ephemeral_user_bot`, no row exists in `users_bots`; bot is in `BotManager._bots`. |
| `test_promote_inserts_users_bots_row` | Module 2 | `promote_user_bot` writes the row with encrypted `mcp_config` / `tools_config`, removes ephemeral status. |
| `test_save_user_bot_targets_users_bots_table` | Module 2 | `save_user_bot` writes `navigator.users_bots` (not `ai_bots`); `save_agent` is untouched. |
| `test_warm_up_marks_ready` | Module 3 | Mock `agent.configure`, MCP handshake, FAISS build → status reaches `ready`. |
| `test_warm_up_records_error_on_mcp_failure` | Module 3 | MCP handshake raises → status `error`, error string surfaced. |
| `test_handler_post_returns_creating` | Module 4 | `POST /api/v1/agents/user/` returns 201 with `status="creating"` immediately. |
| `test_handler_status_polling` | Module 4 | `GET .../{id}/status` reflects async warm-up. |
| `test_handler_promote_idempotent` | Module 4 | `PUT` after first call returns 409 (already persisted). |
| `test_handler_delete_ephemeral_vs_persisted` | Module 4 | Delete behaves correctly for both states. |
| `test_faiss_dump_and_load_roundtrip_s3` | Module 6 | Dump → load returns equivalent retrievals (using a stub S3). |
| `test_tools_catalog_returns_registry` | Module 7 | `GET /api/v1/tools/catalog` returns same slugs as `TOOL_REGISTRY`. |
| `test_validate_mcp_http_ok_and_error` | Module 8 | Stub HTTP server: success and timeout/refused cases. |

### Integration Tests

| Test | Description |
|---|---|
| `test_ephemeral_to_chat_end_to_end` | POST create → poll until ready → POST `/api/v1/agents/chat/{id}` returns a successful answer using the ephemeral agent's tools. |
| `test_promote_then_chat_uses_db_row` | POST → PUT promote → restart BotManager (drop in-memory cache) → chat resolves via `get_user_bot` from DB. |
| `test_pageindex_mode_end_to_end` | Upload PDF + `rag_mode='pageindex'` → warm-up builds PageIndex → chat answers from indexed content. |
| `test_vector_mode_end_to_end` | Upload PDF + `rag_mode='vector'` → warm-up builds FAISS → chat answers; promote dumps FAISS to S3. |

### Test Data / Fixtures

```python
# tests/conftest.py additions (sketch — not implementation)
@pytest.fixture
async def bot_manager(aiohttp_app):
    return aiohttp_app["bot_manager"]

@pytest.fixture
def ephemeral_config():
    return {
        "name": "trial-bot",
        "llm": "google",
        "model_config": {"model": "gemini-2.0-flash"},
        "system_prompt_template": "You are helpful.",
        "tools_config_plain": ["weather", "search"],
        "mcp_config_plain": [],
        "use_vector": True,
        "vector_config": {"rag_mode": "vector"},
    }
```

---

## 5. Acceptance Criteria

- [ ] `POST /api/v1/agents/user/` creates an ephemeral bot in
  `BotManager._bots` with `status == "creating"` and **no row** in
  `navigator.users_bots`.
- [ ] `GET /api/v1/agents/user/{id}/status` returns warm-up phase
  transitions: `creating` → `warming` → `ready` (or `error` with a
  human-readable detail).
- [ ] An ephemeral bot is reachable through
  `POST /api/v1/agents/chat/{id}` once `ready`, with no AgentTalk
  changes.
- [ ] Default ephemeral TTL is 24h; configurable via env. Cleanup runs
  through the existing `BotManager._cleanup_expired_bots` task.
- [ ] `PUT /api/v1/agents/user/{id}` INSERTs the row via the new
  `BotManager.save_user_bot` (writes `navigator.users_bots` via
  `UserBotModel` — NOT through `save_agent`), removes the ephemeral
  entry, and returns the persisted `UserBotModel` payload. Calling
  it twice returns 409.
- [ ] `DELETE /api/v1/agents/user/{id}` works for ephemeral and
  persisted states, removing S3 documents on the persisted path
  (matching today's DELETE behavior in `UserAgentHandler`).
- [ ] `GET /api/v1/tools/catalog` returns the entries in
  `parrot_tools.TOOL_REGISTRY` as JSON, sorted by slug.
- [ ] MCP HTTP handshake is validated during warm-up; a failing
  handshake leaves the agent in `status=error` and prevents promote.
- [ ] When `vector_config['rag_mode'] == 'vector'`, FAISS is built
  during warm-up; on promote, the index is dumped to S3 and the
  location stored in `vector_config['faiss_persist_path']`.
- [ ] When `vector_config['rag_mode'] == 'pageindex'`, the
  `parrot.pageindex` builder runs during warm-up; on promote, the
  generated index file path is stored in `documents`.
- [ ] Existing `PUT /api/v1/user_agents` flow continues to work
  unchanged (regression suite green).
- [ ] All unit + integration tests above pass: `pytest tests/ -v`.
- [ ] `docs/api/feat-149-ephemeral-agents-api.md` exists, is committed
  on `dev`, and contains every section listed in §7 "Frontend Handoff
  Document". A reader who has never seen this repo can run
  `/sdd-proposal` in `navigator-frontend-next` using only that
  document as input.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# All paths under packages/ai-parrot/src/

from parrot.manager.manager import BotManager                       # parrot/manager/manager.py:81
from parrot.handlers.agents.users import UserAgentHandler           # parrot/handlers/agents/users.py:161
from parrot.handlers.models.users_bots import UserBotModel          # parrot/handlers/models/users_bots.py:26
from parrot.handlers.models._encrypted_field import seal, unseal    # used by users_bots.py
from parrot.stores.faiss_store import FAISSStore                    # parrot/stores/faiss_store.py:32
from parrot.bots.abstract import AbstractBot                        # parent of agents
from parrot.mcp.config import MCPServerConfig                       # parrot/mcp/config.py
from parrot.mcp.client import MCPClient                             # parrot/mcp/client.py
from parrot.mcp.integration import MCPToolProxy                     # parrot/mcp/integration.py:44
from parrot_tools import TOOL_REGISTRY                              # external pkg, used in parrot/tools/__init__.py:184
from parrot.conf import PARROT_SCHEMA                               # used in users_bots.py
# parrot.pageindex.builder exposes async functions, not a single class — see §6 "Existing Class Signatures"
```

### Existing Class Signatures

```python
# parrot/manager/manager.py
class BotManager:
    def __init__(
        self,
        enable_database_bots: bool = ENABLE_DATABASE_BOTS,
        enable_crews: bool = ENABLE_CREWS,
        enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
        enable_swagger_api: bool = ENABLE_SWAGGER,
    ) -> None: ...
    def add_bot(self, bot: AbstractBot) -> None: ...                 # line 569
    async def get_bot(                                               # line 575
        self, name: str, new: bool = False, session_id: str = "", **kwargs
    ) -> AbstractBot: ...
    def remove_bot(self, name: str) -> None: ...                     # line 693
    async def get_user_bot(self, request, chatbot_id) -> AbstractBot: ...  # line 737
    def get_bots(self) -> dict[str, AbstractBot]: ...                # line 800
    def add_agent(self, agent: AbstractBot) -> None: ...             # line 809  — keyed by str(agent.chatbot_id)
    async def save_agent(self, name: str, **kwargs) -> None: ...     # line 817

# parrot/handlers/models/users_bots.py
class UserBotModel(Model):
    chatbot_id: uuid.UUID                                            # PK, default_factory=uuid.uuid4
    user_id: int                                                     # PK
    name: str
    description: str
    avatar: str
    enabled: bool = True
    timezone: str = "UTC"
    role: str
    goal: str
    backstory: str
    rationale: str
    capabilities: str
    prompt_config: dict
    system_prompt_template: Optional[str]
    human_prompt_template: Optional[str]
    pre_instructions: List[str]
    llm: str = "google"
    model_config: dict
    use_vector: bool = False
    vector_config: dict                                              # carries rag_mode, faiss_persist_path
    documents: List[dict]
    context_search_limit: int = 10
    context_score_threshold: float = 0.61
    mcp_config: Optional[str]                                        # encrypted text
    tools_config: Optional[str]                                      # encrypted text
    tools_enabled: bool = True
    auto_tool_detection: bool = True
    tool_threshold: float = 0.7
    operation_mode: str = "adaptive"
    memory_type: str = "memory"
    memory_config: dict
    max_context_turns: int = 5
    use_conversation_history: bool = True
    permissions: dict
    language: str = "en"
    disclaimer: Optional[str]
    created_at: datetime
    updated_at: datetime

# parrot/handlers/agents/users.py
class UserAgentHandler(BaseView):                                    # line 161
    async def _parse_request(self) -> Tuple[Dict, List[Tuple[str, str, str]]]: ...      # line 188 — JSON or multipart
    async def _parse_multipart(self) -> Tuple[Dict, List[Tuple[str, str, str]]]: ...    # line 205
    async def _resolve_user_id(self) -> Optional[int]: ...           # line 152
    def _file_manager(self) -> FileManagerToolkit: ...               # ~line 304 — S3 if env set, local fallback
    async def _ingest_uploads(self, ...) -> List[dict]: ...          # ~line 321 — uploads to S3 + returns documents[]

# parrot/stores/faiss_store.py
class FAISSStore(AbstractStore):                                     # line 32
    def __init__(self, ...) -> None: ...                             # line 48
    async def add_documents(self, documents, **kwargs): ...          # line 367
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EphemeralUserAgentHandler.post` | `BotManager.create_ephemeral_user_bot` | direct call | `parrot/manager/manager.py` (NEW method) |
| `BotManager.create_ephemeral_user_bot` | `BotManager.add_agent` | direct call | `manager.py:809` |
| `BotManager.promote_user_bot` | `BotManager.save_user_bot` (NEW) | direct call | added in Module 2 — writes `navigator.users_bots` via `UserBotModel` |
| `EphemeralUserAgentHandler` request parsing | `UserAgentHandler._parse_request` | shared mixin (refactor) | `users.py:188` |
| Document upload | `UserAgentHandler._ingest_uploads` | shared mixin or call | `users.py:321` |
| FAISS dump on promote | `FileManagerToolkit.put_object` (s3) | new `dump_to_s3` method on FAISSStore | needs verification of FileManagerToolkit S3 API surface during impl |
| Tool catalog | `parrot_tools.TOOL_REGISTRY` | dict iteration | `parrot/tools/__init__.py:184` (import path confirmed) |
| MCP handshake validator | `MCPClient` connect + list_tools | new helper in `mcp/integration.py` | `parrot/mcp/integration.py` |
| AgentTalk reachability | `BotManager.get_user_bot` (existing) | already wired | `parrot/handlers/agent.py:932` |

### Does NOT Exist (Anti-Hallucination)

- ~~`navigator.user_bots`~~ — table is `navigator.users_bots` (with `s`).
  See `UserBotModel.Meta` and `PARROT_SCHEMA`.
- `BotManager.save_user_bot` — does NOT exist today. Module 2 adds
  it. Only `save_agent` exists currently (line 817), and it writes
  `navigator.ai_bots` via `BotModel` — do NOT overload it for the
  promote path.
- ~~`AbstractBot.warm_up`~~ — the readiness contract is `await
  agent.configure(app)`. No explicit `warm_up()`.
- ~~`PgVectorStore.create_namespace()` / dynamic per-agent namespace~~
  — does not exist. We use FAISS for ephemerals instead (per §1
  decision) precisely to avoid this gap.
- ~~`POST /api/v1/user_agents`~~ — only PUT/PATCH/GET/DELETE exist
  there. The new POST lives at `/api/v1/agents/user/`.
- ~~`stdio` MCP attach during runtime~~ — explicitly out of scope for
  ephemeral creation (see §7 Constraints).
- ~~`AgentRegistry.register` for ephemeral bots~~ — the registry is
  for module-load registered agents. Ephemerals live in
  `BotManager._bots`, not the registry.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Reuse `_encrypted_field.seal/unseal` for `mcp_config` and
  `tools_config` even in memory — keeps the in-memory model
  byte-compatible with the eventual DB row, so promote is a thin
  INSERT.
- Warm-up is a single coroutine launched with
  `asyncio.create_task(...)`. Do **not** block the POST response on
  it.
- Status updates flow through a small lock-protected dict on
  `BotManager`; readers (`GET status`) use a simple snapshot copy.
- All new HTTP routes go through the same auth / session helpers
  `UserAgentHandler` already uses (`_get_session`, `_resolve_user_id`).
- Keep refactors of `UserAgentHandler` minimal: extract a
  `_UserAgentRequestMixin` only if duplication grows past two methods.

### Known Risks / Gotchas

- **`save_agent` is for `ai_bots`, not `users_bots`.**
  `BotManager.save_agent` (line 817) writes `navigator.ai_bots` via
  `BotModel`. Module 2 adds a sibling `save_user_bot` that writes
  `navigator.users_bots` via `UserBotModel`. Do not overload
  `save_agent`; do not delete it (existing `save_agent` callers stay
  intact).
- **PageIndex API surface.** `parrot.pageindex.builder` exposes a set
  of async free functions, not a single Builder class. The warm-up
  must call them in order; document the chosen entrypoint in the
  task that wires this up (likely `detect_page_index` →
  `extract_toc_content` → `toc_transformer`).
- **FAISS persistence to S3.** `FAISSStore` is in-process by default;
  serialization format is not standardized in the repo. Choose tar of
  index file + docstore pickle, ship as a single S3 object.
  `FileManagerToolkit` S3 surface (`put_object` / `get_object` names)
  must be verified before the task implements `dump_to_s3`.
- **Concurrency on promote.** `PUT` while warm-up is still in
  `creating` should return 409 (not 200, not silent wait). Idempotency
  on a second `PUT` after success returns 409 too.
- **Per-user ownership checks.** Every route must compare
  `chatbot_id` ownership against `_resolve_user_id` to prevent one
  user reading another's ephemeral. Mirror the check
  `UserAgentHandler` already does on PATCH/DELETE.
- **Cleanup on TTL expiry.** When `_cleanup_expired_bots` removes an
  ephemeral, it must also drop the `EphemeralAgentStatus` entry and
  delete any temp S3 docs that were not promoted (orphan sweep).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `parrot_tools` | already pinned | provides `TOOL_REGISTRY` for the catalog endpoint. |
| `faiss-cpu` (or `faiss-gpu`) | as in current `pyproject.toml` | already required by `FAISSStore`. |
| (none new) | — | feature is additive on top of existing deps. |

### Frontend Handoff Document

`docs/api/feat-149-ephemeral-agents-api.md` is the input the
`navigator-frontend-next` team will feed to `/sdd-proposal` to design
the UI for ephemeral agents. It MUST contain the following sections —
this list is the contract Module 10 fulfils:

1. **Context (3-5 paragraphs)** — what an ephemeral agent is, why the
   memory-first lifecycle exists, the `creating → warming → ready`
   flow, and how it differs from the existing
   `PUT /api/v1/user_agents` flow. No backend internals — describe it
   from the user's perspective.

2. **End-to-end UI flow** — a numbered walkthrough of the screens the
   user goes through: pick LLM/model, write prompt, pick tools (from
   catalog), add MCP servers, upload documents, choose RAG mode
   (PageIndex vs Vector), click "Create" → see warm-up progress →
   chat → optionally "Save".

3. **HTTP endpoints** — for each of the routes added by FEAT-149:
   - Method + path
   - Auth requirement (session cookie, `user_id` resolved server-side)
   - Content-Type (note multipart for create-with-files)
   - **Request payload** — full JSON shape with field-by-field
     descriptions, types, required/optional, default values, and a
     concrete example.
   - **Response payload** — full JSON shape, status codes (200 / 201
     / 202 / 400 / 401 / 404 / 409 / 422 / 500), one example per
     status code where the body differs.
   - **Error envelope** — describe the standard error shape returned
     by the handlers.
   - **Idempotency notes** — e.g. promote returns 409 if already
     persisted; status polling is safe to call repeatedly.

   Routes to document (verbatim list):
   - `POST   /api/v1/agents/user/`
   - `GET    /api/v1/agents/user/{chatbot_id}/status`
   - `PUT    /api/v1/agents/user/{chatbot_id}`
   - `DELETE /api/v1/agents/user/{chatbot_id}`
   - `GET    /api/v1/tools/catalog`
   - Cross-reference (do NOT re-document) the existing
     `PUT/PATCH/GET/DELETE /api/v1/user_agents` routes that the
     frontend will also call for the persisted-bot views.

4. **Polling guidance** — recommended polling interval for the status
   endpoint (suggest 1s for the first 10s, then 3s, with a 5-minute
   ceiling), what each `phase` value means in UX terms, and which
   `progress` keys can be surfaced as a per-subsystem progress bar.

5. **File upload protocol** — multipart layout (the `config` JSON
   part + the `files[]` parts), the env-driven max upload size, the
   list of MIME types each RAG mode accepts.

6. **Tool catalog payload** — the exact JSON shape returned by
   `GET /api/v1/tools/catalog`, with notes on which fields are stable
   contracts vs. which may be enriched later (cross-link to the
   open question in §8 of this spec).

7. **MCP server config payload** — the JSON shape for an HTTP MCP
   entry inside `mcp_config_plain`, including how handshake errors
   surface in the warm-up `error` field.

8. **Saving / promoting** — what changes in the agent's "identity"
   when promoted (it stays at the same `chatbot_id`, just stops
   being ephemeral), and what the frontend should re-fetch to
   refresh its list view.

9. **Open questions for the frontend team** — explicit list of
   product decisions the frontend has to make (e.g. whether to show
   a "Discard" button alongside "Save", whether to expose the
   `permissions` field in the create form, whether the share-key
   flow from §8 of this spec lands in v1).

10. **Out-of-scope reminders** — what FEAT-149 does **not** ship
    (sharing, stdio MCP, runtime tool authoring) so the frontend
    spec does not assume them.

The document is plain Markdown, written so it can be pasted as the
`Problem Statement` and `Constraints & Requirements` body of a
`/sdd-proposal` run in `navigator-frontend-next`.

---

## Worktree Strategy

- Default isolation unit: **per-spec** (sequential tasks in one
  worktree). The modules are tightly coupled around `BotManager` and
  the new handler; parallelizing risks merge churn on `manager.py`.
- Suggested branch: `feat-149-ephemeral-agents`, branched from `dev`.
- Cross-feature dependencies: none. FEAT-148 (formbuilder list) and
  FEAT-147 (Odoo, crew result storage) are merged.

---

## 8. Open Questions

- [x] Sharing scheme — *Owner: Jesus*: how do we share an agent with
  another user? Two candidates: (a) a one-time signed share key that
  promotes the recipient to a co-owner row, (b) a per-user permission
  list on `users_bots.permissions`. Implementation deferred to a
  follow-up FEAT: a per-user permission list under `users_bots.permissions`
- [x] FAISS-on-S3 packaging — *Owner: implementer*: tar + pickle,
  parquet, or a custom format? Decide in the task that adds
  `dump_to_s3` / `load_from_s3`.: parquet for easily upload to s3.
- [x] Should `discard_ephemeral_user_bot` also delete the temp S3
  docs the user uploaded, or keep them for a grace period? Default
  proposal: delete on discard; keep on TTL expiry for 24h then sweep: delete on discard.
- [x] Tool catalog payload shape — minimal `{slug, dotted_path}` or
  enriched with description/category metadata? Depends on what
  metadata `TOOL_REGISTRY` carries today; verify in impl.: we need to enrich the TOOL_REGISTRY metadata.
- [x] Should ephemeral status surface granular `progress` per
  subsystem (tools / mcp / rag) or just the top-level phase?
  Recommend granular for better UX; cost is one extra dict in
  status responses: granular.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-06 | Jesus Lara | Initial draft (FEAT-149). |
