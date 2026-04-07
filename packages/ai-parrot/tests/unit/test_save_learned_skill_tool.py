"""Unit tests for SaveLearnedSkillTool."""
import pytest
from pathlib import Path
from parrot.memory.skills.tools import SaveLearnedSkillTool
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.models import SkillDefinition


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "learned").mkdir()
    return d


@pytest.fixture
async def registry(skills_dir):
    reg = SkillFileRegistry(skills_dir)
    await reg.load()
    return reg


@pytest.fixture
def tool(registry, skills_dir):
    return SaveLearnedSkillTool(
        file_registry=registry,
        learned_dir=skills_dir / "learned",
    )


class TestSaveLearnedSkillTool:
    @pytest.mark.asyncio
    async def test_writes_md_file(self, tool, skills_dir):
        result = await tool._execute(
            name="extraer_datos",
            description="Extrae datos de texto",
            content="Instrucciones para extraer datos...",
            triggers=["/extraer"],
        )
        assert result.success is True
        assert (skills_dir / "learned" / "extraer_datos.md").exists()

    @pytest.mark.asyncio
    async def test_hot_adds_to_registry(self, tool, registry):
        await tool._execute(
            name="nuevo",
            description="Test skill",
            content="Do something",
            triggers=["/nuevo"],
        )
        assert registry.get("/nuevo") is not None

    @pytest.mark.asyncio
    async def test_name_collision(self, tool, registry):
        # Add first
        await tool._execute(
            name="duplicado",
            description="First",
            content="Body",
            triggers=["/dup1"],
        )
        # Try duplicate
        result = await tool._execute(
            name="duplicado",
            description="Second",
            content="Body",
            triggers=["/dup2"],
        )
        # Should be rejected
        assert result.success is False
        assert "exists" in str(result.error).lower() or "collision" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_trigger_collision(self, tool, registry):
        # Add first
        await tool._execute(
            name="skill_a",
            description="First",
            content="Body",
            triggers=["/same_trigger"],
        )
        # Try same trigger
        result = await tool._execute(
            name="skill_b",
            description="Second",
            content="Body",
            triggers=["/same_trigger"],
        )
        assert result.success is False
        assert "collision" in str(result.error).lower() or "exists" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_file_content_valid(self, tool, skills_dir):
        await tool._execute(
            name="test_skill",
            description="Test description",
            content="Test instructions",
            triggers=["/test"],
            category="testing",
        )
        file_path = skills_dir / "learned" / "test_skill.md"
        content = file_path.read_text()
        assert "name: test_skill" in content
        assert "description: Test description" in content
        assert "/test" in content
        assert "source: learned" in content
        assert "Test instructions" in content

    @pytest.mark.asyncio
    async def test_result_metadata(self, tool):
        result = await tool._execute(
            name="meta_skill",
            description="Test",
            content="Body",
            triggers=["/meta"],
        )
        assert result.success is True
        assert result.metadata["name"] == "meta_skill"
        assert "/meta" in result.metadata["triggers"]
