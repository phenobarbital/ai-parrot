# Feature Specification: Declarative PBAC Policy Rules on AbstractBot

**Feature ID**: FEAT-101
**Date**: 2026-04-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x
**Proposal**: `sdd/proposals/policy-rules-abstractbot.brainstorm.md` (Option C)
**Builds on**: FEAT-077 (Policy-Based Access Control Integration)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-077 established the PBAC engine (`PDP`, `PolicyEvaluator`, `Guardian`) and wired it
into ai-parrot's handler layer for tool/agent filtering. However, **individual bots still
cannot declare their own access rules**, and the legacy `_permissions` RBAC dict in
`AbstractBot.retrieval()` remains the only enforcement point for agent access.

Specific gaps:
1. `AbstractBot.retrieval()` uses a hardcoded RBAC check (users/groups/job_codes/programs/organizations)
   that is disconnected from the PBAC engine.
2. `ChatbotHandler` lists all agents without policy filtering — users see bots they can't use.
3. `ToolList` returns all tools globally without policy filtering.
4. No way to declare policies in code, YAML BotConfig, or per-agent YAML files.
5. `AgentRegistry` cannot register policies because it has no reference to the aiohttp `Application`.

### Goals
- Replace `_permissions` entirely with PBAC delegation in `retrieval()`.
- Add three policy declaration channels: class attribute, BotConfig YAML, programmatic method.
- Filter bot listings (`ChatbotHandler`) and tool listings (`ToolList`) via PBAC.
- Pass aiohttp `Application` to `AgentRegistry` so it can register policies with the PDP.
- Auto-load per-agent YAML policy files from `policies/agents/<name>.yaml`.
- Re-enable PBAC in `app.py` (navigator-auth Rust bug is fixed).

### Non-Goals (explicitly out of scope)
- Hot-reload of policy files at runtime (deferred to v2).
- Per-agent tool filtering (only global tool listing filter in this spec).
- MCP server filtering (covered by FEAT-077).
- Migration scripts for existing `_permissions` usage (no bots use it in production; manual).
- Frontend permission API changes (`POST /api/v1/abac/check` already exists via PDP).

---

## 2. Architectural Design

### Overview

Three-channel declarative policy system converging into a single PDP evaluator:

1. **Class attribute** (`policy_rules`) — static rules on AbstractBot subclasses.
2. **BotConfig YAML** (`policies:` section) — rules in `agents.yaml` declarative config.
3. **Programmatic method** (`get_policy_rules()`) — dynamic rules computed at instantiation.

All rules are converted to `ResourcePolicy` objects and loaded into the `PolicyEvaluator`
during agent registration. Per-agent YAML files in `policies/agents/<name>.yaml` are
loaded by `setup_pbac()` as part of the standard policy directory scan.

`retrieval()` delegates entirely to `evaluator.check_access()`. `ChatbotHandler` and
`ToolList` use `evaluator.filter_resources()` for batch filtering.

### Component Diagram
```
                       ┌─────────────────────┐
                       │   policies/ dir      │
                       │  ├─ defaults.yaml    │
                       │  ├─ agents.yaml      │
                       │  ├─ tools.yaml       │
                       │  └─ agents/          │
                       │     └─ <name>.yaml   │
                       └────────┬─────────────┘
                                │ PolicyLoader.load_from_directory()
                                ▼
┌──────────────┐    ┌───────────────────────┐    ┌──────────────────┐
│ AbstractBot  │    │   PolicyEvaluator     │    │  AgentRegistry   │
│ .policy_rules├───▶│  .load_policies()     │◀───┤  .setup(app)     │
│ .get_policy_ │    │  .check_access()      │    │  .register()     │
│   rules()    │    │  .filter_resources()  │    │  collects rules  │
└──────────────┘    └───────┬───────────────┘    └──────────────────┘
                            │                     ┌──────────────────┐
                            │                     │  BotConfig YAML  │
                            │                     │  policies: [...]  │
                            │                     └──────────────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
     ┌──────────────┐ ┌──────────┐ ┌───────────┐
     │ retrieval()  │ │ ChatBot  │ │ ToolList  │
     │ check_access │ │ Handler  │ │ Handler   │
     │ agent:chat   │ │ filter_  │ │ filter_   │
     │              │ │ resources│ │ resources │
     └──────────────┘ └──────────┘ └───────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` (abstract.py) | modifies | Remove `_permissions`, `default_permissions()`. Add `policy_rules`, `get_policy_rules()`. Rewrite `retrieval()`. |
| `AgentRegistry` (registry.py) | modifies | Add `setup(app)` method. Collect and register policies from bots. |
| `BotConfig` (registry.py) | extends | Add `policies: Optional[list[PolicyRuleConfig]]` field. |
| `BotManager` (manager.py) | modifies | Call `registry.setup(app)` in `load_bots()`. |
| `ChatbotHandler` (bots.py) | modifies | Add PBAC filtering to `_get_one()` and `_get_all()`. |
| `ToolList` (bots.py) | modifies | Add PBAC filtering to `get()`. |
| `setup_pbac()` (pbac.py) | modifies | Load `policies/agents/` subdirectory. |
| `app.py` | modifies | Re-enable PBAC setup block. |

### Data Models

```python
class PolicyRuleConfig(BaseModel):
    """Simple policy rule format for bot-level declaration.

    Designed for extensibility: start with action/effect/groups/roles,
    extend later with conditions (time, IP, attributes).
    """
    action: str  # e.g., "agent:chat", "agent:configure", "agent:list"
    effect: Literal["allow", "deny"] = "allow"
    groups: Optional[list[str]] = None  # subject groups
    roles: Optional[list[str]] = None   # subject roles
    priority: int = 10  # default below operator YAML (20+)
    description: Optional[str] = None
    conditions: Optional[dict[str, Any]] = None  # future: time, IP, etc.
```

### New Public Interfaces

```python
class AbstractBot(ABC):
    # Class-level policy declaration (optional)
    policy_rules: ClassVar[list[dict]] = []

    def get_policy_rules(self) -> list[dict]:
        """Return policy rules for this bot. Override for dynamic rules.

        Returns list of dicts matching PolicyRuleConfig schema.
        Default implementation returns the class attribute.
        """
        return self.__class__.policy_rules

class AgentRegistry:
    def setup(self, app: web.Application) -> None:
        """Store aiohttp Application reference for PDP policy registration."""

    def _collect_and_register_policies(self, name: str, factory, bot_config) -> None:
        """Collect policy_rules from class + BotConfig and register with PDP."""
```

---

## 3. Module Breakdown

### Module 1: PolicyRuleConfig Model
- **Path**: `parrot/auth/models.py` (new file)
- **Responsibility**: Pydantic model for simple policy rule format. Conversion method
  `to_resource_policy(agent_name)` that creates a navigator-auth `ResourcePolicy`.
- **Depends on**: `navigator_auth.abac.policies.resource_policy.ResourcePolicy`

### Module 2: AbstractBot Policy API
- **Path**: `parrot/bots/abstract.py`
- **Responsibility**: Remove `_permissions` dict, `default_permissions()` method, and
  inline RBAC logic in `retrieval()`. Add `policy_rules` class attribute and
  `get_policy_rules()` method. Rewrite `retrieval()` to delegate to PDP evaluator.
- **Depends on**: Module 1 (PolicyRuleConfig for type hints)

### Module 3: BotConfig Extension
- **Path**: `parrot/registry/registry.py`
- **Responsibility**: Add `policies: Optional[list[PolicyRuleConfig]]` field to `BotConfig`.
- **Depends on**: Module 1 (PolicyRuleConfig model)

### Module 4: AgentRegistry Policy Registration
- **Path**: `parrot/registry/registry.py`
- **Responsibility**: Add `setup(app)` method to `AgentRegistry`. In `register()`, collect
  `policy_rules` from the factory class and `policies` from BotConfig, convert to
  `ResourcePolicy` objects, and register with the PDP evaluator via
  `evaluator.load_policies()`. Handle ordering: PDP must be initialized first.
- **Depends on**: Module 1, Module 3

### Module 5: BotManager Wiring
- **Path**: `parrot/manager/manager.py`
- **Responsibility**: In `load_bots(app)`, call `self.registry.setup(app)` before
  loading modules and registering agents, so the registry has `app` before any
  `register()` calls. Ensures correct ordering.
- **Depends on**: Module 4

### Module 6: ChatbotHandler PBAC Filtering
- **Path**: `parrot/handlers/bots.py`
- **Responsibility**: Add PBAC filtering to `ChatbotHandler._get_all()` using
  `evaluator.filter_resources(ctx, ResourceType.AGENT, names, "agent:list")` and
  to `_get_one(name)` using `evaluator.check_access()`. Build `EvalContext` from
  session following the pattern in `agent.py:_build_eval_context()`.
- **Depends on**: Module 2 (retrieval rewrite establishes the pattern)

### Module 7: ToolList PBAC Filtering
- **Path**: `parrot/handlers/bots.py`
- **Responsibility**: Add PBAC filtering to `ToolList.get()` using
  `evaluator.filter_resources(ctx, ResourceType.TOOL, tool_names, "tool:list")`.
- **Depends on**: Module 6 (shares eval context building pattern)

### Module 8: Re-enable PBAC in app.py
- **Path**: `app.py`
- **Responsibility**: Uncomment the `setup_pbac()` block. Wire
  `PBACPermissionResolver` to `BotManager`. Ensure correct startup ordering:
  PBAC setup → BotManager.setup(app) → load_bots (which calls registry.setup).
- **Depends on**: Modules 4, 5

### Module 9: Per-Agent YAML Auto-Loading
- **Path**: `parrot/auth/pbac.py`
- **Responsibility**: Extend `setup_pbac()` to also load policies from
  `policies/agents/` subdirectory (recursive YAML scan).
- **Depends on**: None (standalone enhancement to setup_pbac)

### Module 10: Tests
- **Path**: `tests/auth/test_policy_rules.py` (new file)
- **Responsibility**: Unit tests for PolicyRuleConfig, AbstractBot.get_policy_rules(),
  retrieval() PBAC delegation, ChatbotHandler filtering, ToolList filtering,
  AgentRegistry policy registration.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_policy_rule_config_valid` | Module 1 | Valid PolicyRuleConfig creation with all fields |
| `test_policy_rule_config_defaults` | Module 1 | Default effect=allow, priority=10 |
| `test_policy_rule_to_resource_policy` | Module 1 | Conversion to navigator-auth ResourcePolicy |
| `test_policy_rule_config_invalid` | Module 1 | Validation error on invalid action/effect |
| `test_abstractbot_policy_rules_class_attr` | Module 2 | Class attribute collected correctly |
| `test_abstractbot_get_policy_rules_default` | Module 2 | Default returns class attribute |
| `test_abstractbot_get_policy_rules_override` | Module 2 | Override returns custom rules |
| `test_abstractbot_no_permissions_attr` | Module 2 | `_permissions` and `default_permissions()` removed |
| `test_retrieval_pbac_allowed` | Module 2 | retrieval() yields wrapper when evaluator allows |
| `test_retrieval_pbac_denied` | Module 2 | retrieval() raises HTTPUnauthorized when denied |
| `test_retrieval_no_pdp_fallback` | Module 2 | retrieval() allows all when PDP not configured |
| `test_botconfig_policies_field` | Module 3 | BotConfig accepts policies list |
| `test_registry_setup_stores_app` | Module 4 | setup(app) stores Application reference |
| `test_registry_collects_class_policies` | Module 4 | Policies collected from factory.policy_rules |
| `test_registry_collects_botconfig_policies` | Module 4 | Policies collected from BotConfig.policies |
| `test_registry_registers_with_evaluator` | Module 4 | Policies loaded into evaluator |
| `test_chatbot_handler_get_all_filters` | Module 6 | _get_all() filters denied agents |
| `test_chatbot_handler_get_one_denied` | Module 6 | _get_one() returns 403 for denied agent |
| `test_toollist_filters_denied_tools` | Module 7 | get() filters denied tools |
| `test_toollist_no_pbac_returns_all` | Module 7 | get() returns all tools when PDP absent |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_agent_policy` | Register bot with policy_rules → retrieval denies unauthorized user |
| `test_end_to_end_bot_listing_filter` | Register 2 bots with different policies → listing returns only allowed |
| `test_per_agent_yaml_loaded` | Place YAML in policies/agents/ → evaluator uses it |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_evaluator():
    """Mock PolicyEvaluator with configurable check_access/filter_resources."""

@pytest.fixture
def mock_app_with_pbac(mock_evaluator):
    """aiohttp Application with app['abac'].pdp._evaluator = mock_evaluator."""

@pytest.fixture
def bot_with_policy_rules():
    """AbstractBot subclass with policy_rules = [{"action": "agent:chat", ...}]."""
```

---

## 5. Acceptance Criteria

- [ ] `AbstractBot._permissions` and `default_permissions()` are removed.
- [ ] `AbstractBot.policy_rules` class attribute and `get_policy_rules()` method exist.
- [ ] `AbstractBot.retrieval()` delegates to `evaluator.check_access()` — no inline RBAC logic.
- [ ] `retrieval()` falls back to allow-all when PDP is not configured (backward compat).
- [ ] `BotConfig` has a `policies` field accepting `list[PolicyRuleConfig]`.
- [ ] `AgentRegistry.setup(app)` stores the aiohttp Application.
- [ ] `AgentRegistry.register()` collects and loads policies into the PDP evaluator.
- [ ] `ChatbotHandler._get_all()` filters agents via `evaluator.filter_resources()`.
- [ ] `ChatbotHandler._get_one()` returns 403 when `evaluator.check_access()` denies.
- [ ] `ToolList.get()` filters tools via `evaluator.filter_resources()`.
- [ ] `setup_pbac()` loads `policies/agents/` subdirectory.
- [ ] PBAC is re-enabled in `app.py`.
- [ ] All unit and integration tests pass.
- [ ] No breaking changes to bots that don't declare `policy_rules`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# navigator-auth ABAC (verified via parrot/auth/pbac.py:28-31, parrot/handlers/agent.py imports)
from navigator_auth.abac.policies.resources import ResourceType      # AGENT, TOOL, etc.
from navigator_auth.abac.policies.evaluator import PolicyEvaluator   # check_access(), filter_resources()
from navigator_auth.abac.context import EvalContext                  # User context for evaluation
from navigator_auth.abac.policies.environment import Environment     # Time conditions
from navigator_auth.abac.pdp import PDP                              # Policy Decision Point
from navigator_auth.abac.guardian import Guardian                    # Policy Enforcement Point
from navigator_auth.conf import AUTH_SESSION_OBJECT                  # Session key constant

# navigator-session (verified via parrot/handlers/agent.py)
from navigator_session import get_session                             # Session from request

# parrot.auth (verified via parrot/auth/__init__.py:29-37)
from parrot.auth import (
    UserSession, PermissionContext,                                   # permission.py
    AbstractPermissionResolver, DefaultPermissionResolver,            # resolver.py
    PBACPermissionResolver,                                          # resolver.py:247
    setup_pbac,                                                      # pbac.py:35
)

# parrot.registry (verified via parrot/registry/__init__.py:1-3)
from parrot.registry import AgentRegistry, BotConfig, BotMetadata    # registry.py
```

### Existing Class Signatures

```python
# parrot/bots/abstract.py:92-98
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, ToolInterface, VectorInterface, ABC):
    # line 333-337: _permissions initialization (TO BE REMOVED)
    _default = self.default_permissions()
    _permissions = kwargs.get('permissions', _default)
    self._permissions = {**_default, **_permissions}

    # line 644-667: (TO BE REMOVED)
    def default_permissions(self) -> dict: ...

    # line 669-670: (TO BE REMOVED)
    def permissions(self): return self._permissions

    # line 2213-2296: (TO BE REWRITTEN)
    @asynccontextmanager
    async def retrieval(
        self,
        request: web.Request = None,
        app: Optional[Any] = None,
        llm: Optional[Any] = None,
        **kwargs
    ) -> AsyncIterator["RequestBot"]: ...

# parrot/registry/registry.py:198-219
class BotConfig(BaseModel):
    name: str                                                         # line 200
    class_name: str                                                   # line 201
    module: str                                                       # line 202
    enabled: bool = True                                              # line 203
    config: Dict[str, Any] = Field(default_factory=dict)              # line 204
    tools: Optional[ToolConfig] = Field(default=None)                 # line 206
    toolkits: List[str] = Field(default_factory=list)                 # line 207
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)   # line 208
    model: Optional[ModelConfig] = Field(default=None)                # line 209
    system_prompt: Optional[Union[str, Dict[str, Any]]] = ...        # line 210
    prompt: Optional[PromptConfig] = Field(default=None)              # line 211
    vector_store: Optional[StoreConfig] = Field(default=None)         # line 212
    tags: Optional[Set[str]] = Field(default_factory=set)             # line 214
    singleton: bool = False                                           # line 215
    at_startup: bool = False                                          # line 216
    startup_config: Dict[str, Any] = Field(default_factory=dict)      # line 217
    priority: int = 0                                                 # line 218
    # NOTE: no 'policies' field exists — must be added

# parrot/registry/registry.py:221
class AgentRegistry:
    # line 315-329
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
    ) -> None: ...

    # line 312-313
    def get_metadata(self, name: str) -> Optional[BotMetadata]: ...

    # NOTE: no setup(app) method exists — must be added

# parrot/manager/manager.py:68
class BotManager:
    app: web.Application = None                                       # line 68

    # line 696-704
    def setup(self, app: web.Application) -> web.Application: ...

    # line 238-281
    async def load_bots(self, app: web.Application) -> None:
        # line 265: calls await self.registry.instantiate_startup_agents(app)

# parrot/handlers/bots.py:280+
class ChatbotHandler(AbstractModel):
    # line 441-452
    async def get(self): ...
    # line 454-473
    async def _get_one(self, name: str): ...
    # line 475-498
    async def _get_all(self): ...

# parrot/handlers/bots.py:1010-1041
@user_session()
class ToolList(BaseView):
    async def get(self): ...   # returns discover_all() unfiltered

# parrot/auth/pbac.py:35-40
def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]": ...

# parrot/auth/resolver.py:247-287
class PBACPermissionResolver(AbstractPermissionResolver):
    def __init__(self, evaluator: "PolicyEvaluator", logger=None) -> None: ...
    async def can_execute(self, context, tool_name, required_permissions) -> bool: ...
    async def filter_tools(self, context, tools) -> list[Any]: ...

# parrot/handlers/agent.py:80-148
async def _check_pbac_agent_access(self, agent_id: str, action: str = "agent:chat") -> web.Response: ...

# parrot/handlers/agent.py:356-388
async def _build_eval_context(self) -> Any:
    # Extracts session, builds EvalContext with username, groups, roles, programs
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PolicyRuleConfig.to_resource_policy()` | `ResourcePolicy` constructor | creates ResourcePolicy | `navigator_auth.abac.policies.resource_policy` (external) |
| `AbstractBot.retrieval()` (rewritten) | `PolicyEvaluator.check_access()` | method call via `app['abac']._evaluator` | `parrot/auth/pbac.py:152` (evaluator injection) |
| `AgentRegistry.setup(app)` | `app['abac']._evaluator` | reads PDP from app | `parrot/auth/pbac.py:156` (PDP.setup registers app['abac']) |
| `AgentRegistry.register()` | `PolicyEvaluator.load_policies()` | registers bot policies | external: `navigator_auth.abac.policies.evaluator` |
| `BotManager.load_bots()` | `AgentRegistry.setup(app)` | method call before load_modules | `parrot/manager/manager.py:238` |
| `ChatbotHandler._get_all()` | `PolicyEvaluator.filter_resources()` | batch filter | `parrot/handlers/bots.py:475` |
| `ChatbotHandler._get_one()` | `PolicyEvaluator.check_access()` | single check | `parrot/handlers/bots.py:454` |
| `ToolList.get()` | `PolicyEvaluator.filter_resources()` | batch filter | `parrot/handlers/bots.py:1015` |
| `app.py` PBAC block | `setup_pbac()` | function call | `app.py:201-224` (currently commented) |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractBot.policy_rules`~~ — does not exist yet (to be added in Module 2)
- ~~`AbstractBot.get_policy_rules()`~~ — does not exist yet (to be added in Module 2)
- ~~`BotConfig.policies`~~ — field does not exist yet (to be added in Module 3)
- ~~`AgentRegistry.app`~~ — no `app` reference on AgentRegistry currently
- ~~`AgentRegistry.setup(app)`~~ — method does not exist (to be added in Module 4)
- ~~`BotManager.set_default_resolver()`~~ — referenced in app.py comment but NOT implemented
- ~~`ChatbotHandler._is_agent_allowed()`~~ — does not exist (was in user-provided patch, never merged)
- ~~`ChatbotHandler._build_eval_context()`~~ — does not exist (must be created or extracted from agent.py pattern)
- ~~`policies/agents/`~~ — directory does not exist (only `policies/agents.yaml` file exists)
- ~~`parrot/auth/models.py`~~ — file does not exist (to be created in Module 1)
- ~~`PolicyEvaluator.add_policy()`~~ — use `load_policies(list)` instead (batch API)
- ~~`Guardian.filter_tools()`~~ — mentioned in FEAT-077 brainstorm as future work, not yet implemented in navigator-auth

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **EvalContext building**: Follow the pattern in `agent.py:_build_eval_context()` (line 356).
  Extract session via `request.session` or `get_session(request)`, get `AUTH_SESSION_OBJECT`,
  build `EvalContext` with username, groups, roles, programs.
- **Fail-open for listings, fail-closed for access**: `ChatbotHandler` and `ToolList` should
  return all items if PDP is not configured (fail-open, backward compat). `retrieval()` should
  also allow-all when PDP absent (fail-open), but deny when PDP is present and denies (fail-closed).
- **Graceful import guards**: Use `try/except ImportError` for navigator-auth imports with
  module-level flags (e.g., `_PBAC_AVAILABLE`), matching existing pattern in `agent.py`.
- **Superuser bypass**: Handled by policy (`defaults.yaml:allow_superuser_all` at priority 100).
  Do NOT hardcode superuser checks in `retrieval()` — let the PDP handle it.

### Policy Precedence (informational — enforced by PDP)
1. Enforcing policies short-circuit (highest priority, DENY wins).
2. Higher `priority` number evaluated first.
3. At equal priority, DENY takes precedence over ALLOW.
4. Default effect (`PolicyEffect.DENY`) if no policy matches.

Code-declared rules default to `priority=10`, below operator YAML files which use `priority>=20`.

### Known Risks / Gotchas
- **Startup ordering**: `setup_pbac(app)` MUST be called BEFORE `BotManager.load_bots(app)`.
  The `app['abac']` key must exist when `AgentRegistry.setup(app)` reads it. Current `app.py`
  already calls PBAC setup before BotManager setup — just uncomment.
- **Dynamic agents**: Agents created after startup (e.g., via PUT /api/v1/bots) need their
  policies registered at creation time. The `_register_bot_into_manager()` method in
  `ChatbotHandler` should call `_collect_and_register_policies()` on the new bot.
- **navigator-auth version**: Requires `navigator-auth >= 0.19.0` for `ResourceType.AGENT`,
  `ResourceType.TOOL`, and `filter_resources()`. Verify version pin in `pyproject.toml`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>=0.19.0` | PBAC engine: PolicyEvaluator, PDP, Guardian, ResourceType |

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules share tightly coupled files (`abstract.py`, `registry.py`,
  `bots.py`, `app.py`). Each module builds on the prior one's changes.
- **Cross-feature dependencies**: Depends on FEAT-077 being merged (PBAC engine in
  `parrot/auth/`). FEAT-077 status: approved. Verify `parrot/auth/pbac.py` and
  `parrot/auth/resolver.py` exist on the working branch before starting.

---

## 8. Open Questions

- [x] **Validation strictness**: Should invalid `policy_rules` entries fail agent registration
      or be logged and skipped? — *Owner: Jesus Lara*: logged and skipped
- [x] **Default priority for code-declared rules**: Proposed `priority=10` (below operator
      YAML at 20+). Confirm. — *Owner: Jesus Lara*: priority=10
- [x] **Hot-reload of per-agent YAML**: Deferred to v2 per FEAT-077 brainstorm. Confirm
      still deferred. — *Owner: Jesus Lara*: deferred to v2.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-15 | Jesus Lara | Initial draft from brainstorm Option C |
