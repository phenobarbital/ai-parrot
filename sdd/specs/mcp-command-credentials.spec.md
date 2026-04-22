# Feature Specification: Vault-Backed Credentials for Telegram /add_mcp

**Feature ID**: FEAT-113
**Date**: 2026-04-21
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The Telegram integration exposes three commands — `/add_mcp`, `/list_mcp`,
`/remove_mcp` — that let an end user attach their own HTTP MCP server to the
agent for that user's session
(`packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`). The
current implementation stores the **entire raw JSON payload**, including the
bearer token / API key, in a per-user Redis hash at
`mcp:telegram:{user_id}:servers` (`mcp_commands.py:51`, `:86-87`,
`:164-181`).

This has three problems:

1. **Secrets live in cleartext in Redis.** Anyone with access to the Redis
   instance (ops, backup tapes, RDB snapshots, a `MONITOR` stream, an
   exported dump) can read every user's MCP bearer token verbatim. The rest
   of the platform already routes long-lived secrets through the
   Navigator/Parrot Vault (AES-GCM + keyed via `navigator_session.vault`).
   The Telegram MCP flow is the only path that bypasses it.

2. **It duplicates the Vault pattern that FEAT-063 just established.**
   `CredentialsHandler` and `vault_utils.store_vault_credential /
   retrieve_vault_credential / delete_vault_credential` are the canonical
   way to persist per-user secrets in this repo
   (`packages/ai-parrot/src/parrot/handlers/vault_utils.py:69-160`). There
   is no reason the Telegram MCP flow should reinvent its own Redis-hash
   persistence layer.

3. **It leaks the token into group chats.** The command message is only
   best-effort deleted (`mcp_commands.py:431-436`) and the JSON is
   subsequently logged on any Redis or ToolManager failure. Routing the
   secret through the Vault keeps the blast radius of a debug log or Redis
   dump inert.

### Goals

- Continue to accept `/add_mcp <json>` in Telegram DMs, with the same
  user-visible JSON schema (`name`, `url`, `auth_scheme`, `token` / `api_key`
  / `username`+`password`, `headers`, `allowed_tools`, `blocked_tools`,
  `transport`, `description`).
- Store every **secret** field (`token`, `api_key`, `username`, `password`)
  in the user's Vault (`user_credentials` DocumentDB collection, AES-GCM,
  keyed per-user) via `vault_utils.store_vault_credential`.
- Store every **non-secret** field (`name`, `url`, `transport`,
  `description`, `headers`, `allowed_tools`, `blocked_tools`,
  `auth_scheme`, `api_key_header`, `use_bearer_prefix`) in DocumentDB
  alongside other user MCP configs, mirroring the pattern
  `MCPPersistenceService` already uses
  (`parrot/handlers/mcp_persistence.py`).
- Rehydrate MCP servers into the user's cloned `ToolManager` during
  `TelegramAgentWrapper._initialize_user_context` (the same hook that
  already calls `rehydrate_user_mcp_servers`
  — `wrapper.py:963-983`) by loading the non-secret config from DocumentDB
  and the secret from the Vault, reconstructing the `MCPClientConfig`, and
  calling `tool_manager.add_mcp_server(config)`.
- Preserve the Telegram-DM-only guardrail and the best-effort command-message
  delete.

### Non-Goals (explicitly out of scope)

- Supporting anything beyond HTTP MCP transports that are already in the
  `/add_mcp` schema. mTLS, OAuth2, AWS Sig V4 credential types from
  `AuthScheme` are **not** added here — the existing module only allows
  `none`, `bearer`, `api_key`, `basic` (`mcp_commands.py:63-69`) and this
  spec preserves that allow-list.
- A generic "MCP via Vault" for MS Teams, Slack, or the HTTP handler. Those
  wrappers have their own `_initialize_user_context` equivalents and will
  be migrated in a follow-up feature.
- Deprecating `MCPPersistenceService` / `UserMCPServerConfig` for the
  *catalog* activation flow (the `add_perplexity_mcp_server` / POST
  `/mcp/activate` endpoints). Those already use the Vault via
  `vault_credential_name`. This feature only replaces the Telegram
  command's ad-hoc Redis path.
- A one-way Redis → Vault migration script for *existing* stored payloads.
  See §8 Open Questions — may be added as a dedicated task if we find
  production users with stored configs.

---

## 2. Architectural Design

### Overview

Split the `/add_mcp` payload into **two halves** at the command-handler
layer:

- **Non-secret config** → a new `UserTelegramMCPConfig` DocumentDB document,
  stored in a dedicated collection (`telegram_user_mcp_configs`) with
  compound key `(user_id, name)`. Mirrors `UserMCPServerConfig` but is
  Telegram-scoped — the `/add_mcp` flow is free-form (any HTTP MCP URL),
  whereas `UserMCPServerConfig` is registry-scoped (catalog entries).
- **Secrets** (the subset of the JSON payload containing `token`,
  `api_key`, `username`, `password`) → the Vault via
  `store_vault_credential(user_id, vault_name, secret_params)`. The
  deterministic `vault_name` is `"tg_mcp_{name}"` so that the rehydration
  path can recover it from the non-secret doc's
  `vault_credential_name` field without any naming collision with
  catalog-based MCP credentials (which use `mcp_{server}_{agent_id}`).

The `rehydrate_user_mcp_servers` helper is rewritten to read from
DocumentDB + Vault instead of Redis. The command handlers
(`add_mcp_handler`, `list_mcp_handler`, `remove_mcp_handler`) are updated
likewise. The Redis key `mcp:telegram:{user_id}:servers` and the
`redis_client` parameter threaded through `register_mcp_commands` are
removed.

### Component Diagram
```
/add_mcp <json>
   │
   ▼
add_mcp_handler
   ├── _reject_non_private ──→ (reply + return if not DM)
   ├── parse JSON
   ├── _build_config ──→ MCPClientConfig (live object, still unused for persistence)
   │
   ├── split_secret_and_public(payload)
   │      ├── secret_params = {token | api_key | username+password}  (may be empty)
   │      └── public_params = rest (name, url, auth_scheme, headers, …)
   │
   ├── tool_manager.add_mcp_server(config)              ← session-live tools
   │
   ├── TelegramMCPPersistenceService.save(user_id, name, public_params, vault_name)
   │      └── DocumentDb upsert  collection=telegram_user_mcp_configs
   │
   ├── store_vault_credential(user_id, vault_name, secret_params)  (if secret_params)
   │
   ├── best-effort delete command message (keep existing _maybe_delete)
   └── reply "Connected <name> with N tool(s)."

_initialize_user_context (wrapper.py:963)
   │
   └── rehydrate_user_mcp_servers(tool_manager, user_id)
           ├── TelegramMCPPersistenceService.list(user_id) → public_params[]
           ├── for each: retrieve_vault_credential(user_id, vault_name) → secret_params
           ├── merge(public_params, secret_params) → _build_config() → MCPClientConfig
           └── tool_manager.add_mcp_server(config)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.integrations.telegram.mcp_commands` | rewrites | Redis-path replaced by Vault-path. Public API (`register_mcp_commands`, `rehydrate_user_mcp_servers`) stays; `redis_client` parameter is removed. |
| `parrot.integrations.telegram.wrapper.TelegramAgentWrapper._initialize_user_context` | trivial | Stop passing `redis_client` to the rehydrate call. |
| `parrot.handlers.vault_utils` | uses | `store_vault_credential`, `retrieve_vault_credential`, `delete_vault_credential` (verbatim — no new helpers). |
| `parrot.interfaces.documentdb.DocumentDb` | uses | `write`, `update_one`, `read`, `read_one`, `delete` — same pattern as `MCPPersistenceService`. |
| `parrot.mcp.client.MCPClientConfig` / `AuthScheme` / `AuthCredential` | reuses | Existing `_build_config` keeps converting JSON → live `MCPClientConfig`. No change to the dataclass. |
| `parrot.tools.manager.ToolManager.add_mcp_server` / `remove_mcp_server` | uses | Unchanged signatures; called identically. |

### Data Models

New Pydantic document for the non-secret Telegram-scoped config:

```python
# packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py (NEW)
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TelegramMCPPublicParams(BaseModel):
    """Non-secret subset of an /add_mcp payload safe to persist in DocumentDB."""
    name: str = Field(..., min_length=1, max_length=128)
    url: str
    transport: str = "http"
    description: Optional[str] = None
    auth_scheme: str = "none"  # "none" | "bearer" | "api_key" | "basic"
    api_key_header: Optional[str] = None       # api_key scheme only
    use_bearer_prefix: Optional[bool] = None   # api_key scheme only
    headers: Dict[str, str] = Field(default_factory=dict)
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None


class UserTelegramMCPConfig(BaseModel):
    """Persisted non-secret config for a /add_mcp HTTP server."""
    user_id: str                    # tg_<telegram_id> or nav_user_id (§6)
    name: str                       # server name (the command's JSON `name`)
    params: TelegramMCPPublicParams
    vault_credential_name: Optional[str] = None  # "tg_mcp_{name}" when secrets present
    active: bool = True
    created_at: str                 # ISO-8601 UTC
    updated_at: str
```

Vault document (existing schema; no changes):
- Collection: `user_credentials`
- Key: `(user_id, name=vault_credential_name)`
- Body: `{user_id, name, credential: <AES-GCM base64>, created_at, updated_at}`
- Plaintext payload before encryption:
  `{"token": "..."} | {"api_key": "..."} | {"username": "...", "password": "..."}`

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py (NEW)
class TelegramMCPPersistenceService:
    """CRUD for the telegram_user_mcp_configs DocumentDB collection."""

    COLLECTION: str = "telegram_user_mcp_configs"

    async def save(
        self,
        user_id: str,
        name: str,
        params: TelegramMCPPublicParams,
        vault_credential_name: Optional[str],
    ) -> None: ...

    async def list(self, user_id: str) -> List[UserTelegramMCPConfig]: ...

    async def read_one(
        self, user_id: str, name: str
    ) -> Optional[UserTelegramMCPConfig]: ...

    async def remove(self, user_id: str, name: str) -> bool: ...
```

`mcp_commands.py` — public surface **preserved** except for the removal
of the `redis_client` parameter:

```python
def register_mcp_commands(
    router: Router,
    tool_manager_resolver: ToolManagerResolver,
) -> None: ...

async def rehydrate_user_mcp_servers(
    tool_manager: "ToolManager",
    user_id: str,
) -> int: ...
```

---

## 3. Module Breakdown

### Module 1: Telegram MCP Persistence Service
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/mcp_persistence.py`
- **Responsibility**: DocumentDB CRUD on `telegram_user_mcp_configs`.
  Defines `TelegramMCPPublicParams` and `UserTelegramMCPConfig`.
  Upsert on save, soft-delete on remove (`active=False`) consistent
  with `MCPPersistenceService`.
- **Depends on**: `parrot.interfaces.documentdb.DocumentDb`, `pydantic`.

### Module 2: Secret / public splitter
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`
  (new helper inside the existing module — not a new file).
- **Responsibility**: `_split_secret_and_public(payload: dict)
  -> tuple[TelegramMCPPublicParams, dict[str, Any]]`. Extracts secret fields
  according to `auth_scheme` and returns `(public_params, secret_params)`.
  Raises `ValueError` on the same validation conditions as the current
  `_build_config` (so handlers keep echoing `_USAGE`).
- **Depends on**: Module 1.

### Module 3: Rewritten command handlers + rehydration
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`.
- **Responsibility**:
  - Rewrite `add_mcp_handler` to call `tool_manager.add_mcp_server`,
    then `TelegramMCPPersistenceService.save`, then
    `store_vault_credential` (only if `secret_params`).
  - Rewrite `list_mcp_handler` to list from DocumentDB (via
    `TelegramMCPPersistenceService.list`). Never touch the Vault — the
    listing still must not echo secrets.
  - Rewrite `remove_mcp_handler` to call
    `tool_manager.remove_mcp_server`, then
    `TelegramMCPPersistenceService.remove`, then
    `delete_vault_credential` (best-effort; `KeyError` is not an error).
  - Rewrite `rehydrate_user_mcp_servers` to load public params from
    DocumentDB, pull the matching secrets from the Vault, rebuild the
    `MCPClientConfig`, and register it.
  - Remove `_REDIS_KEY_TEMPLATE`, `_redis_key`, `_persist_config`,
    `_load_all_configs`, `_forget_config`, and the `redis_client`
    parameter from `register_mcp_commands`.
- **Depends on**: Module 1, Module 2,
  `parrot.handlers.vault_utils.{store,retrieve,delete}_vault_credential`,
  `parrot.tools.manager.ToolManager`.

### Module 4: Wrapper rehydration call site
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py`
  (lines 963-983 — existing rehydration block).
- **Responsibility**: Drop the `redis_client` kwarg passed to
  `rehydrate_user_mcp_servers`. Keep the `try/except` that logs and
  continues on failure.
- **Depends on**: Module 3.

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py`
  (file will be new; verify path against existing Telegram tests before
  committing TASK-001).
- **Responsibility**: Unit tests for split_secret_and_public, handler
  happy paths, rehydration cycle, absence of secrets from /list_mcp
  output, and absence of the Redis key on add/remove.
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_split_secret_bearer` | Module 2 | `auth_scheme=bearer` → `secret_params={"token": "sk-..."}`, `public_params` excludes `token`. |
| `test_split_secret_api_key` | Module 2 | `auth_scheme=api_key` → secrets contain `api_key`; `api_key_header` + `use_bearer_prefix` remain in public. |
| `test_split_secret_basic` | Module 2 | `auth_scheme=basic` → secrets `{username, password}`; public excludes both. |
| `test_split_secret_none` | Module 2 | `auth_scheme=none` → `secret_params=={}`; `vault_credential_name` is `None` on the saved doc. |
| `test_split_missing_bearer_token` | Module 2 | Raises `ValueError("bearer auth requires a 'token' field.")`. |
| `test_persistence_save_upsert` | Module 1 | First call writes, second call updates the same `(user_id, name)` doc. |
| `test_persistence_list_excludes_inactive` | Module 1 | `active=False` docs are not returned by `list`. |
| `test_persistence_remove_soft_delete` | Module 1 | `remove` sets `active=False`; subsequent `read_one` returns `None`. |
| `test_add_mcp_happy_path` | Module 3 | `add_mcp_handler` invokes ToolManager, persistence, and Vault in that order (verified via mocks). |
| `test_add_mcp_rolls_back_on_vault_failure` | Module 3 | Vault raises → DocumentDB doc is removed and `tool_manager.remove_mcp_server` is called so nothing is half-persisted. |
| `test_list_mcp_hides_secrets` | Module 3 | `/list_mcp` output contains only `name — url (scheme)` lines; no occurrence of any `token`/`api_key`/`password` from the input. |
| `test_remove_mcp_clears_vault_and_doc` | Module 3 | DELETE path removes from ToolManager, DocumentDB, and Vault. Missing Vault entry does **not** raise. |
| `test_rehydrate_reassembles_config` | Module 3 | Saved public + Vault secret rebuild a `MCPClientConfig` equal to the original `_build_config` input. |
| `test_rehydrate_skips_missing_secret` | Module 3 | If Vault entry is missing (`KeyError`), the one server is skipped, rehydration of others continues, a warning is logged. |
| `test_redis_key_is_never_written` | Module 3 | After `/add_mcp`, the former Redis key `mcp:telegram:{user_id}:servers` does not exist (regression guard). |
| `test_non_private_chat_rejected` | Module 3 | Preserves existing guardrail (`_reject_non_private`). |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_add_list_remove` | Against an in-memory DocumentDB + real Vault crypto: `/add_mcp` a bearer-token server, `/list_mcp` shows it with no secrets, `/remove_mcp` removes it from both stores, second `/list_mcp` is empty. |
| `test_wrapper_rehydration_on_login` | After `_initialize_user_context` runs, the user's cloned ToolManager has the same tools the `/add_mcp` command registered in the previous session. |

### Test Data / Fixtures

```python
import pytest

@pytest.fixture
def bearer_payload() -> dict:
    return {
        "name": "fireflies",
        "url": "https://api.fireflies.ai/mcp",
        "auth_scheme": "bearer",
        "token": "sk-test-0123456789",
    }

@pytest.fixture
def api_key_payload() -> dict:
    return {
        "name": "brave",
        "url": "https://api.brave.com/mcp",
        "auth_scheme": "api_key",
        "api_key": "bsa-...-redacted",
        "api_key_header": "X-Brave-Key",
    }

@pytest.fixture
def basic_payload() -> dict:
    return {
        "name": "internal",
        "url": "https://internal.example/mcp",
        "auth_scheme": "basic",
        "username": "svc",
        "password": "p@ss!word",
    }
```

---

## 5. Acceptance Criteria

- [ ] `/add_mcp` with `auth_scheme=bearer|api_key|basic|none` works
      end-to-end in a Telegram DM, producing the same reply text as today
      (`"Connected '<name>' with N tool(s)."`).
- [ ] After `/add_mcp`, the Redis key `mcp:telegram:{user_id}:servers`
      **does not exist** — verified by an integration test that inspects
      `redis_client.exists(...)` after the command returns.
- [ ] Secrets (`token`, `api_key`, `username`, `password`) are present
      **only** in the `user_credentials` Vault collection (encrypted), and
      are never written to `telegram_user_mcp_configs`.
- [ ] `/list_mcp` never emits any value that was part of the secret
      subset of the original payload — enforced by a test that fails if
      any secret fixture string is a substring of the reply.
- [ ] `/remove_mcp <name>` removes the entry from: the live `ToolManager`
      (if present), `telegram_user_mcp_configs` (soft-delete), and
      `user_credentials` (hard delete via
      `delete_vault_credential`).
- [ ] A process restart followed by
      `TelegramAgentWrapper._initialize_user_context` re-registers all
      active `/add_mcp` servers for the user without the user re-issuing
      the command.
- [ ] `rehydrate_user_mcp_servers` no longer accepts a `redis_client`
      parameter; call site in `wrapper.py` updated accordingly.
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py -v`).
- [ ] No new breaking changes to the `/add_mcp` user-facing JSON schema.
- [ ] Vault master keys unavailable → `/add_mcp` returns a single-sentence
      error and does **not** leave a half-persisted state (no doc, no
      live tools, no Vault entry).

---

## 6. Codebase Contract

### Verified Imports

```python
# Telegram command module (target of the rewrite)
# file: packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py
from ...mcp.client import AuthCredential, AuthScheme, MCPClientConfig  # line 41
from ...tools.manager import ToolManager                               # line 44 (TYPE_CHECKING)

# Vault helpers (use verbatim — already exported and used by CredentialsHandler)
# file: packages/ai-parrot/src/parrot/handlers/vault_utils.py
from parrot.handlers.vault_utils import (
    store_vault_credential,     # line 69
    retrieve_vault_credential,  # line 116
    delete_vault_credential,    # line 149
)
# file: packages/ai-parrot/src/parrot/handlers/credentials_utils.py
from parrot.handlers.credentials_utils import (
    encrypt_credential,   # line 19
    decrypt_credential,   # line 52
)

# DocumentDB context manager — used by MCPPersistenceService and vault_utils
# file: packages/ai-parrot/src/parrot/interfaces/documentdb.py
from parrot.interfaces.documentdb import DocumentDb

# Existing MCP persistence service that this spec DOES NOT replace
# file: packages/ai-parrot/src/parrot/handlers/mcp_persistence.py
from parrot.handlers.mcp_persistence import MCPPersistenceService  # line 36
from parrot.mcp.registry import UserMCPServerConfig                # line 27 (reference only; not used by the new Telegram flow)
```

### Existing Class Signatures

```python
# parrot/tools/manager.py:203
class ToolManager(MCPToolManagerMixin):
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,                 # line 215
        debug: bool = False,                                     # line 216
        include_search_tool: bool = False,                       # line 217
        resolver: Optional["AbstractPermissionResolver"] = None, # line 218
    ): ...
    # line 1385
    def clone(self, *, include_search_tool: bool = False) -> "ToolManager": ...

# parrot/tools/mcp_mixin.py:57
class MCPToolManagerMixin:
    async def add_mcp_server(
        self,
        config: 'MCPServerConfig',
        context: Optional['ReadonlyContext'] = None,
    ) -> List[str]: ...                                          # line 61, returns list of registered tool names
    # line 354
    async def remove_mcp_server(self, server_name: str) -> bool: ...

# parrot/mcp/client.py:14
class AuthScheme(str, Enum):
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"
    OAUTH2 = "oauth2"        # not accepted by /add_mcp today
    MTLS = "mtls"            # not accepted by /add_mcp today
    AWS_SIG_V4 = "aws_sig_v4" # not accepted by /add_mcp today

# parrot/mcp/client.py:25
class AuthCredential(BaseModel):
    scheme: AuthScheme
    token: Optional[str] = None
    api_key: Optional[str] = None
    api_key_header: Optional[str] = "X-API-Key"
    use_bearer_prefix: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    # mTLS / AWS Sig V4 fields exist but are unused by this feature.

# parrot/mcp/client.py:130 (dataclass)
@dataclass
class MCPClientConfig:
    name: str
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    description: Optional[str] = None
    auth_credential: Optional[AuthCredential] = None
    auth_type: Optional[AuthScheme] = None
    auth_config: Dict[str, Any] = field(default_factory=dict)
    token_supplier: Optional[Callable[[], Optional[str]]] = None
    transport: str = "auto"
    base_path: Optional[str] = None
    events_path: Optional[str] = None
    socket_path: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    header_provider: Optional[Callable[['ReadonlyContext'], Dict[str, str]]] = None
    tool_filter: Optional[Union[List[str], Callable]] = None
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None
    require_confirmation: Union[bool, Callable[[str, Dict[str, Any]], bool]] = False
    timeout: float = 30.0
    retry_count: int = 3
    startup_delay: float = 0.5
    kill_timeout: float = 5.0

# parrot/integrations/telegram/auth.py:43 (dataclass)
@dataclass
class TelegramUserSession:
    telegram_id: int                                         # line 47
    nav_user_id: Optional[str] = None                        # line 52
    authenticated: bool = False                              # line 56
    tool_manager: Optional["ToolManager"] = field(...)       # line 80
    user_agent: Optional["AbstractBot"] = field(...)         # line 83
    post_login_ran: bool = field(default=False, ...)         # line 86
    # property at line 88
    @property
    def user_id(self) -> str:
        # Returns nav_user_id when authenticated, else f"tg:{telegram_id}"
        ...

# parrot/integrations/telegram/mcp_commands.py (current, being rewritten)
_TELEGRAM_CHANNEL = "telegram"                               # line 50
_REDIS_KEY_TEMPLATE = "mcp:{channel}:{user_id}:servers"      # line 51 — TO BE REMOVED
_ALLOWED_SCHEMES = {"none", "bearer", "api_key", "apikey", "basic"}  # line 63-69
def _build_config(payload: Dict[str, Any]) -> MCPClientConfig: ...   # line 90 — kept
async def _persist_config(redis_client, user_id, name, payload):     # line 164 — REMOVE
async def _load_all_configs(redis_client, user_id):                  # line 184 — REMOVE
async def _forget_config(redis_client, user_id, name):               # line 204 — REMOVE
async def rehydrate_user_mcp_servers(redis_client, tool_manager, user_id) -> int:  # line 213 — REWRITE (drop redis_client)
async def add_mcp_handler(message, tool_manager_resolver, redis_client): ...       # line 266 — REWRITE (drop redis_client)
async def list_mcp_handler(message, redis_client): ...                              # line 354 — REWRITE (drop redis_client)
async def remove_mcp_handler(message, tool_manager_resolver, redis_client): ...    # line 387 — REWRITE (drop redis_client)
def register_mcp_commands(router, tool_manager_resolver, redis_client): ...        # line 439 — REWRITE (drop redis_client)

# parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    # line 418
    def _get_user_tool_manager(self, session: TelegramUserSession) -> Optional[Any]: ...
    # line 895
    async def _initialize_user_context(
        self,
        session: TelegramUserSession,
        message: Optional[Message] = None,
    ) -> None: ...
    # Rehydration block: lines 963-983 (calls rehydrate_user_mcp_servers).
    # Redis client fetched via self.app.get("redis") at line 965 — will
    # become unused for MCP and can stay for jira_post_auth etc.

# parrot/handlers/mcp_persistence.py
COLLECTION: str = "user_mcp_configs"                        # line 31
class MCPPersistenceService:                                # line 36
    async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None: ...  # line 49
    async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]: ...  # line 94
    async def remove_user_mcp_config(self, user_id: str, agent_id: str, server_name: str) -> bool: ...    # line 136

# parrot/handlers/vault_utils.py
VAULT_CRED_COLLECTION: str = "user_credentials"             # line 36
def load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]: ...  # line 44
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None: ...  # line 69
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]: ...  # line 116 (raises KeyError if not found)
async def delete_vault_credential(user_id: str, vault_name: str) -> None: ...  # line 149
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TelegramMCPPersistenceService.save` | `DocumentDb.update_one` | upsert | pattern matches `parrot/handlers/mcp_persistence.py:84-85` |
| `add_mcp_handler` (rewritten) | `ToolManager.add_mcp_server` | method call | signature at `parrot/tools/mcp_mixin.py:57-61` |
| `add_mcp_handler` (rewritten) | `store_vault_credential` | function call | `parrot/handlers/vault_utils.py:69` |
| `remove_mcp_handler` (rewritten) | `ToolManager.remove_mcp_server` + `delete_vault_credential` | method + function | `parrot/tools/mcp_mixin.py:354`; `parrot/handlers/vault_utils.py:149` |
| `rehydrate_user_mcp_servers` (rewritten) | `TelegramMCPPersistenceService.list` + `retrieve_vault_credential` + `_build_config` + `ToolManager.add_mcp_server` | sequential calls | verified above |
| `TelegramAgentWrapper._initialize_user_context` | `rehydrate_user_mcp_servers(tool_manager, user_id)` | call | `parrot/integrations/telegram/wrapper.py:963-983` (drop `redis_client` arg) |

### Does NOT Exist (Anti-Hallucination)

The following are **confirmed not to exist** in this repo. Do not
reference them.

- ~~`parrot.interfaces.VaultInterface`~~ — no such class; Vault access is
  the `vault_utils` function surface plus `navigator_session.vault`.
- ~~`parrot.handlers.credentials.CredentialsHandler.store_mcp_secret`~~
  — `CredentialsHandler` exposes HTTP CRUD only; use `vault_utils`.
- ~~`parrot.integrations.telegram.mcp_commands.VaultClient`~~ — no such
  object; call `store_vault_credential` directly.
- ~~`UserMCPServerConfig` used for the Telegram /add_mcp flow~~ — that
  model is registry-scoped (`server_name`, `agent_id`). Telegram
  `/add_mcp` servers are free-form HTTP URLs and belong in a separate
  `UserTelegramMCPConfig` collection. Reusing
  `UserMCPServerConfig.agent_id` would require either a sentinel
  "agent_id" or a schema change — both are worse than a dedicated
  collection.
- ~~`SessionData` class inside `parrot/`~~ — session data is the
  `navigator_session` dict attached to the aiohttp request; not used by
  this feature since the Telegram flow has no request-scoped handler.
- ~~`redis_client.hmget("mcp:...")` post-migration~~ — the Redis hash at
  `mcp:telegram:{user_id}:servers` is retired. The `redis_client`
  parameter is dropped from every public symbol in `mcp_commands.py`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout. All persistence / Vault calls are `await`ed.
- Pydantic v2 (`BaseModel` + `Field`) for new data models.
- Logging via module-level `logger = logging.getLogger(__name__)` (module
  already has this at line 47). Never include the raw payload in a log
  message — log only `name`, the command verb, and the `user_id`.
- Mirror `MCPPersistenceService` conventions:
  - soft-delete on remove (`active: False` + `updated_at`);
  - upsert on save;
  - strip `_id` before parsing DocumentDB docs into Pydantic models.
- Preserve the DM-only guardrail (`_reject_non_private`) and the
  best-effort command-message delete (`_maybe_delete`).
- User identifier: use `str(message.from_user.id)` with the existing
  `tg:{id}` prefix convention, i.e. `f"tg:{message.from_user.id}"`, for
  both `TelegramMCPPersistenceService` and `store_vault_credential`.
  This matches `TelegramUserSession.user_id`'s unauthenticated fallback
  (`auth.py:93`) and keeps Vault documents namespaced so a future move
  to a Navigator-authenticated `nav_user_id` can migrate both tables
  atomically. **Do not** use the bare integer `telegram_id` — it would
  collide with authenticated-user IDs in the same DocumentDB collection.

### Known Risks / Gotchas

- **Vault master key unavailable.** `load_vault_keys` raises
  `RuntimeError` when `navigator-session` is not installed or
  `MASTER_KEYS` env var is missing (`vault_utils.py:53-57`). In that
  case, `/add_mcp` must reply with a single-sentence error and must not
  leave the server registered on the live ToolManager. Implementation
  order: **persist config → store secret → register with ToolManager**.
  If the secret store fails, we roll back the DocumentDB doc. If
  ToolManager registration fails, we roll back the Vault entry and the
  doc.
- **Rehydration partial failure.** Preserve the existing per-server
  `try/except` in `rehydrate_user_mcp_servers` — one broken secret must
  not prevent the others from loading.
- **Rehydration hook path.** `_initialize_user_context` already wraps
  the rehydration call in its own `try/except` (`wrapper.py:979-983`).
  Do not remove that outer guard even after the inner helper is
  refactored.
- **Secret lifetime in memory.** After `tool_manager.add_mcp_server`
  succeeds, the live `MCPClientConfig` still carries the plaintext
  token. That matches today's behaviour — nothing to fix here, but do
  not add any `repr`/log that would dump the config.
- **Migration of existing Redis data.** Users who already ran
  `/add_mcp` on the current `main` have their config in Redis.
  Acceptable to drop it (they re-issue the command once) per §8; if we
  decide a migration is required, add TASK-NNN at
  decomposition time.
- **Backwards-compat callers of `register_mcp_commands` /
  `rehydrate_user_mcp_servers`.** `grep` shows the only caller is
  `wrapper.py:969`; removing `redis_client` from the public signatures
  is safe within this repo. The task implementation must `grep` again
  before committing to confirm no new call sites appeared.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-session` | existing | Vault AES-GCM crypto + master-key config. |
| `pydantic` | existing | `TelegramMCPPublicParams`, `UserTelegramMCPConfig`. |
| `aiogram` | existing | Telegram command routing (unchanged). |
| `parrot.interfaces.documentdb.DocumentDb` | existing | Upsert / read / delete. |

No new dependencies are introduced.

---

## 8. Open Questions

- [x] Do we need a one-shot migration from the existing
  `mcp:telegram:{user_id}:servers` Redis hash into the Vault +
  DocumentDB pair, or is it acceptable to ask users to re-issue
  `/add_mcp` once after the change? — *Owner: Jesus*: there are no existing records, this is a new feature.
- [x] Should `user_id` be changed from `tg:{telegram_id}` to
  `session.user_id` (i.e. prefer `nav_user_id` when available) so that
  post-login a Telegram user's MCP servers follow their Navigator
  identity? Argument for: single Vault namespace. Argument against:
  servers added pre-login would be "lost" after authentication. —
  *Owner: Jesus*: Yes
- [x] Should `/list_mcp` show a `(secret stored ✓)` / `(no secret)` hint
  per row, for UX clarity? Requires a DocumentDB read only, no Vault
  read. — *Owner: Jesus*: we don't have DocumentDB access for this feature.

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Tight coupling — Module 1 (persistence service) is a
  hard dependency for Modules 2-3; Module 4 is a two-line call-site
  change in `wrapper.py` that must merge atomically with the Module 3
  rewrite so `rehydrate_user_mcp_servers` and its caller stay in sync.
  No meaningful parallelism; a split worktree would just add
  coordination overhead.
- **Cross-feature dependencies**: FEAT-063 (user-based-credentials)
  must already be merged — this spec relies on
  `parrot.handlers.vault_utils` which was introduced there. `git log --
  packages/ai-parrot/src/parrot/handlers/vault_utils.py` confirms it is
  present on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-21 | Jesus Lara | Initial draft. |
