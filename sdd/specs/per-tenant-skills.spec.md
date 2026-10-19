---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-integrations, ai-parrot-server]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [skills, multi-tenant, skill-registry, agents-dir, prompt-layer, telegram]
---

# Feature Specification: Per-Tenant Skills for `SkillRegistryMixin`

**Feature ID**: FEAT-707
**Date**: 2026-10-19
**Author**: Jesus Lara (spec drafted with Claude; design research by codex `gpt-5.6-luna`)
**Status**: approved
**Target version**: 1.3.0
**Exploration**: `sdd/proposals/per-tenant-skills.brainstorm.md` (accepted 2026-10-19, Recommended Option A)

---

## 1. Motivation & Business Requirements

### Problem Statement

`SkillRegistryMixin` loads an agent's skills from one place:
`AGENTS_DIR/{agent_id}/skills/` (authored, incl. composite `{name}/SKILL.md`)
plus the reserved `skills/learned/` subdirectory. That tree is loaded **once**
at `configure()` and is shared by every caller of the bot.

Some behaviours are the *same skill* with a *tenant-specific variant*: the
Revenue of one customer is not computed against the same accounting accounts
as the Revenue of another. `agents/troc_finance/skills/` already contains
exactly this family (`revenue_by_division`, `ebitda_breakdown`,
`ebitda_by_division`, `financial_projection_*`). Today the only way to serve
two tenants is a single skill carrying every variation (easy for the LLM to
confuse) or one agent per tenant with copied skill trees.

User's framing (verbatim, Spanish): *"en vez de hacer un skill único con todas
las variaciones (y que podrían confundirse fácilmente) se aporta el tenant como
parte de un argumento de cada método del SkillMixin … para mantener la
compatibilidad hacia atrás el per-tenant skill debe ser un flag activable
per-agent."*

**Premise correction (brainstorm):** the code does not use `skills.d`; the
directory is `skills/` and already hosts `learned/` and the `SkillRegistry`'s
`skills.json`/`versions.json`. The hard-cut rename was replaced by a reserved
`tenants/` namespace, so **no rename and no migration happen**.

**Affected**: agent authors serving several customers from one agent (finance
and reporting agents first) and operators deploying one instance per
environment. **Why now**: 7 local `agents/*/skills/` trees and 3 code
consumers of the mixin — the layout decision is cheap today.

### Goals

- G1. Opt-in per-agent flag `tenant_based` (default `False`); with it off the
  behaviour is byte-for-byte today's.
- G2. Tenant skill trees at `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`,
  global tree unchanged at `AGENTS_DIR/{agent_id}/skills/`; eager discovery at
  `configure()`, explicit reload method.
- G3. A **tenant view** = tenant tree shadowing the global tree by skill
  `name` and by `/trigger`; un-overridden globals remain visible; a tenant can
  never see another tenant's skills (isolation by construction).
- G4. Both lifetimes: tenant fixed per bot instance **and** tenant varying per
  request on a shared singleton, with concurrent requests isolated.
- G5. Tenant sources with fixed precedence: explicit `tenant=` kwarg →
  `RequestContext.kwargs["tenant"]` → instance default `tenant_id` → none.
  `UserContext.metadata["tenant"]` is the channel-agnostic carrier wrappers
  map onto the explicit kwarg. `PermissionContext.tenant_id` is **not** a
  source.
- G6. Every consumer reads the *current view*: `SkillFileToolkit` tools, the
  `/trigger` middleware, `<available_skills>` prompt layers,
  `NarrativeMixin.narrate()`, Telegram `/skills` listing.
- G7. DB-like `SkillRegistry` scoped per tenant (`org/agent/{tenant}`
  namespace, persistence under the tenant tree) with global fallback for
  search/context and tenant-side writes.
- G8. Channel binding in scope: HTTP handlers pass the server-resolved
  `RequestScope.tenant` and discard a client-supplied `tenant`; Telegram binds
  a static per-bot `TelegramAgentConfig.tenant`.
- G9. The `/trigger`-activated skill becomes request-local (ContextVar), closing
  the pre-existing singleton race that would otherwise leak a tenant's skill
  into a concurrent request (design-research S5, user decision 2026-10-19).
- G10. `global_only: true` frontmatter guard; learned skills always global;
  learned saves refresh the `<available_skills>` layers.

### Non-Goals (explicitly out of scope)

- Renaming `skills/` to `skills.d` or migrating existing trees (rejected in
  brainstorm; see "Premise correction").
- Lazy/on-demand tenant discovery (rejected: eager + explicit reload).
- Tenant-aware `skill_paths` (FEAT-188 explicit directories stay global).
- A superuser "act as tenant" override on HTTP (v1: the session's single
  Navigator `program` only).
- Reading the tenant from `PermissionContext.tenant_id` (Telegram hard-codes
  `"default"`, `build_principal_context()` defaults it to the principal).
- Tenant-scoped learned skills or tenant-scoped `extract_skills_from_conversation`.
- A cap on the number of per-tenant prompt layers (one static layer per
  tenant; a single variable-fed layer is the documented follow-up).
- `AgentStudioAgent` (`skill_paths`-only consumer) stays `tenant_based=False`.
- Option B (tenant-keyed single registry), C (one instance per tenant) and D
  (tenant in frontmatter) — rejected in the brainstorm.

---

## 2. Architectural Design

### Overview

**Option A — composed tenant views over per-tree registries.** The existing
`SkillFileRegistry` stays the per-*tree* primitive and is not modified. At
`configure()`, with `tenant_based=True`, the mixin loads the global registry
exactly as today plus one `SkillFileRegistry` per discovered
`tenants/{tenant}/skills/` tree. A new `parrot/skills/tenancy.py` module owns:

- tenant-id validation (`validate_tenant_id()`: safe path segment **and** not
  in `RESERVED_TENANT_NAMES`), tenant directory construction through
  `secure_path()` (symlink-resolving containment), and tenant directory
  discovery;
- two per-asyncio-task `ContextVar`s: the **current tenant** (bound for the
  lifetime of one `ask()` / `ask_stream()` call) and the **active skill**
  (the `/trigger`-selected `SkillDefinition`, request-local — G9);
- `SkillView`, a read-only composite over `(tenant registry, global
  registry)` exposing the `SkillFileRegistry` read API (`get`, `get_by_name`,
  `list_skills`, `has_trigger`, `learned_dir`) with the collision matrix below
  computed once at construction.

The mixin exposes one accessor, `current_skill_view(tenant=None)`, which
resolves the tenant (explicit → ContextVar → instance default) and returns the
matching view (global view when the tenant is unresolved or unknown). Every
consumer receives a **provider callable** (`view_provider=lambda:
bot.current_skill_view()`) instead of a registry instance, so toolkits,
middleware, narrative and the Telegram wrapper all read the same per-request
view and a forgotten consumer can only ever stay *global-only* (safe
direction).

`BaseBot.ask()` / `ask_stream()` gain a named `tenant: Optional[str] = None`
parameter (consumed at the boundary; never forwarded in `**kwargs`) and call
the mixin's cooperative `_enter_skill_tenant()` / `_exit_skill_tenant()`
hooks around the whole call — including streaming iteration — mirroring the
existing `current_agent_name` binding (`base.py:1093`, reset at `base.py:1806`).

Prompt: with `tenant_based=True` the `<available_skills>` block is rendered
**once per view at configure** into static **REQUEST-phase** layers named
`available_skills` (global view) and `available_skills:{tenant}`, each with a
`condition` that reads the tenant ContextVar, `cacheable=True` (content differs
per tenant, so provider prefix caches simply differ). REQUEST-phase layers
keep their `condition` through `PromptBuilder.configure()` (`builder.py:268-287`
only `partial_render`s CONFIGURE layers). The transient `skill_active` layer
stops being added/removed on the shared builder: it becomes a **permanent
conditional REQUEST layer** fed by an `active_skill_body` request variable
(G9). `save_learned_skill()` re-installs the layers after a successful save
(learned skills are global and must appear in every view).

DB-like registry: one `SkillRegistry` per tenant namespace
`{org_id}/{agent_id}/{tenant}` persisted under `tenants/{tenant}/skills/`,
sharing the global registry's already-loaded embedding model (eager and
cheap: a FAISS `IndexFlatIP` per tenant). `search_skills()` queries tenant +
global, de-duplicates by name (tenant wins), sorts by relevance and limits
**after** the merge; `get_skill_context()` asks the tenant registry first and
the global one only when the tenant result is empty; `document_skill` /
`update_skill` write to the active tenant's registry.

Channel binding: a new `resolve_request_tenant(app, request)` helper in
`ai-parrot-server` `handlers/scope.py` wraps the installed scope resolver;
`chat.py` and `agents/abstract.py` pop any `tenant` from the client body
(WARNING log) and pass `tenant=` from the helper. `TelegramAgentConfig.tenant`
(static, one bot = one customer) is passed as `tenant=` on every
`agent.ask()`, copied into `UserContext.metadata["tenant"]` and used as
`UserSession.tenant_id` instead of `"default"`; the shared instance default
is never mutated per user.

**Resolved-answer map** (brainstorm `[x]` → where it lands): flag/layout/
precedence → this overview + M1/M3; unresolved tenant → global view + DEBUG
log (M3, AC-R3); absent tenant dir → global view + one warning per tenant per
instance (M3, AC-R4); `global_only` → collision matrix + M2 (AC-V4);
`document_skill` tenant-side / extraction global → M8 (AC-S3/S4);
`narrate(tenant=)` → M5 (AC-C4); key `"tenant"` → M3/M9/M10; HTTP source →
M9 (AC-H1..H3); Telegram source → M10 (AC-T1..T3); docs → M11; one layer per
tenant, no cap → M4 (AC-P1..P3).

### Collision matrix (effective view = `SkillView.compose()`)

| Case | Tenant tree has | Global tree has | Effective view | Log |
|---|---|---|---|---|
| C1 | skill `X` | skill `X` | tenant `X` (shadow) | INFO at configure (`shadows global`) |
| C2 | skill `X` with `/t` | skill `Y` with `/t` | `/t` → tenant `X`; `get_by_name("Y")` still resolves global `Y`; `list_skills()` contains both | INFO (`trigger /t shadowed`) |
| C3 | skill `X` | skill `X` with `global_only: true` | global `X`; tenant `X` **dropped** from the view | ERROR naming both files |
| C4 | skill `X` with `/t` (`name != G`) | skill `G` with `/t`, `global_only: true` | `/t` → global `G`; tenant `X` kept by name only (its `/t` dropped) | ERROR |
| C5 | skill `X` | — | tenant `X` | — |
| C6 | — | skill `X` | global `X` (fallback) | — |
| C7 | two tenants, same `/t` | any | independent per view | — |
| C8 | learned skill `L` (global `learned/`) | — | visible in every view; a tenant-authored `L` shadows it inside that tenant | INFO |
| C9 | `learned/` dir inside a tenant tree | — | ignored | WARNING (reserved) |
| C10 | malformed file | — | skipped, rest of tenant loads | WARNING (today's `discover_skills_in_dir` contract) |

`SkillView.list_skills()` order: tenant skills (registry order), then globals
whose name is not shadowed — stable, so prompt layers are deterministic.

### Component Diagram

```
                       ask(question, tenant=?, ctx=?)                ask_stream(...)
                              │ M6: _enter_skill_tenant(tenant, ctx) ──► ContextVar _skill_tenant
                              ▼
   ┌──────────────── SkillRegistryMixin (M3) ─────────────────────────────────────┐
   │ tenant_based / tenant_id    _resolve_tenant()    current_skill_view(tenant)  │
   │ _skill_file_registry (global)  _tenant_registries{t}  _tenant_views{t}      │
   │ _skill_registry (global store) _tenant_store_registries{t}  (M8)            │
   │ reload_tenant_skills()   _install_skill_prompt_layers()   _active_skill ⇄ CV│
   └───────┬──────────────────┬──────────────────┬───────────────────┬───────────┘
           │ view_provider    │ view_provider    │ layers (M4)       │ registry_provider
           ▼                  ▼                  ▼                   ▼
   SkillFileToolkit   trigger middleware   PromptBuilder        SkillRegistryToolkit
   (M5)               (M5, M7 sets CV)     available_skills      (M5/M8)
                                           available_skills:{t}
                                           skill_active (perm., cond.)   ◄── M7 create_system_prompt
           ▲                  ▲
   tenancy.py (M1): validate_tenant_id · tenant_skills_dir · discover_tenant_dirs
                    SkillView(compose) · current_skill_tenant · set_active_skill
   models/parsers (M2): SkillDefinition.global_only
   ──────────────────────────────────────────────────────────────────────────────
   HTTP (M9): chat.py / agents/abstract.py ─ resolve_request_tenant(app, request) ─► tenant=
   Telegram (M10): TelegramAgentConfig.tenant ─► tenant= · UserContext.metadata · UserSession.tenant_id
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/skills/mixin.py` `SkillRegistryMixin` | modifies | flags, cooperative `__init__`, tenant scan, views, resolver, hooks, reload, per-tenant stores, layer (re)install, ContextVar-backed `_active_skill` |
| `parrot/skills/file_registry.py` `SkillFileRegistry` | depends on (unchanged) | the per-tree primitive |
| `parrot/skills/tenancy.py` (new) | creates | validation, paths, ContextVars, `SkillView` |
| `parrot/skills/models.py` + `parsers.py` | extends | `SkillDefinition.global_only` |
| `parrot/skills/prompt.py` | extends | keyword-only `name`/`phase`/`condition`/`cacheable`; `build_active_skill_layer()` |
| `parrot/skills/middleware.py` | modifies | `view_provider`; sets the active skill through `set_active_skill()` |
| `parrot/skills/tools.py` | modifies | `view_provider` / `registry_provider` on both toolkits and the factory |
| `parrot/skills/__init__.py` | extends | re-exports `SkillView`, `current_skill_tenant`, `set_active_skill`, `current_active_skill` |
| `parrot/bots/base.py` `ask()` / `ask_stream()` | modifies | named `tenant` param; bind/unbind hooks |
| `parrot/bots/abstract.py` `create_system_prompt()` | modifies | reads the active-skill ContextVar; permanent `skill_active` layer; passes `active_skill_body` |
| `parrot/bots/mixins/narrative.py` | modifies | `narrate(..., tenant=None)` via the view |
| `parrot/skills/store.py` `SkillRegistry` | depends on (unchanged) | one instance per tenant namespace; `configure(embedding_model=…)` shares the model |
| `ai-parrot-server` `handlers/scope.py` | extends | `resolve_request_tenant()` |
| `ai-parrot-server` `handlers/chat.py`, `handlers/agents/abstract.py` | modifies | drop client `tenant`, pass server tenant |
| `ai-parrot-integrations` `telegram/models.py`, `telegram/wrapper.py` | modifies | static `tenant`, per-request pass-through, `UserSession.tenant_id`, view-based listing, `set_active_skill` |
| `parrot/utils/paths.py` | uses (unchanged) | `validate_path_segment`, `secure_path` |
| `parrot/utils/helpers.py` `RequestContext` | uses (unchanged) | `ctx.kwargs["tenant"]` |
| `agents/*/skills/` trees (gitignored) | none | `tenants/` is additive |

### Data Models

```python
# parrot/skills/models.py — field added to the existing model (verified: models.py:60-82)
class SkillDefinition(BaseModel):
    ...
    global_only: bool = False   # frontmatter `global_only: true` → tenant trees may not shadow this skill

# parrot/skills/tenancy.py — new (no persistence; in-memory composition results)
RESERVED_TENANT_NAMES: frozenset[str] = frozenset({
    "skills", "learned", "tenants", "prompts", "queries", "kb", "documents", "flows", "_drafts", "_shared",
})
TENANTS_DIRNAME: Final[str] = "tenants"
SKILLS_DIRNAME: Final[str] = "skills"

@dataclass(frozen=True)
class TenantTreeReport:
    """Configure-time audit of one tenant tree (one INFO log line per tenant)."""
    tenant: str
    skills_dir: Path
    loaded: int
    shadowing: tuple[str, ...]          # names that shadow a global skill (C1)
    shadowed_triggers: tuple[str, ...]  # triggers taken from a differently-named global (C2)
    dropped: tuple[str, ...]            # names dropped because of `global_only` (C3/C4)
```

### New Public Interfaces

```python
# parrot/skills/tenancy.py
def validate_tenant_id(value: str) -> str: ...
def tenant_skills_dir(agent_root: Path, tenant: str) -> Path: ...
def discover_tenant_dirs(agent_root: Path, logger: logging.Logger | None = None) -> dict[str, Path]: ...
def current_skill_tenant() -> Optional[str]: ...
def bind_skill_tenant(tenant: Optional[str]) -> Token: ...
def reset_skill_tenant(token: Token) -> None: ...
def current_active_skill() -> Optional[SkillDefinition]: ...
def set_active_skill(skill: Optional[SkillDefinition]) -> None: ...
class SkillView: ...                      # read API identical to SkillFileRegistry's read methods

# parrot/skills/mixin.py — SkillRegistryMixin additions
tenant_based: bool = False
tenant_id: Optional[str] = None
def current_skill_view(self, tenant: Optional[str] = None) -> Optional[SkillView]: ...
def known_tenants(self) -> frozenset[str]: ...
async def reload_tenant_skills(self, tenant: Optional[str] = None) -> dict[str, TenantTreeReport]: ...

# parrot/bots/base.py
async def ask(..., tenant: Optional[str] = None, ...) -> AIMessage
async def ask_stream(..., tenant: Optional[str] = None, ...) -> AsyncIterator[...]

# parrot/bots/mixins/narrative.py
async def narrate(self, facts: dict[str, Any], skill: str, tenant: Optional[str] = None) -> Optional[str]

# ai-parrot-server parrot/handlers/scope.py
async def resolve_request_tenant(app: Any, request: web.Request) -> str | None: ...

# ai-parrot-integrations parrot/integrations/telegram/models.py
TelegramAgentConfig.tenant: Optional[str] = None     # YAML key `tenant`
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: tenancy module | yes | Signatures in M1 skeleton; collision matrix §2; reserved-name set fixed; `secure_path` for every tenant path; ContextVars default `None` | — |
| M2: `global_only` frontmatter | yes | Field default `False`; parser coerces with `bool(metadata.get("global_only", False))`; composite skills inherit via `parse_skill_file` (`parsers.py:157-158`) | — |
| M3: mixin wiring | no | Core of the feature; precedence, hook lifetimes and reload semantics interact with `configure()` ordering | needs the thinking model |
| M4: prompt layers | yes | Keyword-only params; names `available_skills` / `available_skills:{tenant}`; REQUEST phase; `cacheable=True`; `build_active_skill_layer()` contract fixed in skeleton | — |
| M5: consumers (tools, middleware, narrative) | yes | `view_provider` / `registry_provider` keyword-only, default `None` → today's behaviour; every read goes through `_view()` / `_registry()` helpers | — |
| M6: `ask` / `ask_stream` binding | yes | Named param; `getattr(self, "_enter_skill_tenant", None)`; reset in the same `finally` as `current_agent_name.reset` | — |
| M7: request-local active skill | no | Touches `AbstractBot.create_system_prompt` (shared, hot path) | needs the thinking model |
| M8: per-tenant store | yes | Namespace/persistence/merge rules fixed in §2 and skeleton | — |
| M9: HTTP binding | yes | Helper contract fixed; pop-before-forward in three places (`chat.py:450`, `:496`, `:530/:556`) and `agents/abstract.py:886` | — |
| M10: Telegram binding | yes | Field + `from_dict`; four wrapper edit sites fixed | — |
| M11: docs | yes | File path and CONTEXT.md paragraph fixed | — |
| M12: tests | yes | §4 tables | — |

### Module 1: Tenancy primitives (`tenancy.py`)
- **Path**: `packages/ai-parrot/src/parrot/skills/tenancy.py` (new)
- **Responsibility**: tenant-id validation, secure tenant paths and discovery, the two per-task ContextVars, the `SkillView` composite and `TenantTreeReport`.
- **Depends on**: `parrot.skills.file_registry.SkillFileRegistry` (read API), `parrot.skills.models.SkillDefinition`, `parrot.utils.paths.validate_path_segment` / `secure_path`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/skills/tenancy.py  (new)
  from contextvars import ContextVar, Token
  from parrot.utils.paths import secure_path, validate_path_segment   # verified: utils/paths.py:52 / :33
  from .file_registry import SkillFileRegistry                       # verified: skills/file_registry.py:17
  from .models import SkillDefinition                                 # verified: skills/models.py:60

  RESERVED_TENANT_NAMES: frozenset[str]
  TENANTS_DIRNAME: Final[str] = "tenants"
  SKILLS_DIRNAME: Final[str] = "skills"

  def validate_tenant_id(value: str) -> str:
      """Return ``value`` when it is a safe single path segment (``validate_path_segment``) and not a
      reserved name (case-insensitive); raise ``ValueError`` otherwise. Never touches the filesystem."""

  def tenant_skills_dir(agent_root: Path, tenant: str) -> Path:
      """``secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME)``;
      raises ``ValueError`` when the resolved path (symlinks followed) escapes ``agent_root``."""

  def discover_tenant_dirs(agent_root: Path, logger: logging.Logger | None = None) -> dict[str, Path]:
      """List ``agent_root/tenants/*/`` directories whose name passes ``validate_tenant_id`` and whose
      ``skills/`` subdirectory passes ``tenant_skills_dir``; entries failing either are skipped with a
      WARNING. Returns ``{tenant: skills_dir}`` sorted by tenant. Missing ``tenants/`` → ``{}``."""

  _skill_tenant: ContextVar[Optional[str]]             # default None
  _active_skill: ContextVar[Optional[SkillDefinition]]  # default None

  def current_skill_tenant() -> Optional[str]: ...
  def bind_skill_tenant(tenant: Optional[str]) -> Token: ...
  def reset_skill_tenant(token: Token) -> None: ...
  def current_active_skill() -> Optional[SkillDefinition]: ...
  def set_active_skill(skill: Optional[SkillDefinition]) -> None:
      """Request-local replacement for ``bot._active_skill = skill`` (design-research S5)."""

  @dataclass(frozen=True)
  class TenantTreeReport: ...   # see §2 Data Models

  class SkillView:
      """Read-only overlay of a tenant registry over the global registry (collision matrix §2)."""
      def __init__(self, global_registry: SkillFileRegistry, tenant_registry: Optional[SkillFileRegistry] = None,
                   *, tenant: Optional[str] = None, logger: logging.Logger | None = None) -> None: ...
      tenant: Optional[str]                       # None for the global view
      report: Optional[TenantTreeReport]          # None for the global view
      @property
      def learned_dir(self) -> Path: ...          # always the GLOBAL registry's learned_dir (learned skills are global)
      def get(self, trigger: str) -> Optional[SkillDefinition]: ...
      def get_by_name(self, name: str) -> Optional[SkillDefinition]: ...
      def list_skills(self) -> List[SkillDefinition]: ...
      def has_trigger(self, trigger: str) -> bool: ...
      def compose(self) -> "SkillView":
          """Recompute the effective name/trigger indexes from the two registries (called by the
          constructor and after a learned-skill hot-add); applies C1–C8; returns self."""
  ```

### Module 2: `global_only` frontmatter
- **Path**: `packages/ai-parrot/src/parrot/skills/models.py`, `packages/ai-parrot/src/parrot/skills/parsers.py`
- **Responsibility**: declare and parse the guard field; composite skills inherit it through `parse_skill_file` (`parsers.py:157-158`).
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/skills/models.py:77
  class SkillDefinition(BaseModel):
      global_only: bool = Field(default=False, description="Tenant trees may not shadow this skill (name or trigger).")

  # modifies packages/ai-parrot/src/parrot/skills/parsers.py:113 (after `priority = int(...)`)
  global_only = bool(metadata.get("global_only", False))      # passed to SkillDefinition(...) at parsers.py:118
  ```

### Module 3: Mixin wiring (`SkillRegistryMixin`)
- **Path**: `packages/ai-parrot/src/parrot/skills/mixin.py`, `packages/ai-parrot/src/parrot/skills/__init__.py`
- **Responsibility**: flags, tenant discovery at configure, views, resolver, enter/exit hooks, reload, layer (re)install, ContextVar-backed `_active_skill`, cleanup; re-exports.
- **Depends on**: M1, M2, M4, M5 (keyword params), M8 (store registries).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/skills/mixin.py:27-80 (attribute block) and the methods below
  class SkillRegistryMixin:
      tenant_based: bool = False
      """Opt-in per-tenant skill trees under ``AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/``."""
      tenant_id: Optional[str] = None
      """Instance-level default tenant (lowest precedence). Class attribute or ``tenant_id=`` kwarg."""
      _tenant_registries: Dict[str, "SkillFileRegistry"]
      _tenant_views: Dict[str, "SkillView"]
      _global_view: Optional["SkillView"]
      _tenant_store_registries: Dict[str, SkillRegistry]
      _warned_tenants: set[str]

      def __init__(self, *args: Any, **kwargs: Any) -> None:
          """Cooperative: pops ``tenant_based`` / ``tenant_id`` from kwargs (same pattern as
          NarrativeMixin.__init__, narrative.py:48) then ``super().__init__(*args, **kwargs)``.
          Sets ``self._tenant_id`` only when a tenant_id is given (keeps intent_router.py:809 default)."""

      @property
      def _active_skill(self) -> Optional[SkillDefinition]:
          """Request-local: reads ``tenancy.current_active_skill()`` (S5)."""
      @_active_skill.setter
      def _active_skill(self, skill: Optional[SkillDefinition]) -> None: ...   # tenancy.set_active_skill

      def _resolve_tenant(self, explicit: Optional[str] = None, ctx: Optional["RequestContext"] = None) -> Optional[str]:
          """Precedence: ``explicit`` → ``ctx.kwargs.get("tenant")`` → ``current_skill_tenant()`` →
          ``self._tenant_id`` → ``None``. Validates via ``validate_tenant_id`` (ValueError propagates).
          Returns ``None`` when ``tenant_based`` is False (DEBUG log when a tenant was supplied)."""

      def known_tenants(self) -> frozenset[str]: ...

      def current_skill_view(self, tenant: Optional[str] = None) -> Optional["SkillView"]:
          """The view for ``tenant`` (resolved when None). Unknown tenant → global view + ONE warning per
          tenant per instance; ``tenant_based=False`` → global view; no registry → ``None``."""

      def _enter_skill_tenant(self, tenant: Optional[str], ctx: Optional["RequestContext"]) -> Optional[Token]:
          """Called by BaseBot.ask/ask_stream (M6). Resolves and binds the tenant ContextVar; returns the
          token (None when tenant_based is False)."""
      def _exit_skill_tenant(self, token: Optional[Token]) -> None: ...

      async def _configure_skill_file_registry(self) -> None:   # modifies mixin.py:141
          """Today's global load + (tenant_based) ``_load_tenant_skill_trees()`` + views + middleware/toolkit
          with ``view_provider=self.current_skill_view`` + ``_install_skill_prompt_layers()``."""
      async def _load_tenant_skill_trees(self, agent_root: Path) -> dict[str, "TenantTreeReport"]:
          """discover_tenant_dirs → one SkillFileRegistry per tenant (learned_dir = global learned_dir, never
          scanned inside the tenant tree) → SkillView per tenant; one INFO line per tenant."""
      def _install_skill_prompt_layers(self) -> None:
          """Replace-by-name: ``available_skills`` (global view), ``available_skills:{t}`` per tenant,
          and the permanent ``skill_active`` layer (M4/M7). Idempotent."""
      async def reload_tenant_skills(self, tenant: Optional[str] = None) -> dict[str, "TenantTreeReport"]:
          """Rescan one or all tenant trees, rebuild views, store registries and prompt layers."""

      async def save_learned_skill(...) -> Optional[SkillDefinition]:   # modifies mixin.py:274
          """Unchanged contract (global learned/); on success recomposes every view and re-installs the
          prompt layers (S11)."""

      async def _configure_skill_registry(self) -> None:       # modifies mixin.py:105 — see M8
      async def _cleanup_skill_registry(self) -> None:         # modifies mixin.py:473 — cleans tenant stores too
  ```
  ```python
  # modifies packages/ai-parrot/src/parrot/skills/__init__.py:67 (import block) and :109 (__all__)
  from .tenancy import SkillView, TenantTreeReport, current_skill_tenant, current_active_skill, set_active_skill, validate_tenant_id
  ```

### Module 4: Prompt layers (`prompt.py`)
- **Path**: `packages/ai-parrot/src/parrot/skills/prompt.py`
- **Responsibility**: render a view into a named, phase-aware, conditional layer; build the permanent `skill_active` layer.
- **Depends on**: M1 (`SkillView` read API, ContextVars), `parrot.bots.prompts.PromptLayer` / `RenderPhase`.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/skills/prompt.py:29
  def render_skills_prompt_layer(
      registry: "SkillFileRegistry | SkillView",
      max_skills: Optional[int] = None,
      priority: int = 45,
      *,
      name: str = "available_skills",
      phase: RenderPhase = RenderPhase.CONFIGURE,
      condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
      cacheable: Optional[bool] = None,
  ) -> PromptLayer:
      """Unchanged defaults (byte-identical output for today's callers). With ``tenant_based`` the mixin
      passes ``name="available_skills:{tenant}"``, ``phase=RenderPhase.REQUEST``,
      ``condition=lambda _ctx: current_skill_tenant() == tenant`` and ``cacheable=True``; the global layer
      gets ``condition=lambda _ctx: current_skill_tenant() not in known_tenants``."""

  def build_active_skill_layer(priority: int = 90) -> PromptLayer:
      """Permanent REQUEST-phase layer ``name="skill_active"``, ``template="$active_skill_body"``,
      ``condition=lambda ctx: bool(ctx.get("active_skill_body"))``, ``cacheable=False`` (S5)."""
  ```

### Module 5: View-aware consumers (tools, middleware, narrative)
- **Path**: `packages/ai-parrot/src/parrot/skills/tools.py`, `packages/ai-parrot/src/parrot/skills/middleware.py`, `packages/ai-parrot/src/parrot/bots/mixins/narrative.py`
- **Responsibility**: every read goes through a provider callable; defaults keep today's behaviour.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/skills/tools.py:398 (SkillFileToolkit.__init__)
  def __init__(self, file_registry: "SkillFileRegistry", learned_dir: Optional[Path] = None,
               max_asset_bytes: int = 64 * 1024, *, view_provider: Optional[Callable[[], Any]] = None, **kwargs) -> None:
      """``view_provider`` (when given) is called on every tool invocation; ``file_registry`` remains the
      fallback and the hot-add target of ``save_learned_skill`` (global)."""
  def _view(self) -> Any: ...   # view_provider() or self._file_registry; used by list_skill_commands/load_skill/read_skill_asset

  # modifies packages/ai-parrot/src/parrot/skills/tools.py:90 (SkillRegistryToolkit.__init__)
  def __init__(self, registry: SkillRegistry, agent_id: str, include_write_tools: bool = True,
               *, registry_provider: Optional[Callable[[], SkillRegistry]] = None, **kwargs) -> None: ...
  def _registry(self) -> SkillRegistry: ...   # registry_provider() or self._registry; used by search/read/list/document/update

  # modifies packages/ai-parrot/src/parrot/skills/tools.py:635
  def create_skill_tools(registry, agent_id, include_write_tools=True, file_registry=None, learned_dir=None,
                         *, view_provider=None, registry_provider=None) -> List[AbstractTool]: ...

  # modifies packages/ai-parrot/src/parrot/skills/middleware.py:16
  def create_skill_trigger_middleware(registry: "SkillFileRegistry", bot: "AbstractBot", priority: int = -10,
                                      *, view_provider: Optional[Callable[[], Any]] = None) -> PromptMiddleware:
      """Lookups go through ``view_provider()`` when given; a matched skill is published with
      ``tenancy.set_active_skill(skill)`` (replaces ``bot._active_skill = skill``, middleware.py:64)."""

  # modifies packages/ai-parrot/src/parrot/bots/mixins/narrative.py:54 / :100
  async def narrate(self, facts: dict[str, Any], skill: str, tenant: Optional[str] = None) -> Optional[str]: ...
  async def _load_narrative_skill(self, name: str, tenant: Optional[str] = None) -> Optional[SkillDefinition]:
      """``await self._configure_skill_registry()`` then ``self.current_skill_view(tenant)`` → ``get_by_name``."""
  ```

### Module 6: `ask()` / `ask_stream()` tenant binding
- **Path**: `packages/ai-parrot/src/parrot/bots/base.py`
- **Responsibility**: named `tenant` parameter; bind/unbind the tenant ContextVar for the whole call, including generator iteration in `ask_stream`.
- **Depends on**: M3 hooks (duck-typed via `getattr`, so non-mixin bots are untouched).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/bots/base.py:1037 (ask) and :1808 (ask_stream)
  async def ask(self, question: str, ..., use_tools: bool = True, trace_context=None,
                tenant: Optional[str] = None, **kwargs) -> AIMessage:
      """``tenant`` is consumed here (never forwarded). Right after ``_agent_token = current_agent_name.set(self.name)``
      (base.py:1093): ``_tenant_token = enter(tenant, ctx) if (enter := getattr(self, "_enter_skill_tenant", None)) else None``;
      in the ``finally`` that resets ``current_agent_name`` (base.py:1806): ``self._exit_skill_tenant(_tenant_token)``."""
  async def ask_stream(self, ..., trace_context=None, tenant: Optional[str] = None, **kwargs) -> AsyncIterator[...]:
      """Same binding at base.py:1836 / reset at base.py:2263 — the token lives for the generator's lifetime."""
  ```

### Module 7: Request-local active skill (S5)
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py` (`create_system_prompt`), plus the middleware edit in M5 and the Telegram edit in M10.
- **Responsibility**: stop mutating the shared `PromptBuilder` per request; read the `/trigger` skill from the ContextVar; clear it after the prompt is built.
- **Depends on**: M1, M4.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/bots/abstract.py:3569-3593 (inside create_system_prompt)
  # lazy imports (same style as the existing `from parrot.bots.prompts.layers import ...` at :3571)
  from parrot.skills.tenancy import current_active_skill, set_active_skill
  from parrot.skills.prompt import build_active_skill_layer
  active = current_active_skill() or getattr(self, "_active_skill", None)        # legacy attribute fallback
  if self._prompt_builder.get("skill_active") is None:                           # verified: builder.py:242
      self._prompt_builder.add(build_active_skill_layer())                       # permanent, idempotent
  result = self._build_prompt(..., active_skill_body=(active.template_body if active else ""), **kwargs)
  set_active_skill(None)                                                          # transient for ONE ask, as today
  # the `self._prompt_builder.remove("skill_active")` / `self._active_skill = None` block is deleted
  ```

### Module 8: Per-tenant DB-like store
- **Path**: `packages/ai-parrot/src/parrot/skills/mixin.py` (`_configure_skill_registry`, `search_skills`, `get_skill_context`, `document_skill`, `_add_skill_tools`, `_cleanup_skill_registry`)
- **Responsibility**: one `SkillRegistry` per tenant namespace sharing the global embedding model; merge/fallback/write-routing rules from §2.
- **Depends on**: M1, M3, `parrot.skills.store.create_skill_registry` (unchanged).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/skills/mixin.py:105 (_configure_skill_registry)
  # per tenant: create_skill_registry(namespace=f"{org_id}/{agent_id}/{tenant}",
  #                                   persistence_path=tenant_skills_dir(agent_root, tenant), extraction_llm=...)
  #             await reg.configure(embedding_model=self._skill_registry._embedding_model)   # verified: store.py:202-216
  def _current_store_registry(self, tenant: Optional[str] = None) -> Optional[SkillRegistry]:
      """Tenant registry when resolved and known, else the global one (same resolution as current_skill_view)."""
  async def search_skills(self, query: str, category: Optional[str] = None, max_results: int = 5,
                          tenant: Optional[str] = None) -> List[Dict[str, Any]]:
      """Tenant + global results, de-duplicated by name (tenant wins), sorted by relevance desc, limited
      AFTER the merge; each dict gains ``"namespace"``."""
  async def get_skill_context(self, query: str, max_skills=None, max_tokens=None, tenant: Optional[str] = None) -> str:
      """Tenant registry first; global registry only when the tenant result is empty."""
  async def document_skill(self, ..., tenant: Optional[str] = None) -> Optional[Skill]:
      """Writes to ``_current_store_registry(tenant)``; ``extract_skills_from_conversation`` stays global."""
  # _add_skill_tools passes registry_provider=self._current_store_registry (M5)
  # _cleanup_skill_registry awaits cleanup() on every tenant registry too (store.py:926)
  ```

### Module 9: HTTP tenant binding (`ai-parrot-server`)
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/scope.py`, `packages/ai-parrot-server/src/parrot/handlers/chat.py`, `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py`
- **Responsibility**: server-side tenant resolution; client-supplied `tenant` discarded and logged.
- **Depends on**: M6 (`tenant=` kwarg), existing `SessionScopeResolver` (`scope.py:73`).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-server/src/parrot/handlers/scope.py (after get_scope_resolver, :140)
  async def resolve_request_tenant(app: Any, request: web.Request) -> str | None:
      """``get_scope_resolver(app).resolve(request).tenant`` when ``has_installed_resolver(app)``; ``None`` otherwise
      (no resolver, zero or several programs). Never raises on resolver failure (resolver returns owner-only)."""

  # modifies packages/ai-parrot-server/src/parrot/handlers/chat.py:450 (right after `stream = data.pop('stream', False)`)
  if data.pop('tenant', None) is not None: self.logger.warning("Ignoring client-supplied tenant for bot %s", ...)
  tenant = await resolve_request_tenant(app, self.request)
  # chat.py:530 (ask_stream) and :556 (ask): add `tenant=tenant,`; the :496 custom-method merge is already clean (pop above)

  # modifies packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py:886
  response = await agent.ask(question=query, use_conversation_history=False, use_vector_context=False,
                             max_tokens=16000, tenant=await resolve_request_tenant(self.request.app, self.request))
  ```

### Module 10: Telegram tenant binding (`ai-parrot-integrations`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py`, `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: static per-bot tenant; per-request pass-through; permission context + user context carry it; view-based listing; request-local skill activation.
- **Depends on**: M3, M6, M1 (`set_active_skill`).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:74 and :270
  class TelegramAgentConfig:
      tenant: Optional[str] = None     # YAML `tenant: pokemon`; from_dict: tenant=data.get("tenant")

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
  @staticmethod
  def _build_permission_context(session, chat_id=None, bot_id=None, tenant_id: Optional[str] = None):   # :1266
      """``UserSession(tenant_id=tenant_id or "default")`` (replaces the literal at :1303); caller :1489 passes
      ``tenant_id=self.config.tenant``."""
  def _build_user_context(self, session) -> UserContext:                                                # :1331
      """adds ``metadata["tenant"] = self.config.tenant`` when set."""
  async def _invoke_agent(...):                                                                          # :1450
      """both ``agent.ask(...)`` calls (:1514, :1540) gain ``tenant=self.config.tenant``."""
  def _list_agent_skills(self) -> list[dict]:                                                             # :1938
      """``view = getattr(self.agent, "current_skill_view", None)`` → ``view(self.config.tenant).list_skills()``
      when available, else today's ``_skill_file_registry`` read."""
  # :2083 `self.agent._active_skill = skill_def` → `set_active_skill(skill_def)` and the ask gains `tenant=self.config.tenant`
  ```

### Module 11: Documentation
- **Path**: `docs/skills/per-tenant-skills.md` (new), `.agent/CONTEXT.md` (Skills section, `:122`)
- **Responsibility**: layout, precedence, collision matrix, channel binding, `global_only`, reload, the request-local active skill.
- **Depends on**: M1–M10 shipped names.

### Module 12: Tests
- **Path**: see §4.
- **Depends on**: all modules.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_validate_tenant_id_accepts_safe_segment` / `_rejects_traversal` / `_rejects_reserved_names` | M1 | `pokemon`, `acme-01` ok; `..`, `a/b`, `""`, `skills`, `learned`, `tenants`, `_shared`, `Skills` rejected |
| `test_tenant_skills_dir_secure_path_escape` | M1 | symlinked `tenants/evil → /tmp` raises / is skipped by discovery with a WARNING |
| `test_discover_tenant_dirs_sorted_and_filtered` | M1 | ignores files, invalid names, dirs without `skills/` |
| `test_skill_view_c1_shadow_by_name` … `test_skill_view_c10` | M1 | one test per collision-matrix row; `list_skills()` order deterministic |
| `test_skill_view_learned_dir_is_global` | M1 | view's `learned_dir` is the global registry's |
| `test_contextvars_default_none_and_reset` | M1 | bind/reset round-trip; token reset after exception |
| `test_parse_global_only_frontmatter` / `_composite_inherits_global_only` | M2 | `global_only: true` → field; absent → `False`; `SKILL.md` composite inherits |
| `test_tenant_based_false_is_byte_identical` | M3 | with the flag off: no scan, no ContextVar, same tools/middleware/layers as today (compare against a snapshot built with the flag absent) |
| `test_configure_loads_tenant_trees_eagerly` | M3 | two tenants → two registries, two views, INFO per tenant with counts |
| `test_tenant_learned_dir_in_tenant_tree_ignored` | M3 | C9 warning, no scan |
| `test_resolve_tenant_precedence` | M3 | explicit > ctx.kwargs > ContextVar > instance default > None |
| `test_unresolved_tenant_global_view_debug` | M3 | AC-R3 |
| `test_unknown_tenant_warns_once_per_instance` | M3 | AC-R4 (two calls, one WARNING) |
| `test_invalid_tenant_raises_before_fs` | M3 | `ask(tenant="../x")` → `ValueError`, no filesystem access (monkeypatched `discover`) |
| `test_reload_tenant_skills_adds_new_tenant` | M3 | create dir after configure → reload → view exists, layer installed |
| `test_save_learned_skill_refreshes_layers_and_views` | M3 | learned skill visible in global and tenant layers/views after save (S11) |
| `test_cleanup_closes_tenant_stores` | M3/M8 | every tenant `SkillRegistry.cleanup()` awaited |
| `test_render_layer_defaults_unchanged` | M4 | default call returns today's `available_skills` CONFIGURE layer (string-equal to the existing fixture) |
| `test_render_layer_tenant_variant` | M4 | name/phase/condition/cacheable as specified; condition true only when ContextVar matches |
| `test_global_layer_hidden_when_tenant_view_active` | M4 | with `pokemon` bound, `available_skills` renders `None`, `available_skills:pokemon` renders |
| `test_build_active_skill_layer_condition` | M4 | renders only when `active_skill_body` non-empty; `cacheable=False` |
| `test_file_toolkit_uses_view_provider` / `test_registry_toolkit_uses_registry_provider` | M5 | provider called per invocation; `None` provider = today's behaviour |
| `test_middleware_sets_active_skill_contextvar` | M5/M7 | `/trigger` → `current_active_skill()` set, `bot.__dict__` untouched |
| `test_narrate_tenant_variant` | M5 | `narrate(facts, "revenue", tenant="pokemon")` uses the tenant body; no tenant → global |
| `test_ask_binds_and_resets_tenant` / `test_ask_stream_holds_tenant_across_iteration` / `_reset_on_exception` | M6 | ContextVar visible inside a tool call mid-stream; reset in `finally` |
| `test_non_mixin_bot_ignores_tenant_kwarg` | M6 | bot without the mixin accepts `tenant=` and never forwards it |
| `test_create_system_prompt_no_builder_mutation` | M7 | builder layer set identical before/after a call with an active skill; `skill_active` present once |
| `test_active_skill_cleared_after_prompt` | M7 | transient-for-one-ask preserved |
| `test_legacy_attribute_fallback` | M7 | a non-mixin bot with `_active_skill` attribute still gets the body injected |
| `test_store_namespace_and_persistence_per_tenant` | M8 | `org/agent/pokemon`, `tenants/pokemon/skills/skills.json` |
| `test_store_shares_embedding_model` | M8 | tenant registries' `_embedding_model is global._embedding_model` |
| `test_search_skills_merge_before_limit` | M8 | tenant wins on name, sorted by relevance, `max_results` applied after merge, `namespace` present |
| `test_get_skill_context_tenant_then_global` | M8 | global used only when tenant result empty |
| `test_document_skill_routes_to_tenant` / `test_extract_skills_stays_global` | M8 | AC-S3/S4 |
| `test_resolve_request_tenant_no_resolver` / `_single_program` / `_multi_program` | M9 | `None`, `"pokemon"`, `None` |
| `test_chat_handler_drops_client_tenant` / `_passes_server_tenant_stream_and_sync` | M9 | AC-H1..H3 (fake bot records kwargs) |
| `test_ask_agent_passes_tenant` | M9 | `agents/abstract.py:886` call carries `tenant=` |
| `test_telegram_config_tenant_from_yaml` | M10 | `from_dict` |
| `test_telegram_permission_context_tenant` / `_user_context_metadata` / `_invoke_passes_tenant` / `_skill_command_uses_contextvar` / `_list_skills_uses_view` | M10 | AC-T1..T3 |

### Integration Tests
| Test | Description |
|---|---|
| `test_two_tenants_concurrent_on_singleton` (`asyncio.gather`) | one mixin bot, `ask(tenant="pokemon")` and `ask(tenant="epson")` concurrently with a tool that records `list_skill_commands` output: no cross-tenant skill in either; `/revenue` resolves to each tenant's file; `<available_skills>` block per request matches its view |
| `test_trigger_isolation_concurrent` | two concurrent `/revenue` asks on a singleton: each system prompt contains only its own tenant's body (S5) |
| `test_fixed_tenant_instance` | `tenant_id="pokemon"` class attr → every call uses the pokemon view without a kwarg |
| `test_global_only_end_to_end` | tenant tree shadows a `global_only` skill → dropped, ERROR logged, global served |
| `test_read_skill_asset_tenant_composite` | assets read from the tenant composite skill, never the global one |
| `test_existing_skill_system_unchanged` | `packages/ai-parrot/tests/integration/test_skill_system.py` passes untouched (flag off) |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/test_skill_file_registry.py
- packages/ai-parrot/tests/unit/test_skill_trigger_middleware.py
- packages/ai-parrot/tests/unit/test_save_learned_skill_tool.py
- packages/ai-parrot/tests/unit/test_budget_narrative_skill.py
- packages/ai-parrot/tests/unit/test_skill_definition.py
- packages/ai-parrot/tests/integration/test_skill_system.py
- tests/unit/test_skills_prompt_layer.py
- tests/unit/test_load_skill_tool.py
- tests/unit/test_list_skill_commands_tool.py
- tests/unit/test_read_skill_asset_tool.py
- tests/unit/test_skill_registry_toolkit.py
- tests/unit/test_skills_directory_loader.py
- tests/unit/test_skill_parsers.py
- tests/unit/test_skill_models.py
- packages/ai-parrot/tests/unit/test_skill_tenancy.py
- packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py
- packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py
- packages/ai-parrot/tests/unit/test_skill_active_request_local.py
- packages/ai-parrot/tests/unit/test_skill_tenant_store.py
- packages/ai-parrot/tests/unit/test_ask_tenant_binding.py
- packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py
- packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py
- packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py
markers: none

(The first 14 entries exist today and pin the flag-off contract; the rest are created by M12. Run with
`PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-integrations/src` inside a worktree.)

### Test Data / Fixtures
```python
@pytest.fixture
def agent_tree(tmp_path: Path) -> Path:
    """AGENTS_DIR/{agent}/skills/{revenue.md, ebitda.md(global_only), learned/} +
    tenants/pokemon/skills/{revenue/SKILL.md + accounts.csv, ebitda.md} + tenants/epson/skills/revenue.md
    + tenants/evil -> symlink outside + tenants/skills/ (reserved name, must be skipped)."""

@pytest.fixture
def tenant_bot(agent_tree, monkeypatch):
    """Minimal SkillRegistryMixin host with _agents_dir=agent_tree.parent, _prompt_builder, _prompt_pipeline,
    tool_manager stub, tenant_based=True; SkillRegistry.configure patched to a fake embedding model."""

@pytest.fixture
def fake_scope_app():
    """aiohttp app with a stub ScopeResolver returning RequestScope(tenant=...) for M9 tests."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-0. All §4 unit and integration tests pass; the 14 pre-existing files in the Validation Contract pass **unmodified**.
- [ ] AC-B1. `tenant_based=False` (default): no `tenants/` scan, no ContextVar binding, identical tools/middleware/layer set to today; a `tenant=` kwarg is ignored with one DEBUG log.
- [ ] AC-B2. No existing public signature loses a parameter; all new parameters are keyword-only or trailing with defaults; no new third-party dependency.
- [ ] AC-L1. Layout: global tree `AGENTS_DIR/{agent_id}/skills/` unchanged; tenant trees at `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`; `learned/` inside a tenant tree is ignored with a WARNING; `save_learned_skill` always writes to the global `skills/learned/`.
- [ ] AC-L2. After a successful `save_learned_skill`, the learned skill appears in the global and every tenant `<available_skills>` layer and view without restart.
- [ ] AC-R1. Precedence explicit kwarg → `ctx.kwargs["tenant"]` → bound ContextVar → `tenant_id` instance default → none, covered by `test_resolve_tenant_precedence`.
- [ ] AC-R2. Invalid tenant ids (`..`, `/`, empty, any `RESERVED_TENANT_NAMES` entry, case-insensitive) raise `ValueError` before any filesystem access.
- [ ] AC-R3. Unresolved tenant with `tenant_based=True` → global view, no error, DEBUG log.
- [ ] AC-R4. Valid tenant with no directory → global view + exactly one WARNING per tenant per instance.
- [ ] AC-V1. A tenant view never contains another tenant's skills (name, trigger, asset): `test_two_tenants_concurrent_on_singleton` and `test_read_skill_asset_tenant_composite`.
- [ ] AC-V2. Shadowing by name and by trigger per the collision matrix C1–C10, each row tested.
- [ ] AC-V3. Concurrent `ask()` calls for different tenants on one instance are isolated (`asyncio.gather`), including mid-stream tool calls.
- [ ] AC-V4. `global_only: true` prevents tenant shadowing (C3/C4) with an ERROR naming both files.
- [ ] AC-P1. One static REQUEST-phase layer per view: `available_skills` (global) and `available_skills:{tenant}`; exactly one renders per request; `cacheable=True`.
- [ ] AC-P2. `render_skills_prompt_layer()` with default arguments produces today's layer byte-for-byte.
- [ ] AC-P3. The prompt-builder layer set is not mutated per request; `skill_active` is a single permanent conditional layer (AC-A1).
- [ ] AC-A1. `_active_skill` is request-local: two concurrent `/trigger` asks on a singleton each render only their own skill body (S5).
- [ ] AC-A2. The activated skill is cleared after one `create_system_prompt()` (today's transient contract).
- [ ] AC-A3. `bot._active_skill = skill` on a mixin bot and `set_active_skill()` are equivalent; a non-mixin bot's plain attribute still works (legacy fallback).
- [ ] AC-C1..C4. `SkillFileToolkit` tools, the `/trigger` middleware and `/skills` listing, Telegram `_list_agent_skills()`, and `narrate(tenant=)` all read the current view.
- [ ] AC-S1. One `SkillRegistry` per tenant, namespace `{org}/{agent}/{tenant}`, persistence under the tenant tree, sharing the global embedding model.
- [ ] AC-S2. `search_skills()` merges tenant + global (tenant wins by name), sorts by relevance, limits after the merge; `get_skill_context()` falls back to global only when the tenant result is empty.
- [ ] AC-S3. `document_skill` / `update_skill` write to the active tenant's registry (global when none).
- [ ] AC-S4. `extract_skills_from_conversation` writes to the global registry regardless of tenant.
- [ ] AC-S5. `_cleanup_skill_registry()` cleans every tenant registry.
- [ ] AC-E1. `reload_tenant_skills(tenant=None)` picks up a tenant directory created after configure and rebuilds its view, store and layer.
- [ ] AC-H1. HTTP: a `tenant` key in the client body never reaches `ask()` / `ask_stream()` / the custom-method merge; it is logged at WARNING.
- [ ] AC-H2. HTTP: `tenant=` equals the installed resolver's `RequestScope.tenant` (single Navigator program); `None` with no resolver or with zero/several programs.
- [ ] AC-H3. `ask_agent()` (`handlers/agents/abstract.py`) passes the same server-resolved tenant.
- [ ] AC-T1. `TelegramAgentConfig.tenant` parsed from YAML; both `agent.ask` calls in `_invoke_agent` and the `/skill` command pass `tenant=`.
- [ ] AC-T2. `UserSession.tenant_id` equals the configured tenant (or `"default"` when unset); `UserContext.metadata["tenant"]` set when configured.
- [ ] AC-T3. The shared agent's `tenant_id` / `_tenant_id` is never assigned by the Telegram wrapper or by `post_login`.
- [ ] AC-D1. `docs/skills/per-tenant-skills.md` exists and `.agent/CONTEXT.md` Skills section mentions `tenant_based`, the layout and the precedence.
- [ ] AC-Q1. `ruff check` clean on every touched file; Google docstrings and type hints on every new symbol.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `c588e1ec3` (dev, 2026-10-19). Implementation agents MUST NOT reference
> imports, attributes, or methods not listed here without first verifying they exist.

### Verified Imports
```python
from parrot.skills import SkillRegistryMixin, SkillFileRegistry, SkillsDirectoryLoader, SkillDefinition, SkillSource  # verified: packages/ai-parrot/src/parrot/skills/__init__.py:49-110
from parrot.skills.mixin import SkillRegistryMixin                     # verified: skills/mixin.py:27
from parrot.skills.file_registry import SkillFileRegistry             # verified: skills/file_registry.py:17
from parrot.skills.parsers import discover_skills_in_dir, parse_skill_file, parse_skill_directory  # verified: skills/parsers.py:162 / :60 / :132
from parrot.skills.prompt import render_skills_prompt_layer           # verified: skills/prompt.py:29
from parrot.skills.middleware import create_skill_trigger_middleware  # verified: skills/middleware.py:16
from parrot.skills.tools import SkillFileToolkit, SkillRegistryToolkit, create_skill_tools  # verified: skills/tools.py:371 / :69 / :635
from parrot.skills.store import SkillRegistry, create_skill_registry  # verified: skills/store.py:126 / :934
from parrot.skills.models import SkillDefinition, SkillSource, SkillCategory, Skill  # verified: skills/models.py:60 / :53 ; mixin.py:19
from parrot.bots.prompts import PromptLayer, RenderPhase              # verified: used by skills/prompt.py:24; layers.py:35-51
from parrot.bots.prompts.layers import PromptLayer, RenderPhase       # verified: bots/abstract.py:3571 (lazy)
from parrot.utils.helpers import RequestContext, current_context, _current_ctx  # verified: utils/helpers.py:7 / :58 / :53
from parrot.auth.context import UserContext                           # verified: auth/context.py:39
from parrot.utils.paths import validate_path_segment, secure_path, SAFE_SEGMENT_RE  # verified: utils/paths.py:33 / :52 / :29
from parrot.conf import AGENTS_DIR                                    # verified: conf.py:181
from parrot.auth.permission import PermissionContext, UserSession, build_principal_context  # verified: auth/permission.py:134 / :47 / :170
# ai-parrot-server only (never imported from core):
from parrot.handlers.scope import RequestScope, SessionScopeResolver, get_scope_resolver, has_installed_resolver  # verified: packages/ai-parrot-server/src/parrot/handlers/scope.py:38 / :73 / :140 / :135
from parrot.handlers.studio.access import studio_scope_kwargs         # verified: packages/ai-parrot-server/src/parrot/handlers/studio/access.py:73
# ai-parrot-integrations only:
from parrot.integrations.telegram.models import TelegramAgentConfig  # verified: packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:42
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:                                                 # line 27
    enable_skill_registry: bool = True                                    # line 57
    skill_registry_expose_tools: bool = True                              # line 58
    skill_paths: List[Path] = []                                          # line 65
    inject_skills_into_prompt: bool = True                                # line 69
    skill_prompt_max_entries: Optional[int] = None                        # line 73
    _skill_registry: Optional[SkillRegistry] = None                       # line 78
    _skill_file_registry: Optional["SkillFileRegistry"] = None            # line 79
    _active_skill: Optional[SkillDefinition] = None                       # line 80  (becomes a property, M3)
    def _resolve_agents_dir(self) -> Optional[Path]: ...                  # line 82  (self._agents_dir → parrot.conf.AGENTS_DIR)
    async def _configure_skill_registry(self) -> None: ...                # line 105; namespace f"{org_id}/{agent_id}" (113), persistence_path = agents_dir / agent_id / "skills" (121)
    async def _configure_skill_file_registry(self) -> None: ...           # line 141; skills_dir = agents_dir / agent_id / "skills" (165); middleware (188-192); layer (232-237); toolkit (257-260)
    async def save_learned_skill(self, name, content, description, triggers, category="general") -> Optional[SkillDefinition]: ...  # line 274; hot-add at 345
    async def _add_skill_tools(self) -> None: ...                         # line 347; create_skill_tools(registry=..., agent_id=..., include_write_tools=True) at 359
    async def get_skill_context(self, query, max_skills=None, max_tokens=None) -> str: ...  # line 374
    async def document_skill(self, name, content, description="", category="general", tags=None, triggers=None) -> Optional[Skill]: ...  # line 394
    async def extract_skills_from_conversation(self, conversation, context=None) -> Optional[Skill]: ...  # line 424
    async def search_skills(self, query, category=None, max_results=5) -> List[Dict[str, Any]]: ...  # line 445
    async def _cleanup_skill_registry(self) -> None: ...                  # line 473; awaits self._skill_registry.cleanup()
# mixin.py imports (lines 14-21): inspect, logging, Path, typing; .models (SkillCategory, SkillDefinition, Skill); .store; .tools — no parrot.bots import (safe for abstract.py lazy imports)

# packages/ai-parrot/src/parrot/skills/file_registry.py
class SkillFileRegistry:                                                  # line 17
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None: ...  # line 29; self.learned_dir = learned_dir or skills_dir / "learned" (35)
    async def load(self) -> None: ...                                     # line 41 (authored excludes "learned" subdir, line 43)
    def _register(self, skill: SkillDefinition) -> None: ...              # line 86 (duplicate name/trigger → error log, first wins)
    def get(self, trigger: str) -> Optional[SkillDefinition]: ...         # line 108
    def get_by_name(self, name: str) -> Optional[SkillDefinition]: ...    # line 119
    def add(self, skill: SkillDefinition) -> None: ...                    # line 130
    def list_skills(self) -> List[SkillDefinition]: ...                   # line 138
    def has_trigger(self, trigger: str) -> bool: ...                      # line 142

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition: ...             # line 60; priority = int(metadata.get("priority", 90)) (113); SkillDefinition(...) (118)
def parse_skill_directory(skill_dir: Path) -> SkillDefinition: ...        # line 132; parse_skill_file(skill_md) (157) + model_copy(update={"assets_dir": ...}) (158)
def discover_skills_in_dir(directory: Path, logger=_LOGGER, exclude_names: Iterable[str] = ()) -> List[SkillDefinition]: ...  # line 162

# packages/ai-parrot/src/parrot/skills/models.py
class SkillSource(str, Enum): AUTHORED = "authored"; LEARNED = "learned"   # line 53
class SkillDefinition(BaseModel):                                         # line 60
    name: str; description: str; triggers: list[str]; source: SkillSource = AUTHORED; priority: int = 90 (71)
    version: str = "1.0"; category: str | None = None; template_body: str; token_count: int; file_path: Path
    assets_dir: Path | None = Field(default=None, ...)                    # line 77
    MAX_TOKENS: ClassVar[int] = 1000                                      # line 82

# packages/ai-parrot/src/parrot/skills/prompt.py
def render_skills_prompt_layer(registry: SkillFileRegistry, max_skills: Optional[int] = None, priority: int = 45) -> PromptLayer: ...  # line 29; returns name="available_skills", phase=CONFIGURE (61-97)

# packages/ai-parrot/src/parrot/skills/middleware.py
def create_skill_trigger_middleware(registry: SkillFileRegistry, bot: "AbstractBot", priority: int = -10) -> PromptMiddleware: ...  # line 16
#   reserved "/skills", "/help" (50-59); registry.get(trigger) (62); bot._active_skill = skill (64)

# packages/ai-parrot/src/parrot/skills/tools.py
class SkillRegistryToolkit(AbstractToolkit):                              # line 69
    def __init__(self, registry: SkillRegistry, agent_id: str, include_write_tools: bool = True, **kwargs) -> None: ...  # line 90; self._registry (98)
    # reads: search 118, read 180, list 181/209/304, upload 262/313
class SkillFileToolkit(AbstractToolkit):                                  # line 371
    def __init__(self, file_registry: "SkillFileRegistry", learned_dir: Optional[Path] = None, max_asset_bytes: int = 64 * 1024, **kwargs) -> None: ...  # line 398; self._file_registry (406)
    async def list_skill_commands(self) -> ToolResult: ...                # line 413 (list_skills at 419)
    async def load_skill(self, name: str) -> ToolResult: ...              # line 454 (get_by_name at 462)
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult: ...  # line 491
    async def save_learned_skill(self, name, description, content, triggers=None, category="general") -> ToolResult: ...  # line 543
def create_skill_tools(registry, agent_id, include_write_tools=True, file_registry=None, learned_dir=None) -> List[AbstractTool]: ...  # line 635

# packages/ai-parrot/src/parrot/skills/store.py
class SkillRegistry:                                                      # line 126 (namespace "<org_id>/<agent_id>"; "_shared" reserved by FEAT-467, 139-140)
    def __init__(self, namespace="default", embedding_model: str | Any = "sentence-transformers/all-mpnet-base-v2", dimension=768, redis_url=None, persistence_path: Path | None = None, extraction_llm=None, min_diff_threshold=50): ...  # line 148
    async def configure(self, extraction_llm=None, embedding_model=None) -> None: ...  # line 202; sets self._embedding_model from the arg when given (213-215); FAISS IndexFlatIP per instance
    async def upload_skill(...)                                            # line 281
    async def search_skills(self, query, category=None, tags=None, include_deprecated=False, max_results=5) -> list[SkillSearchResult]: ...  # line 554
    async def get_relevant_skills(...) -> str                              # line 778
    async def list_skills(...)                                             # line 814
    # persistence: persistence_path / "skills.json", "versions.json"      # lines 885-903
    async def cleanup(self) -> None: ...                                   # line 926
def create_skill_registry(namespace: str, persistence_path: str | None = None, ...) -> SkillRegistry: ...  # line 934

# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class RenderPhase(str, Enum): CONFIGURE = "configure"; REQUEST = "request"   # line 35
@dataclass(frozen=True)
class PromptLayer:                                                        # line 51
    name: str; priority; template: str; phase: RenderPhase = REQUEST; condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str]; cacheable: Optional[bool] = None       # __post_init__: cacheable defaults to phase == CONFIGURE
    def render(self, context) -> Optional[str]: ...                       # line 82 (condition evaluated per call)
    def partial_render(self, context) -> PromptLayer: ...                 # line 96 (clears condition; ONLY applied to CONFIGURE layers)

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:                                                      # line 35
    def add(self, layer: PromptLayer) -> PromptBuilder: ...               # line 200 (self._layers[layer.name] = layer — replace-by-name)
    def remove(self, name: str) -> PromptBuilder: ...                     # line 212
    def get(self, name: str) -> Optional[PromptLayer]: ...                # line 242
    def configure(self, context) -> None: ...                             # line 268 (REQUEST-phase layers kept verbatim, 283)
    def build(self, context) -> str: ...                                  # line 288
    def build_segments(self, context) -> List[CacheableSegment]: ...      # line 317

# packages/ai-parrot/src/parrot/bots/abstract.py
def __init__(self, ...):                                                  # line 274; options consumed via kwargs.pop(...) (377-409) — NO generic setattr of unknown kwargs
def _build_prompt(self, user_context="", vector_context="", kb_context="", pageindex_context="", metadata=None, **kwargs): ...  # line 1451; **kwargs → request_context (1491-1500)
def create_system_prompt(...):                                            # _active_skill block at 3569-3593: adds PromptLayer("skill_active", priority=90, REQUEST) then remove + self._active_skill = None
async def session(self, ctx=None, *, request=None, app=None, llm=None, user_id=None, session_id=None, **ctx_kwargs): ...  # line 4203; _current_ctx token set 4322 / reset 4327
async def post_login(self, user_context: "UserContext") -> None: ...      # line 4426 (no-op; wrappers call it once per user)
async def clone_for_user(self, user_context) -> "AbstractBot": ...        # line 4448 (NotImplementedError)

# packages/ai-parrot/src/parrot/bots/base.py
async def ask(self, question, session_id=None, user_id=None, ..., ctx: Optional[RequestContext] = None, permission_context=None, a2ui_surface_state=None, structured_output=None, system_prompt=None, output_mode=OutputMode.DEFAULT, format_kwargs=None, use_tools=True, trace_context=None, **kwargs) -> AIMessage  # line 1037-1060
#   _agent_token = current_agent_name.set(self.name) (1093); ctx = _current_ctx.get() when None (1108); finally: current_agent_name.reset(_agent_token) (1806)
async def ask_stream(self, question, ..., use_tools=True, trace_context=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]  # line 1808-1829
#   _agent_token = current_agent_name.set(self.name) (1836); finally reset (2263)

# packages/ai-parrot/src/parrot/bots/mixins/narrative.py
class NarrativeMixin(SkillRegistryMixin):                                 # line 29
    def __init__(self, *args, **kwargs) -> None: super().__init__(*args, **kwargs)   # line 48 (cooperative pattern to copy)
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]: ...  # line 54
    async def _load_narrative_skill(self, name: str) -> Optional[SkillDefinition]: ...  # line 100 (self._configure_skill_registry() then _skill_file_registry.get_by_name)

# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py
tenant_id = getattr(self, "_tenant_id", "default")                       # line 809 (only existing reader of a bot-level _tenant_id)

# packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext: __init__(request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs) → self.kwargs  # line 7
_current_ctx: ContextVar[Optional[RequestContext]]                        # line 53
def current_context() -> Optional[RequestContext]: ...                    # line 58

# packages/ai-parrot/src/parrot/auth/context.py
@dataclass(frozen=True) class UserContext: channel; user_id; display_name=None; email=None; session_id=None; metadata: Dict[str, Any]  # line 39

# packages/ai-parrot/src/parrot/utils/paths.py
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")             # line 29
def validate_path_segment(value: str, name: str = "path segment") -> str: ...  # line 33 (no reserved-name check)
def secure_path(base, *segments, name="path segment") -> Path: ...        # line 52 (normpath containment + symlink-resolved containment)

# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession: user_id; tenant_id: str; roles                         # line 47
class PermissionContext: tenant_id property → self.session.tenant_id      # line 134
def build_principal_context(principal, ..., tenant_id: Optional[str] = None, ...) -> PermissionContext  # line 170 (tenant_id defaults to principal, 202)

# packages/ai-parrot-server/src/parrot/handlers/scope.py
class RequestScope: user_id: str | None; tenant: str | None; groups: frozenset[str]; is_superuser: bool; ...  # line 38
EMPTY_SCOPE = RequestScope(user_id=None, tenant=None, ...)               # line 61
class SessionScopeResolver: async def resolve(self, request) -> RequestScope  # line 73 / 82; tenant = programs_list[0] iff exactly one program (120)
def has_installed_resolver(app: Any) -> bool                              # line 135
def get_scope_resolver(app: Any) -> ScopeResolver                         # line 140
def scope_grants(*, tenant, visibility, allowed_groups, scope) -> bool    # line 153

# packages/ai-parrot-server/src/parrot/handlers/studio/access.py
async def studio_scope_kwargs(app, request, chatbot) -> dict              # line 73 ({"studio_scope": …} or {})

# packages/ai-parrot-server/src/parrot/handlers/chat.py
from .studio.access import studio_scope_kwargs                            # line 34
data = await self.request.json()                                          # line 397 (or handle_upload at 394)
stream = data.pop('stream', False)                                        # line 450
async with chatbot.session(request=self.request, app=app, llm=llm, **await studio_scope_kwargs(...)) as bot:  # line 454-455
method_params = {**method_params, **data}                                 # line 496 (custom-method dispatch)
async for event in await bot.ask_stream(question=..., ..., request=self.request, **data):  # line 530-540
response = await bot.ask(question=..., ..., request=self.request, **data)  # line 556-566

# packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py
async def ask_agent(self, query=None, prompt_file=None, *args, **kwargs) -> Tuple[AgentResponse, AIMessage]  # line 835
agent = self.request.app[self.agent_id]                                   # line 846
response = await agent.ask(question=query, use_conversation_history=False, use_vector_context=False, max_tokens=16000)  # line 886-891

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
@dataclass class TelegramAgentConfig: name; chatbot_id; bot_token=None; allowed_chat_ids=None; welcome_message=None; system_prompt_override: Optional[str] = None (74); kind="telegram"; ...  # line 42
    @classmethod from_dict(...): return cls(name=name, ..., system_prompt_override=data.get("system_prompt_override"), ...)  # line 270

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
self.config = config   # TelegramAgentConfig                               # line 134
@staticmethod def _build_permission_context(session, chat_id=None, bot_id=None) -> Any  # line 1265-1266; UserSession(user_id=..., tenant_id="default", roles=frozenset()) (1301-1304)
def _build_user_context(self, session) -> UserContext                     # line 1331; metadata keys: telegram_id, telegram_username, nav_user_id, jira_account_id, jira_cloud_id (1338-1348)
async def _invoke_agent(self, session, question, *, memory, output_mode=OutputMode.TELEGRAM, message=None, attachments=None)  # line 1450
permission_context = self._build_permission_context(session, chat_id=chat_id, bot_id=self._bot_id)  # line 1489 (only caller)
agent.ask(enriched, user_id=..., session_id=..., memory=memory, output_mode=output_mode, permission_context=permission_context, attachments=attachments)  # lines 1514-1521 and 1540-1547
def _list_agent_skills(self) -> list[dict]                                 # line 1938; reads agent._skill_file_registry.list_skills() (1954-1957) and agent._skill_registry._skills
self.agent._active_skill = skill_def                                      # line 2083 (/skill command) followed by self.agent.ask(question, output_mode=OutputMode.TELEGRAM) (2084)

# packages/ai-parrot/src/parrot/conf.py
AGENTS_DIR = config.get("AGENTS_DIR", fallback=BASE_DIR.joinpath("agents"))   # line 181
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `tenancy.validate_tenant_id` | `validate_path_segment` | call | `utils/paths.py:33` |
| `tenancy.tenant_skills_dir` | `secure_path` | call | `utils/paths.py:52` |
| `SkillView` | `SkillFileRegistry.get/get_by_name/list_skills/has_trigger/learned_dir` | delegation | `file_registry.py:108-142`, `:35` |
| `SkillRegistryMixin._load_tenant_skill_trees` | `SkillFileRegistry(skills_dir, learned_dir).load()` | constructor + await | `file_registry.py:29-41` |
| `SkillRegistryMixin._install_skill_prompt_layers` | `PromptBuilder.add` (replace-by-name) | call | `builder.py:200` |
| `SkillRegistryMixin._enter_skill_tenant` | `BaseBot.ask` / `ask_stream` | `getattr` hook after `current_agent_name.set` | `base.py:1093`, `:1836` |
| `SkillRegistryMixin._exit_skill_tenant` | same `finally` as `current_agent_name.reset` | call | `base.py:1806`, `:2263` |
| `SkillRegistryMixin._resolve_tenant` | `RequestContext.kwargs` | dict read | `helpers.py:7` |
| `create_system_prompt` | `tenancy.current_active_skill/set_active_skill`, `prompt.build_active_skill_layer`, `PromptBuilder.get` | lazy import + call | `abstract.py:3569-3593`, `builder.py:242` |
| `SkillFileToolkit._view` | `view_provider()` → `SkillView` | callable | `tools.py:398-407` |
| `SkillRegistryToolkit._registry` | `registry_provider()` → `SkillRegistry` | callable | `tools.py:90-98` |
| trigger middleware | `tenancy.set_active_skill` | call (replaces attribute write) | `middleware.py:64` |
| per-tenant `SkillRegistry` | `create_skill_registry(namespace, persistence_path, extraction_llm)` + `configure(embedding_model=...)` | call | `store.py:934`, `:202-215` |
| `resolve_request_tenant` | `has_installed_resolver`, `get_scope_resolver(app).resolve(request).tenant` | call | `scope.py:135`, `:140`, `:82` |
| `chat.py` | `bot.ask(..., tenant=)`, `bot.ask_stream(..., tenant=)` | kwarg | `chat.py:556`, `:530` |
| `ask_agent` | `agent.ask(..., tenant=)` | kwarg | `agents/abstract.py:886` |
| Telegram `_invoke_agent` | `agent.ask(..., tenant=self.config.tenant)` | kwarg | `wrapper.py:1514`, `:1540` |
| Telegram `_build_permission_context(tenant_id=)` | `UserSession(tenant_id=...)` | constructor | `wrapper.py:1301-1304`, caller `:1489` |
| Telegram `_list_agent_skills` | `agent.current_skill_view(tenant)` | duck-typed `getattr` | `wrapper.py:1954` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AGENTS_DIR/{agent_id}/skills.d/`~~ — no `skills.d` anywhere; the directory is `skills/`.
- ~~`AGENTS_DIR/{agent_id}/tenants/`~~ — no code references `tenants/` yet (new in M1).
- ~~`parrot.skills.tenancy`~~, ~~`SkillView`~~, ~~`TenantTreeReport`~~, ~~`validate_tenant_id`~~, ~~`tenant_skills_dir`~~, ~~`discover_tenant_dirs`~~, ~~`current_skill_tenant`~~, ~~`bind_skill_tenant`~~, ~~`set_active_skill`~~, ~~`current_active_skill`~~ — all new (M1).
- ~~`SkillRegistryMixin.tenant_based`~~, ~~`.tenant_id`~~, ~~`._tenant_registries`~~, ~~`._tenant_views`~~, ~~`._resolve_tenant()`~~, ~~`.current_skill_view()`~~, ~~`.known_tenants()`~~, ~~`.reload_tenant_skills()`~~, ~~`._enter_skill_tenant()`~~, ~~`._exit_skill_tenant()`~~, ~~`._install_skill_prompt_layers()`~~, ~~`._current_store_registry()`~~ — new (M3/M8).
- ~~`SkillRegistryMixin.__init__`~~ — the mixin has no `__init__` today (M3 adds the cooperative one; `NarrativeMixin.__init__` at narrative.py:48 is the pattern).
- ~~`AbstractBot._tenant_id`~~ — not defined on `AbstractBot`/`BaseBot`; `intent_router.py:809` reads it with a `"default"` fallback. (`_tenant_id` assignments found elsewhere belong to knowledge catalogs, msteams, sharepoint.)
- ~~`AbstractBot.__init__` generic `setattr` for unknown kwargs~~ — options are consumed with explicit `kwargs.pop(...)` (abstract.py:377-409); a `tenant_id=` constructor kwarg only works through the mixin `__init__`.
- ~~`RequestContext.tenant`~~, ~~`UserContext.tenant`~~ — neither has a tenant field; only `RequestContext.kwargs` and `UserContext.metadata` dicts.
- ~~`SkillFileRegistry.get_for_tenant()`~~, ~~`SkillDefinition.tenant`~~ — do not exist.
- ~~`SkillDefinition.global_only`~~ — new (M2); `parse_skill_file` ignores unknown frontmatter keys today.
- ~~`BaseBot.ask(tenant=...)`~~ / ~~`ask_stream(tenant=...)`~~ — `tenant` is not a named parameter today; it would land in `**kwargs` (M6 adds it).
- ~~`render_skills_prompt_layer(name=..., phase=..., condition=..., cacheable=...)`~~ — only `(registry, max_skills, priority)` today (M4).
- ~~`build_active_skill_layer()`~~ — new (M4).
- ~~`SkillFileToolkit(view_provider=...)`~~, ~~`SkillRegistryToolkit(registry_provider=...)`~~, ~~`create_skill_trigger_middleware(view_provider=...)`~~ — new keyword-only params (M5).
- ~~`PromptLayer` with a callable template~~ — `template` is a `str`; "render from the current view at request time" needs static per-view layers (design-research S4 rejected).
- ~~`validate_path_segment(value, *, what=...)`~~ — that keyword form is the *other* `validate_path_segment` in `knowledge/contracts/evidence.py:54`; the reusable one in `utils/paths.py:33` takes `name=`.
- ~~`validate_path_segment` reserved-name check~~ — it only enforces `SAFE_SEGMENT_RE`; reserved names are M1's job.
- ~~`docs/skills/`~~ — no such directory under `docs/` yet (M11 creates it).
- ~~`TelegramAgentConfig.tenant`~~ — no tenant field today (M10).
- ~~`UserContext.metadata["tenant"]`~~ — no wrapper sets this key today (M10 Telegram will).
- ~~`TelegramUserSession.programs` / `.tenant`~~ — the Navigator login payload parsed in `telegram/auth.py` carries `user_id`, `token`, `display_name`, `email`; no programs/tenant.
- ~~`parrot.handlers.scope` in core~~ — `RequestScope` / `SessionScopeResolver` live only in `ai-parrot-server`; core code must not import them (the mixin receives a plain `tenant` string).
- ~~`resolve_request_tenant()`~~ — new (M9).
- ~~`PermissionContext.tenant_id` as a trustworthy tenant~~ — exists (permission.py:134) but is `"default"` on Telegram and the principal id via `build_principal_context()`; not a source.
- ~~`SkillRegistry` namespace segment validation~~ — the store does not split or validate `namespace` (only documents `"_shared"`), so `org/agent/tenant` is accepted as-is.
- ~~`packages/ai-parrot-server/tests/unit/`~~ — server tests live in `packages/ai-parrot-server/tests/handlers/` (and siblings); integrations tests in `packages/ai-parrot-integrations/tests/telegram/`.

### Edit Sites (Blueprint Anchors)

Verified against: `c588e1ec3` (dev). `/sdd-task` MUST re-run the `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | `    assets_dir: Path \| None = Field(` | `models.py:77` | 1 |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | `    priority = int(metadata.get("priority", 90))` | `parsers.py:113` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    _active_skill: Optional[SkillDefinition] = None` | `mixin.py:80` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    async def _configure_skill_registry(self) -> None:` | `mixin.py:105` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    async def _configure_skill_file_registry(self) -> None:` | `mixin.py:141` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    async def save_learned_skill(` | `mixin.py:274` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    async def document_skill(` | `mixin.py:394` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    async def search_skills(` | `mixin.py:445` | 1 |
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | `    async def _cleanup_skill_registry(self) -> None:` | `mixin.py:473` | 1 |
| `packages/ai-parrot/src/parrot/skills/__init__.py` | MODIFY | `from .mixin import (` | `__init__.py:67` | 1 |
| `packages/ai-parrot/src/parrot/skills/__init__.py` | MODIFY | `    "SkillRegistryHooks",` | `__init__.py:109` | 1 |
| `packages/ai-parrot/src/parrot/skills/prompt.py` | MODIFY | `def render_skills_prompt_layer(` | `prompt.py:29` | 1 |
| `packages/ai-parrot/src/parrot/skills/middleware.py` | MODIFY | `def create_skill_trigger_middleware(` | `middleware.py:16` | 1 |
| `packages/ai-parrot/src/parrot/skills/middleware.py` | MODIFY | `            bot._active_skill = skill  # Set via closure reference` | `middleware.py:64` | 1 |
| `packages/ai-parrot/src/parrot/skills/tools.py` | MODIFY | `class SkillRegistryToolkit(AbstractToolkit):` | `tools.py:69` | 1 |
| `packages/ai-parrot/src/parrot/skills/tools.py` | MODIFY | `class SkillFileToolkit(AbstractToolkit):` | `tools.py:371` | 1 |
| `packages/ai-parrot/src/parrot/skills/tools.py` | MODIFY | `def create_skill_tools(` | `tools.py:635` | 1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `        use_tools: bool = True,` ⏎ `        trace_context=None,` ⏎ `        **kwargs,` ⏎ `    ) -> AIMessage:` (ask signature) | `base.py:1057-1060` | `trace_context=None,` ×4 — use the 4-line context |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `        trace_context=None,` ⏎ `        **kwargs,` ⏎ `    ) -> AsyncIterator[Union[str, AIMessage]]:` (ask_stream signature) | `base.py:1827-1829` | `) -> AsyncIterator[Union[str, AIMessage]]:` ×1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `        # FEAT-228: bind agent identity for per-agent cost/usage attribution.` ⏎ `        _agent_token = current_agent_name.set(self.name)` (ask body) | `base.py:1092-1093` | `_agent_token = current_agent_name.set(self.name)` ×4 (220, 667, 1093, 1836) — anchor by enclosing method |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `            current_agent_name.reset(_agent_token)  # FEAT-228` (ask `finally`) | `base.py:1806` | ×3 with the comment (844, 1806, 2263) — anchor by enclosing method |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | same two anchors inside `ask_stream` | `base.py:1836`, `:2263` | see above |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `            _has_active_skill = hasattr(self, "_active_skill") and self._active_skill is not None` | `abstract.py:3569` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/narrative.py` | MODIFY | `    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:` | `narrative.py:54` | 1 |
| `packages/ai-parrot/src/parrot/bots/mixins/narrative.py` | MODIFY | `    async def _load_narrative_skill(self, name: str) -> Optional[SkillDefinition]:` | `narrative.py:100` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/scope.py` | MODIFY | `def get_scope_resolver(app: Any) -> ScopeResolver:` | `scope.py:140` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | `        stream = data.pop('stream', False)` | `chat.py:450` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | `                        async for event in await bot.ask_stream(` | `chat.py:530` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/chat.py` | MODIFY | `                response = await bot.ask(` | `chat.py:556` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | MODIFY | `            response = await agent.ask(` | `agents/abstract.py:886` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `    system_prompt_override: Optional[str] = None` | `models.py:74` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `            system_prompt_override=data.get("system_prompt_override"),` | `models.py:270` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `            tenant_id="default",` | `wrapper.py:1303` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _build_user_context(self, session: TelegramUserSession) -> UserContext:` | `wrapper.py:1331` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    async def _invoke_agent(` | `wrapper.py:1450` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `                            permission_context=permission_context,` ⏎ `                            attachments=attachments,` (singleton branch) / `                permission_context=permission_context,` (per-user branch) | `wrapper.py:1520`, `:1546` | distinct indentation → 1 each |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _list_agent_skills(self) -> list[dict]:` | `wrapper.py:1938` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `                    self.agent._active_skill = skill_def` | `wrapper.py:2083` | 1 |
| `docs/skills/per-tenant-skills.md` | CREATE | — | — | — |
| `.agent/CONTEXT.md` | MODIFY | `### Skills` | `CONTEXT.md:122` | 1 |
| `packages/ai-parrot/tests/unit/test_skill_tenancy.py`, `test_skill_tenant_mixin.py`, `test_skill_tenant_prompt_layers.py`, `test_skill_active_request_local.py`, `test_skill_tenant_store.py`, `test_ask_tenant_binding.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **ContextVar scoping** exactly like `AbstractBot.session()` (`_current_ctx`, helpers.py:53) and FEAT-228 `current_agent_name` in `ask()`: bind after the agent-name token, reset in the same `finally`; the token is a local, never an attribute.
- **Cooperative mixin `__init__`**: copy `NarrativeMixin.__init__` (narrative.py:48) — pop own kwargs, then `super().__init__(*args, **kwargs)`. Set `self._tenant_id` only when a value is given so `intent_router.py:809`'s `"default"` fallback is preserved.
- **Provider callables, not registry instances**, for every consumer (S6). A consumer with `view_provider=None` must behave byte-identically to today.
- **Replace-by-name layer installs** (`PromptBuilder.add`, builder.py:200); never `remove()` per request. Layer names: `available_skills`, `available_skills:{tenant}`, `skill_active`.
- **Secure paths**: every tenant path through `secure_path(agent_root, "tenants", tenant, "skills")`; reserved names checked case-insensitively before any filesystem access; discovery skips (WARNING) anything that fails.
- **Lazy imports inside `create_system_prompt`** (the existing style at abstract.py:3571) to avoid `parrot.bots.abstract` ↔ `parrot.skills` import cycles; `mixin.py` imports no `parrot.bots` module (verified lines 14-21).
- **Logging** via `self.logger` / module logger; one INFO per tenant tree at configure (`tenant=%s skills=%d shadowing=%s dropped=%s`).
- **Async-first**: discovery and loading are `await`ed inside `configure()`; no blocking I/O in `ask()` (views are precomputed).
- Google docstrings + full type hints; `ruff check` (TID251 bans) gate; `black` 120 cols.

### Known Risks / Gotchas
- **Singleton race on `_active_skill` (S5, fixed here)**: do not keep the old add/remove block "for safety" — AC-P3 asserts the builder layer set is unchanged across a call.
- **Legacy attribute**: non-mixin bots may still set `_active_skill` directly (Telegram did); `create_system_prompt` keeps `getattr(self, "_active_skill", None)` as fallback (AC-A3). On a mixin bot the attribute is a property over the ContextVar, so `bot._active_skill = x` keeps working.
- **ContextVar and `asyncio.create_task`**: a task created inside `ask()` inherits the bound tenant (context copy) — intended. Thread-pool work does **not**; tools that offload must pass the view explicitly.
- **`ask_stream` generator lifetime**: the token must be reset in the generator's own `finally` (base.py:2263 region); tests cover early `aclose()` and exceptions.
- **Client-body `tenant` on HTTP** (S2): `chat.py:496` merges the remaining body into custom-method params — the pop at `:450` must happen before that branch. Any new handler that forwards `**data` must repeat the pattern (documented in M11).
- **`resolve_request_tenant` without Navigator session**: the resolver returns owner-only scope on any failure (scope.py:89) → `None` tenant → global view. Never raise.
- **Per-tenant store cost**: share `self._skill_registry._embedding_model` (a private attribute of the same package); creating registries before the global one is configured would load the sentence-transformers model N times.
- **`SkillRegistryToolkit.update_skill`** must route through `_registry()` too, or a tenant update would silently land in the global namespace.
- **`global_only` on learned skills**: ignored (learned frontmatter is generated by `save_learned_skill`; C8 applies).
- **Per-tenant layer count**: one static layer per tenant; with hundreds of tenants the builder holds hundreds of layers (each condition is O(1)). Documented follow-up: a single variable-fed layer.
- **Windows/case-insensitive filesystems**: reserved-name check is case-insensitive; tenant ids are compared as given otherwise (no normalisation).
- **Shared files with other features**: `bots/base.py` (`ask`/`ask_stream` signatures) and `bots/abstract.py` (`create_system_prompt`) — coordinate with any in-flight feature touching them; rebase before `/sdd-done`.
- **Worktree tests import the main checkout** unless `PYTHONPATH` lists the three `src` roots (memory: worktree-tests-run-main-checkout-code).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| stdlib `contextvars` | — | per-task tenant and active-skill transport |
| `python-frontmatter` | already a dependency | `global_only` parsing (unchanged usage) |
| `pydantic` | v2, already a dependency | `SkillDefinition.global_only` |

No new third-party dependency.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-707 (`feat-FEAT-707-per-tenant-skills`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M2 (`global_only`) has no edges — runs concurrently with everything.
  - M4 → M1 (imports `current_skill_tenant`, `SkillView` read API).
  - M5 → M1 (middleware imports `set_active_skill`; toolkits type against `SkillView`).
  - M6 has no edge to M1/M3 (duck-typed `getattr(self, "_enter_skill_tenant")`) — concurrent with M1–M5; its tests use a stub hook.
  - M7 → M1, M4 (imports `current_active_skill`, `set_active_skill`, `build_active_skill_layer`).
  - M3 → M1, M2, M4, M5, M8 (wires every provider, layer and store; `__init__.py` re-exports).
  - M8 → M1, M3 (lives in `mixin.py`; `tenant_skills_dir`).
  - M9 → M6 (needs the `tenant=` kwarg to exist in core before the handler tests pass against a real bot; unit tests with a fake bot can run earlier).
  - M10 → M1, M6 (`set_active_skill`, `tenant=` kwarg; `current_skill_view` is duck-typed).
  - M11 → all code modules (documents shipped names). M12 is split per module and travels with each.
- **Shared files**: `packages/ai-parrot/src/parrot/skills/mixin.py` is modified by M3 and M8 — their tasks serialize (or M8 is folded into M3's task set). `tools.py` and `middleware.py` are M5-only; `prompt.py` is M4-only; `base.py` is M6-only; `abstract.py` is M7-only; `wrapper.py` is M10-only (M7's Telegram edit at `:2083` is assigned to M10). `__init__.py` is M3-only.
- **Exclusive resources**: none (no extension rebuild, no lockfile, no migration).
- **Cross-feature dependencies**: none merged-first. No active task in `sdd/tasks/active/` touches `parrot/skills/` (checked at brainstorm time); `agent-skill-system` (FEAT-088) and `skills-tools-toolkit` (FEAT-207) are shipped. Watch for concurrent edits to `bots/base.py` `ask()` kwargs.

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → `dev`.
- [x] Directory layout — *Resolved in brainstorm*: `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`; global stays `skills/`; **no** `skills.d` rename.
- [x] Tenant lifetime — *Resolved in brainstorm*: both fixed-per-instance and per-request on a shared instance must work.
- [x] Tenant sources — *Resolved in brainstorm*: explicit kwarg, bot attribute, `RequestContext`/`UserContext.metadata`, ContextVar transport (all four); precedence kwarg > ctx/UserContext > bot attribute. (Spec refinement from design research S1/S3: `UserContext.metadata["tenant"]` is mapped by wrappers onto the explicit kwarg; the shared instance default is never mutated per user.)
- [x] Override semantics — *Resolved in brainstorm*: tenant shadows global by name/trigger; globals without override stay visible.
- [x] Learned skills — *Resolved in brainstorm*: always written to the global `skills/learned/`.
- [x] Loading strategy — *Resolved in brainstorm*: eager scan of `tenants/*` at `configure()`.
- [x] `store.py` scope — *Resolved in brainstorm*: in scope; namespace `org_id/agent_id/{tenant}`.
- [x] Unresolved tenant with `tenant_based=True` — *Resolved in brainstorm*: global-only view, no error (fail-closed to global), DEBUG log.
- [x] Unknown tenant id (valid name, no `tenants/{tenant}/` dir) — *Resolved in brainstorm*: warning once per tenant per instance + global view.
- [x] `global_only: true` frontmatter guard — *Resolved in brainstorm*: yes, in v1; a tenant skill colliding with a `global_only` global is dropped with an error log, global wins.
- [x] `document_skill` with an active tenant — *Resolved in brainstorm*: writes to the tenant namespace `org/agent/{tenant}` (global when no tenant); `extract_skills_from_conversation` stays global like learned skills.
- [x] `NarrativeMixin.narrate()` tenant — *Resolved in brainstorm*: explicit `tenant: str | None = None` parameter, falling back to the ContextVar and then the instance default.
- [x] Tenant key / channel plumbing — *Resolved in brainstorm*: key is `"tenant"` in both `RequestContext.kwargs` and `UserContext.metadata`; Telegram and the HTTP handlers populate it **in this feature**.
- [x] HTTP tenant source — *Resolved in brainstorm*: server-resolved `RequestScope.tenant` (single Navigator `program`) passed as `tenant=`; a `tenant` key in the client body is discarded and logged; no superuser override in v1.
- [x] Telegram tenant source — *Resolved in brainstorm*: new static `TelegramAgentConfig.tenant` (one bot = one customer) copied into `UserContext.metadata["tenant"]` and used as `UserSession.tenant_id` instead of `"default"`; bots without it are global-only.
- [x] Docs location — *Resolved in brainstorm*: new `docs/skills/per-tenant-skills.md` + a paragraph in the Skills section of `.agent/CONTEXT.md`.
- [x] Per-tenant `<available_skills>` layer cap — *Resolved in brainstorm*: one layer per tenant, no cap in v1; `skill_prompt_max_entries` bounds each layer; a single variable-fed REQUEST layer is the documented follow-up if tenant counts grow.
- [x] Q19. Request-local `_active_skill` (design-research S5) — *Resolved at spec time (user, 2026-10-19)*: fix in this feature (M7): ContextVar-backed `_active_skill`, permanent conditional `skill_active` layer, Telegram and middleware use `set_active_skill()`.
- [x] Q20. Per-tenant prompt layers vs. one dynamic layer (design-research S4) — *Resolved at spec time (author)*: keep per-tenant static REQUEST layers (verified that `PromptBuilder.configure()` preserves REQUEST-layer conditions and that `PromptLayer.template` is static); the brainstorm decision stands.
- [ ] Q21. Should `reload_tenant_skills()` also be exposed as an operator HTTP endpoint / Telegram operator command? — *Owner: Jesus Lara* (does not block implementation; v1 default: method only).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.163.0) · Status: completed
> · Transcript: `sdd/state/FEAT-707/design_research/`
> All 25 `affected_paths` passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make tenant resolution a first-class request scope (architecture) | CONFIRM | `tenant` is a named `ask()`/`ask_stream()` parameter consumed at the boundary; one resolver with fixed precedence bound for the whole call via ContextVar; wrappers map `UserContext.metadata["tenant"]` to the kwarg instead of attaching `UserContext` to `RequestContext`. | §2 Overview, M3, M6 |
| S2 | Enforce the HTTP tenant trust boundary centrally (risk) | CONFIRM | Verified `chat.py:496/540/566` forward the body and `ask_agent` never resolves a scope. New `resolve_request_tenant()`; both handlers drop a client `tenant` and pass the server one. | M9, AC-H1..H3 |
| S3 | Do not store Telegram user tenants on a shared agent (risk) | CONFIRM | Verified `wrapper.py:1301-1304`, `:1331`, `:1514/:1540`. Static `TelegramAgentConfig.tenant` passed per request; instance default never mutated by the wrapper or `post_login`. | M10, AC-T3 |
| S4 | Replace the proposed per-tenant prompt-layer set (architecture) | REJECT | Verified `builder.py:200-212` and `:268-287` / `layers.py:96-130`: name overwrite only for equal names (ours are distinct) and `condition` is cleared only for CONFIGURE layers; REQUEST layers keep it. `PromptLayer.template` is static, so "render from the view" needs a new layer type. Differing content ⇒ differing provider cache prefixes, so `cacheable=True` is safe. Kept from the suggestion: REQUEST phase, distinct names, ContextVar-reading condition. | §2 Overview, M4, §8 Q20 |
| S5 | Make active skills request-local before enabling singleton tenants (risk) | CONFIRM (user decision) | Verified `abstract.py:3569-3593`, `middleware.py:64`, `wrapper.py:2083`: shared mutable slot and per-request builder mutation ⇒ cross-tenant leak on a singleton. Fixed in M7. | M7, AC-A1..A3, AC-P3, §8 Q19 |
| S6 | Inject a current-view resolver into every skill consumer (architecture) | CONFIRM | Already Option A's intent; made explicit as `view_provider` / `registry_provider` callables on both toolkits, the middleware, `narrate()` and `_list_agent_skills()`. | M5, M10, AC-C1..C4 |
| S7 | Define the overlay collision matrix and implement `global_only` explicitly (api) | CONFIRM | Verified `parsers.py:60-130` ignores unknown keys and `file_registry.py:86` is per-tree first-wins. Collision matrix C1–C10 in §2; `global_only` in M2. | §2 Collision matrix, M1, M2, AC-V2/V4 |
| S8 | Treat DB-backed skills as a separate overlay design problem (architecture) | CONFIRM | Verified `store.py:148-160` (`embedding_model` accepts an object) and `search_skills` (single index). Decided: shared embedding model; merge-before-limit with tenant-wins de-dup and `namespace` tag; context = tenant first, global when empty; writes tenant-side. | M8, AC-S1..S5 |
| S9 | Use secure path construction for tenant directories (risk) | CONFIRM | Verified `paths.py:33` lacks reserved names and `secure_path` (`:52`) resolves symlinks. `validate_tenant_id()` + `tenant_skills_dir()` via `secure_path`; discovery skips failures. | M1, AC-R2, §7 |
| S10 | Add concurrency and isolation tests before rollout (testing) | CONFIRM | `asyncio.gather` two-tenant runs, ContextVar reset on exception/cancellation, name/trigger/asset isolation, warning de-dup, HTTP body rejection, Telegram binding, store fallback/update routing. | §4, AC-V1/V3 |
| S11 | Specify prompt invalidation for learned global skills (risk) | CONFIRM | Verified `prompt.py:29-100` snapshots `list_skills()` once. `save_learned_skill()` recomposes views and re-installs the layers. | M3, AC-L2 |

Summary: **10** confirmed · **1** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-19 | Jesus Lara (with Claude) | Initial draft from the accepted brainstorm; design research folded in; S5 scope decided by the user |
