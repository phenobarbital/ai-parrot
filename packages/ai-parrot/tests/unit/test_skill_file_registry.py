"""Unit tests for SkillFileRegistry."""
import pytest
from pathlib import Path
from parrot.memory.skills.file_registry import SkillFileRegistry
from parrot.memory.skills.models import SkillDefinition, SkillSource

VALID_SKILL = """---
name: resumen
description: Resume textos largos
triggers:
  - /resumen
---

Identifica ideas principales y genera bullet points.
"""

VALID_SKILL_2 = """---
name: traductor
description: Traduce texto
triggers:
  - /traducir
  - /translate
---

Traduce el texto al idioma solicitado.
"""


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "learned").mkdir()
    return d


class TestSkillFileRegistry:
    @pytest.mark.asyncio
    async def test_load_authored(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.get("/resumen") is not None
        assert reg.get("/resumen").source == SkillSource.AUTHORED

    @pytest.mark.asyncio
    async def test_load_learned(self, skills_dir):
        learned_skill = """---
name: resumen
description: Resume textos largos
triggers:
  - /resumen
---

Identifica ideas principales y genera bullet points.
"""
        (skills_dir / "learned" / "resumen.md").write_text(learned_skill)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        skill = reg.get("/resumen")
        assert skill is not None
        assert skill.source == SkillSource.LEARNED

    @pytest.mark.asyncio
    async def test_skip_malformed(self, skills_dir):
        (skills_dir / "bad.md").write_text("no frontmatter here")
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.list_skills() == []

    @pytest.mark.asyncio
    async def test_name_collision(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        (skills_dir / "learned" / "resumen.md").write_text(VALID_SKILL)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.get("/resumen") is None  # both skipped

    @pytest.mark.asyncio
    async def test_trigger_lookup(self, skills_dir):
        (skills_dir / "traductor.md").write_text(VALID_SKILL_2)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.get("/traducir") is not None
        assert reg.get("/translate") is not None
        assert reg.get("/unknown") is None

    @pytest.mark.asyncio
    async def test_hot_add(self, skills_dir):
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        skill = SkillDefinition(
            name="nuevo",
            description="Test",
            triggers=["/nuevo"],
            template_body="body",
            token_count=5,
            file_path=Path("/tmp/nuevo.md"),
        )
        reg.add(skill)
        assert reg.get("/nuevo") is not None

    @pytest.mark.asyncio
    async def test_list_skills(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        (skills_dir / "traductor.md").write_text(VALID_SKILL_2)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert len(reg.list_skills()) == 2

    @pytest.mark.asyncio
    async def test_empty_dir(self, skills_dir):
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.list_skills() == []

    @pytest.mark.asyncio
    async def test_missing_dir(self, tmp_path):
        reg = SkillFileRegistry(tmp_path / "nonexistent")
        await reg.load()
        assert reg.list_skills() == []

    @pytest.mark.asyncio
    async def test_has_trigger(self, skills_dir):
        (skills_dir / "resumen.md").write_text(VALID_SKILL)
        reg = SkillFileRegistry(skills_dir)
        await reg.load()
        assert reg.has_trigger("/resumen") is True
        assert reg.has_trigger("/missing") is False
