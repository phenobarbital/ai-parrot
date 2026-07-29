---
type: Wiki Overview
title: 'Feature Specification: Jira OAuth 2.0 (3LO) Per-User Authentication'
id: doc:sdd-specs-feat-107-jira-oauth2-3lo-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When multiple users interact with the same agent (via Telegram or AgenTalk),
  they all share the same Jira identity. The `reporter` defaults to the bot account,
  `currentUser()` in JQL resolves to the bot, and Jira's activity feed attributes
  everything to a single service account.
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.auth.resolver
  rel: mentions
- concept: mod:parrot.integrations.telegram
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.decorators
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
- concept: mod:parrot_tools.toolkit
  rel: mentions
---

# Feature Specification: Jira OAuth 2.0 (3LO) Per-User Authentication

**Feature ID**: FEAT-107
**Date**: 2026-04-17
**Author**: Jesus
**Status**: approved
**Target version**: 0.9.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`JiraToolkit` authenticates using a single system account (basic_auth with API token or PAT). All Jira operations — create, assign, transition, comment — appear as the system account user. This breaks audit trails, collapses permission boundaries, and makes it impossible to know who actually performed an action through the agent.

When multiple users interact with the same agent (via Telegram or AgenTalk), they all share the same Jira identity. The `reporter` defaults to the bot account, `currentUser()` in JQL resolves to the bot, and Jira's activity feed attributes everything to a single service account.

### Goals

- Users can authorize their own Jira account via OAuth 2.0 (3LO) so all operations execute under their identity.
- The authorization flow works across channels: AgenTalk (web chat) and Telegram (autonomous bot).
- Tokens are stored per-user in Redis and auto-refreshed transparently (Atlassian uses rotating refresh tokens).
- When a user hasn't authorized, the toolkit signals this cleanly via a protocol that the LLM can present as an actionable link.
- Backward compatibility: system-account (basic_auth/token_auth) mode continues working unchanged as fallback.
- The solution introduces framework-level primitives (`_pre_execute`/`_post_execute` hooks, `AuthorizationRequired` exception, `CredentialResolver` abstraction, `channel` field on `PermissionContext`) reusable by other toolkits (O365, GitHub, Workday).

### Non-Goals (explicitly out of scope)

- Telegram Mini App (WebView) integration — Deep Link is the MVP; Mini App is a future upgrade.
- Multi-site Jira selection UI — auto-select first accessible site for now.
- OAuth for Jira Data Center / Server (only Jira Cloud's 3LO).
- Abstracting a generic `OAuthProvider` base across multiple services (Jira-specific first, refactor later).
- Encrypting tokens at rest in Redis beyond Redis ACLs + TLS.

---

## 2. Architectural Design

### Overview

The solution introduces 5 new components and modifies 4 existing ones. The core insight is that the Toolkit never holds credentials — it reads them from Redis on each operation via a `CredentialResolver`, identified by the `user_id` flowing through the existing `permission_context` mechanism.

Two processes are inherently decoupled: the OAuth callback (HTTP request from Atlassian redirect) and the agent session (WebSocket or Telegram). Redis serves as the rendezvous point — the callback writes tokens, the toolkit reads them.

### Component Diagram

```
                    ┌─────────────────────────────────────────┐
                    │           ATLASSIAN CLOUD                │
                    │  auth.atlassian.com  (consent, tokens)  │
                    │  api.atlassian.com   (Jira REST API)    │
                    └──────────┬──────────────────────────────┘
                               │
 ┌─────────────────────────────┼──────────────────────────────────┐
 │            AI-PARROT BACKEND│                                   │
 │                             │                                   │
 │  ┌──────────────────────────▼──────────────────┐               │
 │  │         JiraOAuthManager                     │               │
 │  │  create_authorization_url()                  │               │
 │  │  handle_callback(code, state)                │               │
 │  │  get_valid_token(channel, user_id)           │               │
 │  │  _refresh_tokens() [rotating]                │               │
 │  └────────────────────┬────────────────────────┘               │
 │                       │                                         │
 │  ┌────────────────────▼────────────────────────┐               │
 │  │  CredentialResolver ─────▶ Redis             │               │
 │  │  resolve(channel, user_id) → TokenSet|None   │               │
 │  │                    jira:oauth:tg:555 = {...}  │               │
 │  │                    jira:nonce:abc = {...}     │               │
 │  └────────────────────┬────────────────────────┘               │
 │                       │                                         │
 │  ┌────────────────────▼────────────────────────┐               │
 │  │  JiraToolkit (modified)                      │               │
 │  │  _pre_execute() → resolve creds → JIRA()    │               │
 │  │  ↕ AuthorizationRequired if no creds         │               │
 │  └──────────────────────────────────────────────┘               │
 │                                                                  │
 │  ┌──────────────────────────────────────────────┐               │
 │  │  /api/auth/jira/callback (aiohttp route)     │               │
 │  │  Verifies state, exchanges code, stores      │               │
 │  │  tokens, notifies channel                    │               │
 │  └──────────────────────────────────────────────┘               │
 └─────────────────────────────────────────────────────────────────┘
              │                           │
   ┌──────────▼──────────┐    ┌──────────▼──────────┐
   │  Telegram Bot        │    │  AgenTalk WebSocket  │
   │  /connect_jira       │    │  JiraConnectTool     │
   │  /disconnect_jira    │    │  hot-swap post-auth  │
   │  deep link flow      │    │  inline auth link    │
   └──────────────────────┘    └──────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Add `_pre_execute()` and `_post_execute()` lifecycle hooks |
| `ToolkitTool._execute()` | modifies | Call toolkit's `_pre_execute()` before bound method |
| `ToolManager.execute_tool()` | modifies | Catch `AuthorizationRequired`, convert to ToolResult |
| `PermissionContext` | extends | Add `channel` field |
| `JiraToolkit` | modifies | Add `oauth2_3lo` auth_type, `CredentialResolver`, JIRA client caching |
| `AutonomousOrchestrator.setup_routes()` | uses | Calls `manager.setup(app)` (idempotent) when manager is present |

### Data Models

```python
class JiraTokenSet(BaseModel):
    """Per-user Jira OAuth2 token set, stored in Redis."""
    access_token: str
    refresh_token: str
    expires_at: float                   # epoch timestamp
    cloud_id: str                       # Jira site UUID
    site_url: str                       # https://mysite.atlassian.net
    account_id: str                     # Atlassian accountId
    display_name: str                   # "Jesus Garcia"
    email: Optional[str] = None
    scopes: list[str] = []
    granted_at: float = 0
    last_refreshed_at: float = 0
    available_sites: list[dict] = []    # all sites from accessible-resources

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - 60)

    @property
    def api_base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}"


class AuthorizationRequired(Exception):
    """Raised when a toolkit needs user authorization before operating.
    ToolManager catches this and returns ToolResult(status='authorization_required').
    """
    tool_name: str
    message: str
    auth_url: Optional[str] = None
    provider: str = "jira"
    scopes: list[str] = []
```

### New Public Interfaces

```python
# --- CredentialResolver abstraction ---
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        """Return credentials or None if user hasn't authorized."""
        ...
    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Generate authorization URL for the user."""
        ...

class OAuthCredentialResolver(CredentialResolver):
    def __init__(self, oauth_manager: JiraOAuthManager): ...

class StaticCredentialResolver(CredentialResolver):
    def __init__(self, server_url: str, username: str, password: str): ...

# --- JiraOAuthManager ---
class JiraOAuthManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        redis_url: Optional[str] = None,     # (TASK-775) build owned client on startup
        redis_client: Any = None,            # or pass a pre-built client
        scopes: Optional[list[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
    ) -> None: ...                           # raises ValueError if both redis_* missing
    def setup(self, app: web.Application) -> None: ...   # idempotent; route + signals
    async def _on_startup(self, app: web.Application) -> None: ...
    async def _on_cleanup(self, app: web.Application) -> None: ...
    async def create_authorization_url(self, channel: str, user_id: str, extra_state: dict = None) -> tuple[str, str]: ...
    async def handle_callback(self, code: str, state: str) -> JiraTokenSet: ...
    async def get_valid_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]: ...
    async def revoke(self, channel: str, user_id: str) -> None: ...
    async def is_connected(self, channel: str, user_id: str) -> bool: ...

# --- AbstractToolkit lifecycle hooks ---
class AbstractToolkit:
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        """Hook called before every tool execution. Override in subclasses."""
        pass
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any:
        """Hook called after every tool execution. Override for observability."""
        return result
```

---

## 3. Module Breakdown

### Module 1: AbstractToolkit Lifecycle Hooks
- **Path**: `packages/ai-parrot/src/parrot/tools/toolkit.py`
- **Responsibility**: Add `_pre_execute(tool_name, **kwargs)` and `_post_execute(tool_name, result, **kwargs)` to `AbstractToolkit`. Modify `ToolkitTool._execute()` to call these hooks on the parent toolkit before/after the bound method.
- **Depends on**: nothing new

### Module 2: AuthorizationRequired Exception + ToolManager Handling
- **Path**: `packages/ai-parrot/src/parrot/auth/exceptions.py`
- **Path**: `packages/ai-parrot/src/parrot/tools/manager.py` (modify)
- **Responsibility**: Define `AuthorizationRequired` exception. Modify `ToolManager.execute_tool()` to catch it and convert to `ToolResult(status='authorization_required', metadata={auth_url, provider})`.
- **Depends on**: Module 1 (hooks can raise it)

### Module 3: PermissionContext — Add `channel` Field
- **Path**: `packages/ai-parrot/src/parrot/auth/permission.py` (modify)
- **Responsibility**: Add optional `channel: str = None` field to `PermissionContext` so toolkits know the originating channel (telegram, agentalk, teams, api).
- **Depends on**: nothing new

### Module 4: CredentialResolver Abstraction
- **Path**: `packages/ai-parrot/src/parrot/auth/credentials.py`
- **Responsibility**: Define `CredentialResolver` ABC, `OAuthCredentialResolver`, and `StaticCredentialResolver`. The resolver is the bridge between the toolkit and the token store.
- **Depends on**: Module 5 (OAuthCredentialResolver wraps JiraOAuthManager)

### Module 5: JiraOAuthManager
- **Path**: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
- **Responsibility**: Complete OAuth 2.0 (3LO) lifecycle: generate authorization URLs with CSRF state, exchange codes for tokens, discover cloud_id via accessible-resources, resolve user identity via /myself, store/retrieve tokens from Redis, handle rotating refresh tokens with Redis lock for race conditions.
- **Depends on**: Redis (existing), httpx

### Module 6: OAuth Callback HTTP Routes
- **Path**: `packages/ai-parrot/src/parrot/auth/routes.py`
- **Responsibility**: aiohttp routes for `/api/auth/jira/callback`. Verify state nonce, delegate to JiraOAuthManager, render success/error HTML page, notify the originating channel (Telegram message, WebSocket event).
- **Depends on**: Module 5, `AutonomousOrchestrator.setup_routes()` for mounting

### Module 7: JiraToolkit — OAuth2 3LO Mode
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (modify)
- **Responsibility**: Add `auth_type="oauth2_3lo"` support. Accept `credential_resolver` parameter. Override `_pre_execute()` to resolve credentials and create/cache JIRA client per user. Raise `AuthorizationRequired` when no credentials found. Cache JIRA client instances keyed by `(user_id, token_hash)`.
- **Depends on**: Module 1, Module 2, Module 4

### Module 8: Telegram Integration — /connect_jira Commands
- **Path**: `packages/ai-parrot/src/parrot/integrations/telegram/` (modify or new handler)
- **Responsibility**: Bot commands `/connect_jira`, `/disconnect_jira`, `/jira_status`. Deep link flow: generate auth URL, send to user, receive notification post-callback. `TelegramOAuthNotifier` to send confirmation message after successful callback.
- **Depends on**: Module 5, Module 6

### Module 9: AgenTalk Integration — JiraConnectTool + Hot-Swap
- **Path**: AgenTalk session handler (modify)
- **Responsibility**: On session start, check if user has Jira tokens. If yes, create `JiraToolkit(auth_type="oauth2_3lo")`. If no, register `JiraConnectTool` placeholder that returns auth URL. After successful OAuth callback, hot-swap: remove placeholder, register full toolkit, `_sync_tools_to_llm()`.
- **Depends on**: Module 4, Module 5, Module 7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pre_execute_called_before_tool` | Module 1 | ToolkitTool calls _pre_execute on parent toolkit before bound method |
| `test_post_execute_called_after_tool` | Module 1 | ToolkitTool calls _post_execute with result after bound method |
| `test_pre_execute_exception_propagates` | Module 1 | AuthorizationRequired from _pre_execute propagates to caller |
| `test_auth_required_to_tool_result` | Module 2 | ToolManager converts AuthorizationRequired to ToolResult |
| `test_auth_required_preserves_url` | Module 2 | ToolResult.metadata contains auth_url and provider |
| `test_permission_context_channel` | Module 3 | PermissionContext accepts and stores channel field |
| `test_oauth_resolver_with_valid_token` | Module 4 | OAuthCredentialResolver returns TokenSet when Redis has valid token |
| `test_oauth_resolver_without_token` | Module 4 | OAuthCredentialResolver returns None when Redis has no token |
| `test_static_resolver_always_returns` | Module 4 | StaticCredentialResolver always returns same credentials |
| `test_authorization_url_generation` | Module 5 | JiraOAuthManager generates valid URL with correct params |
| `test_state_nonce_stored_in_redis` | Module 5 | Nonce stored with 10min TTL, deleted after use |
| `test_code_exchange` | Module 5 | Mock Atlassian token endpoint, verify tokens stored |
| `test_rotating_refresh_token` | Module 5 | After refresh, NEW refresh token persisted in Redis |
| `test_refresh_race_condition` | Module 5 | Concurrent refresh requests: only one wins, second reads fresh |
| `test_expired_refresh_cleanup` | Module 5 | Failed refresh (401) revokes user and raises PermissionError |
| `test_callback_valid_state` | Module 6 | Callback with valid state+code stores tokens, returns 200 |
| `test_callback_invalid_state` | Module 6 | Callback with expired/invalid nonce returns error |
| `test_callback_missing_code` | Module 6 | Callback without code returns 400 |
| `test_jira_toolkit_oauth_mode` | Module 7 | JiraToolkit with oauth2_3lo doesn't create client in __init__ |
| `test_jira_toolkit_pre_execute_resolves` | Module 7 | _pre_execute resolves credentials and creates JIRA client |
| `test_jira_toolkit_client_caching` | Module 7 | Same user_id reuses cached JIRA client if token unchanged |
| `test_jira_toolkit_raises_auth_required` | Module 7 | No credentials → AuthorizationRequired with auth_url |
| `test_jira_toolkit_legacy_unaffected` | Module 7 | auth_type=basic_auth continues working unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_oauth_flow` | Simulate: generate URL → mock consent → callback → tokens in Redis → toolkit resolves and executes |
| `test_telegram_connect_disconnect` | /connect_jira → callback → /jira_status → /disconnect_jira → verify revoked |
| `test_multi_user_isolation` | Two users authorize independently; each sees their own Jira identity |
| `test_token_refresh_cycle` | Force token expiration → next tool call triggers transparent refresh |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_atlassian_responses():
    """Mock httpx responses for Atlassian OAuth endpoints."""
    return {
        "token": {"access_token": "at_123", "refresh_token": "rt_456", "expires_in": 3600, "scope": "read:jira-work offline_access"},
        "resources": [{"id": "cloud-uuid-1", "name": "mysite", "url": "https://mysite.atlassian.net", "scopes": [...]}],
        "myself": {"accountId": "acc-123", "displayName": "Jesus Garcia", "emailAddress": "jesus@example.com"},
    }

@pytest.fixture
def redis_client():
    """Async Redis client for testing."""
    import redis.asyncio as aioredis
    return aioredis.from_url("redis://localhost:6379/15", decode_responses=True)

@pytest.fixture
def oauth_manager(redis_client):
    return JiraOAuthManager(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="https://test.example.com/api/auth/jira/callback",
        redis_client=redis_client,
    )
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] `JiraToolkit` with `auth_type="basic_auth"` or `"token_auth"` continues to work identically (zero regression)
- [ ] `AbstractToolkit._pre_execute()` / `_post_execute()` hooks are available to all toolkits, not just Jira
- [ ] `AuthorizationRequired` is caught by `ToolManager` and converted to a structured `ToolResult`
- [ ] OAuth callback stores rotating refresh tokens atomically (no token loss on concurrent refresh)
- [ ] CSRF protection via state nonce with 10-minute TTL
- [ ] JIRA client is cached per-user and invalidated when token changes
- [ ] `/connect_jira` deep link flow works in Telegram (all clients: desktop, mobile, web)
- [ ] AgenTalk session correctly hot-swaps placeholder tool for full toolkit post-authorization
- [ ] `PermissionContext.channel` is populated and propagated from all channels
- [ ] No new external dependencies beyond `httpx` (already used elsewhere)

---

## 6. Codebase Contract

### Verified Imports

```python
# Core toolkit classes
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool  # verified: parrot/tools/toolkit.py
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # verified: parrot/tools/abstract.py
from parrot.tools.manager import ToolManager, ToolDefinition  # verified: parrot/tools/manager.py

# JiraToolkit (ai-parrot-tools package)
from parrot_tools.jiratoolkit import JiraToolkit, JiraInput  # verified: parrot_tools/jiratoolkit.py
from parrot_tools.toolkit import AbstractToolkit  # re-export, verified: parrot_tools/toolkit.py

# Auth (TYPE_CHECKING only — classes may not fully exist yet)
from parrot.auth.permission import PermissionContext  # referenced in TYPE_CHECKING blocks
from parrot.auth.resolver import AbstractPermissionResolver  # referenced in TYPE_CHECKING blocks

# Decorators
from parrot_tools.decorators import tool_schema, requires_permission  # verified: used in jiratoolkit.py:53

# Existing infra
from jira import JIRA  # external dependency, verified: jiratoolkit.py:46
```

### Existing Class Signatures

```python
# parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):
    def __init__(self, name: str, bound_method: callable, description: str = None, args_schema: Type[BaseModel] = None, **kwargs)
    self.bound_method: callable
    async def _execute(self, **kwargs) -> Any:
        return await self.bound_method(**kwargs)  # line ~159

class AbstractToolkit(ABC):
    _tool_cache: Dict[str, ToolkitTool]
    _tools_generated: bool
    exclude_tools: tuple[str, ...]
    tool_prefix: Optional[str] = None
    def __init__(self, **kwargs)
    def get_tools(self, ...) -> List[AbstractTool]  # returns list(_tool_cache.values())
    def _generate_tools(self) -> None  # inspects public async methods
    def _create_tool_from_method(self, name: str, bound_method: callable) -> ToolkitTool
    async def start(self) -> None  # no-op, override in subclasses
    # NOTE: No _pre_execute or _post_execute exists yet — Module 1 adds them

# parrot/tools/abstract.py
class AbstractTool(ABC):
    name: str
    description: str
    args_schema: Type[BaseModel]
    async def execute(self, *args, **kwargs) -> ToolResult  # pops _permission_context, _resolver
    async def _execute(self, **kwargs) -> Any  # abstract, subclasses implement

@dataclass
class ToolResult:
    success: bool = True
    status: str = 'success'
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None

# parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):
    _tools: Dict[str, Union[ToolDefinition, AbstractTool]]
    _resolver: Optional[AbstractPermissionResolver]
    def add_tool(self, tool, name=None) -> None
    def register_toolkit(self, toolkit) -> List[AbstractTool]
    async def execute_tool(self, tool_name, parameters, permission_context=None) -> Any
        # Existing: passes _permission_context and _resolver to tool.execute()
        # Does NOT currently catch AuthorizationRequired — Module 2 adds this

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):
    input_class = JiraInput
    _tool_manager: Optional[ToolManager] = None
    def __init__(self, server_url, auth_type, username, password, token, ..., **kwargs)
        # Creates self.jira = self._init_jira_client() in __init__
    def _set_jira_client(self)
        self.jira = self._init_jira_client()
    def _init_jira_client(self) -> JIRA  # supports basic_auth, token_auth, oauth (OAuth1)
    def set_tool_manager(self, manager: ToolManager)
    # All tool methods (jira_get_issue, jira_search_issues, etc.) use self.jira directly
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_pre_execute()` hook | `ToolkitTool._execute()` | Called before `self.bound_method()` | `toolkit.py` ToolkitTool._execute |
| `_post_execute()` hook | `ToolkitTool._execute()` | Called after `self.bound_method()`, receives result | `toolkit.py` ToolkitTool._execute |
| `AuthorizationRequired` | `ToolManager.execute_tool()` | try/except in execute_tool | `manager.py` execute_tool method |
| `CredentialResolver` | `JiraToolkit._pre_execute()` | Called to resolve creds before each tool call | New in jiratoolkit.py |
| `JiraOAuthManager` | `OAuthCredentialResolver` | Resolver delegates to manager for token ops | New in auth/credentials.py |
| `OAuth callback route` | `AutonomousOrchestrator.setup_routes()` | `manager.setup()` mounts route + signals (TASK-775 / TASK-776) | `orchestrator.py` setup_routes |
| `BotManager.setup(app)` → `app['redis']` | `JiraOAuthManager._on_startup`, FEAT-108 `VaultTokenSync`, navigator-auth refresh tokens | Idempotent publication; BotManager only closes it when it built it (TASK-776) | `manager.py` `_register_shared_redis` / `_cleanup_shared_redis` |
| `JiraOAuthManager(app=...)` | `app['redis']` | `_on_startup` resolves in order: explicit `redis_client` > `app['redis']` > `redis_url` (TASK-776) | `jira_oauth.py` `_on_startup` |
| `PermissionContext.channel` | `ToolManager.execute_tool()` | Passed through existing permission_context flow | `manager.py` execute_tool |

### Does NOT Exist (Anti-Hallucination)

…(truncated)…
