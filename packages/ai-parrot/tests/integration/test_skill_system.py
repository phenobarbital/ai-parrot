"""Integration tests for the Agent Skill System.

Verifies the full skill system flow:
- Loading skills -> trigger detection -> prompt injection -> cleanup
- Learned skill hot-add
- Disabled mixin scenarios
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from parrot.memory.skills.models import SkillDefinition, SkillSource
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.middleware import create_skill_trigger_middleware
from parrot.memory.skills.parsers import parse_skill_file
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

        # 5. Inject skill layer (as create_system_prompt would do)
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

        # 7. Remove transient layer (as create_system_prompt would do)
        bot._prompt_builder.remove("skill_active")
        bot._active_skill = None
        assert bot._prompt_builder.get("skill_active") is None
        assert bot._active_skill is None

    @pytest.mark.asyncio
    async def test_next_request_clean(self, skills_dir):
        """After skill activation and cleanup, next request has no skill."""
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

    @pytest.mark.asyncio
    async def test_skill_layer_priority(self, skills_dir):
        """Skill layer priority is 90, after CUSTOM(80)."""
        registry = SkillFileRegistry(skills_dir)
        await registry.load()

        skill = registry.get("/resumen")
        assert skill is not None

        layer = PromptLayer(
            name="skill_active",
            priority=skill.priority,
            template=skill.template_body,
            phase=RenderPhase.REQUEST,
        )
        assert layer.priority == 90


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
        skill = parse_skill_file(learned_file)
        registry.add(skill)

        # Now available
        assert registry.get("/extraer") is not None
        assert registry.get("/extraer").source == SkillSource.LEARNED

    @pytest.mark.asyncio
    async def test_hot_add_with_middleware(self, skills_dir):
        """Hot-added skill works with middleware trigger detection."""
        registry = SkillFileRegistry(skills_dir)
        await registry.load()
        bot = MagicMock()
        bot._active_skill = None

        mw = create_skill_trigger_middleware(registry, bot)

        # Initially /extraer doesn't exist
        result = await mw.apply("/extraer datos", {})
        assert result == "/extraer datos"  # passes through

        # Hot-add
        skill = SkillDefinition(
            name="extraer",
            description="Extrae datos",
            triggers=["/extraer"],
            template_body="Extrae los datos.",
            token_count=5,
            file_path=skills_dir / "learned" / "extraer.md",
        )
        registry.add(skill)

        # Now trigger works
        result = await mw.apply("/extraer datos", {})
        assert result == "datos"
        assert bot._active_skill.name == "extraer"


class TestSkillSystemDisabled:
    """Bot without SkillsMixin works normally."""

    @pytest.mark.asyncio
    async def test_no_middleware(self):
        """Pipeline without skill middleware passes triggers through."""
        pipeline = PromptPipeline()
        # No middleware registered
        result = await pipeline.apply("/resumen texto", {})
        assert result == "/resumen texto"  # passes through unchanged

    @pytest.mark.asyncio
    async def test_builder_without_skill_layer(self):
        """PromptBuilder works normally without skill layers."""
        builder = PromptBuilder.default()
        prompt = builder.build({})
        # Should build without errors and NOT contain skill content
        assert "bullet points" not in prompt
        assert "ideas principales" not in prompt


class TestMultipleSkills:
    """Test with multiple skills loaded."""

    @pytest.mark.asyncio
    async def test_multiple_skills_different_triggers(self, skills_dir):
        """Multiple skills with different triggers work correctly."""
        traductor_skill = """---
name: traductor
description: Traduce texto
triggers:
  - /traducir
  - /translate
---

Traduce el texto al idioma solicitado.
"""
        (skills_dir / "traductor.md").write_text(traductor_skill)

        registry = SkillFileRegistry(skills_dir)
        await registry.load()
        bot = MagicMock()
        bot._active_skill = None

        mw = create_skill_trigger_middleware(registry, bot)

        # Test first skill
        await mw.apply("/resumen text", {})
        assert bot._active_skill.name == "resumen"

        bot._active_skill = None

        # Test second skill
        await mw.apply("/traducir text", {})
        assert bot._active_skill.name == "traductor"

        bot._active_skill = None

        # Test alias trigger
        await mw.apply("/translate text", {})
        assert bot._active_skill.name == "traductor"

    @pytest.mark.asyncio
    async def test_skills_listing(self, skills_dir):
        """Reserved /skills trigger lists all available skills."""
        traductor_skill = """---
name: traductor
description: Traduce texto
triggers:
  - /traducir
---

Traduce el texto al idioma solicitado.
"""
        (skills_dir / "traductor.md").write_text(traductor_skill)

        registry = SkillFileRegistry(skills_dir)
        await registry.load()
        bot = MagicMock()
        bot._active_skill = None

        mw = create_skill_trigger_middleware(registry, bot)
        result = await mw.apply("/skills", {})

        assert "/resumen" in result.lower()
        assert "/traducir" in result.lower()
        assert "available" in result.lower()
