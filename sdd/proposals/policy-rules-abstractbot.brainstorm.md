# Brainstorm: Policy Rules on AbstractBot — Declarative PBAC for Agents & Tools

**Date**: 2026-04-15
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: C
**Parent Brainstorm**: `sdd/proposals/policy-based-access-control.brainstorm.md` (Option D — Hybrid)

---

## Problem Statement

The prior PBAC brainstorm (Option D — Hybrid) established the architecture for integrating
navigator-auth's PBAC engine into ai-parrot. This brainstorm addresses the **next layer**:
how individual bots declare, register, and enforce their own policy rules.

Currently:
1. **`AbstractBot.retrieval()`** (abstract.py:2214-2296) uses a legacy `_permissions` dict
   with hardcoded RBAC checks (users, groups, job_codes, programs, organizations). This
   must be **replaced entirely** with PBAC evaluation via the PDP.
2. **`ChatbotHandler`** (bots.py:454-498) lists/returns agents without any policy filtering.
   Users see all agents regardless of authorization.
3. **`ToolList`** (bots.py:1010-1041) returns all discovered tools globally with no
   policy-based filtering.
4. **No declarative policy API** — bots cannot declare their own access rules in code,
   YAML config, or at registration time. Policies exist only as standalone YAML files
   in the `policies/` directory.
5. **`AgentRegistry`** (registry.py:315-329) has no access to the aiohttp `Application`,
   so it cannot register policies with the PDP at registration time.

**Who is affected:**
- **Developers** writing agents: need a simple way to declare "this agent requires group X"
  directly in code or YAML config, without editing standalone policy files.
- **Operators**: need per-agent policy files that are auto-loaded alongside the agent.
- **End users**: should only see agents and tools they're authorized to access.

## Constraints & Requirements

- Replace `_permissions` dict entirely — no backward-compatible fallback needed (no bots
  currently use it in production).
- Single enforcement point for agent access: `retrieval()` delegates to PDP's
  `evaluator.check_access()`.
- `ChatbotHandler` filters bot listings using `evaluator.filter_resources()` (batch) and
  `check_access()` (single) — it gets PDP from `request.app['abac']`.
- `ToolList` filters globally using `evaluator.filter_resources(ResourceType.TOOL, ...)`.
- Declarative policy rules must be simple (allow/deny + action + roles/groups) but designed
  for future extensibility to full PBAC conditions (time, IP, attributes).
- `AgentRegistry` must receive the aiohttp `Application` at setup time so policy rules
  declared on bots can be registered with the PDP.
- Per-agent YAML policy files (`policies/agents/<agent-name>.yaml`) auto-loaded alongside
  the agent.
- Programmatic policy declaration via class attribute, method override, and BotConfig YAML.
- navigator-auth ABAC Rust backend bug is fixed — PBAC can be re-enabled in `app.py`.

---

## Options Explored

### Option A: Minimal — PBAC in retrieval() + Handler Filtering Only

Replace the legacy `_permissions` logic in `retrieval()` with a single
`evaluator.check_access(ResourceType.AGENT, self.name, "agent:chat")` call. Add
`evaluator.filter_resources()` calls in `ChatbotHandler` and `ToolList`. No declarative
policy API on AbstractBot — all policies remain in standalone YAML files.

Pros:
- Smallest change surface — only modifies `retrieval()`, `ChatbotHandler`, and `ToolList`.
- No new abstractions or registration plumbing.
- Policies managed entirely via YAML files — single source of truth.

Cons:
- Developers must hand-write YAML policy files for every new agent — no code-level
  declaration.
- No connection between agent code and its required policies — easy to forget.
- `AgentRegistry` unchanged — no `app` reference, no auto-registration.
- BotConfig YAML has no `policies:` section — declarative agents can't specify access rules.

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PolicyEvaluator, EvalContext, ResourceType | Already in use |

Existing Code to Reuse:
- `parrot/auth/pbac.py` — `setup_pbac()` returns evaluator (line 35)
- `parrot/handlers/agent.py` — `_check_pbac_agent_access()` pattern (line 80)
- `parrot/handlers/agent.py` — `_build_eval_context()` pattern (line 356)

---

### Option B: Declarative Policy Class Attribute + YAML Config Only

Add a `policy_rules` class attribute to AbstractBot and a `policies:` section to BotConfig.
At agent registration time, these are converted to PBAC YAML and written to
`policies/agents/<name>.yaml`. The PDP loads them on next policy reload.

Pros:
- Developers declare policies in code or YAML alongside the agent definition.
- Generates standard YAML policy files — single format for all policies.
- No runtime policy injection — PDP loads everything from disk.

Cons:
- File I/O at registration time — writing YAML files during app startup is fragile.
- Policy reload timing: PDP may have already loaded policies before agents register theirs.
- No programmatic policy addition after startup (e.g., dynamically created agents).
- Requires filesystem write access to `policies/` directory.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PolicyEvaluator, PolicyLoader | Already in use |
| `pyyaml` | Write generated policy YAML | Already a dependency |

Existing Code to Reuse:
- `parrot/registry/registry.py` — `BotConfig` model (line 198)
- `parrot/registry/registry.py` — `AgentRegistry.register()` (line 315)
- `policies/agents.yaml` — existing format reference

---

### Option C: Full Declarative + Programmatic — Register Policies with PDP at Startup

Three-channel policy declaration:
1. **Class attribute** (`policy_rules`) on AbstractBot subclasses.
2. **BotConfig YAML** (`policies:` section) for declarative agents.
3. **Programmatic method** (`get_policy_rules()`) on AbstractBot for runtime rules.

At agent registration/instantiation time, `AgentRegistry` (which now holds a reference to
`app`) collects rules from all three channels and registers them with the PDP's
`PolicyEvaluator` via `evaluator.load_policies()`. Per-agent YAML files in
`policies/agents/<name>.yaml` are also auto-loaded.

`retrieval()` is rewritten to delegate entirely to `evaluator.check_access()`.
`ChatbotHandler` and `ToolList` use `evaluator.filter_resources()` for batch filtering.

Pros:
- All three declaration channels (code, YAML config, per-agent YAML files) converge into
  the same PDP evaluator — single enforcement engine.
- `AgentRegistry` receives `app` at setup, enabling policy registration during startup.
- `get_policy_rules()` method allows dynamic agents to compute rules at instantiation time.
- Simple initial format (action + effect + roles/groups) with clear extension path to full
  PBAC conditions.
- Per-agent YAML files are the natural resting place — auto-generated from code if desired,
  or hand-written for complex policies.
- `retrieval()` becomes thin — just delegates to PDP, no inline permission logic.

Cons:
- More moving parts: class attribute, method, YAML config, per-agent YAML files, PDP
  registration. Needs clear precedence rules.
- `AgentRegistry` API changes (accepts `app` parameter).
- Must handle ordering: PDP initialized → agents registered → policies from agents loaded.

Effort: Medium-High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | PolicyEvaluator, PolicyLoader, EvalContext, ResourceType | Already in use |
| `pyyaml` | Parse/generate per-agent policy YAML | Already a dependency |

Existing Code to Reuse:
- `parrot/auth/pbac.py` — `setup_pbac()` (line 35) returns evaluator
- `parrot/auth/resolver.py` — `PBACPermissionResolver` (line 247)
- `parrot/auth/permission.py` — `to_eval_context()` (line 150)
- `parrot/registry/registry.py` — `AgentRegistry.register()` (line 315)
- `parrot/registry/registry.py` — `BotConfig` model (line 198)
- `parrot/handlers/agent.py` — `_build_eval_context()` pattern (line 356)
- `policies/agents.yaml` — existing policy format
- `policies/tools.yaml` — existing tool policy format

---

### Option D: Middleware-Centric — All Enforcement via Guardian Middleware

Move all PBAC enforcement to navigator-auth's Guardian middleware. `retrieval()` drops
all permission logic. Handlers don't filter — middleware intercepts requests and blocks
unauthorized access before they reach handlers.

Pros:
- Single enforcement point — no code in handlers or `retrieval()`.
- Maximum reuse of navigator-auth middleware.

Cons:
- Middleware can't filter bot *listings* — it operates on routes, not data.
- `ToolList` filtering requires data-level filtering, not route-level.
- `retrieval()` context (which bot, which action) isn't available at middleware time.
- Breaks the requirement that `retrieval()` is the single enforcement point for agent access.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth >= 0.19.0` | Guardian middleware | Already in use |

Existing Code to Reuse:
- `navigator_auth.abac.middleware` — middleware interceptor

---

## Recommendation

**Option C (Full Declarative + Programmatic)** is recommended because:

1. **Covers all declaration channels**: Developers can declare policies in code (class
   attribute), YAML config (BotConfig), or override `get_policy_rules()` for dynamic rules.
   All three converge into the PDP — single source of truth for enforcement.

2. **`retrieval()` becomes thin and correct**: Instead of 40 lines of inline RBAC checks,
   it becomes a 10-line delegation to `evaluator.check_access()`. The PDP handles caching,
   priority resolution, and condition evaluation.

3. **Handler filtering is natural**: `ChatbotHandler` and `ToolList` already have access to
   `request.app` and can get the PDP/evaluator directly. `filter_resources()` handles
   batch filtering efficiently.

4. **Extensible from day one**: The simple format (`action + effect + roles/groups`) maps
   directly to the existing YAML policy schema. Adding time-based conditions or IP
   restrictions later requires only extending the rule format — the PDP already supports it.

5. **Per-agent YAML files**: `policies/agents/<name>.yaml` gives operators a clear,
   auditable per-agent policy file. Auto-loading during `setup_pbac()` is trivial via
   `PolicyLoader.load_from_directory()`.

**Tradeoff**: More moving parts than Option A, but the complexity is well-structured (three
inputs → one PDP) and each channel serves a distinct user persona (developer, operator,
advanced developer).

---

## Feature Description

### User-Facing Behavior

**For agent developers (code-level declaration):**
```python
class FinanceAgent(Agent):
    policy_rules = [
        {"action": "agent:chat", "effect": "allow", "groups": ["finance", "accounting"]},
        {"action": "agent:chat", "effect": "deny", "groups": ["contractors"]},
    ]
```
Or override `get_policy_rules()` for dynamic rules:
```python
class DynamicAgent(Agent):
    def get_policy_rules(self) -> list[dict]:
        rules = [{"action": "agent:chat", "effect": "allow", "groups": ["engineering"]}]
        if self.config.get("restricted"):
            rules.append({"action": "agent:chat", "effect": "deny", "groups": ["interns"]})
        return rules
```

**For agent developers (YAML BotConfig):**
```yaml
# agents.yaml
- name: hr_assistant
  class_name: Chatbot
  module: parrot.bots.chatbot
  policies:
    - action: "agent:chat"
      effect: allow
      groups: ["*"]
    - action: "agent:configure"
      effect: allow
      groups: ["admin"]
```

**For operators (per-agent YAML policy files):**
```yaml
# policies/agents/finance_bot.yaml
version: "1.0"
policies:
  - name: finance_bot_access
    effect: allow
    resources: ["agent:finance_bot"]
    actions: ["agent:chat"]
    subjects:
      groups: ["finance", "accounting"]
    priority: 20
```

**For end users:**
- `GET /api/v1/bots` returns only agents the user is authorized to see (filtered by PBAC).
- `GET /api/v1/bots/{id}` returns 403 if the user lacks `agent:list` permission for that agent.
- `GET /api/v1/agent_tools` returns only tools the user is authorized to see (filtered by PBAC).
- Agent chat returns 403 if PBAC denies `agent:chat` for the user.

### Internal Behavior

**Startup flow:**
1. `setup_pbac(app)` initializes PDP, loads policies from `policies/` directory (including
   `policies/agents/*.yaml`), registers evaluator as `app['abac']`.
2. `AgentRegistry.setup(app)` stores a reference to the aiohttp Application.
3. For each bot registration:
   a. Collect `policy_rules` class attribute (if any).
   b. Collect `policies` from BotConfig YAML (if any).
   c. Call `get_policy_rules()` on the bot class/instance (if overridden).
   d. Convert collected rules to `ResourcePolicy` objects.
   e. Register with PDP via `evaluator.load_policies(policies)`.

**`retrieval()` enforcement (single point):**
1. Extract session from request → build `EvalContext`.
2. Call `evaluator.check_access(ctx, ResourceType.AGENT, self.name, "agent:chat")`.
3. If denied → raise `HTTPUnauthorized` with reason from `EvaluationResult`.
4. If allowed → yield `RequestBot` wrapper.
5. Superuser bypass handled by policy (not hardcoded) — `defaults.yaml` already has
   `allow_superuser_all` at priority 100.

**`ChatbotHandler` filtering:**
1. `_get_all()`: Get evaluator from `request.app['abac']`, build `EvalContext` from session.
   Call `evaluator.filter_resources(ctx, ResourceType.AGENT, agent_names, "agent:list")`.
   Return only allowed agents.
2. `_get_one(name)`: Call `evaluator.check_access(ctx, ResourceType.AGENT, name, "agent:list")`.
   Return 403 if denied.

**`ToolList` filtering:**
1. `get()`: Discover all tools, get evaluator from `request.app['abac']`, build `EvalContext`.
   Call `evaluator.filter_resources(ctx, ResourceType.TOOL, tool_names, "tool:list")`.
   Return only allowed tools.

**Policy precedence (highest to lowest):**
1. Per-agent YAML files (`policies/agents/<name>.yaml`) — operator overrides.
2. Programmatic `get_policy_rules()` — dynamic runtime rules.
3. `policy_rules` class attribute — static code-level rules.
4. `policies:` in BotConfig YAML — declarative config rules.
5. Global policies (`policies/defaults.yaml`, `policies/agents.yaml`) — baseline.

All are loaded into the same PDP evaluator. navigator-auth's priority resolution
(higher priority number = evaluated first, DENY takes precedence at equal priority)
handles conflicts.

### Edge Cases & Error Handling

- **No PDP configured** (PBAC disabled): `retrieval()` checks `app.get('abac')`. If None,
  falls back to allow-all (backward compatible during development). Logs warning.
- **Bot with no policy_rules and no YAML**: Falls through to global policies in
  `defaults.yaml`. If `defaults.effect = deny`, access is denied by default.
- **Conflicting rules** (class says allow, YAML says deny): PDP priority resolution applies.
  Operator YAML files should use higher priority numbers to override code-level rules.
- **Dynamic agent created after startup**: `get_policy_rules()` is called at instantiation
  time. Rules registered with evaluator via `evaluator.load_policies()`.
- **Invalid policy_rules format**: Validation at registration time via Pydantic model.
  Invalid rules logged as warnings and skipped.
- **Missing session/userinfo in retrieval()**: Raise `HTTPUnauthorized` (same as current).
- **Evaluator exception**: Catch, log warning, deny access (fail-closed for retrieval,
  fail-open for listing to avoid breaking the UI).

---

## Capabilities

### New Capabilities
- `bot-policy-rules-declarative`: Class attribute `policy_rules` and BotConfig `policies:`
  section for declaring PBAC rules alongside agent definitions.
- `bot-policy-rules-programmatic`: `get_policy_rules()` method on AbstractBot for dynamic
  policy rule computation at instantiation time.
- `bot-policy-auto-registration`: Automatic registration of bot-declared policies with
  the PDP evaluator during agent registration/startup.
- `per-agent-policy-yaml`: Auto-loading of `policies/agents/<name>.yaml` files alongside
  agent definitions.
- `tool-list-pbac-filtering`: PBAC-based filtering in `ToolList` handler for global tool
  visibility control.
- `bot-list-pbac-filtering`: PBAC-based filtering in `ChatbotHandler` for agent listing
  and detail endpoints.

### Modified Capabilities
- `abstract-bot-retrieval`: Replace legacy `_permissions` RBAC with PBAC delegation to
  PDP evaluator. Remove `_permissions`, `default_permissions()`.
- `agent-registry-app-ref`: `AgentRegistry` receives and stores aiohttp `Application`
  reference for PDP policy registration.
- `bot-config-model`: Add `policies: Optional[list[PolicyRuleConfig]]` field to BotConfig.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/abstract.py` | modifies | Remove `_permissions`, `default_permissions()`, rewrite `retrieval()` to delegate to PDP. Add `policy_rules` class attr and `get_policy_rules()` method. |
| `parrot/registry/registry.py` | modifies | `AgentRegistry` gains `app` reference via `setup(app)`. `BotConfig` gains `policies:` field. Registration collects and loads policies. |
| `parrot/handlers/bots.py` | modifies | `ChatbotHandler._get_all()` and `_get_one()` filter via evaluator. `ToolList.get()` filters via evaluator. |
| `parrot/auth/pbac.py` | modifies | `setup_pbac()` loads per-agent YAML from `policies/agents/`. |
| `parrot/manager/manager.py` | modifies | `BotManager` passes `app` to `AgentRegistry.setup(app)`. |
| `app.py` | modifies | Re-enable PBAC setup (uncomment + wire registry). |
| `policies/agents/` | new | Directory for per-agent YAML policy files. |
| `parrot/auth/models.py` | new | `PolicyRuleConfig` Pydantic model for simple rule format. |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (patches in brainstorm invocation)
# Pattern for PBAC check in retrieval() — to be simplified
try:
    from navigator_auth.abac.policies.resources import ResourceType as _ResourceType
    _ABAC_RESOURCE_AVAILABLE = True
except ImportError:
    _ResourceType = None
    _ABAC_RESOURCE_AVAILABLE = False
```

```python
# Source: user-provided (patches in brainstorm invocation)
# Pattern for _is_agent_allowed in ChatbotHandler
async def _is_agent_allowed(self, agent_name: str) -> bool:
    """Evaluate ABAC/PBAC policy for viewing a bot in list/detail endpoints."""
    if not _PBAC_AVAILABLE:
        return True
    # ... evaluator.check_access() pattern
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/bots/abstract.py:2213-2220
@asynccontextmanager
async def retrieval(
    self,
    request: web.Request = None,
    app: Optional[Any] = None,
    llm: Optional[Any] = None,
    **kwargs
) -> AsyncIterator["RequestBot"]:

# From parrot/bots/abstract.py:644-667
def default_permissions(self) -> dict:
    # Returns: {"organizations": [], "programs": [], "job_codes": [], "users": [], "groups": []}

# From parrot/bots/abstract.py:333-337
# _permissions initialization:
_default = self.default_permissions()
_permissions = kwargs.get('permissions', _default)
self._permissions = {**_default, **_permissions}

# From parrot/registry/registry.py:315-329
def register(
    self,
    name: str,
    factory: Type[AbstractBot],
    *,
    singleton: bool = False,
    tags: Optional[Iterable[str]] = None,
    priority: int = 0,
    dependencies: Optional[List[str]] = None,
    replace: bool = False,
    at_startup: bool = False,
    startup_config: Optional[Dict[str, Any]] = None,
    bot_config: Optional["BotConfig"] = None,
    **kwargs: Any
) -> None:

# From parrot/registry/registry.py:198-219
class BotConfig(BaseModel):
    name: str
    class_name: str
    module: str
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)
    tools: Optional[ToolConfig] = Field(default=None)
    toolkits: List[str] = Field(default_factory=list)
    # ... (no policies field currently)
    tags: Optional[Set[str]] = Field(default_factory=set)
    singleton: bool = False
    at_startup: bool = False
    startup_config: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0

# From parrot/handlers/bots.py:1010-1041
@user_session()
class ToolList(BaseView):
    async def get(self):
        raw = discover_all()
        # ... returns all tools without filtering

# From parrot/handlers/bots.py:454-498
class ChatbotHandler(AbstractModel):
    async def _get_one(self, name: str):
        # No PBAC check — returns agent if found
    async def _get_all(self):
        # No PBAC filtering — returns all agents

# From parrot/auth/pbac.py:35-40
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]":

# From parrot/manager/manager.py:696-704
class BotManager:
    def setup(self, app: web.Application) -> web.Application:
        self.app = app if isinstance(app, web.Application) else app.get_app()
        self.app['bot_manager'] = self

# From parrot/handlers/agent.py:80-148
async def _check_pbac_agent_access(self, agent_id: str, action: str = "agent:chat") -> web.Response:
    # Gets guardian/pdp from app, builds EvalContext, calls check_access()

# From parrot/handlers/agent.py:356-388
async def _build_eval_context(self) -> Any:
    # Extracts session, builds EvalContext with username, groups, roles, programs
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from navigator_auth.abac.policies.resources import ResourceType  # AGENT, TOOL, etc.
from navigator_auth.abac.policies.evaluator import PolicyEvaluator  # check_access(), filter_resources()
from navigator_auth.abac.context import EvalContext  # User context for policy evaluation
from navigator_auth.abac.policies.environment import Environment  # Time conditions
from navigator_auth.abac.pdp import PDP  # Policy Decision Point
from navigator_auth.abac.guardian import Guardian  # Policy Enforcement Point
from navigator_auth.conf import AUTH_SESSION_OBJECT  # Session key constant
from navigator_session import get_session  # Session extraction from request
```

#### Key Attributes & Constants
- `app['abac']` → `PDP` instance (registered by `PDP.setup(app)`, pbac.py:155)
- `app['security']` → `Guardian` instance (registered by `PDP.setup(app)`, pbac.py:155)
- `pdp._evaluator` → `PolicyEvaluator` instance (injected in pbac.py:151)
- `AbstractBot._permissions` → `dict` (abstract.py:337) — **TO BE REMOVED**
- `AbstractBot.default_permissions()` → `dict` (abstract.py:644) — **TO BE REMOVED**
- `AgentRegistry._registered_agents` → `Dict[str, BotMetadata]` (registry.py:~240)
- `BotManager.app` → `web.Application` (manager.py:68)

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractBot.policy_rules`~~ — does not exist yet (to be added)
- ~~`AbstractBot.get_policy_rules()`~~ — does not exist yet (to be added)
- ~~`BotConfig.policies`~~ — field does not exist yet (to be added)
- ~~`AgentRegistry.app`~~ — no `app` reference on AgentRegistry currently
- ~~`AgentRegistry.setup(app)`~~ — method does not exist (to be added)
- ~~`BotManager.set_default_resolver()`~~ — method does not exist (referenced in app.py comment but not implemented)
- ~~`ChatbotHandler._is_agent_allowed()`~~ — does not exist (user-provided patch, not merged)
- ~~`policies/agents/`~~ — directory does not exist yet (only `policies/agents.yaml` file exists)
- ~~`parrot/auth/models.py`~~ — file does not exist yet (PolicyRuleConfig to be created)

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The changes to `abstract.py` (remove `_permissions`,
  add `policy_rules`, rewrite `retrieval()`) are the foundation that `ChatbotHandler` and
  `ToolList` depend on conceptually but not technically — handler filtering can be developed
  in parallel since it uses the PDP directly, not `retrieval()`. The `PolicyRuleConfig`
  model, `BotConfig.policies` field, and `AgentRegistry.setup(app)` are prerequisites for
  auto-registration but not for handler filtering.

- **Cross-feature independence**: Shares `abstract.py` with any other bot features.
  Shares `bots.py` handlers with bot CRUD features. No known in-flight specs conflict.

- **Recommended isolation**: `per-spec` — sequential tasks in one worktree.

- **Rationale**: Changes touch tightly coupled files (`abstract.py`, `registry.py`,
  `bots.py`, `app.py`) that benefit from sequential development where each task can
  see the prior task's changes. Handler filtering (ChatbotHandler, ToolList) could
  theoretically be parallelized but the shared handler file makes it risky.

---

## Open Questions

- [ ] **Policy rule format validation**: Should invalid `policy_rules` entries fail agent
      registration (strict) or be logged and skipped (lenient)? — *Owner: Jesus Lara*
- [ ] **Priority assignment for auto-registered rules**: What default priority should
      code-declared rules get? Suggestion: 10 (below operator YAML at 20+) so operators
      can always override. — *Owner: Jesus Lara*
- [ ] **Hot-reload of per-agent YAML**: If an operator edits `policies/agents/finance_bot.yaml`
      at runtime, should the PDP detect and reload? (Deferred to v2 per prior brainstorm,
      but confirming.) — *Owner: Jesus Lara*
