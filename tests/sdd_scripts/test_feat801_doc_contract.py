"""FEAT-801 contract: spec template Documentation chapter and authored-page template."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDocContract:
    def test_spec_template_has_docs_block(self):
        """sdd/templates/spec.md has # docs: block."""
        text = (REPO_ROOT / "sdd/templates/spec.md").read_text()
        assert "# docs:" in text
        assert "policy: required" in text

    def test_spec_template_has_section_10(self):
        """sdd/templates/spec.md has ## 10. Documentation."""
        text = (REPO_ROOT / "sdd/templates/spec.md").read_text()
        assert "## 10. Documentation" in text

    def test_techwiki_page_template_exists(self):
        """sdd/templates/techwiki-page.md exists with six sections."""
        path = REPO_ROOT / "sdd/templates/techwiki-page.md"
        assert path.exists()
        text = path.read_text()
        for section in ["Purpose", "Public API", "Configuration", "Usage Examples", "Gotchas", "Related"]:
            assert f"## {section}" in text

    def test_sdd_spec_twins_carry_docs_hint(self):
        """All three sdd-spec twins mention the Documentation chapter."""
        for twin in [
            ".claude/commands/sdd-spec.md",
            ".agents/skills/sdd-spec/SKILL.md",
            ".agent/workflows/sdd-spec.md",
        ]:
            text = (REPO_ROOT / twin).read_text()
            assert "Documentation chapter" in text, f"{twin} missing docs hint"
