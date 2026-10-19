# TASK-4498: Tenant-aware skill prompt layers

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4494
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. With `tenant_based=True` the mixin installs one static
REQUEST-phase `<available_skills>` layer per view (`available_skills` for the
global view, `available_skills:{tenant}` per tenant), each with a `condition`
that reads the tenant ContextVar. REQUEST-phase layers keep their condition
through `PromptBuilder.configure()` (verified, design-research S4 triage).
This task also adds `build_active_skill_layer()` — the permanent conditional
`skill_active` layer that replaces per-request builder mutation (S5, used by TASK-4501).

---

## Scope

- Extend `render_skills_prompt_layer()` with keyword-only `name`, `phase`, `condition`, `cacheable`.
  Defaults reproduce today's layer byte-for-byte (AC-P2). Accept a `SkillView` or a `SkillFileRegistry` (duck-typed: only `list_skills()` is used).
- Add `build_active_skill_layer(priority: int = 90) -> PromptLayer`.
- Add two small condition factories used by the mixin: `tenant_layer_condition(tenant)` and `global_layer_condition(known_tenants)`.
- Write `packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py`.

**NOT in scope**: installing layers on a builder (TASK-4503), `create_system_prompt` (TASK-4501).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/prompt.py` | MODIFY | new keyword params + `build_active_skill_layer` + condition factories |
| `packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts import PromptLayer, RenderPhase          # verified: skills/prompt.py:24 (existing import)
from parrot.skills.tenancy import current_skill_tenant, SkillView  # created by TASK-4494
from parrot.skills.file_registry import SkillFileRegistry          # verified: skills/prompt.py:26 (existing relative import)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/prompt.py
def render_skills_prompt_layer(registry: SkillFileRegistry, max_skills: Optional[int] = None, priority: int = 45) -> PromptLayer:  # line 29
#   three returns, all PromptLayer(name="available_skills", priority=priority, template=..., phase=RenderPhase.CONFIGURE)  # 61-66, 71-76, 93-98

# packages/ai-parrot/src/parrot/bots/prompts/layers.py
@dataclass(frozen=True)
class PromptLayer:                                                   # line 51
    name: str; priority: LayerPriority | int; template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = frozenset()
    cacheable: Optional[bool] = None      # __post_init__: None → (phase == CONFIGURE)
    def render(self, context) -> Optional[str]: ...                  # line 82; condition evaluated per call; string.Template.safe_substitute
```

### Does NOT Exist
- ~~`render_skills_prompt_layer(name=..., phase=..., condition=..., cacheable=...)`~~ — added here.
- ~~`build_active_skill_layer`~~, ~~`tenant_layer_condition`~~, ~~`global_layer_condition`~~ — added here.
- ~~`PromptLayer` with a callable template~~ — `template` is a `str`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/prompt.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/prompt.py#render_skills_prompt_layer",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/layers.py#PromptLayer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- AC-P2: `render_skills_prompt_layer(registry)` / `(registry, max_skills=N)` output must be identical to today — existing `tests/unit/test_skills_prompt_layer.py` asserts `phase == CONFIGURE` and `name == "available_skills"`.
- Skill names/descriptions may contain `$`: the layer goes through `Template.safe_substitute` at render time. The current code already has this property; do not add escaping (out of scope), but the `skill_active` template must be exactly `"$active_skill_body"` so the body is substituted, not parsed.
- Conditions read the ContextVar, not the `ctx` dict, so they work no matter what variables the request context carries.

---

## Implementation Blueprint

### Steps (in order)
1. Change the signature and thread the four params into all three `PromptLayer(...)` returns — *why*: tenant layers need name/phase/condition/cacheable (spec M4).
2. Add the condition factories — *why*: the mixin should not hand-write lambdas (keeps the rule in one place).
3. Add `build_active_skill_layer` — *why*: permanent conditional layer for S5.
4. Tests.

### `packages/ai-parrot/src/parrot/skills/prompt.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def render_skills_prompt_layer(' packages/ai-parrot/src/parrot/skills/prompt.py)
# imports (top): add
from typing import Any, Callable, Collection, Dict
from .tenancy import current_skill_tenant

# REPLACE the signature at prompt.py:29-33:
def render_skills_prompt_layer(
    registry: Any,
    max_skills: Optional[int] = None,
    priority: int = 45,
    *,
    name: str = "available_skills",
    phase: RenderPhase = RenderPhase.CONFIGURE,
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
    cacheable: Optional[bool] = None,
) -> PromptLayer:
# In each of the three `return PromptLayer(...)` (prompt.py:61, :71, :93) replace
#   name="available_skills", ... phase=RenderPhase.CONFIGURE,
# with
#   name=name, ... phase=phase, condition=condition, cacheable=cacheable,
# FILL IN: update the docstring (Args + Returns) — `registry` is any object with list_skills()
#          (SkillFileRegistry or SkillView) — bounded by AC-P2 (defaults unchanged)


def tenant_layer_condition(tenant: str) -> Callable[[Dict[str, Any]], bool]:
    """Condition true only while ``tenant`` is the bound skill tenant (FEAT-707)."""
    return lambda _ctx: current_skill_tenant() == tenant


def global_layer_condition(known_tenants: Collection[str]) -> Callable[[Dict[str, Any]], bool]:
    """Condition true when no KNOWN tenant is bound (unresolved/unknown tenants see the global view)."""
    # FILL IN: snapshot `known` as a frozenset at call time? NO — accept a Collection the caller can
    #          update on reload (pass the mixin's live set); return lambda _ctx: current_skill_tenant() not in known_tenants
    #          — bounded by AC-R3/AC-R4 (unknown tenant → global view) and AC-E1 (reload adds tenants)


def build_active_skill_layer(priority: int = 90) -> PromptLayer:
    """Permanent REQUEST-phase ``skill_active`` layer rendering ``$active_skill_body`` when non-empty (S5)."""
    return PromptLayer(
        name="skill_active",
        priority=priority,
        template="$active_skill_body",
        phase=RenderPhase.REQUEST,
        condition=lambda ctx: bool(ctx.get("active_skill_body")),
        cacheable=False,
    )
```
**Why**: `priority=90` matches today's transient layer (abstract.py:3575, "After CUSTOM(80)"); `cacheable=False` because the body changes per request.

### `packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py` (CREATE)
```python
"""FEAT-707 — tenant-aware skill prompt layers (TASK-4498)."""
from pathlib import Path

import pytest

from parrot.bots.prompts import RenderPhase
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.prompt import (
    build_active_skill_layer, global_layer_condition, render_skills_prompt_layer, tenant_layer_condition,
)
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant

# FILL IN tests:
#  test_render_layer_defaults_unchanged — same template/name/phase/cacheable as before for a populated registry
#  test_render_layer_tenant_variant — name/phase/condition/cacheable passed through
#  test_tenant_condition_matches_only_bound_tenant
#  test_global_condition_hidden_when_known_tenant_bound / shown for unknown or None tenant
#  test_global_condition_sees_live_set_updates (add to the set after building → condition reflects it)
#  test_build_active_skill_layer_condition (renders body only when active_skill_body non-empty; cacheable False)
#  test_render_accepts_skill_view
# — bounded by AC-P1, AC-P2, AC-R3, AC-R4
```

### FILL IN checklist
- [ ] docstring update — AC-P2
- [ ] `global_layer_condition` body — AC-R3/R4/E1
- [ ] seven tests

---

## Acceptance Criteria

- [ ] AC-P2: default output identical; `tests/unit/test_skills_prompt_layer.py` passes unmodified.
- [ ] Tenant/global conditions follow the bound ContextVar; global condition honours later additions to the known-tenant set.
- [ ] `build_active_skill_layer()` contract as specified.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_prompt_layers.py -q`
- `pytest tests/unit/test_skills_prompt_layer.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §2 Overview (Prompt paragraph), §3 Module 4.
3. **Check dependencies**: TASK-4494 `done`.
4. **Verify the Codebase Contract**.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4498 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: adds `tenant_layer_condition` / `global_layer_condition` helpers not named in the spec skeleton (they encode the skeleton's lambdas).
