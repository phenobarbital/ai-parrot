---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-integrations]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [skills, multi-tenant, skill-registry, agents-dir, prompt-layer]
---

# Brainstorm: Per-Tenant Skills for `SkillRegistryMixin`

**Date**: 2026-10-19
**Author**: Jesus Lara (discovery with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`SkillRegistryMixin` loads an agent's skills from one place:
`AGENTS_DIR/{agent_id}/skills/` (authored, incl. composite `{name}/SKILL.md`)
plus the reserved `skills/learned/` subdirectory. That tree is loaded **once**
at `configure()` and is shared by every caller of the bot.

Some behaviours are the *same skill* with a *tenant-specific variant*: the
Revenue of one customer is not computed against the same accounting accounts
as the Revenue of another. `agents/troc_finance/skills/` already contains
exactly this family (`revenue_by_division`, `ebitda_breakdown`,
`ebitda_by_division`, `financial_projection_*`). Today the only way to serve
two tenants is a single skill carrying every variation — easy for the LLM to
confuse — or one agent per tenant with copied skill trees.

User's framing (verbatim, Spanish):

> en vez de hacer un skill único con todas las variaciones (y que podrían
> confundirse fácilmente) se aporta el tenant como parte de un argumento de
> cada método del SkillMixin y entonces el "Revenue de Pokemon", buscaría el
> Skill en `$AGENTS_DIR/{agent_id}/{tenant=pokemon}/skills.d/`, para mantener
> la compatibilidad hacia atrás el per-tenant skill debe ser un flag activable
> per-agent, si `tenant_based: bool = True`, los skills se buscarán en el
> per-tenant directory of skills, cayendo en fallback a
> `$AGENTS_DIR/{agent_id}/skills.d/` para global skills.

**Affected**: agent authors who serve several customers from one agent
(finance / reporting agents first), and operators who deploy one agent
instance per environment. **Why now**: very few agents use skills yet
(7 `agents/*/skills/` trees locally, 3 code consumers of the mixin), so the
layout decision is cheap today and expensive later.

### Premise correction found during discovery

The code does **not** use `skills.d`. The directory is `skills/`
(`mixin.py:160`, `file_registry.py:4`), and it already hosts two things that a
rename would have to drag along: the reserved `learned/` subdirectory and the
`skills.json` / `versions.json` files the DB-like `SkillRegistry` persists at
`agents_dir / agent_id / "skills"` (`mixin.py:120`, `store.py:885-903`). The
"hard-cut rename to `skills.d`" was proposed only to stop a tenant named
`skills` from shadowing the global directory. The user accepted the alternative
below (reserved `tenants/` namespace), so **no rename happens**.

## Constraints & Requirements

- **Opt-in, backwards compatible**: a new per-agent flag `tenant_based: bool`
  (default `False`). With the flag off, behaviour is byte-for-byte today's.
- **Layout** (decided): global tree stays `AGENTS_DIR/{agent_id}/skills/`;
  tenant trees live at `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`.
  A tenant id can never collide with `skills/`, `prompts/`, `queries/`, `kb/`,
  `documents/`, `flows/`, `_drafts/`.
- **Resolution** (decided): tenant view = tenant tree **shadowing** the global
  tree by skill `name` and by `/trigger`; global skills without a tenant
  override remain visible (fallback). A tenant must never see another tenant's
  skills.
- **Lifetime** (decided): both modes must work — tenant fixed per bot
  instance *and* tenant varying per request on a shared (singleton) instance.
- **Tenant sources** (decided, precedence high → low): explicit `tenant=`
  kwarg on `ask()` / `ask_stream()` / mixin methods → `RequestContext` /
  `UserContext.metadata["tenant"]` → bot attribute `self._tenant_id`
  (constructor kwarg / `post_login`) → unresolved. A per-request `ContextVar`
  is the **internal transport** so LLM-called tools (`load_skill`,
  `list_skill_commands`, `read_skill_asset`) and the `/trigger` middleware
  read the already-resolved tenant.
- **Unresolved tenant with `tenant_based=True`** → global-only view, no error
  (fail-closed to global, never to another tenant). *Assumption to confirm —
  see Open Questions.*
- **Loading** (decided): **eager** — `tenants/*/skills/` is scanned at
  `configure()`; adding a tenant on disk needs a restart or an explicit
  reload method.
- **Learned skills** (decided): `save_learned_skill` always writes to the
  **global** `skills/learned/`, regardless of the active tenant. Learned skills
  are therefore visible to every tenant.
- **Scope** (decided): both registries — the file-based `SkillFileRegistry`
  **and** the DB-like `SkillRegistry` in `store.py` (namespace becomes
  `org_id/agent_id/{tenant}` with per-tenant persistence under the tenant
  tree; search falls back to the global namespace).
- Tenant ids are untrusted input: validate as a single safe path segment
  (reuse `parrot.utils.paths.validate_path_segment`) and reject reserved
  names (`learned`, `tenants`, `skills`, …).
- No new third-party dependencies. Async-first, `aiohttp` only, Pydantic v2.
- Explicit `skill_paths` (FEAT-188 directory discovery) stay global.

---

## Options Explored

### Option A: Composed tenant views over per-tree registries (overlay)

Keep one `SkillFileRegistry` per *tree*: the global one (today's) plus one per
discovered `tenants/{tenant}/skills/`. A small resolver composes a **read-only
view** per call — "tenant registry first, then global" — exposing the same
read API (`get`, `get_by_name`, `list_skills`, `has_trigger`). The mixin owns
a `_resolve_tenant()` (precedence above), binds the result to a `ContextVar`
for the duration of `ask()` / `ask_stream()`, and every consumer (toolkit,
middleware, prompt layer, `narrate()`) asks the mixin for *the current view*
instead of touching `_skill_file_registry` directly. The `<available_skills>`
block is rendered per tenant at `configure()` (eager) and selected per request
through the existing `PromptLayer.condition` mechanism (one REQUEST-phase
layer per tenant plus the global one; explicitly `cacheable=True`).

✅ **Pros:**
- Isolation is structural: a view never contains another tenant's skills, so
  no consumer can leak by forgetting a filter.
- Zero change to `SkillFileRegistry` semantics; existing tests keep passing.
  The global registry is literally today's object.
- Both lifetimes fall out naturally: fixed-tenant instances just resolve the
  same tenant every time; singleton instances resolve per request.
- Shadowing by name/trigger is a view-level rule, trivially testable.
- Reload-per-tenant is possible later without redesign.

❌ **Cons:**
- N+1 registries in memory (negligible: skills are ≤1000 tokens each).
- Every consumer that reads `_skill_file_registry` must switch to the view
  (`tools.py`, `middleware.py`, `prompt.py`, `narrative.py`, telegram
  `_list_agent_skills`); a missed caller silently stays global-only
  (safe direction, but a functional gap).
- Per-tenant prompt layers multiply the prompt-builder layer count by the
  number of tenants (fine for tens, questionable for hundreds).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| stdlib `contextvars` | per-task tenant transport | same pattern as `parrot.utils.helpers._current_ctx` and FEAT-525 `read_omitted_content` |
| `python-frontmatter` (already a dep) | skill parsing | unchanged |
| `pydantic` v2 (already a dep) | `TenantSkillConfig` / view models | unchanged |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/skills/file_registry.py` — `SkillFileRegistry` as the per-tree primitive (unchanged).
- `packages/ai-parrot/src/parrot/skills/parsers.py:162` — `discover_skills_in_dir()` for each tenant tree.
- `packages/ai-parrot/src/parrot/skills/mixin.py:141` — `_configure_skill_file_registry()` grows the tenant scan + view wiring.
- `packages/ai-parrot/src/parrot/bots/prompts/layers.py:51` — `PromptLayer.condition` for per-tenant `<available_skills>` selection.
- `packages/ai-parrot/src/parrot/utils/helpers.py:53-58` — `_current_ctx` / `current_context()` precedent for ContextVar scoping.
- `packages/ai-parrot/src/parrot/utils/paths.py:33` — `validate_path_segment()` for tenant ids.
- `packages/ai-parrot/src/parrot/skills/store.py:934` — `create_skill_registry(namespace, persistence_path)` instantiated once per tenant namespace.

---

### Option B: Single registry with tenant-qualified keys

Teach `SkillFileRegistry` about tenants directly: add `tenant: str | None` to
`SkillDefinition`, index by `(tenant, name)` and `(tenant, trigger)`, and give
every lookup an optional `tenant=` argument that tries `(tenant, key)` then
`(None, key)`. One registry, one `load()` that walks `skills/` and
`tenants/*/skills/`.

✅ **Pros:**
- One object, one load, one place to reason about collisions.
- `list_skills(tenant=…)` and the prompt layer can be computed on demand.

❌ **Cons:**
- Isolation is by discipline, not by construction: every existing call site
  that calls `list_skills()` / `get()` without a tenant (telegram wrapper,
  `/skills` listing, prompt layer, `narrate()`) now returns a **cross-tenant
  union** unless it is found and fixed — the unsafe direction.
- Changes `SkillDefinition`, `_register()` collision rules and every
  registry test; `add()` for learned skills needs a tenant-aware contract.
- `SkillsDirectoryLoader.load_into()` and FEAT-188 `skill_paths` would need a
  tenant too, or be documented as global-only in a registry that is not.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | `SkillDefinition.tenant` field | model change ripples into parsers/tests |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/skills/file_registry.py:86` — `_register()` becomes tenant-keyed.
- `packages/ai-parrot/src/parrot/skills/models.py:60` — `SkillDefinition` gains `tenant`.

---

### Option C: One bot instance per tenant (`clone_for_user` + `_tenant_id`)

No registry changes beyond the path. A tenant is bound at construction
(`tenant_id=` kwarg) or in `post_login()` via `UserContext.metadata`, the
mixin loads `tenants/{tenant}/skills/` over `skills/` into today's single
registry (tenant files registered first so `_register()`'s "first wins" rule
gives shadowing for free), and integrations run in full-clone mode.

✅ **Pros:**
- Smallest diff; the prompt layer, middleware and tools are untouched.
- Matches the existing `intent_router` convention (`getattr(self, "_tenant_id", "default")`).

❌ **Cons:**
- Does **not** satisfy the decided requirement that a shared singleton must
  serve several tenants per request.
- `clone_for_user()` raises `NotImplementedError` by default
  (`abstract.py:4448`); every tenant-aware agent would have to implement it.
- Memory and configure cost scale with tenants × users.

📊 **Effort:** Low

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/abstract.py:4426` — `post_login(user_context)` hook.
- `packages/ai-parrot/src/parrot/skills/file_registry.py:86` — `_register()` first-wins rule.

---

### Option D (unconventional): Tenant declared in skill frontmatter, single directory

No tenant directories at all. A skill file declares `tenants: [pokemon]` (or
`tenant: pokemon`) in its YAML frontmatter; files without the field are
global. Resolution filters the single registry by the declared tenant with
global fallback. Variants of the same skill coexist as separate files
(`revenue_by_division.pokemon.md`, `revenue_by_division.md`).

✅ **Pros:**
- Zero filesystem layout questions, zero reserved-name problem.
- A skill can serve several tenants (`tenants: [a, b]`) without copies.

❌ **Cons:**
- Puts every tenant's variant side by side in one folder — exactly the
  "easy to confuse" situation the user wants to avoid, now for humans
  editing the tree.
- Two files with the same `name:` in one directory trip today's duplicate
  rules (`_register()`), so names or the collision rule must change.
- Tenant-specific assets of composite skills (`{name}/SKILL.md` + files)
  cannot be separated per tenant.
- Learned skills would need frontmatter injection to stay global.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | read the `tenants` key | already used by `parse_skill_file()` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/skills/parsers.py:60` — `parse_skill_file()` frontmatter parsing.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies **all** decided constraints: shadowing
  by name/trigger, strict isolation, both lifetimes, eager loading and a
  per-request tenant from four sources.
- Isolation is enforced by construction (a view *is* the tenant), which is
  the property that matters for a multi-customer finance agent. Option B's
  "every caller must remember the filter" is the wrong default for
  accounting data; Option C cannot do per-request tenants; Option D
  reintroduces the confusion the feature exists to remove.
- It leaves `SkillFileRegistry` untouched, so the existing unit and
  integration tests (`test_skill_file_registry.py`, `test_skill_system.py`,
  loader/middleware/prompt-layer tests) stay green and only *new* tests are
  needed for the view, the resolver and the mixin wiring.
- The trade-off accepted: a handful of consumers must be migrated from
  `_skill_file_registry` to "the current view", and the prompt builder holds
  one `<available_skills>` layer per tenant. Both are bounded by the number of
  tenants, which for this use case is small.

**On the `skills.d` hard-cut**: rejected in favour of a reserved `tenants/`
namespace (user accepted). Rationale: the rename only protected against a
tenant literally named `skills`, while a tenant named `prompts`, `queries` or
`kb` would still have collided with other per-agent folders; `tenants/` closes
the whole class, and a reserved-name check on tenant ids (`learned`,
`tenants`, `skills`, `prompts`, `queries`, `kb`, `documents`, `flows`,
`_drafts`) closes the inverse case. No migration of the 7 existing trees, no
change to `store.py` persistence paths for the global tree.

---

## Feature Description

### User-Facing Behavior

- Agent author sets `tenant_based = True` on an agent that already mixes in
  `SkillRegistryMixin` (class attribute or constructor kwarg, like
  `skill_paths`). Nothing else changes for agents that do not.
- Directory layout per agent:
  ```
  agents/troc_finance/
  ├── skills/                        ← global tree (fallback), unchanged
  │   ├── revenue_by_division/SKILL.md
  │   ├── ebitda_breakdown/SKILL.md
  │   └── learned/                   ← ALL learned skills, every tenant
  └── tenants/
      ├── pokemon/skills/
      │   └── revenue_by_division/SKILL.md   ← shadows the global one for pokemon
      └── epson/skills/
          └── revenue_by_division.md
  ```
- A caller supplies the tenant in any of these ways (highest precedence
  first): `await agent.ask("...", tenant="pokemon")`; a `RequestContext`
  built by the handler (FEAT-421 `requires_tenant()` pattern, `ctx.kwargs
  ["tenant"]`) or `UserContext.metadata["tenant"]` at `post_login`; a bot-level
  default `tenant_id="pokemon"` set at construction. With no tenant at all the
  agent behaves as global-only.
- For that request: `<available_skills>` lists the pokemon view (pokemon
  overrides + un-overridden globals); `/revenue_by_division` and
  `load_skill(name="revenue_by_division")` resolve to the pokemon file;
  `/skills` and `list_skill_commands` list the pokemon view; `read_skill_asset`
  reads assets from the pokemon composite skill. The epson variant is
  invisible.
- `save_learned_skill` writes to `skills/learned/` and the new skill is
  immediately visible to every tenant.
- `search_skills` / `document_skill` (DB-like registry) operate on the
  `org/agent/pokemon` namespace with fallback search into `org/agent`.
- Logging at configure: one line per tenant tree loaded (`tenant=pokemon, 3
  skills, 1 shadowing global`) so operators can audit overrides.

### Internal Behavior

1. **Configure (eager)**: `_configure_skill_file_registry()` loads the global
   `SkillFileRegistry` exactly as today. When `tenant_based` is on and
   `agents_dir` resolves, it lists `AGENTS_DIR/{agent_id}/tenants/*/`, validates
   each directory name as a tenant id, and builds one `SkillFileRegistry` per
   `tenants/{tenant}/skills/` (no `learned/` inside tenant trees is created or
   scanned). Results go into a `tenant → registry` map on the mixin.
2. **View composition**: a read-only composite exposing the `SkillFileRegistry`
   read API; `get(trigger)` / `get_by_name(name)` try the tenant registry then
   the global; `list_skills()` returns tenant skills plus globals whose name
   is not shadowed; `has_trigger()` follows the same rule. The global view is
   the global registry itself.
3. **Tenant resolution**: `_resolve_tenant(explicit, ctx, user_context)`
   applies the precedence (explicit kwarg → `RequestContext` kwargs /
   `UserContext.metadata` → `self._tenant_id` → `None`), validates the id and
   rejects unknown tenants by falling back to global with a warning (not an
   error — see Open Questions). `ask()` / `ask_stream()` set a module-level
   `ContextVar` for the call's lifetime (same pattern as `session()` with
   `_current_ctx`), reset in `finally`.
4. **Consumers read the view**: `SkillFileToolkit`, the trigger middleware,
   `NarrativeMixin.narrate()`, the telegram wrapper's `_list_agent_skills()`
   and the prompt layer all obtain the registry through one mixin accessor
   (`current_skill_view()`), which reads the ContextVar and falls back to the
   instance default. Toolkits keep holding the mixin-provided accessor rather
   than a registry instance.
5. **Prompt layer**: at configure, `render_skills_prompt_layer()` is called
   once per view (global + each tenant). Each result is registered as a
   REQUEST-phase `PromptLayer` with a `condition` on the request-context
   `skills_tenant` variable (which `_build_prompt(**kwargs)` already forwards),
   `cacheable=True` so FEAT-181 prompt caching is unaffected. Layer names are
   `available_skills` (global) and `available_skills:{tenant}`.
6. **DB-like registry**: `_configure_skill_registry()` creates the global
   `SkillRegistry` as today plus one per tenant with namespace
   `{org_id}/{agent_id}/{tenant}` and `persistence_path =
   tenants/{tenant}/skills/`. `search_skills` / `get_skill_context` query the
   tenant registry first and merge global results; `document_skill` writes to
   the tenant registry when a tenant is active (the DB-like counterpart of
   authored skills), while `extract_skills_from_conversation` follows the
   learned rule (global).
7. **Reload**: an explicit `reload_tenant_skills(tenant=None)` method rescans
   one or all tenant trees (the "add a tenant without restart" escape hatch
   the eager decision implies).

### Edge Cases & Error Handling

- `tenant_based=False` (default): every tenant argument is ignored with a
  single debug log; no tenant scan; no ContextVar set; behaviour identical to
  today.
- `tenant_based=True` but `_resolve_agents_dir()` is `None` (FEAT-188
  `skill_paths`-only agents): tenant trees cannot exist; warn once at
  configure and run global-only.
- Unknown tenant (no `tenants/{tenant}/` directory): global view + warning
  per request (rate-limited to once per tenant per instance).
- Invalid tenant id (`..`, `/`, empty, reserved name): `ValueError` from the
  resolver → `ask()` fails fast; never touches the filesystem.
- Tenant skill with same `name` as global: tenant wins (shadow), logged at
  configure. Tenant skill with same `/trigger` but different `name` as a
  global skill: tenant wins for that trigger within the view; global skill
  remains reachable by `load_skill(name=…)`.
- Two tenants declaring the same trigger: independent, no collision.
- Malformed skill in a tenant tree: skipped with a warning (today's
  `discover_skills_in_dir` contract); the tenant still loads the rest.
- `learned/` directory inside a tenant tree: ignored and warned (reserved).
- Concurrency: the ContextVar is per asyncio task; concurrent `ask()` calls
  for different tenants on one singleton instance cannot cross.
- Streaming: `ask_stream()` must hold the ContextVar for the whole generator
  lifetime (tools fire mid-stream).
- `save_learned_skill` name collision check runs against the **global**
  registry only (learned skills are global) — a tenant-only authored skill
  with the same name is allowed and shadows the learned one within that tenant.
- `cleanup`: `_cleanup_skill_registry()` closes every per-tenant
  `SkillRegistry`.

---

## Capabilities

### New Capabilities
- `tenant-skill-resolution`: precedence-based tenant resolver + per-task
  ContextVar transport, `tenant_based` flag, tenant-id validation and
  reserved-name list.
- `tenant-skill-views`: eager discovery of `tenants/{tenant}/skills/` trees
  into per-tenant `SkillFileRegistry` instances and the read-only shadowing
  view over tenant + global.
- `tenant-aware-skill-prompt-layer`: per-tenant `<available_skills>`
  REQUEST-phase layers selected by condition, cache-eligible.
- `tenant-scoped-skill-store`: per-tenant `SkillRegistry` namespaces
  (`org/agent/tenant`) with global fallback for search/context and
  tenant-local persistence.

### Modified Capabilities
- `skills-tools-toolkit` (FEAT-207, `sdd/specs/skills-tools-toolkit.spec.md`):
  `SkillFileToolkit` tools read the current tenant view; `save_learned_skill`
  explicitly documented as global.
- `skill-registry` (`sdd/specs/skill-registry.spec.md`): trigger middleware
  and `/skills` listing become view-based; `SkillRegistryMixin` gains the
  tenant surface.
- `finance-reporter-tier2-narrative` (`NarrativeMixin.narrate`): resolves the
  skill through the view (tenant-aware narration).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/skills/mixin.py` (`SkillRegistryMixin`) | modifies | `tenant_based`, `tenant_id`, `_resolve_tenant()`, `current_skill_view()`, tenant scan in `_configure_skill_file_registry()`, per-tenant `SkillRegistry` in `_configure_skill_registry()`, `reload_tenant_skills()` |
| `parrot/skills/file_registry.py` | depends on | unchanged API; used as the per-tree primitive |
| new `parrot/skills/tenancy.py` (name TBD in spec) | extends | resolver, ContextVar, reserved names, composite view |
| `parrot/skills/tools.py` (`SkillFileToolkit`, `SkillRegistryToolkit`, `create_skill_tools`) | modifies | accept a view accessor; `save_learned_skill` stays global |
| `parrot/skills/middleware.py` | modifies | `registry` becomes a view accessor so `/trigger` and `/skills` are per tenant |
| `parrot/skills/prompt.py` | extends | layer name/condition parameters for per-tenant layers |
| `parrot/skills/store.py` (`SkillRegistry`, `create_skill_registry`) | depends on | one instance per tenant namespace; no behavioural change expected inside |
| `parrot/bots/base.py` `ask()` / `ask_stream()` | modifies | accept `tenant=` kwarg and bind the ContextVar around the call (cooperative hook, same shape as `session()`) |
| `parrot/bots/mixins/narrative.py` | modifies | `narrate()` resolves via the view |
| `parrot/integrations/telegram/wrapper.py` `_list_agent_skills()` | modifies | lists the tenant view when the wrapper knows the tenant (`UserContext.metadata`) |
| `parrot/bots/studio/agent.py` (`AgentStudioAgent`) | none | `skill_paths`-only consumer; `tenant_based` stays off |
| `agents/*/skills/` trees (gitignored) | none | no migration; `tenants/` is additive |
| docs (`docs/skills/…`, `.agent/CONTEXT.md` Skills section) | extends | document the layout and precedence |
| tests `packages/ai-parrot/tests/unit/test_skill_*`, `tests/unit/test_skills_*` | extends | new view/resolver/mixin/prompt-layer tests; existing ones unchanged |

Breaking changes: none with the flag off. New dependencies: none.
Deployment: operators create `tenants/{tenant}/skills/` next to existing trees.

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (invocation notes, verbatim path proposal — NOT adopted)
$AGENTS_DIR/{agent_id}/{tenant=pokemon}/skills.d/     # per-tenant (proposed)
$AGENTS_DIR/{agent_id}/skills.d/                      # global fallback (proposed)
tenant_based: bool = True                             # per-agent activation flag
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/skills/mixin.py:27
class SkillRegistryMixin:
    enable_skill_registry: bool = True                       # line 57
    skill_paths: List[Path] = []                             # line 65
    inject_skills_into_prompt: bool = True                   # line 69
    _skill_registry: Optional[SkillRegistry] = None          # line 78
    _skill_file_registry: Optional["SkillFileRegistry"] = None  # line 79
    _active_skill: Optional[SkillDefinition] = None          # line 80
    def _resolve_agents_dir(self) -> Optional[Path]: ...     # line 82 (self._agents_dir → parrot.conf.AGENTS_DIR)
    async def _configure_skill_registry(self) -> None: ...   # line 105; namespace f"{org_id}/{agent_id}", persistence_path = agents_dir / agent_id / "skills" (line 120)
    async def _configure_skill_file_registry(self) -> None: ...  # line 141; skills_dir = agents_dir / agent_id / "skills" (line 160), learned_dir = skills_dir / "learned"
    async def save_learned_skill(self, name, content, description, triggers, category="general") -> Optional[SkillDefinition]: ...  # line 274
    async def _add_skill_tools(self) -> None: ...            # line 347
    async def get_skill_context(self, query, max_skills=None, max_tokens=None) -> str: ...  # line 374
    async def _cleanup_skill_registry(self) -> None: ...     # line 473

# From packages/ai-parrot/src/parrot/skills/file_registry.py:17
class SkillFileRegistry:
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None: ...  # line 29
    async def load(self) -> None: ...                        # line 41 (authored excludes "learned"; name collisions → both skipped)
    def _register(self, skill: SkillDefinition) -> None: ... # line 86 (duplicate name / trigger → error log, first wins)
    def get(self, trigger: str) -> Optional[SkillDefinition]: ...        # line 108
    def get_by_name(self, name: str) -> Optional[SkillDefinition]: ...   # line 119
    def add(self, skill: SkillDefinition) -> None: ...       # line 130
    def list_skills(self) -> List[SkillDefinition]: ...      # line 138
    def has_trigger(self, trigger: str) -> bool: ...         # line 142

# From packages/ai-parrot/src/parrot/skills/loader.py:26
class SkillsDirectoryLoader:
    def __init__(self, paths: List[Path], logger: Optional[Logger] = None) -> None: ...  # line 54
    async def discover(self) -> List[SkillDefinition]: ...   # line 62
    async def load_into(self, registry: SkillFileRegistry) -> int: ...  # line 80

# From packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition: ...          # line 60
def parse_skill_directory(skill_dir: Path) -> SkillDefinition: ...     # line 132
def discover_skills_in_dir(directory: Path, logger=_LOGGER, exclude_names: Iterable[str] = ()) -> List[SkillDefinition]: ...  # line 162 (non-recursive)

# From packages/ai-parrot/src/parrot/skills/prompt.py:29
def render_skills_prompt_layer(registry: SkillFileRegistry, max_skills: Optional[int] = None, priority: int = 45) -> PromptLayer: ...
# returns PromptLayer(name="available_skills", phase=RenderPhase.CONFIGURE)

# From packages/ai-parrot/src/parrot/skills/middleware.py:16
def create_skill_trigger_middleware(registry: SkillFileRegistry, bot: "AbstractBot", priority: int = -10) -> PromptMiddleware: ...
# reserved triggers "/skills", "/help"; sets bot._active_skill via closure

# From packages/ai-parrot/src/parrot/skills/tools.py
class SkillRegistryToolkit(AbstractToolkit):                            # line 69
    def __init__(self, registry: SkillRegistry, agent_id: str, include_write_tools: bool = True, **kwargs) -> None: ...  # line 90
class SkillFileToolkit(AbstractToolkit):                                # line 371
    def __init__(self, file_registry: "SkillFileRegistry", learned_dir: Optional[Path] = None, max_asset_bytes: int = 64 * 1024, **kwargs) -> None: ...  # line 398
    async def list_skill_commands(self) -> ToolResult: ...              # line 413
    async def load_skill(self, name: str) -> ToolResult: ...            # line 454
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult: ...  # line 491
    async def save_learned_skill(...) -> ToolResult: ...                # line 543
def create_skill_tools(registry: SkillRegistry, agent_id: str, include_write_tools: bool = True, file_registry: Optional["SkillFileRegistry"] = None, learned_dir: Optional[Path] = None) -> List[AbstractTool]: ...  # line 635

# From packages/ai-parrot/src/parrot/skills/store.py
class SkillRegistry:                                                     # line 126 (namespace "<org_id>/<agent_id>"; "_shared" reserved by FEAT-467)
    def __init__(self, namespace: str = "default", embedding_model=..., dimension: int = 768, redis_url: str | None = None, persistence_path: Path | None = None, extraction_llm=None, min_diff_threshold: int = 50): ...  # line 148
    async def upload_skill(...)                                          # line 281
    async def search_skills(...)                                         # line 554
    async def get_relevant_skills(...)                                   # line 778
    async def list_skills(...)                                           # line 814
    # persistence: persistence_path / "skills.json", "versions.json"     # lines 885-903
def create_skill_registry(namespace: str, persistence_path: str | None = None, ...) -> SkillRegistry: ...  # line 934

# From packages/ai-parrot/src/parrot/skills/models.py:60
class SkillDefinition(BaseModel):
    name: str; description: str; triggers: list[str]
    source: SkillSource = SkillSource.AUTHORED; priority: int = 90; version: str = "1.0"
    category: str | None = None; template_body: str; token_count: int; file_path: Path
    assets_dir: Path | None = None
    MAX_TOKENS: ClassVar[int] = 1000
class SkillSource(str, Enum): AUTHORED = "authored"; LEARNED = "learned"   # line 53

# From packages/ai-parrot/src/parrot/bots/prompts/layers.py
class RenderPhase(str, Enum): CONFIGURE = "configure"; REQUEST = "request"   # line 35
@dataclass(frozen=True)
class PromptLayer:                                                           # line 51
    name: str; priority: LayerPriority | int; template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = frozenset(); cacheable: Optional[bool] = None
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...          # line 82 (condition evaluated here)

# From packages/ai-parrot/src/parrot/bots/prompts/builder.py:35
class PromptBuilder:
    def add(self, layer: PromptLayer) -> PromptBuilder: ...     # line 200
    def remove(self, name: str) -> PromptBuilder: ...           # line 212
    def get(self, name: str) -> Optional[PromptLayer]: ...      # line 242
    def build(self, context: Dict[str, Any]) -> str: ...        # line 288
    def build_segments(self, context: Dict[str, Any]) -> List[CacheableSegment]: ...  # line 317

# From packages/ai-parrot/src/parrot/bots/abstract.py
def _build_prompt(self, user_context="", vector_context="", kb_context="", pageindex_context="", metadata=None, **kwargs): ...  # line 1451; **kwargs forwarded into request_context (line 1491-1500)
async def session(self, ctx: Optional[RequestContext] = None, *, request=None, app=None, llm=None, user_id=None, session_id=None, **ctx_kwargs) -> AsyncIterator["AbstractBot"]: ...  # line 4203; sets _current_ctx token (line 4322), resets in finally (line 4327)
async def post_login(self, user_context: "UserContext") -> None: ...      # line 4426 (no-op default)
async def clone_for_user(self, user_context: "UserContext") -> "AbstractBot": ...  # line 4448 (raises NotImplementedError)
async def ask(self, question, session_id=None, user_id=None, ..., ctx: Optional[RequestContext] = None, ..., use_tools=True, trace_context=None, **kwargs) -> AIMessage  # abstract line 4603; concrete BaseBot.ask at bots/base.py:1037, ask_stream at base.py:1808

# From packages/ai-parrot/src/parrot/utils/helpers.py
class RequestContext:                                                     # line 7; __init__(request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs) → self.kwargs
_current_ctx: ContextVar[Optional[RequestContext]]                        # line 53
def current_context() -> Optional[RequestContext]: ...                    # line 58

# From packages/ai-parrot/src/parrot/auth/context.py:39
@dataclass(frozen=True)
class UserContext:
    channel: str; user_id: str; display_name: Optional[str] = None; email: Optional[str] = None
    session_id: Optional[str] = None; metadata: Dict[str, Any] = field(default_factory=dict)

# From packages/ai-parrot/src/parrot/utils/paths.py
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")             # line 29
def validate_path_segment(value: str, name: str = "path segment") -> str: ...  # line 33
def secure_path(base: Union[str, Path], *segments: str, name: str = "path segment") -> Path: ...  # line 52

# From packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:809
tenant_id = getattr(self, "_tenant_id", "default")   # existing convention for an optional bot-level tenant attribute

# From packages/ai-parrot/src/parrot/bots/mixins/narrative.py:29
class NarrativeMixin(SkillRegistryMixin):
    narrative_skill: Optional[str] = None
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]: ...   # calls self._configure_skill_registry() lazily (line 114)

# From packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:1938
def _list_agent_skills(self) -> list[dict]: ...   # reads agent._skill_file_registry.list_skills() and agent._skill_registry

# From packages/ai-parrot/src/parrot/conf.py:181
AGENTS_DIR = config.get("AGENTS_DIR", fallback=BASE_DIR.joinpath("agents"))   # Path, created if missing
```

#### Verified Imports
```python
from parrot.skills import SkillRegistryMixin, SkillFileRegistry, SkillsDirectoryLoader, SkillDefinition, SkillSource  # packages/ai-parrot/src/parrot/skills/__init__.py:60-110
from parrot.skills.mixin import SkillRegistryMixin                     # skills/mixin.py:27
from parrot.skills.file_registry import SkillFileRegistry             # skills/file_registry.py:17
from parrot.skills.parsers import discover_skills_in_dir, parse_skill_file  # skills/parsers.py:162 / :60
from parrot.skills.prompt import render_skills_prompt_layer           # skills/prompt.py:29
from parrot.skills.middleware import create_skill_trigger_middleware  # skills/middleware.py:16
from parrot.skills.tools import SkillFileToolkit, SkillRegistryToolkit, create_skill_tools  # skills/tools.py:371 / :69 / :635
from parrot.skills.store import SkillRegistry, create_skill_registry  # skills/store.py:126 / :934
from parrot.bots.prompts import PromptLayer, RenderPhase              # bots/prompts/layers.py:35-51 (re-exported; used by skills/prompt.py:24)
from parrot.utils.helpers import RequestContext, current_context, _current_ctx  # utils/helpers.py:7 / :58 / :53
from parrot.auth.context import UserContext                           # auth/context.py:39
from parrot.utils.paths import validate_path_segment, secure_path, SAFE_SEGMENT_RE  # utils/paths.py:33 / :52 / :29
from parrot.conf import AGENTS_DIR                                    # conf.py:181
```

#### Key Attributes & Constants
- `SkillRegistryMixin.skill_paths` → `List[Path]` (mixin.py:65) — FEAT-188 explicit global paths; stay global.
- `SkillRegistryMixin._skill_file_registry` → `Optional[SkillFileRegistry]` (mixin.py:79) — becomes the **global** registry under Option A.
- `SkillFileRegistry.learned_dir` → `Path` (file_registry.py:38) — the only learned location (global).
- Reserved entry name inside `skills/`: `"learned"` (file_registry.py:43, passed as `exclude_subdir`).
- `PromptLayer` priority used by skills layer: `45` (prompt.py:32).
- Existing per-agent folders under `AGENTS_DIR/{agent_id}/`: `skills/`, `prompts/` (agent.py:504), `queries/` (agent.py:520), `kb/`, `documents/` (mixin.py:88 docstring), `flows/` (flows/flow/loader.py:64 is `AGENTS_DIR/flows`, agent-less), `_drafts/` (studio/tools/drafts.py:80, agent-less).
- Local agent trees that already have skills (gitignored `/agents/`): `flex_dashboard`, `oddie`, `odoo_agent`, `Pandas Agent`, `pokemon_analyst`, `porygon`, `troc_finance`.
- Tests touching this surface: `packages/ai-parrot/tests/unit/test_skill_file_registry.py`, `test_skill_trigger_middleware.py`, `test_save_learned_skill_tool.py`, `test_budget_narrative_skill.py`; `tests/unit/test_skills_directory_loader.py`, `test_skills_prompt_layer.py`, `test_load_skill_tool.py`, `test_list_skill_commands_tool.py`, `test_read_skill_asset_tool.py`, `test_skill_registry_toolkit.py`; `packages/ai-parrot/tests/integration/test_skill_system.py`.

### Does NOT Exist (Anti-Hallucination)
- ~~`AGENTS_DIR/{agent_id}/skills.d/`~~ — no `skills.d` anywhere in the code; the directory is `skills/`.
- ~~`AGENTS_DIR/{agent_id}/tenants/`~~ — no code references `tenants/` yet (new in this feature).
- ~~`SkillRegistryMixin.tenant_based`~~, ~~`SkillRegistryMixin.tenant_id`~~, ~~`SkillRegistryMixin._resolve_tenant()`~~, ~~`current_skill_view()`~~, ~~`reload_tenant_skills()`~~ — all new.
- ~~`AbstractBot._tenant_id`~~ — not defined on `AbstractBot`/`BaseBot`; `intent_router.py:809` only reads it with `getattr(..., "default")`. (The `_tenant_id` assignments found live in unrelated classes: knowledge catalogs, msteams, sharepoint.)
- ~~`RequestContext.tenant`~~, ~~`UserContext.tenant`~~ — neither dataclass has a tenant field; only `RequestContext.kwargs` and `UserContext.metadata` dicts.
- ~~`SkillFileRegistry.get_for_tenant()`~~, ~~`SkillDefinition.tenant`~~ — do not exist.
- ~~`parrot.skills.tenancy`~~ — module does not exist yet (proposed name).
- ~~`BaseBot.ask(tenant=...)`~~ — `tenant` is not a named parameter today; it would only land in `**kwargs`.
- ~~`validate_path_segment(value, *, what=...)` in `parrot.utils.paths`~~ — that keyword form is the *other* `validate_path_segment` in `knowledge/contracts/evidence.py:54`; the reusable one in `utils/paths.py:33` takes `name=`.
- ~~`docs/skills/`~~ — no skills docs directory was found under `docs/`; documentation location is an open question.

---

## Parallelism Assessment

- **Internal parallelism**: moderate. The resolver/ContextVar/validation
  module and the per-tenant `SkillRegistry` (store) namespace work are
  independent of each other and of the file-registry view. The view, the
  mixin wiring, the prompt layer and the consumer migrations (tools,
  middleware, narrative, telegram) form a dependent chain: view → mixin →
  consumers.
- **Cross-feature independence**: no active task touches `parrot/skills/`
  (checked `sdd/tasks/active/`). Draft specs `agent-skill-system` (FEAT-088)
  and `skills-tools-toolkit` (FEAT-207) are historical (their code shipped).
  Shared files with risk of concurrent edits: `bots/base.py` (`ask` /
  `ask_stream` signature) and `bots/abstract.py` — coordinate if any
  in-flight feature changes `ask()` kwargs.
- **Recommended isolation**: `mixed` — resolver module and store namespace
  tasks may run in individual sub-worktrees; the view → mixin → consumers
  chain runs sequentially in the feature worktree.
- **Rationale**: the independent pieces have disjoint files; the chain shares
  `mixin.py` and the toolkit constructors, where parallel edits would
  conflict.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: feature → `dev`.
- [x] Directory layout — *Owner: Jesus Lara*: `AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`; global stays `skills/`; **no** `skills.d` rename.
- [x] Tenant lifetime — *Owner: Jesus Lara*: both fixed-per-instance and per-request on a shared instance must work.
- [x] Tenant sources — *Owner: Jesus Lara*: explicit kwarg, bot attribute, `RequestContext`/`UserContext.metadata`, ContextVar transport (all four); precedence kwarg > ctx/UserContext > bot attribute.
- [x] Override semantics — *Owner: Jesus Lara*: tenant shadows global by name/trigger; globals without override stay visible.
- [x] Learned skills — *Owner: Jesus Lara*: always written to the global `skills/learned/`.
- [x] Loading strategy — *Owner: Jesus Lara*: eager scan of `tenants/*` at `configure()`.
- [x] `store.py` scope — *Owner: Jesus Lara*: in scope; namespace `org_id/agent_id/{tenant}`.
- [ ] Unresolved tenant with `tenant_based=True`: this brainstorm assumes **global-only view, no error** (fail-closed to global). Confirm, or require an error. — *Owner: Jesus Lara*
- [ ] Unknown tenant id (valid name, no `tenants/{tenant}/` dir): warn + global view (assumed), or reject? — *Owner: Jesus Lara*
- [ ] Should a frontmatter guard (`global_only: true`) exist so some global skills can never be shadowed by a tenant (e.g. policy skills)? Deferred; not in v1 unless requested. — *Owner: Jesus Lara*
- [ ] `document_skill` (DB-like write tool) with an active tenant: write to the tenant namespace (assumed, mirrors authored skills) or always global like learned skills? — *Owner: Jesus Lara*
- [ ] `NarrativeMixin.narrate(facts, skill)`: gain an explicit `tenant: str | None = None` parameter, or rely purely on the ContextVar / instance default? — *Owner: spec author*
- [ ] Telegram wrapper `_list_agent_skills()`: which `UserContext.metadata` key carries the tenant (`"tenant"` assumed), and is it set by the wrapper today? Verify during spec. — *Owner: spec author*
- [ ] Where do skills docs live? No `docs/skills/` found; candidate is a new `docs/skills/per-tenant-skills.md` plus the Skills paragraph in `.agent/CONTEXT.md`. — *Owner: spec author*
- [ ] Per-tenant `<available_skills>` layers: cap on tenant count before switching to a single REQUEST-phase layer rendered from a `$available_skills` variable supplied by the mixin? Decide threshold in spec. — *Owner: spec author*
