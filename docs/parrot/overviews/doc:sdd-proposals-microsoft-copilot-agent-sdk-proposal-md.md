---
type: Wiki Overview
title: 'FEAT-259: Microsoft Copilot Agent SDK Integration'
id: doc:sdd-proposals-microsoft-copilot-agent-sdk-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Investigate whether ai-parrot agents can be exposed as **Copilot Studio agents**
---

---
id: FEAT-259
title: "Expose ai-parrot Agents as Copilot Studio Agents via Microsoft 365 Agents SDK"
type: feature
mode: investigation
status: discussion
source:
  kind: inline
  jira_key: null
base_branch: dev
confidence: high
research_state: sdd/state/FEAT-259/
---

# FEAT-259: Microsoft Copilot Agent SDK Integration

## 0. Origin

Investigate whether ai-parrot agents can be exposed as **Copilot Studio agents**
using the [Microsoft 365 Agents SDK for Python](https://github.com/microsoft/Agents-for-python).
If feasible, design an integration that follows ai-parrot's existing integration
wrapper pattern.

**Key URLs:**
- SDK docs: https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/quickstart?pivots=python
- Python repo: https://github.com/microsoft/Agents-for-python (MIT, v0.9.0)
- Copilot Studio: https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-microsoft-365-agents-sdk-agent

---

## 1. Synthesis Summary

### Feasibility Verdict: YES — High Confidence

Exposing an ai-parrot agent as a Copilot Studio agent via the Microsoft 365
Agents SDK is **feasible and architecturally well-aligned**. The integration
surface is small (a single-method `Agent` protocol), and both frameworks share
the same async/aiohttp/Pydantic stack.

### Why This Works

| Factor | ai-parrot | MS Agent SDK | Compatibility |
|--------|-----------|-------------|---------------|
| Async model | async/await throughout | async/await throughout | Native match |
| HTTP framework | aiohttp | aiohttp (primary) | Same framework |
| Data models | Pydantic v2 | Pydantic v2 | Same library |
| Agent contract | `agent.ask(text, session_id, user_id) → AIMessage` | `agent.on_turn(context: TurnContext)` | Thin bridge needed |
| Existing pattern | Wrapper classes per platform | `Agent` protocol or `ActivityHandler` subclass | Follows existing pattern |

### Core Insight

The Microsoft 365 Agents SDK defines a minimal protocol:

```python
class Agent(Protocol):
    async def on_turn(self, context: TurnContext): ...
```

The adapter only needs to:
1. Extract `text`, `user_id`, `conversation_id` from `TurnContext.activity`
2. Call `parrot_agent.ask(text, session_id=conversation_id, user_id=user_id)`
3. Send the `AIMessage.content` back via `context.send_activity()`

This is the **same bridge** every existing ai-parrot integration performs —
the only difference is the inbound/outbound message envelope format.

---

## 2. Codebase Findings

### 2.1 Localization — Where the New Code Lives

| Path | Purpose | Evidence |
|------|---------|----------|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/` | New integration package | Follows existing pattern: `msteams/`, `slack/`, `whatsapp/` [F003] |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py` | Main adapter: `MSAgentSDKWrapper` | All integrations have a wrapper.py [F003] |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` | `MSAgentSDKConfig` dataclass | Config model per platform [F003] |
| `packages/ai-parrot-integrations/src/parrot/integrations/models.py` | Add `kind: msagentsdk` dispatch | Central config dispatch [F003] |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | Add `_start_msagentsdk_bot()` | Manager startup per platform [F003] |

### 2.2 Relationship to Existing MS Teams Integration

The current MS Teams integration (`integrations/msteams/`) uses the **legacy
`botbuilder-*` packages** (Bot Framework SDK v4). The Microsoft 365 Agents SDK
(`microsoft-agents-*` v0.9.0) is its **official successor** with:

- Same Activity model (now Pydantic v2 instead of custom serialization)
- Same ActivityHandler dispatch pattern (modernized)
- New `AgentApplication` decorator approach
- Cleaner auth API (same Azure AD underneath)
- Built-in Copilot Studio connectivity [F004]

**Coexistence**: Both integrations can run simultaneously on different HTTP
routes. The new SDK integration targets Copilot Studio specifically, while the
existing botbuilder integration continues serving direct Teams channel
deployments.

**Future migration path**: Eventually the botbuilder-based MS Teams integration
could be migrated to the new SDK, but that is OUT OF SCOPE for this feature.

### 2.3 Constraints Identified

1. **Azure AD required for production** — Copilot Studio requires Azure AD App
   Registration + Azure Bot Service resource. Local development can use
   anonymous auth. [F002]

2. **Endpoint convention** — The SDK and Copilot Studio expect `POST /api/messages`.
   ai-parrot's existing integrations use `/api/{platform}/{safe_id}/messages`.
   The wrapper should register BOTH routes for compatibility. [F002, F003]

3. **Pre-1.0 SDK** — v0.9.0 is pre-release. The namespace already changed once
   (from `microsoft.agents` to `microsoft_agents`). Pin version in dependencies
   and isolate imports. [F001]

4. **Invoke activities require synchronous responses** — Some Activity types
   (`invoke`) require the HTTP response to contain the result. Long-running
   ai-parrot agent processing may need timeout handling. [F002]

---

## 3. Proposed Architecture

### 3.1 High-Level Design

```
Copilot Studio / Teams / Webchat
        │
        ▼  POST /api/messages (Activity JSON + JWT)
        │
[ai-parrot aiohttp server]
        │
        ▼  MSAgentSDKWrapper.handle_request()
        │
        ▼  CloudAdapter.process(request, parrot_m365_agent)
        │
        ▼  ParrotM365Agent.on_turn(context: TurnContext)
        │   ├─ Extract text, user_id, conversation_id from Activity
        │   ├─ await parrot_agent.ask(text, session_id, user_id)
        │   ├─ Format AIMessage → Activity response
        │   └─ await context.send_activity(response)
        │
        ▼  Response flows back through CloudAdapter → ConnectorClient
```

### 3.2 Implementation Approach: Two Classes

#### `ParrotM365Agent` — The Bridge (implements MS Agent Protocol)

```python
from microsoft_agents.hosting.core import TurnContext

class ParrotM365Agent:
    """Bridges ai-parrot AbstractBot to the MS 365 Agent protocol."""
    
    def __init__(self, parrot_agent: AbstractBot):
        self.parrot_agent = parrot_agent
    
    async def on_turn(self, context: TurnContext):
        activity = context.activity
        if activity.type == "message" and activity.text:
            user_id = activity.from_property.id if activity.from_property else None
            session_id = activity.conversation.id if activity.conversation else None
            
            response = await self.parrot_agent.ask(
                question=activity.text,
                session_id=session_id,
                user_id=user_id,
            )
            await context.send_activity(str(response.content))
        
        elif activity.type == "conversationUpdate":
            # Welcome new members
            if activity.members_added:
                await context.send_activity("Hello! I'm ready to help.")
```

#### `MSAgentSDKWrapper` — The Integration Wrapper

Follows the standard ai-parrot integration pattern:

```python
class MSAgentSDKWrapper:
    """ai-parrot integration wrapper for Microsoft 365 Agents SDK."""
    
    def __init__(self, agent: AbstractBot, config: MSAgentSDKConfig, app: web.Application):
        self.agent = agent
        self.config = config
        self.app = app
        
        # Create MS SDK components
        self.m365_agent = ParrotM365Agent(agent)
        self.adapter = CloudAdapter(auth_config=config.auth_configuration)
        
        # Register HTTP route
        safe_id = config.name.replace(" ", "_").lower()
        self.route = f"/api/msagentsdk/{safe_id}/messages"
        self.app.router.add_post(self.route, self.handle_request)
        # Also register canonical /api/messages for Copilot Studio
        self.app.router.add_post(f"/api/messages", self.handle_request)
    
    async def handle_request(self, request: web.Request) -> web.Response:
        return await self.adapter.process(request, self.m365_agent)
```

### 3.3 Configuration

```yaml
# integrations_bots.yaml
agents:
  CopilotAgent:
    kind: msagentsdk
    chatbot_id: main_agent              # ai-parrot bot ID
    client_id: "${MICROSOFT_APP_ID}"    # Azure AD App Registration
    client_secret: "${MICROSOFT_APP_PASSWORD}"
    tenant_id: "${MICROSOFT_TENANT_ID}"
    anonymous_auth: false               # true for local dev
```

### 3.4 Scope Boundaries

**In scope:**
- `MSAgentSDKWrapper` integration class (wrapper + bridge)
- `MSAgentSDKConfig` config model
- Manager registration (`_start_msagentsdk_bot`)
- Config dispatch for `kind: msagentsdk`
- Azure AD authentication support
- Basic message handling (text in → text out)
- Conversation update handling (welcome messages)
- Typing indicator support

**Out of scope (future work):**
- Adaptive Card rendering for rich responses
- Dialog/multi-turn form support via SDK's dialog system
- Streaming responses (SDK's `StreamingResponse`)
- Proactive messaging
- Migration of existing botbuilder-based MS Teams integration
- Tool results displayed as cards
- Human-in-the-Loop bridging
- File/attachment handling

---

## 4. Confidence Map

| Claim | Confidence | Evidence |
|-------|-----------|----------|
| MS Agent SDK `Agent` protocol is a single-method interface | **High** | Directly verified in SDK source [F001] |
| ai-parrot's `agent.ask()` is the universal entry point for integrations | **High** | Verified across 5 existing integrations [F003] |
| Both frameworks use aiohttp + Pydantic v2 + async/await | **High** | Verified in both SDK and ai-parrot [F001, F003] |
| CloudAdapter can integrate with ai-parrot's aiohttp Application | **High** | SDK provides `CloudAdapter.process(request, agent)` [F002] |
| Copilot Studio can connect to any `/api/messages` endpoint | **High** | Documented in MS docs [F002] |
| Existing botbuilder MS Teams integration can coexist | **High** | Different routes, different packages [F004] |
| SDK v0.9.0 is stable enough for production use | **Medium** | Pre-1.0, one known breaking namespace change [F001] |
| Anonymous auth works for local development | **Medium** | Documented but not personally verified [F002] |
| `invoke` activity timeout won't be a problem | **Low** | Depends on ai-parrot agent response time; needs testing |

---

## 5. Open Questions

### Resolved by Research

- [x] **Q: Is the SDK compatible with ai-parrot's stack?** — Yes: same aiohttp + Pydantic v2 + async/await.
- [x] **Q: How complex is the adapter?** — Minimal: single `on_turn` method, bridge `Activity.text` → `agent.ask()` → `send_activity()`.
- [x] **Q: Can it coexist with the existing MS Teams integration?** — Yes: different packages, different HTTP routes.
- [x] **Q: What's needed for Copilot Studio?** — Public HTTPS endpoint at `/api/messages` + Azure AD credentials.

### Unresolved (User Input Needed)

- [ ] **U1: Azure AD credentials availability** — Do we have an Azure AD App
  Registration and Azure Bot Service resource, or do they need to be created?
  This affects the deployment guide scope.

- [ ] **U2: SDK version pinning strategy** — The SDK is v0.9.0 (pre-1.0).
  Should we pin to `~=0.9.0` and accept patch updates, or pin exactly to
  `==0.9.0`? There's been one namespace-breaking change already.

- [ ] **U3: Dual-registration concern** — Registering `/api/messages` (Copilot
  Studio convention) alongside `/api/msagentsdk/{id}/messages` (ai-parrot
  convention) could conflict if multiple MS Agent SDK bots are configured.
  Should we only register the platform-specific route and document the Copilot
  Studio endpoint mapping separately?

---

## 6. Dependencies

### New PyPI Dependencies

```
microsoft-agents-hosting-aiohttp>=0.9.0,<1.0
```

This transitively installs:
- `microsoft-agents-hosting-core`
- `microsoft-agents-activity`
- `pyjwt`
- `azure-core`
- `opentelemetry-api` / `opentelemetry-sdk`

### Impact Assessment

These dependencies should be **optional** (extras in `pyproject.toml`), following
the pattern used for other integrations. Install with:

```bash
uv pip install ai-parrot-integrations[msagentsdk]
```

---

## 7. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| SDK breaking changes (pre-1.0) | Medium | Pin version, isolate imports behind lazy loading |
| Azure AD setup complexity | Low | Document step-by-step; most Teams-using orgs already have this |
| `invoke` activity timeout for long-running agents | Low | Return typing indicator, handle timeouts gracefully |
| Dependency bloat (azure-core, opentelemetry) | Low | Optional extras, not pulled in by default |
| `/api/messages` route conflict | Low | Use per-bot routes; document Copilot Studio proxy config |

---

## 8. Estimated Scope

| Component | Effort |
|-----------|--------|
| `MSAgentSDKConfig` model | Small (1 file) |
| `ParrotM365Agent` bridge class | Small (1 file, ~80 lines) |
| `MSAgentSDKWrapper` integration class | Medium (1 file, ~150 lines) |
| Manager registration | Small (2 files, ~20 lines each) |
| Config dispatch | Small (1 file, ~5 lines) |
| Tests | Medium (unit + integration test fixtures) |
| Documentation | Small (config example + Copilot Studio setup guide) |

**Total estimate**: 3-5 tasks, ~500-700 lines of new code.

---

## 9. Research Audit

| Metric | Value |
|--------|-------|
| Findings | 4 (F001–F004) |
| External URLs fetched | 3 |
| Files read (codebase) | ~40 |
| Greps executed | ~25 |
| Overall confidence | High |
| Truncated | No |
| State directory | `sdd/state/FEAT-259/` |

---

## 10. Recommended Next Step

```
→ /sdd-spec FEAT-259
  Rationale: High-confidence localization, clear architecture, small surface area.
  The proposal is detailed enough to decompose directly into a spec.
```

**Alternatives:**
- `/sdd-brainstorm FEAT-259` — if you want to explore alternative adapter
  designs (e.g., using `AgentApplication` decorator pattern instead of raw
  `Agent` protocol)
- `/sdd-task` directly — the scope is small enough that a spec might be
  unnecessary for a senior engineer familiar with the integration pattern
