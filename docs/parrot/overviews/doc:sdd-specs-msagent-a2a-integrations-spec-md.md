---
type: Wiki Overview
title: 'Feature Specification: MSAgent & A2A YAML Integrations'
id: doc:sdd-specs-msagent-a2a-integrations-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Operators currently need to write custom Python (like `examples/msagent/server.py`)
  to get A2A exposure, broker-backed credential resolution, OAuth2 SSO flows, or AgentCard
  discovery. This blocks production deployments that want declarative, zero-code agent
  surfacing.
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.security
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.manifest
  rel: mentions
- concept: mod:parrot.auth.o365_oauth
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
- concept: mod:parrot.integrations.a2a
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.resume
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: MSAgent & A2A YAML Integrations

**Feature ID**: FEAT-271
**Date**: 2026-07-09
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

`IntegrationBotManager` can start Telegram, Slack, MS Teams, WhatsApp, and MS Agent SDK bots from `integrations_bots.yaml`. However, there is no way to expose an agent as an **A2A (Agent-to-Agent Protocol)** service or as an **MS Agent SDK** bot with full credential broker support purely from YAML config. The existing `msagentsdk` kind does not wire a `CredentialBroker`, and there is no `a2a` kind at all.

Operators currently need to write custom Python (like `examples/msagent/server.py`) to get A2A exposure, broker-backed credential resolution, OAuth2 SSO flows, or AgentCard discovery. This blocks production deployments that want declarative, zero-code agent surfacing.

### Goals
- Add `kind: a2a` to `integrations_bots.yaml` so agents can be exposed as A2A services declaratively.
- Add `kind: msagent` to `integrations_bots.yaml` so agents can be exposed as MS Agent SDK bots with full credential broker + OAuth2 SSO.
- Provide in-process AgentCard discovery via `/.well-known/agent.json` (per-agent) and `/a2a/directory` (multi-agent listing, A2A agents only).
- Every `msagent` bot automatically gets a companion A2A surface.
- Support all `A2ASecurityMiddleware` auth schemes from day one: JWT, API key, mTLS, HMAC, Basic.
- Credentials declared inline in the agent config block (no external manifest file).
- A2A agents default to the shared aiohttp app; per-agent port override supported.

### Non-Goals (explicitly out of scope)
- Refactoring the `if/elif` dispatch chain into a plugin registry (Option B from brainstorm — see `sdd/proposals/msagent-a2a-integrations.brainstorm.md`).
- Introducing a unified "Surface" abstraction layer (Option C from brainstorm).
- Modifying the existing `msagentsdk`, `telegram`, `msteams`, `whatsapp`, or `slack` kinds.
- Agent-to-agent credential delegation (only user credential acquisition via the broker).
- External credential manifest files — credentials are inline in the YAML agent config.
- External A2A discovery services (Redis, database) — discovery is in-process only.

---

## 2. Architectural Design

### Overview

Two new `kind` values are added to `integrations_bots.yaml`, following the established dispatch pattern (config dataclass + `_start_*_bot()` method):

**`kind: a2a`** — Wraps a registered agent with `A2AServer`, mounts routes on the shared aiohttp app (or a dedicated port if `port` is specified), publishes the `AgentCard` at `/.well-known/agent.json`, and registers it in an in-process discovery registry exposed at `GET /a2a/directory`. Optionally wires `A2ASecurityMiddleware` (all schemes supported) and `CredentialBroker` for per-user credential acquisition.

**`kind: msagent`** — Enhanced MS Agent SDK surface that wires the full `CredentialBroker` + OAuth2 SSO + OBO flows proven in `examples/msagent/server.py`. Reuses `MSAgentSDKConfig` and `MSAgentSDKWrapper` but passes a broker, identity mapper, and optional O365 infrastructure. Every `msagent` bot **automatically** gets a companion A2A surface on the same app (sharing the same broker), and the companion's `AgentCard` is also registered in the discovery directory.

### Component Diagram
```
integrations_bots.yaml
    │
    ▼
IntegrationBotConfig.from_dict()
    ├── kind: a2a     → A2AAgentConfig
    ├── kind: msagent  → MSAgentIntegrationConfig
    ├── kind: msagentsdk (existing)
    ├── kind: telegram   (existing)
    ├── ...              (existing)
    │
    ▼
IntegrationBotManager.startup()
    ├── isinstance(A2AAgentConfig)     → _start_a2a_bot()
    │       ├── A2AServer(agent, broker=...)
    │       │     ├── /.well-known/agent.json
    │       │     ├── /a2a/message/send
    │       │     ├── /a2a/rpc
    │       │     └── ...
    │       ├── A2ASecurityMiddleware (JWT/API-key/mTLS/HMAC/Basic)
    │       └── register in app["a2a_discovery_registry"]
    │
    ├── isinstance(MSAgentIntegrationConfig) → _start_msagent_bot()
    │       ├── CredentialBroker.from_config(credentials)
    │       ├── O365OAuthManager (optional, if o365_client_id set)
    │       ├── MSAgentSDKWrapper(agent, config, app, broker=...)
    │       │     └── POST /api/msagentsdk/{safe_id}/messages
    │       └── A2AServer companion (automatic)
    │             ├── POST /a2a/rpc
    │             └── register in app["a2a_discovery_registry"]
    │
    └── GET /a2a/directory → lists all registered AgentCards
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `IntegrationBotConfig` (`models.py`) | extends | Two new `elif kind ==` branches + new config imports |
| `IntegrationBotManager` (`manager.py`) | extends | Two new `_start_*_bot()` methods + new dict attributes |
| `A2AServer` (`ai-parrot-server`) | uses | Wraps agent as A2A HTTP service |
| `A2ASecurityMiddleware` (`ai-parrot-server`) | uses | Auth middleware for A2A routes |
| `MSAgentSDKWrapper` (`ai-parrot-integrations`) | uses | Wraps agent as MS Agent SDK bot |
| `MSAgentSDKConfig` (`ai-parrot-integrations`) | uses | Reused by `_start_msagent_bot()` to construct the wrapper |
| `CredentialBroker` (`ai-parrot`) | uses | Built from inline YAML `credentials` list |
| `ProviderCredentialConfig` (`ai-parrot`) | uses | Models each credential entry in the YAML |

### Data Models

```python
# New: A2AAgentConfig (in ai-parrot-integrations/src/parrot/integrations/a2a/models.py)
@dataclass
class A2AAgentConfig:
    name: str
    chatbot_id: str
    kind: str = "a2a"
    url: Optional[str] = None
    base_path: str = "/a2a"
    port: Optional[int] = None              # per-agent dedicated port (None = shared app)
    tags: List[str] = field(default_factory=list)
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None

    # Security
    jwt_secret: Optional[str] = None
    api_key: Optional[str] = None
    api_key_header: str = "X-API-Key"
    mtls_ca_cert: Optional[str] = None      # path to CA cert for mTLS
    hmac_secret: Optional[str] = None
    basic_credentials: Optional[Dict[str, str]] = None  # user → password
    security_policy: Optional[Dict[str, Any]] = None     # raw SecurityPolicy fields

    # Credential broker
    enable_credential_broker: bool = False
    credentials: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "A2AAgentConfig": ...
```

```python
# New: MSAgentIntegrationConfig (in ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py)
@dataclass
class MSAgentIntegrationConfig:
    name: str
    chatbot_id: str
    kind: str = "msagent"

    # MS Agent SDK fields (forwarded to MSAgentSDKConfig)
    microsoft_app_id: Optional[str] = None
    microsoft_app_password: Optional[str] = None
    microsoft_tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    api_key: Optional[str] = None
    api_key_header: str = "x-api-key"
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    endpoint: Optional[str] = None
    oauth_connections: Dict[str, str] = field(default_factory=dict)
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)

    # A2A companion (always on)
    url: Optional[str] = None               # public base URL
    tags: List[str] = field(default_factory=list)

    # Credential broker
    enable_credential_broker: bool = False
    credentials: List[Dict[str, Any]] = field(default_factory=list)

    # O365 OAuth infra
    o365_client_id: Optional[str] = None
    o365_client_secret: Optional[str] = None
    o365_tenant_id: Optional[str] = None
    redirect_uri: Optional[str] = None

    # JWT for A2A companion
    jwt_secret: Optional[str] = None
    debug: bool = False

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentIntegrationConfig": ...

    def to_msagentsdk_config(self) -> MSAgentSDKConfig:
        """Convert to the inner MSAgentSDKConfig used by MSAgentSDKWrapper."""
        ...
```

### New Public Interfaces

```python
# Discovery endpoint handler (registered on the shared aiohttp app)
async def handle_a2a_directory(request: web.Request) -> web.Response:
    """GET /a2a/directory — returns JSON array of all registered AgentCards."""
    registry: Dict[str, AgentCard] = request.app.get("a2a_discovery_registry", {})
    cards = [card.to_dict() for card in registry.values()]
    return web.json_response(cards)
```

---

## 3. Module Breakdown

### Module 1: A2A Agent Config
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/a2a/models.py`
- **Responsibility**: `A2AAgentConfig` dataclass with `from_dict()` and `__post_init__()` for env var fallback.
- **Depends on**: None (pure data model)

### Module 2: MSAgent Integration Config
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` (extends existing file)
- **Responsibility**: `MSAgentIntegrationConfig` dataclass with `from_dict()`, `__post_init__()`, and `to_msagentsdk_config()`.
- **Depends on**: `MSAgentSDKConfig` (same file)

### Module 3: Config Dispatch Extension
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/models.py`
- **Responsibility**: Add `A2AAgentConfig` and `MSAgentIntegrationConfig` to the import block and add `elif kind == 'a2a'` and `elif kind == 'msagent'` branches in `IntegrationBotConfig.from_dict()`. Update the `agents` type union.
- **Depends on**: Module 1, Module 2

### Module 4: A2A Bot Startup
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
- **Responsibility**: `_start_a2a_bot()` method + `self.a2a_bots` dict + discovery registry wiring + security middleware setup + `/a2a/directory` route registration.
- **Depends on**: Module 1, Module 3, `A2AServer`, `A2ASecurityMiddleware`, `CredentialBroker`

### Module 5: MSAgent Bot Startup
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
- **Responsibility**: `_start_msagent_bot()` method + `self.msagent_bots` dict + credential broker wiring + O365 OAuth setup + companion A2A server + suspend/resume store setup.
- **Depends on**: Module 2, Module 3, Module 4 (for discovery registry), `MSAgentSDKWrapper`, `CredentialBroker`, `A2AServer`

### Module 6: Startup Dispatch Extension
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
- **Responsibility**: Add `isinstance` checks for `A2AAgentConfig` and `MSAgentIntegrationConfig` in `startup()`.
- **Depends on**: Module 4, Module 5

### Module 7: Tests
- **Path**: `tests/integrations/test_a2a_integration.py`, `tests/integrations/test_msagent_integration.py`
- **Responsibility**: Unit tests for config parsing, startup methods, discovery registry, and integration tests for end-to-end YAML → running service.
- **Depends on**: All modules above

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_a2a_config_from_dict` | Module 1 | Parse A2A YAML config into `A2AAgentConfig` |
| `test_a2a_config_env_fallback` | Module 1 | Env var fallback for `jwt_secret`, `api_key` |
| `test_a2a_config_defaults` | Module 1 | Default values for `base_path`, `port`, etc. |
| `test_msagent_config_from_dict` | Module 2 | Parse MSAgent YAML config into `MSAgentIntegrationConfig` |
| `test_msagent_config_to_msagentsdk` | Module 2 | `to_msagentsdk_config()` produces valid `MSAgentSDKConfig` |
| `test_msagent_config_env_fallback` | Module 2 | Env var fallback for MS app credentials |
| `test_kind_dispatch_a2a` | Module 3 | `IntegrationBotConfig.from_dict()` creates `A2AAgentConfig` for `kind: a2a` |
| `test_kind_dispatch_msagent` | Module 3 | `IntegrationBotConfig.from_dict()` creates `MSAgentIntegrationConfig` for `kind: msagent` |
| `test_unknown_kind_skipped` | Module 3 | Unrecognized kinds are silently skipped |
| `test_discovery_registry_a2a_only` | Module 4 | `/a2a/directory` lists only A2A agents, not telegram/slack/etc. |
| `test_a2a_bot_shared_app` | Module 4 | A2A routes mounted on shared app when no `port` set |
| `test_a2a_bot_dedicated_port` | Module 4 | Dedicated `TCPSite` when `port` set |
| `test_a2a_security_middleware_wired` | Module 4 | Security middleware mounted when `jwt_secret` or `api_key` set |
| `test_msagent_broker_wired` | Module 5 | `CredentialBroker` passed to `MSAgentSDKWrapper` |
| `test_msagent_a2a_companion` | Module 5 | Companion A2A surface automatically created |
| `test_msagent_o365_infra` | Module 5 | O365 OAuth manager set up when `o365_client_id` present |
| `test_credentials_inline_parsing` | Module 5 | Inline `credentials` list converted to `ProviderCredentialConfig` |

### Integration Tests
| Test | Description |
|---|---|
| `test_a2a_yaml_to_agent_card` | Full flow: YAML config → A2AServer started → `GET /.well-known/agent.json` returns valid AgentCard |
| `test_a2a_directory_listing` | Multiple A2A agents configured → `/a2a/directory` returns all cards |
| `test_msagent_yaml_to_messaging_route` | Full flow: YAML config → MSAgentSDKWrapper started → messaging route responds |
| `test_msagent_companion_a2a` | MSAgent configured → companion A2A surface responds to `/a2a/rpc` |
| `test_mixed_kinds_coexist` | YAML with telegram + a2a + msagent → all start correctly without interference |

### Test Data / Fixtures
```python
@pytest.fixture
def a2a_yaml_config():
    return {
        "agents": {
            "TestA2A": {
                "kind": "a2a",
                "chatbot_id": "test_agent",
                "url": "http://localhost:8181",
                "tags": ["test"],
                "jwt_secret": "test-secret",
                "enable_credential_broker": True,
                "credentials": [
                    {"provider": "fireflies", "auth": "static_key", "options": {}}
                ],
            }
        }
    }

@pytest.fixture
def msagent_yaml_config():
    return {
        "agents": {
            "TestMSAgent": {
                "kind": "msagent",
                "chatbot_id": "test_agent",
                "url": "http://localhost:3978",
                "welcome_message": "Hello!",
                "enable_credential_broker": True,
                "credentials": [
                    {"provider": "o365", "auth": "oauth2", "options": {}}
                ],
            }
        }
    }
```

---

## 5. Acceptance Criteria

- [ ] `kind: a2a` in `integrations_bots.yaml` starts an `A2AServer` on the shared aiohttp app.
- [ ] `kind: a2a` with `port` set starts a dedicated `TCPSite` on that port.
- [ ] `GET /.well-known/agent.json` returns a valid `AgentCard` for each A2A agent.
- [ ] `GET /a2a/directory` returns a JSON array of AgentCards for **A2A agents only** (not telegram/slack/etc.).
- [ ] `kind: msagent` in `integrations_bots.yaml` starts an `MSAgentSDKWrapper` with a `CredentialBroker`.
- [ ] Every `msagent` bot automatically gets a companion A2A surface (routes mounted, card in directory).
- [ ] `A2ASecurityMiddleware` is wired when any security field (`jwt_secret`, `api_key`, `mtls_ca_cert`, `hmac_secret`, `basic_credentials`) is set — all schemes supported.
- [ ] Inline `credentials` list in YAML is parsed into `ProviderCredentialConfig` objects and passed to `CredentialBroker.from_config()`.
- [ ] O365 OAuth infrastructure (`O365OAuthManager`) is set up when `o365_client_id` is present in `msagent` config.
- [ ] Existing `msagentsdk`, `telegram`, `msteams`, `whatsapp`, and `slack` kinds are unaffected.
- [ ] Missing optional dependencies (`ai-parrot-server` for A2A, MS Agent SDK extras) are handled gracefully with `try/except ImportError`.
- [ ] All unit tests pass.
- [ ] All integration tests pass.
- [ ] No breaking changes to existing `integrations_bots.yaml` configs.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# These imports have been confirmed to work (2026-07-09):
from parrot.a2a.server import A2AServer                     # packages/ai-parrot-server/src/parrot/a2a/server.py:50
from parrot.a2a.models import AgentCard, AgentSkill, AgentCapabilities  # packages/ai-parrot/src/parrot/a2a/models.py
from parrot.a2a.security import A2ASecurityMiddleware        # packages/ai-parrot-server/src/parrot/a2a/security.py:1409
from parrot.a2a.security import SecurityPolicy               # packages/ai-parrot-server/src/parrot/a2a/security.py:218
from parrot.a2a.security import JWTAuthenticator             # packages/ai-parrot-server/src/parrot/a2a/security.py:972
from parrot.a2a.security import MTLSAuthenticator            # packages/ai-parrot-server/src/parrot/a2a/security.py:1206
from parrot.a2a.security import InMemoryCredentialProvider   # packages/ai-parrot-server/src/parrot/a2a/security.py:444
from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper  # packages/ai-parrot-integrations
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig    # packages/ai-parrot-integrations
from parrot.auth.broker import CredentialBroker              # packages/ai-parrot/src/parrot/auth/broker.py:326
from parrot.auth.credentials import ProviderCredentialConfig # packages/ai-parrot/src/parrot/auth/credentials.py:46
from parrot.auth.o365_oauth import O365OAuthManager          # packages/ai-parrot/src/parrot/auth/o365_oauth.py
from parrot.security.audit_ledger import AuditLedger         # packages/ai-parrot/src/parrot/security/audit_ledger.py
from parrot.human.suspended_store import SuspendedExecutionStore  # packages/ai-parrot/src/parrot/human/suspended_store.py
from parrot.integrations.msagentsdk.resume import MsaConversationRefStore  # packages/ai-parrot-integrations
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/a2a/server.py:50
class A2AServer:
    def __init__(
        self,
        agent: "AbstractBot",
        *,
        base_path: str = "/a2a",           # line 88
        version: str = "1.0.0",            # line 89
        capabilities: Optional[AgentCapabilities] = None,  # line 90
        extra_skills: Optional[List[AgentSkill]] = None,   # line 91
        tags: Optional[List[str]] = None,                  # line 92
        broker: Optional[Any] = None,                      # line 94
        identity_mapper: Optional[Any] = None,             # line 95
        credential_resolvers: Optional[Dict[str, Any]] = None,  # line 97 (deprecated)
        suspended_store: Optional[Any] = None,             # line 98
        audit_ledger: Optional[Any] = None,                # line 99
    ):  # line 84
    def setup(self, app: web.Application, url: Optional[str] = None) -> None:  # line 171
    def get_agent_card(self) -> AgentCard:  # line 207

# packages/ai-parrot-server/src/parrot/a2a/security.py:1409
class A2ASecurityMiddleware:
    def __init__(
        self,
        *,
        jwt_authenticator: Optional[JWTAuthenticator] = None,  # line 1439
        mtls_authenticator: Optional[MTLSAuthenticator] = None,  # line 1440
        credential_provider: Optional[CredentialProvider] = None,  # line 1441
        default_policy: Optional[SecurityPolicy] = None,  # line 1442
        skip_paths: Optional[List[str]] = None,  # line 1443
        rate_limiter: Optional[Any] = None,  # line 1444
    ):  # line 1436

# packages/ai-parrot-server/src/parrot/a2a/security.py:218
class SecurityPolicy(BaseModel):
    require_auth: bool = False
    allowed_schemes: List[AuthScheme] = [...]
    allowed_agents: List[str] = []
    denied_agents: List[str] = []
    required_permissions: List[str] = []
    rate_limit: Optional[int] = None
    ip_whitelist: List[str] = []
    require_https: bool = False
    require_mtls: bool = False

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py:63
class MSAgentSDKWrapper:
    def __init__(
        self,
        agent: AbstractBot,
        config: MSAgentSDKConfig,
        app: web.Application,
        broker: Optional["CredentialBroker"] = None,
        identity_mapper: Optional["CanonicalIdentityMapper"] = None,
        agent_class: Optional[type] = None,
    ) -> None:  # line 88

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py:11
@dataclass
class MSAgentSDKConfig:
    name: str                                # line 67
    chatbot_id: str                          # line 68
    client_id: Optional[str] = None          # line 69
    client_secret: Optional[str] = None      # line 70
    tenant_id: Optional[str] = None          # line 71
    anonymous_auth: bool = False             # line 72
    api_key: Optional[str] = None            # line 73
    api_key_header: str = "x-api-key"        # line 74
    app_type: str = "SingleTenant"           # line 75
    authority: Optional[str] = None          # line 76
    kind: str = "msagentsdk"                 # line 77
    welcome_message: Optional[str] = None    # line 78
    system_prompt_override: Optional[str] = None  # line 79
    endpoint: Optional[str] = None           # line 80
    oauth_connections: Dict[str, str] = field(default_factory=dict)  # line 81
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)  # line 82
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentSDKConfig":  # line 132

# packages/ai-parrot-integrations/src/parrot/integrations/models.py:17
@dataclass
class IntegrationBotConfig:
    agents: Dict[str, Union[TelegramAgentConfig, MSTeamsAgentConfig, WhatsAppAgentConfig, SlackAgentConfig, MSAgentSDKConfig]] = field(default_factory=dict)  # line 36
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig':  # line 39
    # Dispatch chain at lines 50-59: telegram, msteams, whatsapp, slack, msagentsdk

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:47
class IntegrationBotManager:
    def __init__(self, bot_manager: 'BotManager'):  # line 58
    # Active bot dicts:
    #   self.telegram_bots    (line 63)
    #   self.msteams_bots     (line 64)
    #   self.whatsapp_bots    (line 65)
    #   self.slack_bots       (line 66)
    #   self.msagentsdk_bots  (line 67)
    async def _get_agent(self, chatbot_id: str, system_prompt_override: Optional[str] = None) -> Optional['AbstractBot']:  # line 118
    async def startup(self, extra_config: Optional[dict] = None) -> None:  # line 130
    # Dispatch chain at lines 150-159: isinstance checks for each config type
    async def _start_msagentsdk_bot(self, name: str, config: MSAgentSDKConfig) -> None:  # line 334

# packages/ai-parrot/src/parrot/auth/broker.py:326
class CredentialBroker:
    def __init__(self, *, audit_ledger=None, identity_mapper=None) -> None:  # line 362
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None:  # line 375
    @classmethod
    def from_config(cls, configs: List[ProviderCredentialConfig], strict: bool = True, **deps) -> "CredentialBroker":  # line 401

# packages/ai-parrot/src/parrot/auth/credentials.py:46
class ProviderCredentialConfig(BaseModel):
    provider: str
    auth: AuthKind  # Literal["obo", "oauth2", "static_key", "mcp", "device_code"]
    options: Dict[str, Any] = {}
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `A2AAgentConfig` | `IntegrationBotConfig.from_dict()` | `elif kind == 'a2a'` branch | `models.py:39` |

…(truncated)…
