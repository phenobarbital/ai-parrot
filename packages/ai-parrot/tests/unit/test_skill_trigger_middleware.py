"""Unit tests for SkillTriggerMiddleware (create_skill_trigger_middleware)."""
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from parrot.memory.skills.middleware import create_skill_trigger_middleware
from parrot.memory.skills.models import SkillDefinition, SkillSource
from parrot.memory.skills.file_registry import SkillFileRegistry


@pytest.fixture
def sample_skill():
    return SkillDefinition(
        name="resumen",
        description="Resume textos",
        triggers=["/resumen"],
        template_body="Genera bullet points",
        token_count=10,
        file_path=Path("/tmp/resumen.md"),
    )


@pytest.fixture
def compound_skill():
    return SkillDefinition(
        name="analisis_financiero",
        description="Analisis financiero",
        triggers=["/analisis_financiero"],
        template_body="Analiza datos financieros",
        token_count=10,
        file_path=Path("/tmp/analisis.md"),
    )


@pytest.fixture
async def registry_with_skills(tmp_path, sample_skill, compound_skill):
    reg = SkillFileRegistry(tmp_path)
    await reg.load()
    reg.add(sample_skill)
    reg.add(compound_skill)
    return reg


@pytest.fixture
def mock_bot():
    return MagicMock()


class TestSkillTriggerMiddleware:
    @pytest.mark.asyncio
    async def test_detects_trigger(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/resumen doc Q4", {})
        assert result == "doc Q4"
        assert mock_bot._active_skill.name == "resumen"

    @pytest.mark.asyncio
    async def test_no_trigger(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("normal message", {})
        assert result == "normal message"

    @pytest.mark.asyncio
    async def test_unknown_trigger(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/unknown text", {})
        assert result == "/unknown text"

    @pytest.mark.asyncio
    async def test_trigger_only(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/resumen", {})
        assert result == ""
        assert mock_bot._active_skill.name == "resumen"

    @pytest.mark.asyncio
    async def test_reserved_skills(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/skills", {})
        assert "resumen" in result.lower()
        assert "available" in result.lower()

    @pytest.mark.asyncio
    async def test_reserved_help(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/help", {})
        assert "resumen" in result.lower()
        assert "available" in result.lower()

    @pytest.mark.asyncio
    async def test_compound_name(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("/analisis_financiero data Q1", {})
        assert result == "data Q1"
        assert mock_bot._active_skill.name == "analisis_financiero"

    @pytest.mark.asyncio
    async def test_empty_message(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply("", {})
        assert result == ""

    @pytest.mark.asyncio
    async def test_none_message(self, registry_with_skills, mock_bot):
        mw = create_skill_trigger_middleware(registry_with_skills, mock_bot)
        result = await mw.apply(None, {})
        assert result is None
