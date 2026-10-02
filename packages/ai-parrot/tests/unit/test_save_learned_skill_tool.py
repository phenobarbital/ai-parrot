"""Unit tests for SkillFileToolkit.save_learned_skill.

FEAT-207 folded the standalone SaveLearnedSkillTool into SkillFileToolkit as the
``save_learned_skill`` method; the class no longer exists on any import path.
Retargeted by FEAT-617 (issue:c3c59277ef77), which also moved these imports off the
deprecated ``parrot.memory.skills.*`` shim. Every original assertion is preserved.
"""
import pytest
from pathlib import Path
from parrot.skills.tools import SkillFileToolkit
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition


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
def toolkit(registry, skills_dir):
    """SkillFileToolkit with a writable learned_dir.

    learned_dir MUST be non-None: SkillFileToolkit.__init__ sets
    exclude_tools = ("save_learned_skill",) when it is None.
    """
    return SkillFileToolkit(
        file_registry=registry,
        learned_dir=skills_dir / "learned",
    )


class TestSaveLearnedSkill:
    @pytest.mark.asyncio
    async def test_writes_md_file(self, toolkit, skills_dir):
        result = await toolkit.save_learned_skill(
            name="extraer_datos",
            description="Extrae datos de texto",
            content="Instrucciones para extraer datos...",
            triggers=["/extraer"],
        )
        assert result.success is True
        assert (skills_dir / "learned" / "extraer_datos.md").exists()

    @pytest.mark.asyncio
    async def test_hot_adds_to_registry(self, toolkit, registry):
        await toolkit.save_learned_skill(
            name="nuevo",
            description="Test skill",
            content="Do something",
            triggers=["/nuevo"],
        )
        assert registry.get("/nuevo") is not None

    @pytest.mark.asyncio
    async def test_name_collision(self, toolkit, registry):
        # Add first
        await toolkit.save_learned_skill(
            name="duplicado",
            description="First",
            content="Body",
            triggers=["/dup1"],
        )
        # Try duplicate
        result = await toolkit.save_learned_skill(
            name="duplicado",
            description="Second",
            content="Body",
            triggers=["/dup2"],
        )
        # Should be rejected
        assert result.success is False
        assert "exists" in str(result.error).lower() or "collision" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_trigger_collision(self, toolkit, registry):
        # Add first
        await toolkit.save_learned_skill(
            name="skill_a",
            description="First",
            content="Body",
            triggers=["/same_trigger"],
        )
        # Try same trigger
        result = await toolkit.save_learned_skill(
            name="skill_b",
            description="Second",
            content="Body",
            triggers=["/same_trigger"],
        )
        assert result.success is False
        assert "collision" in str(result.error).lower() or "exists" in str(result.error).lower()

    @pytest.mark.asyncio
    async def test_file_content_valid(self, toolkit, skills_dir):
        await toolkit.save_learned_skill(
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
    async def test_result_metadata(self, toolkit):
        result = await toolkit.save_learned_skill(
            name="meta_skill",
            description="Test",
            content="Body",
            triggers=["/meta"],
        )
        assert result.success is True
        assert result.metadata["name"] == "meta_skill"
        assert "/meta" in result.metadata["triggers"]
