# TASK-618: Skill System Integration Tests

**Feature**: Agent Skill System
**Spec**: `sdd/specs/agent-skill-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-613, TASK-614, TASK-615, TASK-616, TASK-617
**Assigned-to**: unassigned

---

## Context

> Module 6 of FEAT-088. Comprehensive integration tests that verify the full skill system
> flow: loading skills → trigger detection → prompt injection → cleanup. Also tests
> learned skill hot-add and disabled mixin scenarios. See spec Section 4.

---

## Scope

- Write integration tests that verify:
  - Full flow: user sends `/resumen text` → system prompt contains skill instructions → next request has no skill
  - Learned skill hot-add: LLM saves skill via tool → immediately available for `/trigger` in same session
  - Disabled mixin: Bot without SkillsMixin works normally, no middleware registered
- Verify all acceptance criteria from the spec (Section 5)
- Consolidate and run full test suite: unit + integration

**NOT in scope**: Implementation changes (all implementation should be complete)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_skill_system.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All modules from TASK-613 through TASK-617:
from parrot.memory.skills.models import SkillDefinition, SkillSource
from parrot.memory.skills.parsers import parse_skill_file
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.middleware import create_skill_trigger_middleware
from parrot.memory.skills.mixin import SkillRegistryMixin
from parrot.memory.skills.tools import SaveLearnedSkillTool

# Prompt system:
from parrot.bots.prompts.layers import PromptLayer, RenderPhase
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.middleware import PromptMiddleware, PromptPipeline
```

### Does NOT Exist
- All "Does NOT Exist" items from previous tasks should now exist after TASK-613–617
- If any import fails, the corresponding task was not completed correctly — report and fix

---

## Implementation Notes

### Integration Test Strategy
Tests should simulate the full lifecycle without requiring a running LLM:
1. Create a temporary skills directory with sample `.md` files
2. Initialize `SkillFileRegistry` and load skills
3. Create a mock bot with `_prompt_pipeline` and `_prompt_builder`
4. Register `SkillTriggerMiddleware`
5. Simulate user message flow through pipeline → prompt build → verify output

### Key Constraints
- Use `pytest-asyncio` for all async tests
- Use `tmp_path` fixture for temporary skill directories
- Mock the bot object minimally — only what's needed for middleware + prompt builder
- Do NOT require a real LLM or external services

---

## Acceptance Criteria

- [ ] Integration test: `/resumen text` → skill instructions in system prompt → cleared after
- [ ] Integration test: learned skill hot-add → immediately available via `/trigger`
- [ ] Integration test: bot without SkillsMixin works normally
- [ ] All unit tests still pass: `pytest packages/ai-parrot/tests/unit/test_skill_*.py -v`
- [ ] All integration tests pass: `pytest packages/ai-parrot/tests/integration/test_skill_system.py -v`
- [ ] Full test suite: `pytest packages/ai-parrot/tests/ -k skill -v` — all green

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_skill_system.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from parrot.memory.skills.models import SkillDefinition, SkillSource
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.middleware import create_skill_trigger_middleware
from parrot.bots.prompts.layers import PromptLayer, RenderPhase
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.middleware import PromptPipeline


RESUMEN_SKILL = """---
name: resumen
description: Resume textos largos en bullet points
triggers:
  - /resumen
source: authored
---

Cuando el usuario solicite un resumen:
1. Identifica las ideas principales
2. Genera bullet points (max 7)
3. Manten el tono original
"""


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "learned").mkdir()
    (d / "resumen.md").write_text(RESUMEN_SKILL)
    return d


class TestSkillActivateInPrompt:
    """Full flow: user sends /resumen text, system prompt contains skill instructions."""

    @pytest.mark.asyncio
    async def test_full_flow(self, skills_dir):
        # 1. Load registry
        registry = SkillFileRegistry(skills_dir)
        await registry.load()

        # 2. Create mock bot with prompt pipeline and builder
        bot = MagicMock()
        bot._active_skill = None
        bot._prompt_builder = PromptBuilder.default()
        bot._prompt_pipeline = PromptPipeline()

        # 3. Register middleware
        mw = create_skill_trigger_middleware(registry, bot)
        bot._prompt_pipeline.add(mw)

        # 4. Simulate user message
        query = await bot._prompt_pipeline.apply("/resumen doc Q4", {})
        assert query == "doc Q4"
        assert bot._active_skill is not None
        assert bot._active_skill.name == "resumen"

        # 5. Check skill layer would be injected
        skill_layer = PromptLayer(
            name="skill_active",
            priority=90,
            template=bot._active_skill.template_body,
            phase=RenderPhase.REQUEST,
        )
        bot._prompt_builder.add(skill_layer)
        assert bot._prompt_builder.get("skill_active") is not None

        # 6. Build prompt (layer included)
        prompt = bot._prompt_builder.build({})
        assert "bullet points" in prompt or "ideas principales" in prompt

        # 7. Remove transient layer
        bot._prompt_builder.remove("skill_active")
        bot._active_skill = None
        assert bot._prompt_builder.get("skill_active") is None
        assert bot._active_skill is None

    @pytest.mark.asyncio
    async def test_next_request_clean(self, skills_dir):
        registry = SkillFileRegistry(skills_dir)
        await registry.load()
        bot = MagicMock()
        bot._active_skill = None

        mw = create_skill_trigger_middleware(registry, bot)

        # First request activates skill
        await mw.apply("/resumen texto", {})
        assert bot._active_skill is not None

        # Clear (as create_system_prompt would)
        bot._active_skill = None

        # Second request — no skill
        result = await mw.apply("normal question", {})
        assert result == "normal question"
        assert bot._active_skill is None


class TestLearnedSkillHotAdd:
    """LLM saves skill via tool, immediately available for /trigger."""

    @pytest.mark.asyncio
    async def test_hot_add_flow(self, skills_dir):
        registry = SkillFileRegistry(skills_dir)
        await registry.load()

        # Initially no /extraer trigger
        assert registry.get("/extraer") is None

        # Simulate saving a learned skill
        learned_file = skills_dir / "learned" / "extraer.md"
        learned_file.write_text("""---
name: extraer
description: Extrae datos
triggers:
  - /extraer
source: learned
---

Extrae los datos solicitados del texto.
""")
        from parrot.memory.skills.parsers import parse_skill_file
        skill = parse_skill_file(learned_file)
        registry.add(skill)

        # Now available
        assert registry.get("/extraer") is not None
        assert registry.get("/extraer").source == SkillSource.LEARNED


class TestSkillSystemDisabled:
    """Bot without SkillsMixin works normally."""

    @pytest.mark.asyncio
    async def test_no_middleware(self):
        pipeline = PromptPipeline()
        # No middleware registered
        result = await pipeline.apply("/resumen texto", {})
        assert result == "/resumen texto"  # passes through unchanged
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agent-skill-system.spec.md` — focus on Section 4 (Tests) and Section 5 (Acceptance Criteria)
2. **Check dependencies** — verify TASK-613 through TASK-617 are ALL in `tasks/completed/`
3. **Verify imports** — confirm all modules from previous tasks can be imported
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Write and run tests** — both new integration tests and existing unit tests
6. **Fix any issues** discovered during testing (coordinate with previous task implementations)
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-618-skill-system-integration-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
