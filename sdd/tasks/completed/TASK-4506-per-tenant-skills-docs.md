# TASK-4506: Per-tenant skills documentation

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4497, TASK-4500, TASK-4502, TASK-4504, TASK-4505
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 and brainstorm decision (docs location). Documents what
shipped, using the names that actually landed — hence it runs last.

---

## Scope

- Create `docs/skills/per-tenant-skills.md` covering: when to use it; enabling (`tenant_based`, `tenant_id`); directory layout (global `skills/`, `tenants/{tenant}/skills/`, reserved names); tenant precedence; collision matrix (C1–C10) and `global_only`; learned skills are global; prompt layers (one per tenant, follow-up note); request-local `/trigger` activation; DB-like store namespaces and merge rules; channel binding (HTTP server-resolved tenant and the "pop `tenant` before forwarding `**data`" rule for new handlers; Telegram `tenant:` YAML key); `reload_tenant_skills()`; troubleshooting (unknown tenant warning, invalid id error).
- Add a short paragraph to the **Skills** section of `.agent/CONTEXT.md`.

**NOT in scope**: code changes; the twin `.claude/` / `AGENTS.md` regeneration (not required for CONTEXT.md).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/skills/per-tenant-skills.md` | CREATE | feature guide |
| `.agent/CONTEXT.md` | MODIFY | Skills section paragraph |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Documented public names (verify each exists in the merged code before writing it down):
from parrot.skills import SkillView, TenantTreeReport, current_skill_tenant, current_active_skill, set_active_skill, validate_tenant_id
```

### Existing Signatures to Use
```text
.agent/CONTEXT.md:122  "### Skills"   (section to extend; occurrences: 1)
docs/ has no skills/ directory yet (create it).
```

### Does NOT Exist
- ~~`docs/skills/`~~ — created by this task.
- ~~A `skills.d` directory~~ — never document it; the layout is `skills/` + `tenants/{tenant}/skills/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/skills/per-tenant-skills.md", "action": "CREATE"},
    {"path": ".agent/CONTEXT.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Grep the merged code for every name you document (`tenant_based`, `tenant_id`, `current_skill_view`, `reload_tenant_skills`, `resolve_request_tenant`, `TelegramAgentConfig.tenant`, `global_only`) — *why*: docs must describe what shipped (spec rule: verify before you reference).
2. Write the guide — *why*: AC-D1.
3. Add the CONTEXT.md paragraph — *why*: AC-D1.

### `docs/skills/per-tenant-skills.md` (CREATE)
```markdown
# Per-tenant skills (FEAT-707)

<!-- FILL IN: sections listed in Scope, in that order; include the directory tree from the spec §2 /
     brainstorm "User-Facing Behavior", the precedence list, and the collision matrix table — bounded by AC-D1 -->
```

### `.agent/CONTEXT.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^### Skills' .agent/CONTEXT.md) -->
<!-- AFTER the last paragraph of the "### Skills" section (before the next "---" / "##" heading): -->
**Per-tenant skills (FEAT-707).** With `tenant_based = True`, `SkillRegistryMixin` also loads
`AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/` and serves a per-request *view* in which the tenant
tree shadows the global `skills/` tree by name and `/trigger` (`global_only: true` skills cannot be
shadowed; learned skills stay global). The tenant comes from `ask(tenant=...)` →
`RequestContext.kwargs["tenant"]` → the bound ContextVar → the instance `tenant_id`; HTTP handlers pass
the server-resolved Navigator tenant and drop any client-supplied one, Telegram uses the bot's static
`tenant:`. The `/trigger`-activated skill is request-local. See `docs/skills/per-tenant-skills.md`.
<!-- FILL IN: adjust names to what actually shipped -->
```

### FILL IN checklist
- [ ] guide body
- [ ] CONTEXT.md paragraph names

---

## Acceptance Criteria

- [ ] AC-D1: the guide exists and CONTEXT.md mentions `tenant_based`, the layout and the precedence.
- [ ] Every symbol named in the docs exists in the merged code.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_file_registry.py -q`

---

## Test Specification

Documentation task — the validation command guards that the documented core still imports and passes.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** (whole) and the merged code.
3. **Check dependencies**: TASK-4497, TASK-4500, TASK-4502, TASK-4504, TASK-4505 `done`.
4. **Verify** every documented name.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Write** the docs.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4506 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (seat gpt-5.6-luna, codex, 1 attempt, 69s)
**Date**: 2026-10-19
**Notes**: Merged via coder_merge; merge-tier validation green (feature tier 107+66 passed). Closed with close_task.sh.
