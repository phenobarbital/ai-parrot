# TASK-4502: Tenant-aware `NarrativeMixin.narrate()`

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4499
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (narrative part); brainstorm decision: `narrate()` gains
`tenant: str | None = None`, falling back to the bound ContextVar and then the
instance default. The finance reporter (the motivating revenue/EBITDA use
case) narrates through this method, so the tenant's skill variant must be used.
`current_skill_view()` (TASK-4499) already implements the fallback chain.

---

## Scope

- `narrate(self, facts, skill, tenant: Optional[str] = None)` passes `tenant` to `_load_narrative_skill`.
- `_load_narrative_skill(self, name, tenant=None)`: after `await self._configure_skill_registry()`, resolve via `self.current_skill_view(tenant)`; fall back to `_skill_file_registry` when the view is `None`.
- An invalid tenant (`ValueError` from resolution) is caught by `narrate()`'s existing `except Exception` (narrative is never fatal) — keep that contract.
- Write `packages/ai-parrot/tests/unit/test_narrative_tenant.py`.

**NOT in scope**: the narrative prompt/guard logic, any caller of `narrate()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/narrative.py` | MODIFY | `tenant` param + view lookup |
| `packages/ai-parrot/tests/unit/test_narrative_tenant.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.mixins.narrative import NarrativeMixin    # verified: bots/mixins/narrative.py:29
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/narrative.py
class NarrativeMixin(SkillRegistryMixin):                                        # line 29
    narrative_skill: Optional[str] = None
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:  # line 54
        name = skill or self.narrative_skill
        ...
        try:
            definition = await self._load_narrative_skill(name)                   # ≈ line 73
            ...
        except Exception as exc:  # noqa: BLE001 — narrative is never fatal       # ≈ line 87
    async def _load_narrative_skill(self, name: str) -> Optional[SkillDefinition]:   # line 100
        await self._configure_skill_registry()                                    # line 114
        registry = getattr(self, "_skill_file_registry", None)
        if registry is None:
            return None
        return registry.get_by_name(name)

# packages/ai-parrot/src/parrot/skills/mixin.py (TASK-4499)
    def current_skill_view(self, tenant: Optional[str] = None) -> Optional[SkillView]: ...
```

### Does NOT Exist
- ~~`narrate(..., tenant=...)`~~ — added here.
- ~~`NarrativeMixin.tenant`~~ — the instance default lives on `SkillRegistryMixin` (`tenant_id` / `_tenant_id`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/mixins/narrative.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_narrative_tenant.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/mixins/narrative.py#NarrativeMixin.narrate",
    "sym:packages/ai-parrot/src/parrot/bots/mixins/narrative.py#NarrativeMixin._load_narrative_skill",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin.current_skill_view"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `tenant` to `narrate` and pass it through — *why*: brainstorm decision, AC-C4.
2. Resolve through the view in `_load_narrative_skill` — *why*: one resolution path for every consumer (S6).
3. Tests.

### `packages/ai-parrot/src/parrot/bots/mixins/narrative.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:' .../mixins/narrative.py)
    async def narrate(
        self, facts: dict[str, Any], skill: str, tenant: Optional[str] = None
    ) -> Optional[str]:
        # docstring Args: add `tenant: per-tenant skill variant (FEAT-707); falls back to the bound
        #                 tenant, then the instance default.`
        # body: `definition = await self._load_narrative_skill(name)` → `await self._load_narrative_skill(name, tenant)`

# occurrences: 1 (verified: grep -c '    async def _load_narrative_skill(self, name: str) -> Optional[SkillDefinition]:' .../mixins/narrative.py)
    async def _load_narrative_skill(
        self, name: str, tenant: Optional[str] = None
    ) -> Optional[SkillDefinition]:
        await self._configure_skill_registry()
        view_fn = getattr(self, "current_skill_view", None)
        registry = view_fn(tenant) if callable(view_fn) else None
        if registry is None:
            registry = getattr(self, "_skill_file_registry", None)
        if registry is None:
            return None
        return registry.get_by_name(name)
# FILL IN: update the docstring (Args: tenant) — bounded by Google docstrings
```

### `packages/ai-parrot/tests/unit/test_narrative_tenant.py` (CREATE)
```python
"""FEAT-707 — tenant-aware narrate() (TASK-4502)."""
import pytest

# FILL IN: reuse the host/LLM stubs from packages/ai-parrot/tests/unit/test_budget_narrative_skill.py
#          (read it first); build global skills/revenue.md and tenants/pokemon/skills/revenue.md with
#          distinguishable bodies; tenant_based=True.
# Tests:
#  test_narrate_tenant_variant (tenant="pokemon" → pokemon body reaches the LLM prompt)
#  test_narrate_without_tenant_uses_global
#  test_narrate_uses_bound_contextvar (bind_skill_tenant("pokemon") without the kwarg)
#  test_narrate_invalid_tenant_returns_none (never raises)
# — bounded by AC-C4, AC-R2 (contained by narrate's never-fatal contract)
```

### FILL IN checklist
- [ ] docstrings
- [ ] four tests

---

## Acceptance Criteria

- [ ] AC-C4: `narrate(..., tenant=)` uses the tenant view; existing callers unchanged.
- [ ] `test_budget_narrative_skill.py` passes unmodified.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_narrative_tenant.py -q`
- `pytest packages/ai-parrot/tests/unit/test_budget_narrative_skill.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 5.
3. **Check dependencies**: TASK-4499 `done`.
4. **Verify the Codebase Contract**.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4502 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

**Completed by**: sdd-worker (seat sonnet, native, 1 attempt, 138s)
**Date**: 2026-10-19
**Notes**: Merged via coder_merge; merge-tier validation green (107 passed). Closed with close_task.sh.
