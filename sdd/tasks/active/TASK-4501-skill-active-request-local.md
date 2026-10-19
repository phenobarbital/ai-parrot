# TASK-4501: Request-local active skill and view-aware trigger middleware

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4494, TASK-4498
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 + the middleware part of Module 5; design-research S5 (user
decision 2026-10-19). Today the trigger middleware writes `bot._active_skill`
and `create_system_prompt()` adds/removes a `skill_active` layer on the
SHARED `PromptBuilder` per request (abstract.py:3569-3593). On a singleton
agent two concurrent requests can render each other's skill — with tenants,
one customer's skill in another customer's prompt. This task moves the active
skill to the request-local ContextVar (`set_active_skill` /
`current_active_skill`, TASK-4494), installs `skill_active` once as a permanent
conditional layer (`build_active_skill_layer`, TASK-4498), and makes the
middleware read through an optional `view_provider`.

---

## Scope

- `create_skill_trigger_middleware(registry, bot, priority=-10, *, view_provider=None)`: lookups (`/skills`, `/help` listing and `get(trigger)`) go through `view_provider()` when given; a match calls `set_active_skill(skill)` instead of `bot._active_skill = skill`.
- `AbstractBot.create_system_prompt()`: replace the add/remove block with: read `current_active_skill()` (fallback `getattr(self, "_active_skill", None)` for legacy non-mixin bots), install `build_active_skill_layer()` once if absent, pass `active_skill_body=` into `_build_prompt`, then clear (`set_active_skill(None)` and, for the legacy attribute, set it back to `None` only when it was the source).
- Write `packages/ai-parrot/tests/unit/test_skill_active_request_local.py`.

**NOT in scope**: the mixin's `_active_skill` property (TASK-4503), Telegram `/skill` (TASK-4500), wiring `view_provider` from the mixin (TASK-4503).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/skills/middleware.py` | MODIFY | `view_provider`; `set_active_skill` |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | request-local active skill in `create_system_prompt` |
| `packages/ai-parrot/tests/unit/test_skill_active_request_local.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.middleware import PromptMiddleware                     # verified: skills/middleware.py:11
from parrot.skills.tenancy import current_active_skill, set_active_skill  # TASK-4494
from parrot.skills.prompt import build_active_skill_layer               # TASK-4498
from parrot.bots.prompts.layers import PromptLayer, RenderPhase         # verified: abstract.py:3571 (lazy import style)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/skills/middleware.py
def create_skill_trigger_middleware(registry: SkillFileRegistry, bot: "AbstractBot", priority: int = -10) -> PromptMiddleware:  # line 16
    async def transform(query: str, context: Dict[str, Any]) -> str:
        if trigger in ("/skills", "/help"):
            skills = registry.list_skills()                                # line 51
        skill = registry.get(trigger)                                      # line 62
        if skill is not None:
            bot._active_skill = skill  # Set via closure reference        # line 64
            return remaining
    return PromptMiddleware(name="skill_trigger", priority=priority, transform=transform)   # 72-76

# packages/ai-parrot/src/parrot/bots/abstract.py — inside `async def create_system_prompt(` (line 3544)
        if self._prompt_builder:
            # Inject transient skill layer if a skill was activated via /trigger
            _has_active_skill = hasattr(self, "_active_skill") and self._active_skill is not None   # 3569
            if _has_active_skill:
                from parrot.bots.prompts.layers import PromptLayer, RenderPhase
                skill_layer = PromptLayer(name="skill_active", priority=90, template=self._active_skill.template_body, phase=RenderPhase.REQUEST)
                self._prompt_builder.add(skill_layer)                       # ~3578
            result = self._build_prompt(user_context=user_context, vector_context=vector_context, kb_context=kb_context,
                                        pageindex_context=pageindex_context, metadata=metadata, **kwargs)   # 3580-3587
            # Remove transient skill layer and clear active skill
            if _has_active_skill:
                self._prompt_builder.remove("skill_active")                # 3592
                self._active_skill = None                                   # 3593

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
    def add(self, layer) -> PromptBuilder      # 200 (replace-by-name)
    def get(self, name) -> Optional[PromptLayer]   # 242
# _build_prompt(**kwargs) forwards extra kwargs into request_context (abstract.py:1491-1500) → `active_skill_body` reaches the layer condition/template
```

### Does NOT Exist
- ~~`create_skill_trigger_middleware(view_provider=...)`~~ — added here.
- ~~`PromptBuilder.has()`~~ — use `get(name) is None`.
- ~~Editing `parrot.memory.skills.middleware`~~ — deprecated shim; existing `test_skill_trigger_middleware.py` imports through it and must keep passing.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/skills/middleware.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_skill_active_request_local.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/middleware.py#create_skill_trigger_middleware",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.create_system_prompt",
    "sym:packages/ai-parrot/src/parrot/bots/prompts/builder.py#PromptBuilder"
  ]
}
```

---

## Implementation Notes

### Compatibility with the existing middleware test
`packages/ai-parrot/tests/unit/test_skill_trigger_middleware.py` asserts on `mock_bot._active_skill` after a trigger (MagicMock bot). To keep it passing UNMODIFIED (AC-0), the middleware must ALSO keep setting the attribute when the bot is not a mixin bot with the ContextVar-backed property. Rule: always call `set_active_skill(skill)`; additionally assign `bot._active_skill = skill` (on a mixin bot after TASK-4503 this assignment is the same ContextVar write through the property; on a MagicMock it keeps the old observable behaviour). Verify by running that test file.

### `create_system_prompt` clearing rule
After building: `set_active_skill(None)`; and if the legacy attribute is a plain instance attribute (not the mixin property) and was the source, set it to `None` — `"_active_skill" in vars(self)` distinguishes the two. AC-A2: the skill applies to ONE ask.

### Key Constraints
- AC-P3: the builder's layer set must be identical before and after a call (only the idempotent first-time `add` of `skill_active` is allowed).
- Lazy imports inside the method (existing style at abstract.py:3571) — no module-level `parrot.skills` import in abstract.py.

---

## Implementation Blueprint

### Steps (in order)
1. Middleware: add `view_provider`, a local `_reg()` helper, route the two lookups, set the ContextVar — *why*: S5 + per-tenant `/trigger` (AC-C2).
2. `create_system_prompt`: replace lines 3567-3593's skill handling as below — *why*: AC-A1..A3, AC-P3.
3. Tests.

### `packages/ai-parrot/src/parrot/skills/middleware.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def create_skill_trigger_middleware(' packages/ai-parrot/src/parrot/skills/middleware.py)
from typing import Any, Callable, Dict, Optional
from .tenancy import set_active_skill

def create_skill_trigger_middleware(
    registry: SkillFileRegistry,
    bot: "AbstractBot",
    priority: int = -10,
    *,
    view_provider: Optional[Callable[[], Any]] = None,
) -> PromptMiddleware:
    # docstring: add `view_provider` (per-request SkillView, FEAT-707) and note the request-local activation

    def _reg() -> Any:
        current = view_provider() if view_provider is not None else None
        return current if current is not None else registry

    # in transform(): `registry.list_skills()` (line 51) → `_reg().list_skills()`
    #                 `registry.get(trigger)` (line 62)  → `_reg().get(trigger)`
# occurrences: 1 (verified: grep -c '            bot._active_skill = skill  # Set via closure reference' .../skills/middleware.py)
# REPLACE middleware.py:64 with:
            set_active_skill(skill)  # request-local (FEAT-707, S5)
            bot._active_skill = skill  # legacy observable; a ContextVar write on mixin bots (TASK-4503)
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            _has_active_skill = hasattr(self, "_active_skill") and self._active_skill is not None' .../bots/abstract.py)
# REPLACE from the comment line above abstract.py:3569 through `self._active_skill = None` (3593), keeping the
# `result = self._build_prompt(...)` call, with:
            # FEAT-707 (S5): the /trigger skill is request-local; the layer is permanent and conditional.
            from parrot.skills.prompt import build_active_skill_layer
            from parrot.skills.tenancy import current_active_skill, set_active_skill

            _legacy_attr = "_active_skill" in vars(self)
            active = current_active_skill() or getattr(self, "_active_skill", None)
            if self._prompt_builder.get("skill_active") is None:
                self._prompt_builder.add(build_active_skill_layer())

            result = self._build_prompt(
                user_context=user_context,
                vector_context=vector_context,
                kb_context=kb_context,
                pageindex_context=pageindex_context,
                metadata=metadata,
                active_skill_body=(active.template_body if active is not None else ""),
                **kwargs,
            )

            # FILL IN: clear — set_active_skill(None); if _legacy_attr: self._active_skill = None
            #          — bounded by AC-A2 (one ask) and the clearing rule in Implementation Notes
# FILL IN: if `kwargs` can already contain `active_skill_body`, pop it first so the call does not raise
#          "got multiple values" — bounded by AC-B2 (no breaking change)
```
**Why**: `build_active_skill_layer` renders only when `active_skill_body` is non-empty, so the permanent layer is invisible on normal asks; `PromptBuilder.add` is replace-by-name, so the guard keeps the add idempotent (AC-P3).

### `packages/ai-parrot/tests/unit/test_skill_active_request_local.py` (CREATE)
```python
"""FEAT-707 — request-local active skill (TASK-4501)."""
import asyncio

import pytest

from parrot.skills.middleware import create_skill_trigger_middleware
from parrot.skills.tenancy import current_active_skill, set_active_skill

# FILL IN tests:
#  test_middleware_sets_active_skill_contextvar
#  test_middleware_uses_view_provider (provider registry wins; None provider → constructor registry)
#  test_skills_listing_uses_view
#  test_create_system_prompt_no_builder_mutation — find the lightest existing AbstractBot/BaseBot test
#      double with a PromptBuilder (grep tests for `_prompt_builder`) and compare the builder's layer
#      names before/after two calls; `skill_active` present exactly once
#  test_active_skill_body_rendered_once_then_cleared (AC-A2)
#  test_concurrent_trigger_isolation — two tasks via asyncio.gather each set a different skill and
#      build a prompt; each prompt contains only its own body (AC-A1)
#  test_legacy_attribute_fallback (plain attribute on a non-mixin bot still injected and cleared) (AC-A3)
# — bounded by AC-A1, AC-A2, AC-A3, AC-P3, AC-C2
```

### FILL IN checklist
- [ ] clearing rule — AC-A2
- [ ] `active_skill_body` collision guard — AC-B2
- [ ] seven tests

---

## Acceptance Criteria

- [ ] AC-A1, AC-A2, AC-A3, AC-P3 satisfied and tested.
- [ ] `test_skill_trigger_middleware.py` and `test_skill_system.py` pass unmodified.
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_skill_active_request_local.py -q`
- `pytest packages/ai-parrot/tests/unit/test_skill_trigger_middleware.py -q`
- `pytest packages/ai-parrot/tests/integration/test_skill_system.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §3 Module 7, §7 Known Risks (S5), §9 S5.
3. **Check dependencies**: TASK-4494 and TASK-4498 `done`.
4. **Verify the Codebase Contract** — re-read abstract.py 3560-3600 before replacing.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4501 per-tenant-skills verified`.
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: the middleware keeps the legacy `bot._active_skill = skill` assignment alongside `set_active_skill()` so the pre-existing middleware test stays unmodified (AC-0); on mixin bots both are the same ContextVar write.
