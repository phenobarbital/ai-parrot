# TASK-616: Mixin & Prompt Integration

**Feature**: Agent Skill System
**Spec**: `sdd/specs/agent-skill-system.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-614, TASK-615
**Assigned-to**: unassigned

---

## Context

> Module 4 of FEAT-088. Wires `SkillFileRegistry` + `SkillTriggerMiddleware` into the bot
> lifecycle via the existing `SkillRegistryMixin`. Modifies `create_system_prompt()` to
> inject/remove a transient `PromptLayer` when a skill is active. This is the most
> integration-heavy task. See spec Section 3, Module 4.

---

## Scope

- Extend `SkillRegistryMixin` in `parrot/memory/skills/mixin.py` with:
  - `_skill_file_registry: Optional[SkillFileRegistry] = None` attribute
  - `_active_skill: Optional[SkillDefinition] = None` attribute
  - `async def _configure_skill_file_registry(self) -> None` method that:
    1. Resolves `AGENTS_DIR/{agent_id}/skills/` path
    2. Creates `SkillFileRegistry` with skills_dir and learned_dir
    3. Calls `await registry.load()`
    4. Creates and registers `SkillTriggerMiddleware` in `self._prompt_pipeline`
  - `async def save_learned_skill(self, name, content, description, triggers, category) -> Optional[SkillDefinition]` method
- Modify `_configure_skill_registry()` to also call `_configure_skill_file_registry()`
- Modify `create_system_prompt()` in `AbstractBot` (or via mixin hook) to:
  1. Check `self._active_skill`
  2. If set: create transient `PromptLayer(name="skill_active", priority=90, template=skill.template_body)`
  3. Add to `self._prompt_builder` via `add()`
  4. Call `_build_prompt()` / `build()`
  5. Remove the transient layer via `remove("skill_active")`
  6. Clear `self._active_skill = None`
- Ensure bots without `SkillsMixin` are unaffected

**NOT in scope**: Tool adaptation (TASK-617), test suite (TASK-618)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/skills/mixin.py` | MODIFY | Add file registry attributes, configure method, save_learned_skill |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | ~15 lines in create_system_prompt to inject/remove transient skill layer |
| `packages/ai-parrot/src/parrot/memory/skills/__init__.py` | MODIFY | Export new symbols if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing mixin (to extend):
from parrot.memory.skills.mixin import SkillRegistryMixin  # verified: mixin.py:19

# From TASK-613/614/615:
from parrot.memory.skills.models import SkillDefinition, SkillSource  # TASK-613
from parrot.memory.skills.file_registry import SkillFileRegistry  # TASK-614
from parrot.memory.skills.middleware import create_skill_trigger_middleware  # TASK-615

# Prompt system:
from parrot.bots.prompts.layers import PromptLayer, RenderPhase  # verified: layers.py:50,35
from parrot.bots.prompts.builder import PromptBuilder  # verified: builder.py:20
from parrot.bots.middleware import PromptPipeline  # verified: middleware.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/skills/mixin.py:19-201
class SkillRegistryMixin:
    enable_skill_registry: bool = True           # line 35
    _skill_registry: Optional[SkillRegistry] = None  # line 43
    async def _configure_skill_registry(self) -> None:  # line 45
    async def _add_skill_tools(self) -> None:    # line 78
    async def document_skill(self, name, content, description, category, tags, triggers) -> Optional[Skill]:  # line 117

# packages/ai-parrot/src/parrot/bots/abstract.py:1690-1727
async def create_system_prompt(
    self,
    user_context: str = "",
    vector_context: str = "",
    conversation_context: str = "",
    kb_context: str = "",
    pageindex_context: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    memory_context: Optional[str] = None,
    **kwargs
) -> str:

# packages/ai-parrot/src/parrot/bots/abstract.py:790-848
def _build_prompt(self, user_context, vector_context, ..., **kwargs) -> str:

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:
    def add(self, layer: PromptLayer) -> PromptBuilder:    # line 108
    def remove(self, name: str) -> PromptBuilder:          # line 120
    def build(self, context: Dict[str, Any]) -> str:       # line 196

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST

# packages/ai-parrot/src/parrot/bots/middleware.py:23
class PromptPipeline:
    def add(self, middleware: PromptMiddleware) -> None:    # line 30
```

### Does NOT Exist
- ~~`PromptBuilder.add_transient()`~~ — no transient layer API; use `add()` then `remove()`
- ~~`LayerPriority.SKILL`~~ — no SKILL priority; use int `90` directly
- ~~`SkillRegistryMixin._active_skill`~~ — does not exist yet; add in this task
- ~~`SkillRegistryMixin._skill_file_registry`~~ — does not exist yet; add in this task
- ~~`SkillRegistryMixin._configure_skill_file_registry`~~ — does not exist yet; add in this task
- ~~`AbstractBot._active_skill`~~ — does not exist on AbstractBot; added via mixin

---

## Implementation Notes

### Key Integration Pattern
The transient layer must be added BEFORE `build()` and removed AFTER:

```python
# In create_system_prompt() or the method that calls _build_prompt():
if hasattr(self, '_active_skill') and self._active_skill is not None:
    skill = self._active_skill
    skill_layer = PromptLayer(
        name="skill_active",
        priority=90,  # After CUSTOM(80)
        template=skill.template_body,
        phase=RenderPhase.REQUEST,
    )
    self._prompt_builder.add(skill_layer)

# ... existing build logic ...
result = self._build_prompt(...)

if hasattr(self, '_active_skill') and self._active_skill is not None:
    self._prompt_builder.remove("skill_active")
    self._active_skill = None

return result
```

### AGENTS_DIR Resolution
Look at how `_configure_skill_registry` (line 45) resolves paths. The existing mixin
already knows how to find `AGENTS_DIR`. Follow the same pattern.

### Key Constraints
- `_active_skill` is NOT thread-safe (acceptable per spec, matches `self.status` pattern)
- The transient layer MUST be removed after build to avoid leaking into subsequent requests
- `create_system_prompt()` is on `AbstractBot` — the modification must be guarded with `hasattr` so bots without `SkillsMixin` are unaffected
- `_configure_skill_file_registry()` should be called from within `_configure_skill_registry()` at the end
- File-based skills should coexist with the existing vector-based `SkillRegistry` — don't break it

---

## Acceptance Criteria

- [ ] `SkillRegistryMixin._skill_file_registry` populated at configure time
- [ ] `SkillRegistryMixin._active_skill` attribute exists, defaults to None
- [ ] `SkillTriggerMiddleware` registered in bot's `_prompt_pipeline` during configure
- [ ] Active skill injects `PromptLayer(priority=90)` into system prompt
- [ ] Transient layer removed after prompt build
- [ ] `_active_skill` cleared after prompt build
- [ ] `save_learned_skill()` writes `.md` file and hot-adds to registry
- [ ] Bots without SkillsMixin are unaffected
- [ ] Existing `SkillRegistry` (vector-based) still works alongside file registry
- [ ] No breaking changes to `PromptBuilder`, `PromptLayer`, or `PromptMiddleware` APIs

---

## Test Specification

> Integration-heavy tests for this task are in TASK-618. This task should verify
> the wiring works with basic smoke tests during implementation.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-skill-system.spec.md` for full context
2. **Check dependencies** — verify TASK-614 and TASK-615 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `mixin.py`, `abstract.py` (lines 1690-1727), `builder.py`, `layers.py`
4. **Understand AGENTS_DIR resolution** — read existing `_configure_skill_registry()` to see how paths are resolved
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-616-mixin-prompt-integration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
