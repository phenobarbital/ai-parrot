---
type: Wiki Overview
title: 'Feature Specification: Per-User Auth & OBO for MS Agents SDK Integration'
id: doc:sdd-specs-auth-obo-msagentsdk-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The FEAT-259 transport layer authenticates the **bot↔connector** channel
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.context
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.utils.helpers
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Per-User Auth & OBO for MS Agents SDK Integration

**Feature ID**: FEAT-261
**Date**: 2026-06-26
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor
**Proposal**: `sdd/proposals/auth-obo-msagentsdk.proposal.md`
**Research**: `sdd/proposals/auth-obo-research.md`
**Depends on**: FEAT-259 (transport/bridge — implemented)

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-259 transport layer authenticates the **bot↔connector** channel
(inbound JWT/API-key, outbound MSAL service connection) but does **not**
authenticate **end users** or acquire per-user tokens for downstream APIs.
Four tools (`o365`/Graph, `work-iq`, `jira`, `fireflies`) require per-user
credentials that cannot be obtained through the bot's service identity.

The Microsoft 365 Agents SDK provides a managed OAuth layer via the Bot
Framework Token Service — a per-user, server-side token store keyed by
user + OAuth connection, with refresh handled automatically. This collapses
the custom OAuth dance, credential storage, and suspend/resume infrastructure
that was designed for the A2A path (FEAT-XXX brainstorm).

### Goals

- Enable per-user OAuth sign-in via native Bot Framework sign-in cards on
  the Copilot Studio / Teams / Web Chat surface.
- Handle `invoke` activities (`signin/verifyState`, `signin/tokenExchange`)
  to complete the sign-in round-trip.
- Perform OBO token exchange for Microsoft-cluster APIs (`o365`/Graph,
  `work-iq`) using different scopes off the same Entra sign-in.
- Support non-Microsoft OAuth providers (Jira via generic OAuth2 BF
  connection).
- Bridge resolved per-user tokens into ai-parrot's tool layer through
  `CredentialResolver` and the `_pctx_var` / `RequestContext` mechanism.
- Extract `aad_object_id` (Entra identity) as the canonical user identity
  for token service keying and audit.
- Record `key_fingerprint` per credentialed tool invocation via
  `AuditLedger`.
- Never expose raw tokens in the conversational plane or model context.

### Non-Goals (explicitly out of scope)

- **Bot↔connector auth** — unchanged (FEAT-259 scope).
- **A2A path credential flow** — separate FEAT-XXX, not touched here.
- **Account-linking** (Entra ⇄ Atlassian/Fireflies identity mapping) —
  future concern.
- **Proactive credential refresh notifications** — the token service
  handles refresh silently.
- **Custom OAuth flow** for tools that fit the native BF connection model.
- **Migration of existing `botbuilder`-based MS Teams integration** to use
  this auth layer.

---

## 2. Architectural Design

### Overview

The design leverages the Bot Framework Token Service as the credential
backend. ai-parrot's `CredentialResolver` becomes a thin adapter
(`BFTokenServiceResolver`) that, given a user identity + connection name,
fetches the current user token from the SDK token client. Three of four
target tools (`o365`, `work-iq`, `jira`) map to Azure Bot OAuth connections;
`fireflies` (static API key) requires a custom out-of-band capture.

The sign-in flow is a multi-activity, asynchronous round-trip:
1. Tool needs a credential → bridge emits a **sign-in card** (OAuthCard).
2. User signs in against the token service's hosted OAuth.
3. Completion arrives as an **`invoke`** activity (`signin/verifyState` or
   `signin/tokenExchange`).
4. Turn resumes; the token is retrievable for the connection.

OBO is native for the Microsoft cluster: one Entra sign-in amortizes across
`o365` + `work-iq` by exchanging to different scopes via `OBOConnectionName`
+ `OBOScopes`.

### Component Diagram

```
Copilot Studio / Teams / Web Chat
        │
        ▼  POST Activity (message | invoke)
        │
[MSAgentSDKWrapper.handle_request()]
        │
        ▼  CloudAdapter.process(request, parrot_m365_agent)
        │
[ParrotM365Agent.on_turn(context)]
        │
        ├─ message → _handle_message(context)
        │   ├─ extract aad_object_id from Activity/claims
        │   ├─ build PermissionContext + set _pctx_var
        │   ├─ agent.ask(question, session_id, user_id, ctx=..., trace_context=...)
        │   │   └─ tool invocation → CredentialResolver.resolve(channel, user_id)
        │   │       ├─ BFTokenServiceResolver → SDK token client → token
        │   │       │   ├─ token available → resolved client to tool
        │   │       │   └─ no token → raise CredentialRequired
        │   │       └─ StaticCredentialResolver (fireflies) → static key
        │   └─ CredentialRequired caught → emit OAuthCard sign-in activity
        │
        ├─ invoke/signin/verifyState → _handle_signin_verify(context)
        │   └─ validate magic code → token service stores token → resume
        │
        ├─ invoke/signin/tokenExchange → _handle_signin_exchange(context)
        │   └─ exchange SSO token → token service stores token → resume
        │
        └─ conversationUpdate → _handle_conversation_update(context)
```

### Per-Resource Auth Design

| Tool | IdP | Azure Bot OAuth Connection | OBO | Sign-in UX |
|------|-----|---------------------------|-----|------------|
| `o365`/Graph | Entra | `graph_sso` (Entra v2) | native — `OBOScopes` for Graph | native card / Teams SSO |
| `work-iq` | Entra | shared with `o365` | native — different `OBOScopes` | shared sign-in |
| `jira` | Atlassian | `jira_oauth` (generic OAuth2) | N/A | native card |
| `fireflies` | none | — | N/A | custom out-of-band |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `CredentialResolver` (abstract) | subclass | New `BFTokenServiceResolver` adapter |
| `_pctx_var` / `PermissionContext` | uses | Set per-request context with user identity + channel |
| `RequestContext` | uses | Pass to `ask()` via `ctx=` parameter |
| `ParrotM365Agent.on_turn()` | modifies | Add `invoke` routing + identity extraction |
| `ParrotM365Agent._handle_message()` | modifies | Inject credential context into `ask()` call |
| `MSAgentSDKConfig` | extends | Add `oauth_connections`, `obo_scopes` fields |
| `AbstractBot.ask()` | calls | Use existing `ctx` and `trace_context` parameters |
| `UserContext` | uses | Carry `aad_object_id` as `user_id` |

### Data Models

```python
# New fields on MSAgentSDKConfig
@dataclass
class MSAgentSDKConfig:
    # ... existing fields ...
    oauth_connections: Dict[str, str] = field(default_factory=dict)
    # Maps tool name → Azure Bot OAuth connection name
    # e.g. {"o365": "graph_sso", "jira": "jira_oauth"}
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)
    # Maps tool name → OBO target scopes
    # e.g. {"o365": ["https://graph.microsoft.com/.default"],
    #        "work_iq": ["api://work-iq/.default"]}

# New class
@dataclass
class AuditEntry:
    timestamp: str          # ISO-8601
    user_id: str            # aad_object_id
    channel: str            # "msagentsdk"
    tool: str               # tool name
    connection: str         # OAuth connection name
    key_fingerprint: str    # SHA-256 of first 8 bytes of token
    action: str             # "resolve" | "obo_exchange"
```

### New Public Interfaces

```python
class BFTokenServiceResolver(CredentialResolver):
    """Resolves per-user tokens from the Bot Framework Token Service."""

    def __init__(
        self,
        oauth_connections: Dict[str, str],
        obo_scopes: Dict[str, List[str]],
    ) -> None: ...

    async def resolve(
        self,
        channel: str,
        user_id: str,
        *,
        tool: str | None = None,
        turn_context: Any | None = None,
    ) -> Optional[Any]: ...

    async def get_auth_url(
        self,
        channel: str,
        user_id: str,
    ) -> str: ...


class AuditLedger:
    """Records per-invocation credential usage for compliance."""

    def __init__(self, logger: logging.Logger | None = None) -> None: ...

    def record(self, entry: AuditEntry) -> None: ...

    async def flush(self) -> None: ...
```

---

## 3. Module Breakdown

### Module 1: Config Extension (`msagentsdk/models.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py`
- **Responsibility**: Add `oauth_connections: Dict[str, str]` and
  `obo_scopes: Dict[str, List[str]]` fields to `MSAgentSDKConfig`. Add
  env var fallback in `__post_init__()` for
  `{AGENT_NAME}_OAUTH_CONNECTIONS` (JSON string) and
  `{AGENT_NAME}_OBO_SCOPES` (JSON string).
- **Depends on**: None.

### Module 2: Identity Extraction (`msagentsdk/agent.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
- **Responsibility**: Extract `aad_object_id` from the Activity's
  `from_property` or from validated claims in the `TurnContext`. Fall back
  to `from_property.id` (channel id) if `aad_object_id` is not present.
  Build `UserContext` with the canonical identity.
- **Depends on**: `parrot.auth.context.UserContext`.

### Module 3: Invoke Routing (`msagentsdk/agent.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
- **Responsibility**: Add `invoke` activity routing in `on_turn()`:
  - `signin/verifyState` → `_handle_signin_verify(context)`: validate the
    magic code, let the token service store the token, send a confirmation
    activity.
  - `signin/tokenExchange` → `_handle_signin_exchange(context)`: exchange
    the SSO token, let the token service store the token, send a
    confirmation activity.
  - Other invoke types → log and ignore (existing behavior).
- **Depends on**: Module 2 (identity).

### Module 4: Credential Context Bridge (`msagentsdk/agent.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
- **Responsibility**: In `_handle_message()`, after identity extraction:
  1. Build `UserSession` → `PermissionContext` with `channel="msagentsdk"`,
     `user_id=aad_object_id`.
  2. Set `_pctx_var` with the `PermissionContext`.
  3. Build `RequestContext` with `user_id`, `session_id`.
  4. Pass `ctx=request_context` and `trace_context=trace_context` to
     `agent.ask()`.
  5. Catch `CredentialRequired` from tools → emit OAuthCard sign-in
     activity instead of an error response.
- **Depends on**: Modules 2, 3. `parrot.auth.permission.UserSession`,
  `parrot.auth.permission.PermissionContext`, `parrot.auth.context._pctx_var`,
  `parrot.utils.helpers.RequestContext`.

### Module 5: BFTokenServiceResolver (`msagentsdk/auth.py` — new file)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/auth.py`
- **Responsibility**: `BFTokenServiceResolver` subclass of
  `CredentialResolver`. Given a tool name, resolves the OAuth connection
  name from config, fetches the user token from the SDK token client, and
  optionally performs OBO exchange if `obo_scopes` are configured for the
  tool. Returns the resolved token (never raw — wrapped in a credential
  object). Computes `key_fingerprint` (SHA-256 of first 8 bytes) and
  records to `AuditLedger`.
- **Depends on**: Module 1 (config), Module 6 (AuditLedger),
  `parrot.auth.credentials.CredentialResolver`.

### Module 6: AuditLedger (`parrot/auth/audit.py` — new file)

- **Path**: `packages/ai-parrot/src/parrot/auth/audit.py`
- **Responsibility**: `AuditLedger` class that records `AuditEntry` objects
  per credentialed tool invocation. Initially log-based (structured JSON
  to `self.logger`); can be extended to a persistent store later.
  `AuditEntry` dataclass with `timestamp`, `user_id`, `channel`, `tool`,
  `connection`, `key_fingerprint`, `action`.
- **Depends on**: None (standalone).

### Module 7: Sign-in Card Emission (`msagentsdk/agent.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
- **Responsibility**: When a tool raises `CredentialRequired` (or the
  resolver returns `None` for a required credential), emit a native
  OAuthCard activity via `context.send_activity()` referencing the
  appropriate OAuth connection name. The card triggers the token service's
  hosted OAuth flow. **Never** fall back to service identity for a per-user
  tool; **never** include a secret in the transcript.
- **Depends on**: Modules 3, 4, 5.

### Module 8: Wrapper Auth Wiring (`msagentsdk/wrapper.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py`
- **Responsibility**: In `__init__()`, if `config.oauth_connections` is
  non-empty:
  1. Instantiate `BFTokenServiceResolver` with the connection map and OBO
     scopes.
  2. Instantiate `AuditLedger`.
  3. Pass both to `ParrotM365Agent` (new constructor parameters).
  If OAuth connections are empty, the bridge operates as today (no
  user-token acquisition).
- **Depends on**: Modules 1, 5, 6, and existing wrapper code.

### Module 9: Tests

- **Path**: `tests/integrations/test_msagentsdk/`
- **Responsibility**: Unit tests for all new modules. Integration test for
  the full sign-in round-trip with mocked token service.
- **Depends on**: Modules 1–8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_oauth_connections` | 1 | Validates `oauth_connections` and `obo_scopes` fields parse from dict and env vars |
| `test_config_oauth_connections_empty` | 1 | Empty `oauth_connections` is valid — backward compatible |
| `test_identity_aad_object_id` | 2 | Extracts `aad_object_id` from Activity `from_property` |
| `test_identity_fallback_channel_id` | 2 | Falls back to `from_property.id` when `aad_object_id` absent |
| `test_invoke_signin_verify_state` | 3 | `signin/verifyState` invoke is routed and answered |
| `test_invoke_signin_token_exchange` | 3 | `signin/tokenExchange` invoke is routed and answered |
| `test_invoke_unknown_ignored` | 3 | Non-signin invoke types still ignored (no regression) |
| `test_message_sets_pctx_var` | 4 | `_handle_message` sets `_pctx_var` with correct `PermissionContext` |
| `test_message_passes_ctx_to_ask` | 4 | `ask()` receives `ctx=RequestContext(...)` |
| `test_credential_required_emits_card` | 7 | `CredentialRequired` → OAuthCard activity sent |
| `test_no_service_fallback` | 7 | Missing credential never falls back to service identity |
| `test_resolver_returns_token` | 5 | `BFTokenServiceResolver.resolve()` returns token from mock SDK client |
| `test_resolver_obo_exchange` | 5 | Resolver performs OBO exchange when `obo_scopes` configured |
| `test_resolver_no_token_returns_none` | 5 | Returns `None` when token service has no token for user |
| `test_audit_ledger_records_entry` | 6 | `AuditLedger.record()` logs structured JSON |
| `test_key_fingerprint_computation` | 6 | SHA-256 of first 8 bytes matches expected |
| `test_wrapper_wires_resolver` | 8 | Wrapper creates `BFTokenServiceResolver` when `oauth_connections` non-empty |
| `test_wrapper_no_resolver_when_empty` | 8 | Wrapper skips resolver when `oauth_connections` empty |

### Integration Tests

| Test | Description |
|---|---|
| `test_signin_roundtrip` | Message → CredentialRequired → OAuthCard → invoke/verifyState → token available → tool executes |
| `test_obo_graph_then_workiq` | One Entra sign-in → OBO to Graph scopes → OBO to Work IQ scopes |
| `test_message_unchanged_without_oauth` | Backward compatibility: message flow unchanged when `oauth_connections` is empty |

### Test Data / Fixtures

```python
@pytest.fixture
def oauth_config():
    return MSAgentSDKConfig(
        name="TestBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
        oauth_connections={"o365": "graph_sso", "jira": "jira_oauth"},
        obo_scopes={"o365": ["https://graph.microsoft.com/.default"]},
    )

@pytest.fixture
def mock_activity_with_aad():
    return {
        "type": "message",
        "text": "What's on my calendar?",
        "from": {
            "id": "user-123",
            "name": "Test User",
            "aadObjectId": "00000000-0000-0000-0000-000000000001",
        },
        "conversation": {"id": "conv-456"},
        "channelId": "msteams",
    }

@pytest.fixture
def mock_signin_invoke():
    return {
        "type": "invoke",
        "name": "signin/verifyState",
        "value": {"state": "magic-code-12345"},
        "from": {
            "id": "user-123",
            "aadObjectId": "00000000-0000-0000-0000-000000000001",
        },
        "conversation": {"id": "conv-456"},
    }
```

---

## 5. Acceptance Criteria

- [ ] A tool reporting a missing per-user credential causes a native sign-in
      card (OAuthCard) — never a service-identity fallback, never a secret in
      the transcript.
- [ ] Completed sign-in (`invoke` round-trip handled) yields a per-user token
      retrievable by connection name.
- [ ] `o365` + `work-iq` both work off one Entra sign-in via OBO to distinct
      scopes.
- [ ] `BFTokenServiceResolver` hands tools resolved credentials sourced from
      the BF Token Service; raw tokens never enter model/tool context.
- [ ] `_pctx_var` carries per-request `PermissionContext` set by the bridge
      with `channel="msagentsdk"` and `user_id=aad_object_id`.
- [ ] `RequestContext` is passed to `ask()` via the `ctx=` parameter.
- [ ] `AuditLedger` records `key_fingerprint` per credentialed invocation.
- [ ] Canonical identity derived from `aad_object_id`; falls back to
      `from_property.id` when absent.
- [ ] `on_turn` routes and correctly answers `signin/verifyState` and
      `signin/tokenExchange` invoke activities.
- [ ] `MSAgentSDKConfig` accepts `oauth_connections` and `obo_scopes` fields
      with env var fallback.
- [ ] Empty `oauth_connections` is backward compatible — existing message
      flow unchanged.
- [ ] All unit tests pass: `pytest tests/integrations/test_msagentsdk/ -v`
- [ ] No breaking changes to existing FEAT-259 transport layer.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.

### Verified Imports

```python
# Credential infrastructure
from parrot.auth.credentials import CredentialResolver       # verified: credentials.py:27
from parrot.auth.credentials import OAuthCredentialResolver   # verified: credentials.py:49
from parrot.auth.credentials import StaticCredentialResolver  # verified: credentials.py:81
from parrot.auth.credentials import StaticCredentials         # verified: credentials.py:70

# Auth context
from parrot.auth.context import _pctx_var                    # verified: context.py:33
from parrot.auth.context import UserContext                   # verified: context.py:38
from parrot.auth.permission import UserSession                # verified: permission.py:20
from parrot.auth.permission import PermissionContext          # verified: permission.py:80

# Request context
from parrot.utils.helpers import RequestContext               # verified: helpers.py:7
from parrot.utils.helpers import _current_ctx                 # verified: helpers.py:53

# Tracing
from parrot.core.events.lifecycle.trace import TraceContext    # verified: trace.py:14

# Bot abstraction
from parrot.bots.abstract import AbstractBot                  # verified: abstract.py:156
from parrot.models.responses import AIMessage                 # verified: responses.py:72

# Re-exports from parrot.auth
from parrot.auth import (                                     # verified: auth/__init__.py
    CredentialResolver, OAuthCredentialResolver,
    StaticCredentialResolver, StaticCredentials,
    UserSession, PermissionContext, UserContext,
)

# MS Agent SDK (lazy imports — inside methods only)
from microsoft_agents.authentication.msal import MsalConnectionManager  # verified: wrapper.py:151
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):                                        # line 27
    @abstractmethod
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:   # line 31
    @abstractmethod
    async def get_auth_url(self, channel: str, user_id: str) -> str:        # line 40
    async def is_connected(self, channel: str, user_id: str) -> bool:       # line 44

class OAuthCredentialResolver(CredentialResolver):                    # line 49
    def __init__(self, oauth_manager: "JiraOAuthManager") -> None:          # line 59
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:   # line 62
    async def get_auth_url(self, channel: str, user_id: str) -> str:        # line 65

# packages/ai-parrot/src/parrot/auth/context.py
@dataclass(frozen=True)
class UserContext:                                                    # line 38
    channel: str                                                            # line 42
    user_id: str                                                            # line 43
    display_name: Optional[str] = None                                      # line 44
    email: Optional[str] = None                                             # line 45
    session_id: Optional[str] = None                                        # line 46
    metadata: Dict[str, Any] = field(default_factory=dict)                  # line 47

_pctx_var: contextvars.ContextVar["PermissionContext | None"] = (     # line 33
    contextvars.ContextVar("dataset_manager_pctx", default=None)
)

# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True)
class UserSession:                                                    # line 20
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    def has_role(self, role: str) -> bool:                                   # line 57
    def has_any_role(self, roles: set | frozenset) -> bool:                  # line 68

@dataclass
class PermissionContext:                                              # line 80
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: "Optional[TraceContext]" = None
    extra: dict[str, Any] = field(default_factory=dict)
    @property
    def user_id(self) -> str:                                                # line 129
    @property
    def tenant_id(self) -> str:                                              # line 134

# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:                                                 # line 7
    def __init__(
        self,
        request: web.Request = None,
        app: Optional[Any] = None,
        llm: Optional[Any] = None,
        user_id: Union[str, int] = None,
        session_id: str = None,
        **kwargs
    ):                                                                       # line 11

_current_ctx: ContextVar[Optional[RequestContext]] = ContextVar(      # line 53
    "parrot_request_ctx", default=None
)

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(..., ABC):                                          # line 156
    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        ...
        ctx: Optional[RequestContext] = None,                                # line 3707
        ...
        trace_context: Optional[TraceContext] = None,                        # line 3712
        **kwargs
    ) -> AIMessage:                                                          # line 3694

# packages/ai-parrot-integrations/.../msagentsdk/agent.py
class ParrotM365Agent:                                                # line 14
    def __init__(
        self,
        parrot_agent: AbstractBot,
        welcome_message: Optional[str] = None,
    ) -> None:                                                               # line 33
    async def on_turn(self, context) -> None:                                # line 52
    async def _handle_message(self, context) -> None:                        # line 76
    # Current ask() call at line 104:
    # response = await self.parrot_agent.ask(

…(truncated)…
