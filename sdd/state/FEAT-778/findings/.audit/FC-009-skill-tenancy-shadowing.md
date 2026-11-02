---
id: FC-009
query_id: Q028
type: read
intent: "Read skills tenancy: workspace-over-global shadowing precedent (bundle location question)."
executed_at: 2026-10-30T16:42:58Z
duration_ms: 500
parent_id: null
depth: 0
---

# FC-009 — `SkillView` overlays a tenant tree over the global tree by name/trigger; `global_only` skills cannot be shadowed; tenant bound via ContextVar

## Summary

`skills/tenancy.py` (290 lines, FEAT-707). `tenant_skills_dir(agent_root, tenant)` = `agent_root/tenants/{tenant}/skills` (path-safe). `SkillView` computes `shadowing`/`shadowed_triggers`: a tenant skill with the same name shadows the global one, unless the global is `global_only` (tenant skill dropped with a warning). The active tenant/skill live in ContextVars (`current_tenant` from observability.context). This answers the "workspace > package priority" open question with an existing rule set.

## Citations

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 54-60
  symbol: `tenant_skills_dir`
  excerpt: |
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), SKILLS_DIRNAME, name="tenant id")

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 164-248
  symbol: `SkillView`
  excerpt: |
    locked_names = {skill.name: skill for skill in globals_ if skill.global_only}
    "Tenant skill %s (%s) conflicts with global_only skill (%s); dropping tenant skill"
    self.logger.info("Tenant skill %s shadows global skill %s", ...)

- path: `packages/ai-parrot/src/parrot/skills/tenancy.py`
  lines: 90-104
  symbol: `current_skill_tenant / bind_skill_tenant`
  excerpt: |
    _skill_tenant = current_tenant
    def bind_skill_tenant(tenant: Optional[str]) -> Token: return _skill_tenant.set(tenant)

## Notes

Precedent for "workspace Tier 2 shadows bundled Tier 1 except locked entries".
