---
type: Wiki Overview
title: 'Feature Specification: Microsoft Copilot Agent SDK Integration'
id: doc:sdd-specs-microsoft-copilot-agent-sdk-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot agents are currently exposed through Telegram, MS Teams (via legacy
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.manager
  rel: mentions
- concept: mod:parrot.integrations.models
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Microsoft Copilot Agent SDK Integration

**Feature ID**: FEAT-259
**Date**: 2026-06-25
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor
**Proposal**: `sdd/proposals/microsoft-copilot-agent-sdk.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot agents are currently exposed through Telegram, MS Teams (via legacy
`botbuilder-*` SDK), WhatsApp, and Slack. There is no way to expose an ai-parrot
agent to **Microsoft Copilot Studio** — Microsoft's low-code agent orchestrator
that can route user requests to external agents.

The Microsoft 365 Agents SDK (v0.9.0, MIT, Python `microsoft_agents` namespace)
is the official successor to the `botbuilder-*` packages and the only supported
pathway to register a custom agent inside Copilot Studio.

### Goals

- Expose any ai-parrot `AbstractBot` as a Copilot Studio agent via the
  Microsoft 365 Agents SDK.
- Follow ai-parrot's existing integration wrapper pattern (config model +
  wrapper class + manager registration).
- Support Azure AD authentication for production deployments.
- Support anonymous auth for local development.
- Coexist with the existing `botbuilder`-based MS Teams integration on
  separate HTTP routes.

### Non-Goals (explicitly out of scope)

- Adaptive Card rendering for rich responses.
- Dialog/multi-turn form support via the SDK's dialog system.
- Streaming responses via the SDK's `StreamingResponse`.
- Proactive messaging.
- Migration of the existing `botbuilder`-based MS Teams integration to the new SDK.
- Tool results displayed as cards.
- Human-in-the-Loop bridging through the SDK.
- File/attachment handling.
- Registering `/api/messages` (Copilot Studio canonical route) — per-bot routes
  only; Copilot Studio endpoint mapping is documented for reverse-proxy config.

---

## 2. Architectural Design

### Overview

The integration consists of two main classes:

1. **`ParrotM365Agent`** — A thin bridge that implements the MS Agent SDK's
   `Agent` protocol (single `on_turn(context: TurnContext)` method). It
   extracts text/user/session from the Activity envelope, calls
   `parrot_agent.ask()`, and sends the AIMessage content back via
   `context.send_activity()`.

2. **`MSAgentSDKWrapper`** — The standard ai-parrot integration wrapper that
   owns the `CloudAdapter`, creates the bridge, registers the HTTP route on
   the aiohttp app, and handles auth configuration.

### Component Diagram

```
Copilot Studio / Teams / Webchat
        │
        ▼  POST /api/msagentsdk/{safe_id}/messages  (Activity JSON + JWT)
        │
[ai-parrot aiohttp server]
        │
        ▼  MSAgentSDKWrapper.handle_request()
        │
        ▼  CloudAdapter.process(request, parrot_m365_agent)
        │       ├─ JWT validation (Azure AD) or anonymous passthrough
        │       └─ Activity.model_validate(body)
        │
        ▼  ParrotM365Agent.on_turn(context: TurnContext)
        │   ├─ activity.type == "message" → agent.ask(text, session_id, user_id)
        │   ├─ activity.type == "conversationUpdate" → welcome message
        │   └─ activity.type == "typing" → ignored
        │
        ▼  context.send_activity(response.content)
        │
        ▼  CloudAdapter → ConnectorClient → channel callback
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.ask()` | calls | Bridge calls `ask(question, session_id, user_id)` → `AIMessage` |
| `IntegrationBotManager` | extends | Add `_start_msagentsdk_bot()` + dict for active bots |
| `IntegrationBotConfig.from_dict()` | extends | Add `kind: msagentsdk` dispatch |
| `aiohttp.web.Application` | uses | Register per-bot HTTP route |
| `BotManager.get_app()` | uses | Get aiohttp app for route registration |
| `BotManager.get_bot()` | uses | Resolve ai-parrot agent by `chatbot_id` |

### Data Models

```python
# MSAgentSDKConfig — follows WhatsAppAgentConfig pattern
@dataclass
class MSAgentSDKConfig:
    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    kind: str = "msagentsdk"
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
```

### New Public Interfaces

```python
class ParrotM365Agent:
    """Bridges ai-parrot AbstractBot to the MS 365 Agent protocol."""
    def __init__(self, parrot_agent: AbstractBot): ...
    async def on_turn(self, context: TurnContext) -> None: ...

class MSAgentSDKWrapper:
    """ai-parrot integration wrapper for Microsoft 365 Agents SDK."""
    def __init__(
        self,
        agent: AbstractBot,
        config: MSAgentSDKConfig,
        app: web.Application,
    ): ...
    async def handle_request(self, request: web.Request) -> web.Response: ...
```

---

## 3. Module Breakdown

### Module 1: Config Model (`msagentsdk/models.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py`
- **Responsibility**: `MSAgentSDKConfig` dataclass with Azure AD fields and env
  var fallback (following `WhatsAppAgentConfig` pattern).
- **Depends on**: `navconfig.config` for env var resolution.

### Module 2: Bridge Agent (`msagentsdk/agent.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
- **Responsibility**: `ParrotM365Agent` class implementing the MS Agent SDK
  `Agent` protocol. Maps `Activity` → `agent.ask()` → `send_activity()`.
  Handles `message`, `conversationUpdate`, and `typing` activity types.
- **Depends on**: `microsoft_agents.hosting.core.TurnContext`,
  `microsoft_agents.activity.Activity`, `parrot.bots.abstract.AbstractBot`.

### Module 3: Integration Wrapper (`msagentsdk/wrapper.py`)

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py`
- **Responsibility**: `MSAgentSDKWrapper` class that creates the `CloudAdapter`,
  instantiates `ParrotM365Agent`, registers the HTTP route, configures auth,
  and exposes `handle_request()`.
- **Depends on**: Module 1 (config), Module 2 (bridge),
  `microsoft_agents.hosting.aiohttp.CloudAdapter`.

### Module 4: Manager Registration

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/models.py`
  and `manager.py`
- **Responsibility**: Add `MSAgentSDKConfig` import + `kind == 'msagentsdk'`
  dispatch in `IntegrationBotConfig.from_dict()`. Add
  `_start_msagentsdk_bot()` method and `msagentsdk_bots` dict in
  `IntegrationBotManager`. Update `shutdown()` to stop SDK bots.
- **Depends on**: Modules 1, 3.

### Module 5: Package Init + Dependencies

- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py`
  and `packages/ai-parrot-integrations/pyproject.toml`
- **Responsibility**: Package `__init__.py` with lazy exports. Add
  `msagentsdk` extras group to `pyproject.toml`:
  `microsoft-agents-hosting-aiohttp~=0.9.0`.
- **Depends on**: None.

### Module 6: Tests

- **Path**: `tests/integrations/test_msagentsdk/`
- **Responsibility**: Unit tests for config model, bridge agent, and wrapper.
  Integration test fixtures with mocked `TurnContext` and `Activity`.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_config_from_dict` | Module 1 | Validates config creation from YAML dict |
| `test_config_env_fallback` | Module 1 | Verifies env var resolution for credentials |
| `test_config_anonymous_auth` | Module 1 | Validates anonymous_auth flag handling |
| `test_bridge_message_activity` | Module 2 | Message activity routes to `agent.ask()` |
| `test_bridge_conversation_update` | Module 2 | Welcome message sent on member add |
| `test_bridge_empty_text` | Module 2 | Empty/None text activity is handled gracefully |
| `test_bridge_unknown_activity_type` | Module 2 | Unknown activity types are ignored |
| `test_wrapper_route_registration` | Module 3 | HTTP route registered on aiohttp app |
| `test_wrapper_handle_request` | Module 3 | Request flows through adapter to bridge |
| `test_manager_dispatch` | Module 4 | `kind: msagentsdk` creates `MSAgentSDKConfig` |
| `test_manager_start_bot` | Module 4 | `_start_msagentsdk_bot` wires wrapper correctly |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_message` | POST Activity JSON → wrapper → mock agent → response |
| `test_auth_rejected` | Invalid JWT returns 401 (requires non-anonymous config) |

### Test Data / Fixtures

```python
@pytest.fixture
def msagentsdk_config():
    return MSAgentSDKConfig(
        name="TestCopilotBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
    )

@pytest.fixture
def mock_activity():
    """A minimal MS Agent SDK Activity for message type."""
    return {
        "type": "message",
        "text": "Hello, agent!",
        "from": {"id": "user-123", "name": "Test User"},
        "conversation": {"id": "conv-456"},
        "channelId": "webchat",
        "serviceUrl": "https://smba.trafficmanager.net/teams/",
        "id": "activity-789",
    }
```

---

## 5. Acceptance Criteria

- [ ] `MSAgentSDKConfig` parses from YAML dict with env var fallback for
      credentials (client_id, client_secret, tenant_id).
- [ ] `ParrotM365Agent.on_turn()` correctly routes `message` activities to
      `agent.ask()` and sends the response back via `context.send_activity()`.
- [ ] `MSAgentSDKWrapper` registers per-bot route at
      `/api/msagentsdk/{safe_id}/messages` on the aiohttp app.
- [ ] `IntegrationBotConfig.from_dict()` handles `kind: msagentsdk` and
      produces an `MSAgentSDKConfig` instance.
- [ ] `IntegrationBotManager._start_msagentsdk_bot()` resolves the agent,
      creates the wrapper, and stores it in `msagentsdk_bots`.
- [ ] `IntegrationBotManager.shutdown()` cleans up SDK bots.
- [ ] All unit tests pass: `pytest tests/integrations/test_msagentsdk/ -v`
- [ ] No breaking changes to existing integrations (Telegram, MS Teams,
      WhatsApp, Slack all still start correctly).
- [ ] `microsoft-agents-hosting-aiohttp` is an optional dependency under the
      `msagentsdk` extras group in `pyproject.toml`.
- [ ] SDK imports are lazy (inside methods/functions) so the package can be
      imported without `microsoft-agents-*` installed.
- [ ] Anonymous auth mode works for local development (no Azure AD required).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot  # verified: packages/ai-parrot/src/parrot/bots/abstract.py:156
from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:72

# Integration config models
from parrot.integrations.models import IntegrationBotConfig  # verified: models.py:13
from parrot.integrations.models import TelegramAgentConfig   # verified: models.py:6
from parrot.integrations.models import MSTeamsAgentConfig     # verified: models.py:7
from parrot.integrations.models import WhatsAppAgentConfig    # verified: models.py:8
from parrot.integrations.models import SlackAgentConfig       # verified: models.py:9

# Manager
from parrot.integrations.manager import IntegrationBotManager  # verified: manager.py:45

# navconfig for env vars (used by all config models)
from navconfig import config  # verified: used in msteams/models.py:6, whatsapp/models.py:6
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # line 156
    @abstractmethod
    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        search_type: str = 'similarity',
        search_kwargs: dict = None,
        metric_type: str = 'COSINE',
        use_vector_context: bool = True,
        use_conversation_history: bool = True,
        return_sources: bool = True,
        memory: Optional[Callable] = None,
        ensemble_config: dict = None,
        ctx: Optional[RequestContext] = None,
        structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        format_kwargs: dict = None,
        use_tools: bool = True,
        trace_context: Optional[TraceContext] = None,
        **kwargs
    ) -> AIMessage:  # line 3693–3713

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    input: str              # line 76
    output: Any             # line 79 — the main response content
    response: Optional[str] # line 82
    model: str              # line 111
    provider: str           # line 114
    usage: CompletionUsage  # line 118
    @property
    def content(self) -> Any:  # line 227 — alias for self.output
        return self.output

# packages/ai-parrot-integrations/src/parrot/integrations/models.py
class IntegrationBotConfig:  # line 13
    agents: Dict[str, Union[TelegramAgentConfig, MSTeamsAgentConfig, WhatsAppAgentConfig, SlackAgentConfig]]  # line 32
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig':  # line 35
        # kind dispatch at lines 46–53

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
class IntegrationBotManager:  # line 45
    def __init__(self, bot_manager: 'BotManager'):  # line 55
    self.telegram_bots: Dict  # line 60
    self.msteams_bots: Dict   # line 61
    self.whatsapp_bots: Dict  # line 62
    self.slack_bots: Dict     # line 63
    async def _get_agent(self, chatbot_id: str, system_prompt_override: Optional[str] = None) -> Optional['AbstractBot']:  # line 114
    async def startup(self, extra_config: Optional[dict] = None) -> None:  # line 126
    async def shutdown(self) -> None:  # line 413

# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/models.py (REFERENCE PATTERN)
@dataclass
class WhatsAppAgentConfig:  # line 10
    name: str               # line 31
    chatbot_id: str          # line 32
    phone_id: Optional[str]  # line 33
    kind: str = "whatsapp"   # line 38
    system_prompt_override: Optional[str] = None  # line 41
    def __post_init__(self):  # line 47 — env var fallback pattern
        prefix = self.name.upper()
        if not self.phone_id:
            self.phone_id = config.get(f"{prefix}_WHATSAPP_PHONE_ID")

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py (REFERENCE PATTERN)
@dataclass
class MSTeamsAgentConfig:  # line 13
    name: str                      # line 28
    chatbot_id: str                # line 29
    client_id: Optional[str]       # line 30
    client_secret: Optional[str]   # line 31
    app_type: str = "MultiTenant"  # line 32
    kind: str = "msteams"          # line 34
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MSAgentSDKConfig` | `IntegrationBotConfig.from_dict()` | `kind == 'msagentsdk'` dispatch | `models.py:45-53` |
| `MSAgentSDKWrapper` | `aiohttp.web.Application` | `app.router.add_post()` | pattern at `manager.py:270` (Teams) |
| `ParrotM365Agent` | `AbstractBot.ask()` | `await self.parrot_agent.ask(text, session_id, user_id)` | `abstract.py:3693` |
| `ParrotM365Agent` | `AIMessage.content` | property access on ask() return | `responses.py:227` |
| `IntegrationBotManager._start_msagentsdk_bot` | `BotManager.get_bot()` via `_get_agent()` | method call | `manager.py:114` |
| `MSAgentSDKWrapper` | `BotManager.get_app()` | method call for aiohttp app | `manager.py:1338` |

### Configuration References

```yaml
# integrations_bots.yaml — add alongside existing agents
agents:
  CopilotBot:
    kind: msagentsdk
    chatbot_id: main_agent
    client_id: "${MICROSOFT_APP_ID}"
    client_secret: "${MICROSOFT_APP_PASSWORD}"
    tenant_id: "${MICROSOFT_TENANT_ID}"
    anonymous_auth: false
    welcome_message: "Hello! I'm ready to help."
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.integrations.msagentsdk`~~ — does not exist yet, this feature creates it
- ~~`parrot.integrations.base.AbstractIntegration`~~ — there is no abstract base class for integrations; the wrapper pattern is implicit
- ~~`AbstractBot.process()`~~ — not a real method; use `ask()` instead
- ~~`AbstractBot.chat()`~~ — not a real method; use `ask()` instead
- ~~`AbstractBot.run()`~~ — not a real method; use `ask()` instead
- ~~`AIMessage.text`~~ — not a real attribute; use `.content` property (alias for `.output`)
- ~~`AIMessage.metadata`~~ — not a real attribute; use `.usage`, `.model`, `.provider` etc.
- ~~`IntegrationBotManager.register_bot()`~~ — not a real method; bots are added in `_start_*` methods
- ~~`from microsoft_agents import Agent`~~ — wrong import path; correct is `from microsoft_agents.hosting.core import TurnContext`
- ~~`from microsoft.agents import *`~~ — old namespace; SDK now uses `microsoft_agents` (underscores)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Config model**: Follow `WhatsAppAgentConfig` pattern (dataclass, `__post_init__`
  for env var fallback, `from_dict` classmethod). Reference:
  `packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/models.py:10-60`.
- **Wrapper lifecycle**: Follow `_start_whatsapp_bot` pattern (simplest existing
  integration). Reference: `manager.py:312-325`.
- **Lazy imports**: All `microsoft_agents.*` imports must be inside functions/methods
  (not module-level), following the pattern used by Telegram (`from aiogram import Bot`
  inside `_start_telegram_bot`, manager.py:180).
- **Auth exclusion**: Register the webhook route with the auth middleware exclusion
  list if available (`auth.add_exclude_list(self.route)`).
- **Logging**: Use `navconfig.logging.logging.getLogger()`.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| SDK is pre-1.0 (v0.9.0); namespace changed once | Pin `~=0.9.0`, isolate imports behind lazy loading |
| `invoke` activities require synchronous HTTP response | Return typing indicator; add timeout on `agent.ask()` |
| `CloudAdapter.process()` signature may not match aiohttp `Request` | SDK provides `microsoft_agents.hosting.aiohttp.CloudAdapter` specifically for aiohttp |
| Dependency bloat (azure-core, opentelemetry) | Optional extras only; not pulled by default install |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `microsoft-agents-hosting-aiohttp` | `~=0.9.0` | Core SDK + aiohttp adapter + auth |

Transitively installs: `microsoft-agents-hosting-core`,
`microsoft-agents-activity`, `pyjwt`, `azure-core`, `opentelemetry-api/sdk`.

---

## 8. Open Questions

- [x] **Azure AD credentials availability** — *Resolved in proposal*: Credentials
  are available; no new Azure AD setup needed.
- [x] **SDK version pinning strategy** — *Resolved in proposal*: Use `~=0.9.0`
  (accept patches, reject minor bumps).
- [x] **Dual-registration concern** — *Resolved in proposal*: Use per-bot routes
  only (`/api/msagentsdk/{safe_id}/messages`). Document reverse-proxy mapping
  for Copilot Studio's `/api/messages` expectation.
- [ ] **Copilot Studio agent description** — How should the agent's description
  be configured for Copilot Studio's orchestrator routing? Via config YAML field
  or derived from the ai-parrot bot definition? (Can be decided during implementation.)

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Small scope (~500-700 lines), all modules depend linearly
  (config → bridge → wrapper → manager → tests). No parallelism benefit.
- **Cross-feature dependencies**: None. This is a standalone new integration.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-25 | Jesus Lara / Claude | Initial draft from FEAT-259 proposal |
