# Per-tenant skills (FEAT-707)

Per-tenant skills let one agent serve several tenants while keeping tenant-specific
skill variants isolated. The feature is opt-in and is provided by
`SkillRegistryMixin`.

## When to use it

Use per-tenant skills when the same agent needs different instructions or
skill implementations for different customers, programs, or environments. Set
`tenant_based = True` on the agent class, or pass `tenant_based=True` when the
agent is constructed. Agents that leave the flag at its default (`False`) keep
the existing global-only behavior; tenant arguments are ignored with a debug
log.

Set `tenant_id` when one bot instance has a fixed tenant. A shared instance can
instead receive a tenant for each request with `ask(..., tenant=...)` or
`ask_stream(..., tenant=...)`.

## Enabling and directory layout

The global tree remains `AGENTS_DIR/{agent_id}/skills/`. Tenant trees are
additive and live below `tenants/{tenant}/skills/`:

```text
agents/troc_finance/
├── skills/                              # global fallback
│   ├── revenue_by_division/SKILL.md
│   ├── ebitda_breakdown/SKILL.md
│   └── learned/                         # all learned skills, every tenant
└── tenants/
    ├── pokemon/
    │   └── skills/
    │       └── revenue_by_division/SKILL.md
    └── epson/
        └── skills/
            └── revenue_by_division.md
```

Tenant directories are discovered eagerly during `configure()`. The tenant id
must be a safe path segment and must not be one of the reserved names:
`skills`, `learned`, `tenants`, `prompts`, `queries`, `kb`, `documents`,
`flows`, `_drafts`, or `_shared`. Invalid ids raise `ValueError`; they are
never used to access the filesystem. Tenant trees must contain a `skills/`
directory. A `learned/` directory inside a tenant tree is reserved, ignored,
and warned about; learned skills always belong to the global tree.

## Tenant resolution and precedence

The effective tenant is resolved in this order, from highest to lowest:

1. An explicit `tenant=` argument to `ask()`, `ask_stream()`, or a tenant-aware
   skill method.
2. `RequestContext.kwargs["tenant"]` (channel wrappers may carry the same
   value in `UserContext.metadata["tenant"]`).
3. The request-local tenant bound by the skill ContextVar.
4. The bot instance's `tenant_id` default.
5. No tenant, which selects the global view.

`PermissionContext.tenant_id` is not a source for skill resolution. An unknown
tenant also uses the global view and emits a warning once per tenant per
instance. `current_skill_tenant()` exposes the tenant bound to the current
asyncio task; `current_active_skill()` and `set_active_skill()` carry the
request-local `/trigger` selection.

## Effective view and collision matrix

`current_skill_view()` returns a read-only `SkillView`. A tenant view contains
tenant skills first, followed by global skills whose names are not shadowed.
Tenant and global skills are matched independently by name and by trigger, so a
tenant can override a trigger without hiding the global skill by name. A tenant
cannot see another tenant's tree.

| Case | Tenant tree | Global tree | Effective view | Result |
| --- | --- | --- | --- | --- |
| C1 | Skill `X` | Skill `X` | Tenant `X` | Tenant shadows global by name; logged at configure. |
| C2 | `X` with `/t` | `Y` with `/t` | `/t` resolves to tenant `X`; global `Y` remains by name | Trigger shadow is logged. |
| C3 | Skill `X` | `X` with `global_only: true` | Global `X` only | Tenant `X` is dropped and both files are named in an error log. |
| C4 | `X` with `/t` | `G` with `/t` and `global_only: true` | Global `G` owns `/t`; tenant `X` remains by name | The tenant trigger is dropped and the conflict is logged. |
| C5 | Skill `X` | None | Tenant `X` | Tenant-only skill is visible. |
| C6 | None | Skill `X` | Global `X` | Unoverridden global is the fallback. |
| C7 | Two tenants use `/t` | Any | Independent views | The same trigger is valid in each tenant. |
| C8 | Learned `L` in global `learned/` | None | `L` in every view | A tenant-authored `L` may shadow it in that tenant; learned storage stays global. |
| C9 | `learned/` under a tenant | None | Ignored | The reserved directory is skipped with a warning. |
| C10 | Malformed file | Any | Remaining valid skills | The malformed file is skipped with a warning. |

The `global_only: true` frontmatter field prevents a global skill from being
shadowed by tenant name or trigger. `global_only` defaults to `false`.

## Prompt layers and active skills

With tenant mode enabled, the `<available_skills>` prompt is rendered once for
the global view and once for each discovered tenant view. The layers are named
`available_skills` and `available_skills:{tenant}`, use the REQUEST phase, and
are cacheable. Each request sees only its effective view.

The skill selected by `/trigger` is request-local through a ContextVar. This
prevents concurrent requests on a shared bot from leaking one tenant's active
skill into another request. The active-skill prompt layer is permanent and
conditional; the active body is supplied for the current request. A future
optimization could use one variable-fed layer instead of one static layer per
tenant if tenant counts grow; v1 intentionally has no tenant-layer cap.

## File and DB-backed skill consumers

The file toolkit, trigger middleware, prompt layers, narrative rendering, and
Telegram `/skills` listing all obtain the current `SkillView`. Consequently,
`load_skill`, `read_skill_asset`, `list_skill_commands`, and trigger activation
resolve tenant overrides consistently. `save_learned_skill` writes to the
global `skills/learned/` directory and refreshes the layers for every view.

The DB-like `SkillRegistry` uses one namespace per tenant:
`{org_id}/{agent_id}/{tenant}`. Its persistence path is the corresponding
`tenants/{tenant}/skills/` directory. Tenant searches merge tenant and global
results, de-duplicate by skill name with the tenant winning, sort by relevance,
and apply the result limit after merging. Context lookup asks the tenant store
first and falls back to the global store when it has no result. `document_skill`
and `update_skill` write to the active tenant store; with no tenant they write
to the global store. Conversation extraction and learned-skill storage remain
global.

## Channel binding

### HTTP

HTTP handlers use `resolve_request_tenant(app, request)` and pass the
server-resolved `RequestScope.tenant` to the agent. The client cannot choose a
tenant: handlers pop a client-supplied `tenant` key before forwarding the
remaining body as `**data`, log that it was ignored, and use the server value.
Any new handler that forwards `**data` must apply the same pop-before-forward
rule. Sessions with no single resolved Navigator tenant use the global view.

### Telegram

Set the static tenant on the bot's YAML agent entry:

```yaml
tenant: pokemon
```

This is the `TelegramAgentConfig.tenant` field: one Telegram bot is bound to
one customer. The wrapper passes it to every agent call, copies it into
`UserContext.metadata["tenant"]`, uses it for the user session scope, and uses
the tenant view for `/skills`. Bots without `tenant:` remain global-only. The
`tenant:` value is still ignored when the agent has `tenant_based=False`.

## Reloading tenant skills

Call `await agent.reload_tenant_skills()` to rescan all tenant trees without a
restart, or `await agent.reload_tenant_skills("pokemon")` to rescan one tenant.
The method rebuilds the file views, refreshes the `<available_skills>` layers,
and reconciles tenant DB registries. Removing a tenant tree removes its view
and store on reload.

## Troubleshooting

- **Unknown tenant warning:** no `tenants/{tenant}/skills/` tree was discovered.
  The request safely falls back to global skills. Check the agent id, tenant
  spelling, and directory layout, then call `reload_tenant_skills()`.
- **Invalid tenant id error:** the id is empty, contains path separators or
  traversal, or uses a reserved name. Correct the id; it is rejected before
  filesystem access.
- **Override did not apply:** check that `tenant_based=True`, the request
  tenant is resolved at the expected precedence level, and the skill is not a
  global `global_only` skill.
- **Learned skill is missing for one tenant:** learned skills are intentionally
  global and are stored under `skills/learned/`, never under a tenant tree.
