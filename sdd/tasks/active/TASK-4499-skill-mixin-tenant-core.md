# TASK-4499: `SkillRegistryMixin` tenant core (flags, resolution, views, loading, hooks)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4494
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, first half. Gives the mixin its tenant surface: the
`tenant_based` / `tenant_id` flags, a cooperative `__init__`, the precedence
resolver, the per-tenant `SkillFileRegistry` + `SkillView` maps loaded eagerly
at configure, `current_skill_view()`, the `_enter_skill_tenant` /
`_exit_skill_tenant` hooks called by `BaseBot.ask*` (TASK-4496), and
`reload_tenant_skills()`. Consumer wiring (providers, layers, active skill,
learned refresh) is TASK-4503; the DB-like store is TASK-4504 — both edit the
same file after this task.

---

## Scope

- Class attributes `tenant_based: bool = False`, `tenant_id: Optional[str] = None` (with docstrings).
- Cooperative `__init__(*args, **kwargs)`: pop `tenant_based` / `tenant_id`; set `self._tenant_id` only when a tenant id is given; init per-instance dicts/sets; `super().__init__(*args, **kwargs)`.
- `_resolve_tenant(explicit=None, ctx=None)`, `known_tenants()`, `current_skill_view(tenant=None)`.
- `_enter_skill_tenant(tenant, ctx)` / `_exit_skill_tenant(token)`.
- `_load_tenant_skill_trees(agent_root)` called from `_configure_skill_file_registry()` after the global registry loads (only when `tenant_based` and `agents_dir` resolve); builds `_global_view` always when a global registry exists.
- `reload_tenant_skills(tenant=None)` — rescans and rebuilds registries + views (layers/stores are added to it by TASK-4503/4504 through an overridable `_after_tenant_reload(reports)` hook, defined here as a no-op).
- Re-export `SkillView`, `TenantTreeReport`, `current_skill_tenant`, `current_active_skill`, `set_active_skill`, `validate_tenant_id` from `parrot/skills/__init__.py`.
- Write `packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py`.

**NOT in scope**: providers on middleware/toolkit, prompt layers, `_active_skill` property, learned refresh (TASK-4503); per-tenant `SkillRegistry` (TASK-4504); `ask` changes (TASK-4496).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | tenant core |
| `packages/ai-parrot/src/parrot/skills/__init__.py` | MODIFY | re-exports |
| `packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# mixin.py existing imports (lines 14-21): annotations, inspect, logging, Path,
#   Any, Dict, List, Optional, TYPE_CHECKING; .models (SkillCategory, SkillDefinition, Skill); .store; .tools
from contextvars import Token                                   # stdlib
from .tenancy import (SkillView, TenantTreeReport, bind_skill_tenant, current_skill_tenant,
                      discover_tenant_dirs, reset_skill_tenant, validate_tenant_id)   # TASK-4494
from parrot.utils.helpers import RequestContext                 # verified: utils/helpers.py:7 — import under TYPE_CHECKING only
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:                                        # line 27 — NO __init__ today
    skill_prompt_max_entries: Optional[int] = None               # line 73
    _skill_registry: Optional[SkillRegistry] = None              # line 78
    _skill_file_registry: Optional["SkillFileRegistry"] = None   # line 79
    _active_skill: Optional[SkillDefinition] = None              # line 80
    def _resolve_agents_dir(self) -> Optional[Path]: ...         # line 82
    async def _configure_skill_file_registry(self) -> None:      # line 141
        # agent_id = getattr(self, 'name', None) or getattr(self, 'agent_id', 'default')  (161)
        # agents_dir = self._resolve_agents_dir()  (162); logger = getattr(self, 'logger', logging.getLogger(__name__)) (163)
        # if agents_dir: skills_dir = agents_dir / agent_id / "skills" (165) ... await self._skill_file_registry.load() (174)
        # ... logger.info("SkillFileRegistry loaded: %d skills from %s", ...) (194-198)
        # --- FEAT-188 extensions: run regardless of agents_dir ---  (200)

# packages/ai-parrot/src/parrot/bots/mixins/narrative.py:48 — cooperative __init__ pattern to copy:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

# packages/ai-parrot/src/parrot/utils/helpers.py:7 — RequestContext(request=None, app=None, llm=None, user_id=None, session_id=None, **kwargs) → self.kwargs (dict)
# packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:809 — tenant_id = getattr(self, "_tenant_id", "default")  (do not break)

# packages/ai-parrot/src/parrot/skills/__init__.py
from .mixin import (                                             # line 67
    SkillRegistryMixin,
    SkillRegistryHooks,
)
__all__ = [ ... "SkillRegistryHooks", ]                          # last entry at line 109
```

### Does NOT Exist
- ~~`SkillRegistryMixin.__init__`~~ — added here.
- ~~`AbstractBot` generic setattr of unknown kwargs~~ — options are consumed with explicit `kwargs.pop` (abstract.py:377-409); without the mixin `__init__`, `tenant_id=` would be passed on and may break the base constructor — pop it.
- ~~`AbstractBot._tenant_id`~~ — not defined; only read with a default by intent_router.
- ~~`RequestContext.tenant`~~ — use `ctx.kwargs.get("tenant")`.
- ~~`PermissionContext.tenant_id` as a source~~ — explicitly excluded (spec G5).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/mixin.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/skills/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._configure_skill_file_registry",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._resolve_agents_dir",
    "sym:packages/ai-parrot/src/parrot/utils/helpers.py#RequestContext"
  ]
}
```

---

## Implementation Notes

### Precedence (spec AC-R1 — implement exactly)
`explicit` → `ctx.kwargs.get("tenant")` → `current_skill_tenant()` → `self._tenant_id` (instance default via `getattr(self, "_tenant_id", None)`, falling back to the class attribute `tenant_id`) → `None`.
The first non-empty value is validated with `validate_tenant_id` (ValueError propagates — AC-R2). With `tenant_based=False` return `None` and DEBUG-log once when any tenant was supplied (AC-B1).

### View selection (spec AC-R3/AC-R4)
- resolved `None` → `_global_view` (DEBUG log).
- resolved tenant in `_tenant_views` → that view.
- resolved tenant unknown → `_global_view` + WARNING once per tenant per instance (`_warned_tenants`).
- no global registry at all → `None`.

### Loading (spec C9, C10, edge cases)
- Each tenant registry: `SkillFileRegistry(skills_dir=<tenant skills dir>, learned_dir=<tenant skills dir> / ".learned-disabled")`.
  `load()` scans `learned_dir` (file_registry.py:44) — passing the GLOBAL learned dir would copy every learned skill into each tenant registry, and passing `<tenant>/learned` would load a tenant `learned/` that C9 says to ignore. A never-created `.learned-disabled` path yields no skills because `discover_skills_in_dir` returns `[]` for a missing directory (parsers.py:192). The authored scan already skips a `learned/` subdirectory (`exclude_subdir="learned"`, file_registry.py:43), so a tenant `learned/` is ignored; WARN when it exists (C9). Learned skills still reach every view through the global registry (`SkillView`, C8).
- `tenant_based=True` and `agents_dir` is `None` (skill_paths-only agents) → WARNING once, global only.
- One INFO per tenant: `tenant=%s skills=%d shadowing=%s dropped=%s` from `view.report`.

### Key Constraints
- `tenant_based=False`: no scan, no extra state that changes behaviour (AC-B1).
- `_enter_skill_tenant` returns `None` when `tenant_based` is False (TASK-4496 then skips the reset).
- `_after_tenant_reload` is a no-op hook here; TASK-4503/4504 extend it with `super()`-style calls inside the same class (they edit this method's body, not override it).

---

## Implementation Blueprint

### Steps (in order)
1. Add imports and class attributes next to `_active_skill` — *why*: spec M3 attribute block.
2. Add the cooperative `__init__` — *why*: `tenant_based=` / `tenant_id=` constructor kwargs (spec G1/G5).
3. Add resolver, `known_tenants`, `current_skill_view`, hooks — *why*: single accessor for every consumer.
4. Add `_load_tenant_skill_trees` + call it from `_configure_skill_file_registry` — *why*: eager loading (G2).
5. Add `reload_tenant_skills` + `_after_tenant_reload` — *why*: AC-E1.
6. Re-exports; tests.

### `packages/ai-parrot/src/parrot/skills/mixin.py` (MODIFY) — attributes + __init__
```python
# occurrences: 1 (verified: grep -c '    _active_skill: Optional[SkillDefinition] = None' packages/ai-parrot/src/parrot/skills/mixin.py)
# AFTER — insert below `    _active_skill: Optional[SkillDefinition] = None` (mixin.py:80)
    tenant_based: bool = False
    """Opt-in per-tenant skill trees under ``AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`` (FEAT-707)."""
    tenant_id: Optional[str] = None
    """Instance-level default tenant (lowest precedence). Class attribute or ``tenant_id=`` kwarg."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        tenant_based = kwargs.pop("tenant_based", None)
        tenant_id = kwargs.pop("tenant_id", None)
        super().__init__(*args, **kwargs)
        if tenant_based is not None:
            self.tenant_based = bool(tenant_based)
        default_tenant = tenant_id if tenant_id is not None else type(self).tenant_id
        if default_tenant is not None:
            self._tenant_id = validate_tenant_id(default_tenant)
        self._tenant_registries: Dict[str, "SkillFileRegistry"] = {}
        self._tenant_views: Dict[str, SkillView] = {}
        self._global_view: Optional[SkillView] = None
        self._known_tenants: set[str] = set()
        self._warned_tenants: set[str] = set()
```
**Why**: `_known_tenants` is a live set so `global_layer_condition` (TASK-4498) sees reloads. Setting `_tenant_id` only when given keeps intent_router's `"default"` fallback.

### `mixin.py` (MODIFY) — resolver, view, hooks (insert after `_resolve_agents_dir`, mixin.py:82-103)
```python
    def _resolve_tenant(self, explicit: Optional[str] = None, ctx: Optional["RequestContext"] = None) -> Optional[str]:
        """Resolve the skill tenant: explicit → ctx.kwargs["tenant"] → bound ContextVar → instance default.

        Raises:
            ValueError: the first non-empty candidate is not a valid tenant id.
        """
        # FILL IN: precedence per Implementation Notes; tenant_based False → DEBUG + None — bounded by AC-R1, AC-R2, AC-B1

    def known_tenants(self) -> frozenset[str]:
        """Tenants with a loaded skill tree."""
        return frozenset(self._known_tenants)

    def current_skill_view(self, tenant: Optional[str] = None) -> Optional[SkillView]:
        """View for ``tenant`` (resolved when ``None``); global view for unresolved/unknown tenants."""
        # FILL IN: view selection per Implementation Notes — bounded by AC-R3, AC-R4

    def _enter_skill_tenant(self, tenant: Optional[str], ctx: Optional["RequestContext"]) -> Optional[Token]:
        """Bind the resolved tenant for one ask()/ask_stream() call (called by BaseBot, TASK-4496)."""
        if not self.tenant_based:
            return None
        return bind_skill_tenant(self._resolve_tenant(tenant, ctx))

    def _exit_skill_tenant(self, token: Optional[Token]) -> None:
        """Undo :meth:`_enter_skill_tenant`."""
        if token is not None:
            reset_skill_tenant(token)
```

### `mixin.py` (MODIFY) — loading + reload
```python
# occurrences: 1 (verified: grep -c '    async def _configure_skill_file_registry(self) -> None:' .../skills/mixin.py)
# INSIDE _configure_skill_file_registry, AFTER the `logger.info("SkillFileRegistry loaded: ...")` call (mixin.py:194-198),
# still inside `if agents_dir:`:
            self._global_view = SkillView(self._skill_file_registry, logger=logger)
            if self.tenant_based:
                await self._load_tenant_skill_trees(agents_dir / agent_id)
# AND after the FEAT-188 `skill_paths` block (mixin.py:200-222), before the prompt-layer block:
        # FILL IN: if self._skill_file_registry is not None: (re)build self._global_view so skill_paths
        #          skills are included; if tenant_based and agents_dir is None → WARNING once (global only)
        #          — bounded by spec §2 edge case "skill_paths-only agents"

    async def _load_tenant_skill_trees(self, agent_root: Path) -> Dict[str, TenantTreeReport]:
        """Discover and load every ``tenants/<t>/skills`` tree into a registry + view; one INFO per tenant."""
        # FILL IN: discover_tenant_dirs(agent_root, logger); per tenant: if (dir/"learned").exists() → WARNING (C9);
        #          reg = SkillFileRegistry(skills_dir=dir, learned_dir=dir / ".learned-disabled"); await reg.load();
        #          SkillView(self._skill_file_registry, reg, tenant=t, logger=...);
        #          fill _tenant_registries/_tenant_views/_known_tenants (clear first — reload reuses this);
        #          log report; return {tenant: report} — bounded by G2, C9, C10
        #          (missing learned_dir is safe: discover_skills_in_dir returns [] — parsers.py:192)

    async def reload_tenant_skills(self, tenant: Optional[str] = None) -> Dict[str, TenantTreeReport]:
        """Rescan one (``tenant``) or all tenant trees and rebuild their views; then ``_after_tenant_reload``."""
        # FILL IN: guard global registry/agents_dir; all → _load_tenant_skill_trees; single → validate_tenant_id,
        #          rebuild only that entry (drop it when its dir disappeared); await self._after_tenant_reload(reports)
        #          — bounded by AC-E1

    async def _after_tenant_reload(self, reports: Dict[str, TenantTreeReport]) -> None:
        """Extension point: prompt layers (TASK-4503) and store registries (TASK-4504) refresh here."""
        return None
```

### `packages/ai-parrot/src/parrot/skills/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .mixin import (' packages/ai-parrot/src/parrot/skills/__init__.py)
# BEFORE `from .mixin import (` (line 67):
from .tenancy import (
    SkillView,
    TenantTreeReport,
    current_active_skill,
    current_skill_tenant,
    set_active_skill,
    validate_tenant_id,
)
# occurrences: 1 (verified: grep -c '    "SkillRegistryHooks",' .../skills/__init__.py)
# AFTER `    "SkillRegistryHooks",` (line 109):
    # Tenancy (FEAT-707)
    "SkillView",
    "TenantTreeReport",
    "current_active_skill",
    "current_skill_tenant",
    "set_active_skill",
    "validate_tenant_id",
```

### `packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py` (CREATE)
```python
"""FEAT-707 — SkillRegistryMixin tenant core (TASK-4499)."""
import logging
from pathlib import Path

import pytest

from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant
from parrot.utils.helpers import RequestContext

# FILL IN: fixture `agent_tree(tmp_path)` per spec §4 Test Data (global skills/, tenants/pokemon, tenants/epson,
#          tenants/skills (reserved), tenants/pokemon/skills/learned/); a minimal host class
#          `class Host(SkillRegistryMixin): name = "troc_finance"; enable_skill_registry = False` with
#          `_agents_dir = tmp_path` and no prompt builder/pipeline/tool_manager; call
#          `await host._configure_skill_file_registry()` directly.
# Tests:
#  test_tenant_based_false_no_scan (no tenant registries, current_skill_view() is the global view)
#  test_configure_loads_tenant_trees_eagerly (+ INFO line per tenant via caplog)
#  test_reserved_tenant_dir_skipped
#  test_tenant_learned_dir_ignored_with_warning (C9)
#  test_resolve_tenant_precedence (explicit > ctx.kwargs > ContextVar > instance default > None)
#  test_constructor_kwargs_tenant_based_and_tenant_id
#  test_unresolved_tenant_global_view_debug
#  test_unknown_tenant_warns_once_per_instance
#  test_invalid_tenant_raises
#  test_enter_exit_hooks_bind_and_reset
#  test_reload_tenant_skills_adds_new_tenant
#  test_skill_paths_only_agent_tenant_based_warns
# — bounded by AC-B1, AC-L1, AC-R1..R4, AC-E1
```

### FILL IN checklist
- [ ] `_resolve_tenant` — AC-R1, AC-R2, AC-B1
- [ ] `current_skill_view` — AC-R3, AC-R4
- [ ] global view rebuild after skill_paths + skill_paths-only warning
- [ ] `_load_tenant_skill_trees` — G2, C9, C10
- [ ] `reload_tenant_skills` — AC-E1
- [ ] twelve tests

---

## Acceptance Criteria

- [ ] AC-B1 for `tenant_based=False`; AC-R1..R4 and AC-E1 covered by tests.
- [ ] `parrot.skills` re-exports the six tenancy names.
- [ ] `test_skill_file_registry.py`, `test_skill_system.py` pass unmodified.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_mixin.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_file_registry.py -q`
- `pytest packages/ai-parrot/tests/integration/test_skill_system.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §2 Overview + Collision matrix, §3 Module 3, §7.
3. **Check dependencies**: TASK-4494 `done`.
4. **Verify the Codebase Contract** (especially how `SkillFileRegistry.load()` treats `learned_dir`).
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4499 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: adds the `_after_tenant_reload` extension point (not in the skeleton) so TASK-4503/4504 can hook reload without re-editing its body logic.
