# TASK-4503: `SkillRegistryMixin` consumer wiring (providers, prompt layers, active skill, learned refresh)

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4499, TASK-4498, TASK-4495, TASK-4501
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, second half. TASK-4499 gave the mixin its views; this task
connects every consumer to them: the trigger middleware and `SkillFileToolkit`
get `view_provider=self.current_skill_view`; the `<available_skills>` layers
are installed per view (`_install_skill_prompt_layers`); `_active_skill`
becomes a property over the request-local ContextVar (S5); `save_learned_skill`
recomposes the views and re-installs the layers so a learned skill appears
everywhere (S11, AC-L2); `_after_tenant_reload` re-installs layers.

---

## Scope

- Replace the class attribute `_active_skill: Optional[SkillDefinition] = None` with a property/setter backed by `current_active_skill()` / `set_active_skill()`.
- In `_configure_skill_file_registry()`: pass `view_provider=self.current_skill_view` to `create_skill_trigger_middleware(...)` and to `SkillFileToolkit(...)` — only when `tenant_based` (keep today's calls byte-identical otherwise, AC-B1).
- Replace the FEAT-188 prompt-layer block with a call to `_install_skill_prompt_layers()`; with `tenant_based=False` it must add exactly today's layer (same `render_skills_prompt_layer(registry, max_skills=...)` call).
- `_install_skill_prompt_layers()`: global layer + one per tenant (REQUEST phase, `cacheable=True`, conditions from TASK-4498), replace-by-name, idempotent.
- `save_learned_skill()`: after the hot-add, recompose `_global_view` and every tenant view, then `_install_skill_prompt_layers()`.
- `_after_tenant_reload()`: call `_install_skill_prompt_layers()`, removing layers of tenants that disappeared.
- Write `packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py`.

**NOT in scope**: store registries (TASK-4504), `create_system_prompt` (TASK-4501, done).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/mixin.py` | MODIFY | wiring |
| `packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .tenancy import SkillView, current_active_skill, set_active_skill        # TASK-4494
from .prompt import render_skills_prompt_layer, tenant_layer_condition, global_layer_condition  # TASK-4498
from parrot.bots.prompts import RenderPhase                                   # verified: skills/prompt.py:24
from .middleware import create_skill_trigger_middleware                       # verified: mixin.py:154 (lazy import inside the method)
from .tools import SkillFileToolkit                                           # verified: mixin.py:256 (lazy import inside the method)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/mixin.py (after TASK-4499)
    _active_skill: Optional[SkillDefinition] = None                       # line 80 (to become a property)
    async def _configure_skill_file_registry(self) -> None:               # line 141
            mw = create_skill_trigger_middleware(registry=self._skill_file_registry, bot=self,)   # 188-191
        # --- FEAT-188: Prompt layer injection ---                         # ≈224
        if self._skill_file_registry is not None:
            inject = getattr(self, 'inject_skills_into_prompt', True)
            if inject and self._skill_file_registry.list_skills():
                prompt_builder = getattr(self, '_prompt_builder', None)
                if prompt_builder is not None:
                    from .prompt import render_skills_prompt_layer
                    max_entries = getattr(self, 'skill_prompt_max_entries', None)
                    layer = render_skills_prompt_layer(self._skill_file_registry, max_skills=max_entries,)
                    prompt_builder.add(layer)                              # ≈225-242
            toolkit = SkillFileToolkit(file_registry=self._skill_file_registry, learned_dir=self._skill_file_registry.learned_dir,)  # 257-260
    async def save_learned_skill(self, name, content, description, triggers, category="general") -> Optional[SkillDefinition]:  # 274
        self._skill_file_registry.add(skill)                               # ≈343 hot-add
    # TASK-4499 additions: _tenant_views, _global_view, _known_tenants, current_skill_view(), _after_tenant_reload()

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
    def add(self, layer) -> PromptBuilder      # 200 replace-by-name
    def remove(self, name) -> PromptBuilder    # 212
    def get(self, name) -> Optional[PromptLayer]   # 242
```

### Does NOT Exist
- ~~`_install_skill_prompt_layers`~~ — added here.
- ~~`PromptBuilder.layers` public listing~~ — FILL IN: check `builder.py` for an iteration API before removing stale `available_skills:*` layers; if none exists, track installed names in `self._installed_skill_layers: set[str]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/mixin.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin._configure_skill_file_registry",
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin.save_learned_skill",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder"
  ]
}
```

---

## Implementation Notes

### Layer installation rules (spec §2 Prompt, AC-P1/P2)
- `tenant_based=False`: exactly today — `render_skills_prompt_layer(self._skill_file_registry, max_skills=max_entries)` when `inject_skills_into_prompt` and the registry is non-empty.
- `tenant_based=True`: `available_skills` from `_global_view` with `phase=RenderPhase.REQUEST, condition=global_layer_condition(self._known_tenants), cacheable=True`; for each tenant `available_skills:{t}` from its view with `condition=tenant_layer_condition(t)`, same phase/cacheable. Skip a layer whose view lists no skills (and remove a previously installed one).
- Pass `self._known_tenants` (the live set), not a copy.
- The `_active_skill` property must not break `hasattr(self, "_active_skill")` checks elsewhere (it returns `None` when unset).

### Key Constraints
- Provider callables are bound methods (`self.current_skill_view`) — never a captured view.
- `save_learned_skill`'s name-collision check stays against the GLOBAL registry (spec C8 edge case).

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `_active_skill` class attribute with the property — *why*: S5 on mixin bots (AC-A1, AC-A3).
2. Add `view_provider` to the middleware and toolkit constructions when `tenant_based` — *why*: AC-C1, AC-C2.
3. Add `_install_skill_prompt_layers()` and call it in place of the FEAT-188 layer block — *why*: AC-P1, AC-P2.
4. Refresh views + layers in `save_learned_skill` and `_after_tenant_reload` — *why*: AC-L2, AC-E1.
5. Tests.

### `packages/ai-parrot/src/parrot/skills/mixin.py` (MODIFY) — active skill property
```python
# occurrences: 1 (verified: grep -c '    _active_skill: Optional[SkillDefinition] = None' .../skills/mixin.py)
# REPLACE that line (mixin.py:80) with:
    @property
    def _active_skill(self) -> Optional[SkillDefinition]:
        """The ``/trigger``-activated skill for the current request (request-local, FEAT-707 S5)."""
        return current_active_skill()

    @_active_skill.setter
    def _active_skill(self, skill: Optional[SkillDefinition]) -> None:
        set_active_skill(skill)
```

### `mixin.py` (MODIFY) — providers (inside `_configure_skill_file_registry`)
```python
# middleware construction (mixin.py:188-191):
                mw = create_skill_trigger_middleware(
                    registry=self._skill_file_registry,
                    bot=self,
                    **({"view_provider": self.current_skill_view} if self.tenant_based else {}),
                )
# toolkit construction (mixin.py:257-260):
            toolkit = SkillFileToolkit(
                file_registry=self._skill_file_registry,
                learned_dir=self._skill_file_registry.learned_dir,
                **({"view_provider": self.current_skill_view} if self.tenant_based else {}),
            )
```

### `mixin.py` (MODIFY) — layers
```python
# REPLACE the body of the `# --- FEAT-188: Prompt layer injection ---` block with:
        self._install_skill_prompt_layers()

    def _install_skill_prompt_layers(self) -> None:
        """Install (replace-by-name) the ``<available_skills>`` layers for the global and tenant views."""
        prompt_builder = getattr(self, '_prompt_builder', None)
        if prompt_builder is None or self._skill_file_registry is None:
            return
        if not getattr(self, 'inject_skills_into_prompt', True):
            return
        max_entries = getattr(self, 'skill_prompt_max_entries', None)
        if not self.tenant_based:
            if self._skill_file_registry.list_skills():
                prompt_builder.add(render_skills_prompt_layer(self._skill_file_registry, max_skills=max_entries))
            return
        # FILL IN: tenant mode per "Layer installation rules": global layer from self._global_view with
        #          global_layer_condition(self._known_tenants); one layer per tenant view; remove layers of
        #          tenants no longer known / with empty views (track names in self._installed_skill_layers)
        #          — bounded by AC-P1, AC-E1
```

### `mixin.py` (MODIFY) — learned refresh and reload
```python
# occurrences: 1 (verified: grep -c '    async def save_learned_skill(' .../skills/mixin.py)
# AFTER the hot-add `self._skill_file_registry.add(skill)` (≈mixin.py:343), before `logger.info(...)`:
        self._recompose_skill_views()
        self._install_skill_prompt_layers()

    def _recompose_skill_views(self) -> None:
        """Recompute the global and every tenant view after a global registry change (learned skills)."""
        # FILL IN: self._global_view.compose() when set; view.compose() for each tenant view — bounded by AC-L2

# in `_after_tenant_reload` (added by TASK-4499) replace `return None` with:
        self._recompose_skill_views()
        self._install_skill_prompt_layers()
```

### `packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py` (CREATE)
```python
"""FEAT-707 — mixin consumer wiring (TASK-4503)."""
import pytest

from parrot.bots.prompts import PromptBuilder  # FILL IN: verify the export name in parrot/bots/prompts/__init__.py
from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant

# FILL IN: host fixture like TASK-4499's plus a real PromptBuilder as `_prompt_builder` and a list `_tools`.
# Tests:
#  test_flag_off_installs_exactly_todays_layer (name/phase/template equal to render_skills_prompt_layer(registry))
#  test_tenant_layers_installed_per_view
#  test_only_bound_tenant_layer_renders (builder.build with pokemon bound → pokemon block only)
#  test_unknown_tenant_renders_global_layer
#  test_toolkit_and_middleware_receive_view_provider
#  test_active_skill_property_is_request_local (two tasks)
#  test_save_learned_skill_refreshes_layers_and_views (S11)
#  test_reload_removes_layer_of_deleted_tenant
# — bounded by AC-B1, AC-P1, AC-P2, AC-L2, AC-E1, AC-A1
```

### FILL IN checklist
- [ ] builder iteration API vs `_installed_skill_layers`
- [ ] tenant-mode layer installation — AC-P1, AC-E1
- [ ] `_recompose_skill_views` — AC-L2
- [ ] `PromptBuilder` import path
- [ ] eight tests

---

## Acceptance Criteria

- [ ] AC-B1, AC-P1, AC-P2, AC-L2, AC-E1, AC-A1 (mixin side), AC-C1, AC-C2.
- [ ] Pre-existing skill tests pass unmodified.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_tenant_wiring.py -q`
- `pytest packages/ai-parrot/tests/integration/test_skill_system.py -q`
- `pytest tests/unit/test_skills_prompt_layer.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §2 Prompt paragraph, §3 Module 3.
3. **Check dependencies**: TASK-4499, TASK-4498, TASK-4495, TASK-4501 `done`.
4. **Verify the Codebase Contract** — mixin.py line numbers will have moved after TASK-4499; re-grep.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4503 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: adds private helper `_recompose_skill_views()`.
