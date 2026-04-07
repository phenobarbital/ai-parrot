"""Unit tests for SkillSource, SkillDefinition, and parse_skill_file."""
import pytest
from pathlib import Path
from parrot.memory.skills.models import SkillSource, SkillDefinition
from parrot.memory.skills.parsers import parse_skill_file


VALID_SKILL_MD = """---
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


class TestSkillSource:
    def test_authored_value(self):
        assert SkillSource.AUTHORED == "authored"

    def test_learned_value(self):
        assert SkillSource.LEARNED == "learned"


class TestSkillDefinition:
    def test_valid_definition(self):
        sd = SkillDefinition(
            name="resumen",
            description="Resume textos",
            triggers=["/resumen"],
            template_body="Do X",
            token_count=10,
            file_path=Path("/tmp/resumen.md"),
        )
        assert sd.name == "resumen"
        assert sd.source == SkillSource.AUTHORED
        assert sd.priority == 90

    def test_token_limit_exceeded(self):
        with pytest.raises(Exception, match="token limit"):
            SkillDefinition(
                name="big",
                description="Too big",
                triggers=["/big"],
                template_body="x" * 5000,
                token_count=1500,
                file_path=Path("/tmp/big.md"),
            )

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            SkillDefinition(name="x")


class TestParseSkillFile:
    def test_parse_valid_file(self, tmp_path):
        f = tmp_path / "resumen.md"
        f.write_text(VALID_SKILL_MD)
        skill = parse_skill_file(f)
        assert skill.name == "resumen"
        assert "/resumen" in skill.triggers
        assert skill.token_count > 0
        assert skill.source == SkillSource.AUTHORED

    def test_parse_learned_file(self, tmp_path):
        """Source auto-detected as LEARNED when file is in learned/ subdir."""
        skill_no_source = """---
name: resumen
description: Resume textos largos en bullet points
triggers:
  - /resumen
---

Cuando el usuario solicite un resumen:
1. Identifica las ideas principales
2. Genera bullet points (max 7)
3. Manten el tono original
"""
        learned = tmp_path / "learned"
        learned.mkdir()
        f = learned / "skill.md"
        f.write_text(skill_no_source)
        skill = parse_skill_file(f)
        assert skill.source == SkillSource.LEARNED

    def test_parse_missing_fields(self, tmp_path):
        f = tmp_path / "bad.md"
        f.write_text("---\nname: x\n---\nbody")
        with pytest.raises(Exception):
            parse_skill_file(f)

    def test_parse_auto_detect_source(self, tmp_path):
        """Source auto-detected from path when not in frontmatter."""
        skill_md = """---
name: test
description: Test skill
triggers:
  - /test
---

Do something.
"""
        f = tmp_path / "test.md"
        f.write_text(skill_md)
        skill = parse_skill_file(f)
        assert skill.source == SkillSource.AUTHORED

    def test_parse_optional_fields(self, tmp_path):
        """Optional fields like category and version are populated."""
        skill_md = """---
name: traductor
description: Traduce texto
triggers:
  - /traducir
version: "2.0"
category: translation
---

Traduce al idioma solicitado.
"""
        f = tmp_path / "traductor.md"
        f.write_text(skill_md)
        skill = parse_skill_file(f)
        assert skill.version == "2.0"
        assert skill.category == "translation"
