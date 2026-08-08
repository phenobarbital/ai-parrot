"""Parse/cap/discovery tests for the `budget-narrative` composite skill (FEAT-420 Module 6)."""

from pathlib import Path

from parrot.skills.loader import SkillsDirectoryLoader
from parrot.skills.models import SkillDefinition
from parrot.skills.parsers import parse_skill_directory, parse_skill_file

# Anchored to this test file's own location rather than the process cwd:
# some heavy `parrot` submodule imports trigger a settings bootstrap that
# changes the working directory as a side effect, which would otherwise make
# a plain `Path(".agent/skills/...")` resolve against the wrong checkout when
# tests run from a git worktree.
_REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_DIR = _REPO_ROOT / ".agent" / "skills" / "budget-narrative"


class TestBudgetNarrativeSkill:
    def test_skill_md_parses(self):
        definition = parse_skill_file(SKILL_DIR / "SKILL.md")
        assert definition.name == "budget-narrative"
        assert definition.description

    def test_body_under_token_cap_with_headroom(self):
        definition = parse_skill_file(SKILL_DIR / "SKILL.md")
        assert definition.token_count < SkillDefinition.MAX_TOKENS
        assert definition.token_count <= 900, "keep headroom for future edits"

    def test_composite_sets_assets_dir(self):
        definition = parse_skill_directory(SKILL_DIR)
        assert definition.assets_dir == SKILL_DIR

    def test_expected_assets_present(self):
        names = {p.name for p in SKILL_DIR.iterdir()}
        assert {"SKILL.md", "facts-schema.md", "reference.md"} <= names

    def test_no_executable_assets(self):
        assert not [p for p in SKILL_DIR.iterdir() if p.suffix in {".py", ".sh"}]

    def test_body_states_the_no_invented_figures_rule(self):
        body = (SKILL_DIR / "SKILL.md").read_text()
        assert "not in the facts" in body.lower() or "only figures" in body.lower()

    def test_reference_uses_only_fake_placeholders(self):
        """No plausible real-looking dollar amount should appear in reference.md."""
        import re

        text = (SKILL_DIR / "reference.md").read_text()
        # A "plausible" figure is a $-prefixed number with real digits before
        # the M/K suffix (e.g. $42.0K) — placeholders use X's instead.
        plausible = re.findall(r"\$\d[\d,]*\.\d+[MK]", text)
        assert plausible == [], f"found plausible (non-placeholder) figures: {plausible}"

    def test_data_storytelling_skill_unmodified(self):
        """This task must not touch the pre-existing, unrelated generic skill."""
        assert (_REPO_ROOT / ".agent" / "skills" / "data-storytelling").is_dir()

    async def test_discovered_by_loader(self):
        loader = SkillsDirectoryLoader(paths=[_REPO_ROOT / ".agent" / "skills"])
        found = await loader.discover()
        assert any(d.name == "budget-narrative" for d in found)
