---
type: Wiki Overview
title: 'Brainstorm: MSAgent & A2A Integrations via YAML'
id: doc:sdd-proposals-msagent-a2a-integrations-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Today, `IntegrationBotManager` can start Telegram, Slack, MS Teams, WhatsApp,
  and MS Agent SDK bots from `integrations_bots.yaml`. However, there is no way to
  expose an agent as an **A2A (Agent-to-Agent Protocol)** service or as an **MS Agent
  SDK** bot with full credential broker
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
- concept: mod:parrot.integrations.a2a
  rel: mentions
- concept: mod:parrot.integrations.manager
  rel: mentions
- concept: mod:parrot.integrations.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.wrapper
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Brainstorm: MSAgent & A2A Integrations via YAML

**Date**: 2026-07-09
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

Today, `IntegrationBotManager` can start Telegram, Slack, MS Teams, WhatsApp, and MS Agent SDK bots from `integrations_bots.yaml`. However, there is no way to expose an agent as an **A2A (Agent-to-Agent Protocol)** service or as an **MS Agent SDK** bot with full credential broker support purely from YAML config. The existing `msagentsdk` kind does not wire a `CredentialBroker`, and there is no `a2a` kind at all.

Operators currently need to write custom Python (like `examples/msagent/server.py`) to get A2A exposure, broker-backed credential resolution, OAuth2 SSO flows, or AgentCard discovery. This blocks production deployments that want declarative, zero-code agent surfacing.

**Who is affected**: Platform operators deploying agents, DevOps managing YAML configs, and downstream A2A clients consuming agent services.

## Constraints & Requirements

- Must work within the existing `IntegrationBotManager` dispatch pattern (config dataclass + `_start_*_bot()` method).
- A2A agents share the main aiohttp app by default; per-agent port override must be supported.
- A2A discovery requires in-process `AgentCard` registry exposed at `/.well-known/agent.json` and a `/directory` listing endpoint.
- MS Agent SDK kind must support full credential broker wiring (CredentialBroker, OAuth2 SSO, OBO flows).
- Must not break existing `msagentsdk`, `telegram`, `msteams`, `whatsapp`, or `slack` kinds.
- All new config lives in `ai-parrot-integrations` package.
- Credential broker for user credential acquisition (not agent-to-agent delegation).

---

## Options Explored

### Option A: Extend IntegrationBotManager with A2A + Enhanced MSAgentSDK Kinds

Add two new config dataclasses (`A2AAgentConfig`, `MSAgentConfig`) and their corresponding `_start_*_bot()` methods to `IntegrationBotManager`. The `a2a` kind wraps agents with `A2AServer`, mounts routes on the shared aiohttp app (with optional per-agent port), and registers AgentCards in an in-process `A2ADiscoveryRegistry`. The `msagent` kind (distinct from existing `msagentsdk`) wires the full credential broker + OAuth2 SSO + identity bridge pattern from `examples/msagent/server.py`.

✅ **Pros:**
- Follows the established dispatch pattern exactly — minimal conceptual overhead.
- Each kind has clear, focused responsibility.
- A2A and MSAgent can be mixed freely in the same YAML file.
- Backward-compatible: existing `msagentsdk` kind stays untouched.

❌ **Cons:**
- Two new config dataclasses to maintain.
- `msagent` vs `msagentsdk` naming could confuse operators (need clear docs).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot-server` | `A2AServer`, `A2ASecurityMiddleware` | Already exists |
| `ai-parrot-integrations` | `IntegrationBotManager`, `MSAgentSDKWrapper` | Already exists |
| `parrot.auth.broker` | `CredentialBroker`, `ProviderCredentialConfig` | Already exists |
| `parrot.auth.manifest` | `load_credentials_manifest()` — YAML credential loading | Already exists |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/a2a/server.py` — `A2AServer` class (wraps agent as A2A service)
- `packages/ai-parrot-server/src/parrot/a2a/security.py` — `A2ASecurityMiddleware`, `JWTAuthenticator`
- `packages/ai-parrot/src/parrot/a2a/models.py` — `AgentCard`, `AgentSkill`, `AgentCapabilities`
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` — `MSAgentSDKWrapper`
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` — `MSAgentSDKConfig`
- `packages/ai-parrot-integrations/src/parrot/integrations/models.py` — `IntegrationBotConfig.from_dict()`
- `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` — `IntegrationBotManager`
- `packages/ai-parrot/src/parrot/auth/broker.py` — `CredentialBroker.from_config()`
- `packages/ai-parrot/src/parrot/auth/credentials.py` — `ProviderCredentialConfig`
- `examples/msagent/server.py` — reference implementation for full broker + A2A wiring

---

### Option B: Plugin-Based Kind Registry (Dynamic Dispatch)

Replace the `if/elif` chain in `IntegrationBotConfig.from_dict()` and `IntegrationBotManager.startup()` with a registry pattern: each kind registers a `(config_class, start_callable)` tuple. New kinds (A2A, MSAgent) simply register themselves. This is a refactor-first approach.

✅ **Pros:**
- Eliminates the growing `if/elif` chain — more extensible.
- Third-party integrations could register their own kinds.
- Cleaner separation of concerns.

❌ **Cons:**
- Requires refactoring the existing dispatch in both `models.py` and `manager.py` first.
- Higher blast radius: touches all existing kinds even though they work fine.
- Plugin registration order / import timing can be tricky with lazy imports.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | Same | Plus refactoring of existing dispatch |

🔗 **Existing Code to Reuse:**
- Same as Option A, plus significant modification to `models.py` and `manager.py`.

---

### Option C: Unified "Surface" Abstraction Layer

Introduce an `AgentSurface` abstraction: each kind (`telegram`, `a2a`, `msagent`, etc.) implements a common `AgentSurface` interface with `setup()`, `start()`, `stop()`, and `get_routes()` methods. The YAML config maps to surfaces declaratively. A single agent can have multiple surfaces attached simultaneously from the same YAML block.

✅ **Pros:**
- Elegant long-term architecture — surfaces become first-class.
- A single agent entry can expose both A2A and MSAgent simultaneously.
- Lifecycle management (start/stop/health) becomes uniform.

❌ **Cons:**
- Very high effort — rewrites the entire integration layer.
- Over-engineered for the immediate need (2 new kinds).
- All existing integrations would need to be ported to the new interface.
- Risk of introducing regressions across all 5 existing integrations.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | Same | Plus new abstraction layer |

🔗 **Existing Code to Reuse:**
- Same as Option A, but most code would be refactored rather than reused.

---

## Recommendation

**Option A** is recommended because:

- It follows the established pattern that all 5 existing integrations use. The `if/elif` dispatch chain is pragmatic and works — adding 2 more branches is trivial.
- It has the smallest blast radius: existing `msagentsdk`, `telegram`, `slack`, `msteams`, and `whatsapp` kinds are untouched.
- The A2A server infrastructure (`A2AServer`, `AgentCard`, `A2ASecurityMiddleware`) and the credential broker (`CredentialBroker.from_config()`) already exist and just need to be wired into the YAML config path.
- The `msagent` kind is essentially a codification of the pattern already proven in `examples/msagent/server.py`.
- Option B's registry pattern is a good future refactor but isn't justified by adding just 2 kinds.
- Option C is over-engineered for the task at hand.

---

## Feature Description

### User-Facing Behavior

Operators add entries to `integrations_bots.yaml` with `kind: a2a` or `kind: msagent`:

**A2A example:**
```yaml
agents:
  Jirachi:
    kind: a2a
    chatbot_id: jirachi
    url: https://customer-support.internal:8181
    jwt_secret: "${A2A_JWT_SECRET}"
    tags:
      - general
      - assistant
    enable_credential_broker: true
    credentials:
      - provider: fireflies
        auth: static_key
        options:
          capture_url: "${CAPTURE_BASE_URL}/auth/fireflies/capture"
```

**MSAgent example:**
```yaml
agents:
  Jirachi:
    kind: msagent
    chatbot_id: jirachi
    url: "${CAPTURE_BASE_URL}"
    jwt_secret: "${JWT_SECRET}"
    welcome_message: "Hello! I'm Jirachi."
    microsoft_app_id: "${JIRACHI_MICROSOFT_APP_ID}"
    microsoft_app_password: "${JIRACHI_MICROSOFT_APP_PASSWORD}"
    microsoft_tenant_id: "${JIRACHI_MICROSOFT_TENANT_ID}"
    enable_credential_broker: true
    credentials:
      - provider: fireflies
        auth: static_key
      - provider: o365
        auth: oauth2
    o365_client_id: "${O365_CLIENT_ID}"
    o365_client_secret: "${O365_CLIENT_SECRET}"
    redirect_uri: "${CAPTURE_BASE_URL}/api/auth/oauth2/o365/callback"
    debug: true
```

On server startup, `IntegrationBotManager` reads the YAML file, creates the appropriate config, and for each agent:

- **`a2a`**: Creates an `A2AServer`, mounts it on the shared aiohttp app (or a dedicated port if specified), registers the `AgentCard` with the in-process discovery registry, and optionally wires security middleware (JWT, API key, mTLS).
- **`msagent`**: Creates an `MSAgentSDKWrapper` with a `CredentialBroker`, optional OAuth2 SSO setup, and optionally an `A2AServer` companion on the same app.

### Internal Behavior

**A2A kind flow:**
1. `IntegrationBotConfig.from_dict()` detects `kind: a2a` → creates `A2AAgentConfig`.
2. `IntegrationBotManager.startup()` matches `isinstance(config, A2AAgentConfig)` → calls `_start_a2a_bot()`.
3. `_start_a2a_bot()`:
   a. Resolves the parrot agent via `_get_agent(config.chatbot_id)`.
   b. Optionally builds a `CredentialBroker` from the `credentials` list in YAML.
   c. Creates `A2AServer(agent, base_path=..., tags=..., broker=...)`.
   d. Calls `a2a_server.setup(app, url=config.url)` to mount routes on the shared app.
   e. If `config.port` is set, creates a dedicated `aiohttp.TCPSite` on that port instead.
   f. Registers the `AgentCard` in the `A2ADiscoveryRegistry` (shared in-process dict exposed at `/directory`).
   g. Optionally wires `A2ASecurityMiddleware` (JWT secret, API key, etc.).

**MSAgent kind flow:**
1. `IntegrationBotConfig.from_dict()` detects `kind: msagent` → creates `MSAgentIntegrationConfig`.
2. `IntegrationBotManager.startup()` matches `isinstance(config, MSAgentIntegrationConfig)` → calls `_start_msagent_bot()`.
3. `_start_msagent_bot()`:
   a. Resolves the parrot agent via `_get_agent(config.chatbot_id)`.
   b. Builds a `CredentialBroker` from the YAML `credentials` list using `CredentialBroker.from_config()`.
   c. Optionally sets up O365 OAuth infrastructure (O365OAuthManager) if `o365_client_id` is present.
   d. Creates `MSAgentSDKConfig` from the YAML fields (reusing existing dataclass).
   e. Creates `MSAgentSDKWrapper(agent, config, app, broker=broker)`.
   f. Optionally creates a companion `A2AServer` on the same app (sharing the same broker).
   g. Wires suspend/resume stores (Redis-backed in production, in-memory for dev).

**Discovery registry (in-process):**
- A simple `Dict[str, AgentCard]` stored on the aiohttp app as `app["a2a_discovery_registry"]`.
- Exposed at `GET /a2a/directory` — returns a JSON array of all registered AgentCards.
- Each A2A agent's `GET /.well-known/agent.json` continues to work per-agent.
- Multi-agent discovery: the `/directory` endpoint aggregates all A2A agents registered on this server.

### Edge Cases & Error Handling

- **Missing chatbot_id**: Agent not found in BotManager → logged error, agent skipped.
- **Missing credentials for broker**: If `enable_credential_broker: true` but `credentials` is empty → broker is not created (no credential gating).
- **Port conflict**: If a per-agent port is already in use → startup fails with `OSError`, logged and skipped.
- **A2A + MSAgent for same agent**: Allowed — the A2A surface and MSAgent surface share the same parrot agent instance and credential broker. Each has its own routes.
- **Missing MS Agent SDK dependency**: `MSAgentIntegrationConfig` import guarded with `try/except ImportError` (same pattern as existing `MSAgentSDKConfig`).
- **Missing A2A server dependency**: `A2AServer` import guarded similarly (lives in `ai-parrot-server`).
- **Invalid YAML credentials**: `CredentialBroker.from_config(strict=False)` skips providers that fail to build.
- **No JWT secret for A2A**: Security middleware is not mounted → open access (logged as warning).

---

## Capabilities

### New Capabilities
- `a2a-yaml-integration`: Expose agents as A2A services from `integrations_bots.yaml` with `kind: a2a`.
- `msagent-yaml-integration`: Expose agents as MS Agent SDK bots with full credential broker from `integrations_bots.yaml` with `kind: msagent`.
- `a2a-discovery-registry`: In-process AgentCard registry with `/directory` endpoint for multi-agent discovery.

### Modified Capabilities
- `integration-bot-config`: Extended `IntegrationBotConfig.from_dict()` with two new kind branches.
- `integration-bot-manager`: Extended `IntegrationBotManager` with two new `_start_*_bot()` methods.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot.integrations.models` | extends | Add `A2AAgentConfig`, `MSAgentIntegrationConfig` imports + `elif` branches |
| `parrot.integrations.manager` | extends | Add `_start_a2a_bot()`, `_start_msagent_bot()`, new dict attributes |
| `parrot.a2a.server` (`ai-parrot-server`) | depends on | `A2AServer` used by `_start_a2a_bot()` |
| `parrot.a2a.security` (`ai-parrot-server`) | depends on | `A2ASecurityMiddleware` for JWT/API-key auth on A2A routes |
| `parrot.integrations.msagentsdk.wrapper` | depends on | `MSAgentSDKWrapper` used by `_start_msagent_bot()` |
| `parrot.auth.broker` | depends on | `CredentialBroker.from_config()` for YAML-declared credentials |
| `parrot.auth.credentials` | depends on | `ProviderCredentialConfig` for credential config parsing |

---

## Code Context

### User-Provided Code

```yaml
# Source: user-provided (A2A YAML example)
agents:
  Jirachi:
    kind: a2a
    chatbot_id: jirachi
    url: https://customer-support.internal:8181
    jwt-secret: "my-production-secret"
    welcome_message:
    tags:
      - general
      - assistant
    enable_credential_broker: true
```

```yaml
# Source: user-provided (MSAgent YAML example)
agents:
  Jirachi:
    kind: msagent
    chatbot_id: jirachi
    url:
    jwt-secret: "my-production-secret"
    welcome_message:
    tags:
      - general
      - assistant
    enable_credential_broker: true
    microsoft_app_id:
    microsoft_app_password:
    microsoft_tenant_id:
    redirect_uri:
    debug: true
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-server/src/parrot/a2a/server.py:50
class A2AServer:
    def __init__(
        self,
        agent: "AbstractBot",
        *,
        base_path: str = "/a2a",
        version: str = "1.0.0",
        capabilities: Optional[AgentCapabilities] = None,
        extra_skills: Optional[List[AgentSkill]] = None,
        tags: Optional[List[str]] = None,
        broker: Optional[Any] = None,
        identity_mapper: Optional[Any] = None,
        credential_resolvers: Optional[Dict[str, Any]] = None,
        suspended_store: Optional[Any] = None,
        audit_ledger: Optional[Any] = None,
    ):  # line 84

    def setup(self, app: web.Application, url: Optional[str] = None) -> None:  # line 171
    def get_agent_card(self) -> AgentCard:  # line 207
```

```python
# From packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py:63
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
```

```python
# From packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py:11
@dataclass
class MSAgentSDKConfig:
    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    api_key: Optional[str] = None
    api_key_header: str = "x-api-key"
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    kind: str = "msagentsdk"
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    endpoint: Optional[str] = None
    oauth_connections: Dict[str, str] = field(default_factory=dict)
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentSDKConfig":  # line 132
```

```python
# From packages/ai-parrot-integrations/src/parrot/integrations/models.py:17
@dataclass
class IntegrationBotConfig:
    agents: Dict[str, Union[...]] = field(default_factory=dict)  # line 36

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig':  # line 38
```

```python
# From packages/ai-parrot-integrations/src/parrot/integrations/manager.py:47
class IntegrationBotManager:
    def __init__(self, bot_manager: 'BotManager'):  # line 58
    async def _get_agent(self, chatbot_id: str, system_prompt_override: Optional[str] = None) -> Optional['AbstractBot']:  # line 118
    async def startup(self, extra_config: Optional[dict] = None) -> None:  # line 130
    async def _start_msagentsdk_bot(self, name: str, config: MSAgentSDKConfig) -> None:  # line 334
```

```python
# From packages/ai-parrot/src/parrot/auth/broker.py:326
class CredentialBroker:
    def __init__(self, *, audit_ledger=None, identity_mapper=None) -> None:  # line 362
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None:  # line 375
    @classmethod
    def from_config(cls, configs: List[ProviderCredentialConfig], strict: bool = True, **deps) -> "CredentialBroker":  # line 400
```

```python
# From packages/ai-parrot/src/parrot/auth/credentials.py:46
class ProviderCredentialConfig(BaseModel):
    provider: str
    auth: AuthKind  # Literal["obo", "oauth2", "static_key", "mcp", "device_code"]
    options: Dict[str, Any] = {}
```

```python
# From packages/ai-parrot/src/parrot/a2a/models.py:332
@dataclass
class AgentCard:
    name: str
    description: str
    version: str = "1.0.0"
    url: Optional[str] = None
    skills: List[AgentSkill] = field(default_factory=list)
    capabilities: Optional[AgentCapabilities] = None
    tags: List[str] = field(default_factory=list)
    # ... more fields
    def to_dict(self) -> Dict[str, Any]:  # line 353
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.a2a.server import A2AServer  # packages/ai-parrot-server/src/parrot/a2a/server.py
from parrot.a2a.models import AgentCard, AgentSkill, AgentCapabilities  # packages/ai-parrot/src/parrot/a2a/models.py
from parrot.a2a.security import A2ASecurityMiddleware  # packages/ai-parrot-server/src/parrot/a2a/security.py
from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper  # packages/ai-parrot-integrations
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig  # packages/ai-parrot-integrations
from parrot.auth.broker import CredentialBroker  # packages/ai-parrot/src/parrot/auth/broker.py
from parrot.auth.credentials import ProviderCredentialConfig  # packages/ai-parrot/src/parrot/auth/credentials.py
from parrot.auth.manifest import load_credentials_manifest  # packages/ai-parrot/src/parrot/auth/manifest.py
```

#### Key Attributes & Constants
- `A2AServer.base_path` → `str` (default `"/a2a"`) — packages/ai-parrot-server/src/parrot/a2a/server.py:130
- `A2AServer._tasks` → `Dict[str, Task]` — in-memory task store (line 137)
- `MSAgentSDKWrapper.routes` → `List[str]` — registered route paths
- `MSAgentSDKWrapper.m365_agent` → `ParrotM365Agent` — bridge instance
- `MSAgentSDKWrapper.adapter` → `CloudAdapter` — MS SDK adapter
- `IntegrationBotManager.bot_manager` → `BotManager` — parent manager reference (line 59)
- `IntegrationBotManager.msagentsdk_bots` → `Dict[str, MSAgentSDKWrapper]` (line 67)

### Does NOT Exist (Anti-Hallucination)
- ~~`A2AAgentConfig`~~ — does not exist yet; needs to be created
- ~~`MSAgentIntegrationConfig`~~ — does not exist yet; needs to be created
- ~~`IntegrationBotManager.a2a_bots`~~ — dict does not exist yet; needs to be added
- ~~`IntegrationBotManager.msagent_bots`~~ — dict does not exist yet; needs to be added
- ~~`IntegrationBotManager._start_a2a_bot()`~~ — method does not exist yet
- ~~`IntegrationBotManager._start_msagent_bot()`~~ — method does not exist yet
- ~~`A2ADiscoveryRegistry`~~ — does not exist yet; needs to be created (or use a simple dict on the app)
- ~~`parrot.a2a.server.A2AServer.setup_multi()`~~ — no multi-agent setup method exists
- ~~`parrot.integrations.a2a`~~ — no `a2a/` subpackage in integrations yet
- ~~`kind == 'a2a'` branch in `IntegrationBotConfig.from_dict()`~~ — does not exist
- ~~`kind == 'msagent'` branch in `IntegrationBotConfig.from_dict()`~~ — does not exist

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the A2A config + `_start_a2a_bot()` and the MSAgent config + `_start_msagent_bot()` are independent of each other. The discovery registry is a small shared piece but has no dependencies on either kind's implementation. Three independent work streams: (1) A2A config + startup, (2) MSAgent config + startup, (3) discovery registry.
- **Cross-feature independence**: No conflict with in-flight specs. The `models.py` and `manager.py` files are touched, but the changes are purely additive (new `elif` branches, new methods).
- **Recommended isolation**: `per-spec` — the tasks touch the same files (`models.py`, `manager.py`) and must be integrated sequentially to avoid merge conflicts.
- **Rationale**: While the A2A and MSAgent implementations are logically independent, they both modify `models.py` and `manager.py`. Sequential execution in one worktree avoids merge conflicts and keeps the feature branch coherent.

---

## Open Questions

- [x] Should the `/a2a/directory` endpoint list ALL agents (including non-A2A ones) or only agents with `kind: a2a`? — *Owner: Jesus*: A2A agents only. Only agents declared with `kind: a2a` appear in the `/directory` listing.
- [x] Should the `msagent` kind automatically mount a companion A2A surface (like `examples/msagent/server.py` does), or should this be opt-in via a flag like `enable_a2a_companion: true`? — *Owner: Jesus*: Auto (always on). Every `msagent` bot also gets an A2A endpoint, matching the example server behavior. The companion A2A surface also registers in `/directory`.
- [x] For A2A security: should the YAML support all auth schemes (JWT, API key, mTLS, HMAC) or start with JWT + API key only? — *Owner: Jesus*: All schemes from day one. Support JWT, API key, mTLS, HMAC, and Basic — everything `A2ASecurityMiddleware` already handles.
- [x] Should the credential broker's `credentials` list in YAML reuse the existing `load_credentials_manifest()` format, or should it be inlined directly in the agent config? — *Owner: Jesus*: Inline in agent config. The `credentials:` list lives directly under the agent entry in `integrations_bots.yaml` — simpler and self-contained.
