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

    def test_skill_without_procedure_unchanged(self, tmp_path):
        """A skill with no `procedure` key parses as before; the new field is None."""
        skill_md = """---
name: basic
description: Basic skill
triggers:
  - /basic
---

Follow the basic procedure.
"""
        f = tmp_path / "basic.md"
        f.write_text(skill_md)

        skill = parse_skill_file(f)

        assert skill.procedure is None
        assert skill.name == "basic"
        assert skill.description == "Basic skill"
        assert skill.triggers == ["/basic"]
        assert skill.template_body == "Follow the basic procedure."

    def test_skill_procedure_mapping_kept(self, tmp_path):
        """A `procedure` mapping is stored unchanged."""
        skill_md = """---
name: refunds
description: Handle refunds
triggers:
  - /refund
procedure: {mode: advisory, intents: [refund]}
---

Handle the refund request.
"""
        f = tmp_path / "refunds.md"
        f.write_text(skill_md)

        skill = parse_skill_file(f)

        assert skill.procedure == {"mode": "advisory", "intents": ["refund"]}

    def test_skill_procedure_not_mapping_raises(self, tmp_path):
        """`procedure: "x"` raises ValueError naming the file."""
        skill_md = """---
name: invalid
description: Invalid procedure
triggers:
  - /invalid
procedure: x
---

This skill has invalid procedure metadata.
"""
        f = tmp_path / "invalid.md"
        f.write_text(skill_md)

        with pytest.raises(ValueError, match="'procedure' must be a mapping") as exc_info:
            parse_skill_file(f)

        assert str(f) in str(exc_info.value)
