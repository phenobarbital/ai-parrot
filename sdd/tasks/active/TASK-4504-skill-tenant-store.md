# TASK-4504: Per-tenant DB-like `SkillRegistry`

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4503, TASK-4495
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 and design-research S8. With `tenant_based=True` the mixin
creates one `SkillRegistry` per tenant (namespace `{org_id}/{agent_id}/{tenant}`,
persistence under `tenants/{tenant}/skills/`) that SHARES the global registry's
loaded embedding model (no N× sentence-transformers load). Search merges tenant
and global before limiting; context falls back to global only when the tenant
result is empty; `document_skill` / `update_skill` write tenant-side;
`extract_skills_from_conversation` stays global. Depends on TASK-4503 because
both edit `mixin.py` (serialized), and on TASK-4495 for `registry_provider`.

---

## Scope

- In `_configure_skill_registry()`: after the global registry is configured and when `tenant_based`, create and configure per-tenant registries (needs the tenant list → call `discover_tenant_dirs` here, or configure stores in `_after_tenant_reload` — see Implementation Notes).
- `_current_store_registry(tenant=None)`.
- `_add_skill_tools()`: pass `registry_provider=self._current_store_registry` to `create_skill_tools` when `tenant_based`.
- `search_skills(..., tenant=None)`, `get_skill_context(..., tenant=None)`, `document_skill(..., tenant=None)` per the rules.
- `_cleanup_skill_registry()`: clean every tenant registry.
- `_after_tenant_reload`: create registries for new tenants, clean up removed ones.
- Write `packages/ai-parrot/tests/unit/test_skill_tenant_store.py`.

**NOT in scope**: changes to `store.py` (none needed), file-based views.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | per-tenant stores |
| `packages/ai-parrot/tests/unit/test_skill_tenant_store.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .store import SkillRegistry, create_skill_registry      # verified: mixin.py:20
from .tenancy import discover_tenant_dirs, tenant_skills_dir # TASK-4494
from .models import SkillCategory, Skill                      # verified: mixin.py:19
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/mixin.py
    async def _configure_skill_registry(self) -> None:                   # line 105
        agent_id = getattr(self, 'name', None) or getattr(self, 'agent_id', 'default')
        org_id = getattr(self, 'org_id', 'default'); namespace = f"{org_id}/{agent_id}"
        persistence_path = agents_dir / agent_id / "skills"              # 121
        self._skill_registry = create_skill_registry(namespace=namespace, persistence_path=persistence_path,
                                                      extraction_llm=getattr(self, '_llm', None))   # 123-127
        await self._skill_registry.configure()                           # 129
        if self.skill_registry_expose_tools: await self._add_skill_tools()   # 132-133
        await self._configure_skill_file_registry()                      # 136
    async def _add_skill_tools(self) -> None:                            # 347; create_skill_tools(registry=..., agent_id=..., include_write_tools=True) at 359
    async def get_skill_context(self, query, max_skills=None, max_tokens=None) -> str:   # 374 → self._skill_registry.get_relevant_skills(query=, max_skills=, max_tokens=)
    async def document_skill(self, name, content, description="", category="general", tags=None, triggers=None) -> Optional[Skill]:  # 394 → upload_skill(...)
    async def extract_skills_from_conversation(self, conversation, context=None) -> Optional[Skill]:   # 424 (stays global)
    async def search_skills(self, query, category=None, max_results=5) -> List[Dict[str, Any]]:   # 445; dicts {skill_id, name, description, content, relevance}
    async def _cleanup_skill_registry(self) -> None:                     # 473

# packages/ai-parrot/src/parrot/skills/store.py
class SkillRegistry:                                                     # 126
    def __init__(self, namespace="default", embedding_model: str | Any = "...", ..., persistence_path: Path | None = None, extraction_llm=None, ...)  # 148
    async def configure(self, extraction_llm=None, embedding_model=None) -> None:   # 202; uses the passed embedding_model object when given (213-215)
    _embedding_model                                                     # private attribute set in configure()
    namespace: str
    async def search_skills(self, query, category=None, tags=None, include_deprecated=False, max_results=5) -> list[SkillSearchResult]  # 554
    async def get_relevant_skills(self, query, max_skills=..., max_tokens=...) -> str   # 778
    async def cleanup(self) -> None                                      # 926
def create_skill_registry(namespace: str, persistence_path: str | None = None, ...) -> SkillRegistry   # 934
# packages/ai-parrot/src/parrot/skills/models.py:246
class SkillSearchResult: skill: Skill; content: str; similarity_score: float; relevance_score: float
```

### Does NOT Exist
- ~~`SkillRegistry.namespace` validation~~ — `org/agent/tenant` is accepted as-is (store does not split it).
- ~~A public accessor for the embedding model~~ — read `self._skill_registry._embedding_model` (same package; documented in spec §7).
- ~~`create_skill_registry(embedding_model=...)`~~ — FILL IN: check its signature (store.py:934-950); if it does not forward `embedding_model`, pass the model to `configure(embedding_model=...)` instead.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/mixin.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_tenant_store.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._configure_skill_registry",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin.search_skills",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin.get_skill_context",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin.document_skill",
    "sym:packages/ai-parrot/src/parrot/skills/store.py#SkillRegistry",
    "sym:packages/ai-parrot/src/parrot/skills/store.py#create_skill_registry"
  ]
}
```

---

## Implementation Notes

### Ordering (important)
`_configure_skill_registry()` configures the global store, adds tools, THEN calls `_configure_skill_file_registry()` (which, after TASK-4499, discovers tenants). Create tenant stores AFTER `_configure_skill_file_registry()` returns, iterating `self._known_tenants` — one source of tenant truth. `_add_skill_tools` already ran by then, but it receives a provider (bound method), so later-created registries are picked up.

### Merge rules (spec AC-S2)
- `search_skills`: results from tenant registry (when resolved & known) + global; de-dup by skill name (tenant wins); sort by `relevance_score` desc; slice `max_results` AFTER the merge; add `"namespace"` to each dict.
- `get_skill_context`: tenant `get_relevant_skills`; if it returns an empty/whitespace string, use the global one.
- `document_skill`: `_current_store_registry(tenant).upload_skill(...)`.

### Key Constraints
- `tenant_based=False`: no new registries; `_current_store_registry()` returns the global one; all three methods behave exactly as today (AC-B1).
- New `tenant` params are trailing keywords with default `None` (AC-B2).

---

## Implementation Blueprint

### Steps (in order)
1. Init `self._tenant_store_registries: Dict[str, SkillRegistry] = {}` — add it to the `__init__` from TASK-4499.
2. Add `_configure_tenant_store_registries()` and call it at the end of `_configure_skill_registry()` — *why*: AC-S1.
3. Add `_current_store_registry()`; wire `registry_provider` in `_add_skill_tools` — *why*: tool writes go tenant-side (AC-S3).
4. Update `search_skills`, `get_skill_context`, `document_skill`; cleanup; reload — *why*: AC-S2..S5, AC-E1.
5. Tests with fake registries (no sentence-transformers).

### `packages/ai-parrot/src/parrot/skills/mixin.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _configure_skill_registry(self) -> None:' .../skills/mixin.py)
# AFTER `        await self._configure_skill_file_registry()` inside _configure_skill_registry (≈mixin.py:136):
        if self.tenant_based:
            await self._configure_tenant_store_registries()

    async def _configure_tenant_store_registries(self) -> None:
        """One SkillRegistry per known tenant, sharing the global embedding model (FEAT-707 S8)."""
        # FILL IN: agents_dir/agent_id/org_id as in _configure_skill_registry; for t in sorted(self._known_tenants)
        #          not already in _tenant_store_registries: reg = create_skill_registry(
        #          namespace=f"{org_id}/{agent_id}/{t}", persistence_path=tenant_skills_dir(agents_dir / agent_id, t),
        #          extraction_llm=getattr(self, '_llm', None)); await reg.configure(
        #          embedding_model=getattr(self._skill_registry, "_embedding_model", None)); store it
        #          — bounded by AC-S1 (shared model) and the Ordering note

    def _current_store_registry(self, tenant: Optional[str] = None) -> Optional[SkillRegistry]:
        """Tenant store when resolved and known, else the global store."""
        # FILL IN: if not tenant_based → self._skill_registry; resolved = self._resolve_tenant(tenant);
        #          return self._tenant_store_registries.get(resolved, self._skill_registry) — bounded by AC-S3, AC-R3

# _add_skill_tools (≈mixin.py:359): add to create_skill_tools(...)
            **({"registry_provider": self._current_store_registry} if self.tenant_based else {}),

# search_skills / get_skill_context / document_skill: add trailing `tenant: Optional[str] = None` and
# implement the Merge rules — FILL IN — bounded by AC-S2, AC-S3, AC-B1
# _cleanup_skill_registry: also `await reg.cleanup()` for every tenant store, then clear the dict (AC-S5)
# _after_tenant_reload: after the TASK-4503 lines, `await self._configure_tenant_store_registries()` and
#                       cleanup + drop stores of tenants no longer in _known_tenants (AC-E1)
```

### `packages/ai-parrot/tests/unit/test_skill_tenant_store.py` (CREATE)
```python
"""FEAT-707 — per-tenant DB-like store (TASK-4504)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

# FILL IN: monkeypatch `parrot.skills.mixin.create_skill_registry` with a factory returning fakes that record
#          namespace/persistence_path/configure kwargs and expose AsyncMock search/get_relevant/upload/cleanup.
# Tests:
#  test_store_namespace_and_persistence_per_tenant
#  test_store_shares_embedding_model
#  test_search_skills_merge_before_limit (tenant wins on name; sorted; max_results after merge; namespace key)
#  test_get_skill_context_tenant_then_global
#  test_document_skill_routes_to_tenant / _global_without_tenant
#  test_extract_skills_stays_global
#  test_cleanup_closes_tenant_stores
#  test_flag_off_no_tenant_stores
# — bounded by AC-S1..S5, AC-B1
```

### FILL IN checklist
- [ ] `create_skill_registry` signature check
- [ ] `_configure_tenant_store_registries`, `_current_store_registry`
- [ ] merge rules in three methods
- [ ] cleanup + reload
- [ ] nine tests

---

## Acceptance Criteria

- [ ] AC-S1..S5 satisfied; AC-B1 for the flag off.
- [ ] `test_skill_registry_toolkit.py`, `test_skill_system.py` pass unmodified.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_store.py -q`
- `pytest tests/unit/test_skill_registry_toolkit.py -q`
- `pytest packages/ai-parrot/tests/integration/test_skill_system.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 8, §7 (store cost), §9 S8.
3. **Check dependencies**: TASK-4503 and TASK-4495 `done`.
4. **Verify the Codebase Contract** — mixin.py line numbers moved after TASK-4499/4503.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4504 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: adds private helper `_configure_tenant_store_registries()`.
