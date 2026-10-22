<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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
- **Unresolved tenant with `tenant_based=True`** (decided) → global-only view,
  no error, DEBUG log (fail-closed to global, never to another tenant).
- **Known-looking but absent tenant** (decided): a valid tenant id with no
  `tenants/{tenant}/` directory → global view plus a warning, emitted once per
  tenant per instance.
- **`PermissionContext.tenant_id` is NOT a tenant source** in v1: Telegram
  hard-codes it to `"default"` and `build_principal_context()` defaults it to
  the principal (user id), so trusting it would silently pick wrong trees.
- **Channel binding** (decided, in scope): HTTP handlers (`handlers/chat.py`,
  `handlers/agents/abstract.py`) pass `tenant=` from the server-resolved
  `RequestScope.tenant` and **discard** any `tenant` key the client body
  carries (logged); the Telegram wrapper binds a new static
  `TelegramAgentConfig.tenant` (one bot = one customer) into
  `UserContext.metadata["tenant"]` and into the permission context's
  `UserSession.tenant_id` instead of `"default"`.
- **Tenant key name** (decided): `"tenant"` in both `RequestContext.kwargs`
  and `UserContext.metadata`.
- **Loading** (decided): **eager** — `tenants/*/skills/` is scanned at
  `configure()`; adding a tenant on disk needs a restart or an explicit
  reload method.
- **Learned skills** (decided): `save_learned_skill` always writes to the
  **global** `skills/learned/`, regardless of the active tenant. Learned skills
  are therefore visible to every tenant.
- **`global_only` guard** (decided, v1): a global skill may declare
  `global_only: true` in its frontmatter; a tenant skill with the same name or
  trigger is rejected at configure (error log, global wins).
- **DB-like writes** (decided): `document_skill` / `update_skill` write to the
  active tenant's namespace (`org/agent/{tenant}`), global when no tenant;
  `extract_skills_from_conversation` follows the learned rule (global).
- **`NarrativeMixin.narrate()`** (decided): gains `tenant: str | None = None`,
  falling back to the ContextVar and then the instance default.
- **Prompt layers** (decided): one `<available_skills>` layer per tenant, no
  cap in v1 (`skill_prompt_max_entries` bounds each layer's size).
- **Docs** (decided): new `docs/skills/per-tenant-skills.md` plus a short
  paragraph in the Skills section of `.agent/CONTEXT.md`.
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

### Recommended option / probable scope
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

--- Recommended option body ---

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
- Shadowing by name/trigger (and the `global_only` exception) is a
  view-composition rule, trivially testable.
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py
packages/ai-parrot-server/src/parrot/handlers/chat.py
packages/ai-parrot-server/src/parrot/handlers/scope.py
packages/ai-parrot-server/src/parrot/handlers/studio/access.py
packages/ai-parrot/src/parrot/auth/context.py
packages/ai-parrot/src/parrot/auth/permission.py
packages/ai-parrot/src/parrot/bots/abstract.py
packages/ai-parrot/src/parrot/bots/base.py
packages/ai-parrot/src/parrot/bots/mixins/intent_router.py
packages/ai-parrot/src/parrot/bots/mixins/narrative.py
packages/ai-parrot/src/parrot/bots/prompts/builder.py
packages/ai-parrot/src/parrot/bots/prompts/layers.py
packages/ai-parrot/src/parrot/conf.py
packages/ai-parrot/src/parrot/skills/file_registry.py
packages/ai-parrot/src/parrot/skills/__init__.py
packages/ai-parrot/src/parrot/skills/loader.py
packages/ai-parrot/src/parrot/skills/middleware.py
packages/ai-parrot/src/parrot/skills/mixin.py
packages/ai-parrot/src/parrot/skills/models.py
packages/ai-parrot/src/parrot/skills/parsers.py
packages/ai-parrot/src/parrot/skills/prompt.py
packages/ai-parrot/src/parrot/skills/store.py
packages/ai-parrot/src/parrot/skills/tools.py
packages/ai-parrot/src/parrot/utils/helpers.py
packages/ai-parrot/src/parrot/utils/paths.py
packages/ai-parrot/tests/integration/test_skill_system.py
packages/ai-parrot/tests/unit/test_skill_file_registry.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
