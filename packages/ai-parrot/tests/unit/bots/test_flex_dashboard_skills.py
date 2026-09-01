"""Discovery + trigger tests for the Flex skills (FEAT-491 TASK-2698)."""

from pathlib import Path

import pytest
from parrot.skills.loader import SkillsDirectoryLoader
from parrot.skills.models import SkillDefinition
from parrot.skills.parsers import parse_skill_directory, parse_skill_file

# Anchored to this test file's own location (worktree-safe — see
# test_budget_narrative_skill.py's comment for why).
_REPO_ROOT = Path(__file__).resolve().parents[5]
SKILLS_DIR = _REPO_ROOT / "agents" / "flex_dashboard" / "skills"
WIDGET_DIR = SKILLS_DIR / "widget"
INFOGRAPHIC_DIR = SKILLS_DIR / "infographic"
NARRATIVE_DIR = SKILLS_DIR / "flex-narrative"


class TestSkillsParse:
    def test_widget_skill_md_parses(self):
        definition = parse_skill_file(WIDGET_DIR / "SKILL.md")
        assert definition.name == "widget"
        assert definition.description
        assert definition.triggers == ["/widget"]

    def test_infographic_skill_md_parses(self):
        definition = parse_skill_file(INFOGRAPHIC_DIR / "SKILL.md")
        assert definition.name == "infographic"
        assert definition.triggers == ["/infographic"]

    def test_flex_narrative_skill_md_parses(self):
        definition = parse_skill_file(NARRATIVE_DIR / "SKILL.md")
        assert definition.name == "flex-narrative"
        assert definition.triggers == []

    @pytest.mark.parametrize("skill_dir", [WIDGET_DIR, INFOGRAPHIC_DIR, NARRATIVE_DIR])
    def test_body_under_token_cap(self, skill_dir):
        definition = parse_skill_file(skill_dir / "SKILL.md")
        assert definition.token_count < SkillDefinition.MAX_TOKENS

    def test_widget_composite_sets_assets_dir(self):
        definition = parse_skill_directory(WIDGET_DIR)
        assert definition.assets_dir == WIDGET_DIR

    def test_widget_kpi_table_asset_present(self):
        names = {p.name for p in WIDGET_DIR.iterdir()}
        assert {"SKILL.md", "kpi-table.md"} <= names

    def test_no_executable_assets(self):
        for skill_dir in (WIDGET_DIR, INFOGRAPHIC_DIR, NARRATIVE_DIR):
            assert not [p for p in skill_dir.iterdir() if p.suffix in {".py", ".sh"}]


class TestWidgetBodyContent:
    def test_widget_maps_every_kpi_to_an_output_mode(self):
        kpi_table = (WIDGET_DIR / "kpi-table.md").read_text()
        for kpi_row in (
            "Worked Hours (total)",
            "Payroll (total)",
            "P&L Revenue (total)",
            "Payroll % to Revenue (total)",
            "Worked Hours by Month",
            "Payroll by Month",
            "P&L Revenue by Month",
            "Payroll % to Revenue by Month",
            "Pay Code Hours",
            "Worked Hours by Pay Code Allocation",
            "Rep Utilization by Region",
            "Proximity Staffing",
        ):
            assert kpi_row in kpi_table, f"missing KPI row: {kpi_row}"

        for output_mode in ("KPICard", "STRUCTURED_CHART", "STRUCTURED_TABLE", "STRUCTURED_MAP"):
            assert output_mode in kpi_table

    def test_widget_states_payroll_pct_denominator_rule(self):
        body = (WIDGET_DIR / "SKILL.md").read_text() + (WIDGET_DIR / "kpi-table.md").read_text()
        assert "Revenue ALONE" in body


class TestFlexNarrativeBodyContent:
    def test_states_no_invented_figures_rule(self):
        body = (NARRATIVE_DIR / "SKILL.md").read_text()
        assert "not in the facts" in body.lower() or "only figures" in body.lower()

    def test_references_flex_narrative_facts_fields(self):
        body = (NARRATIVE_DIR / "SKILL.md").read_text()
        for field in (
            "worked_hours_total",
            "payroll_total",
            "revenue_total",
            "payroll_pct",
            "worked_hours_trend",
            "regions_tracked",
        ):
            assert field in body


class TestSkillsDiscovered:
    @pytest.mark.asyncio
    async def test_skills_discovered(self):
        loader = SkillsDirectoryLoader(paths=[SKILLS_DIR])
        found = await loader.discover()
        names = {s.name for s in found}
        assert {"widget", "infographic", "flex-narrative"} <= names

    @pytest.mark.asyncio
    async def test_widget_and_infographic_triggers(self):
        loader = SkillsDirectoryLoader(paths=[SKILLS_DIR])
        found = {s.name: s for s in await loader.discover()}
        assert "/widget" in found["widget"].triggers
        assert "/infographic" in found["infographic"].triggers
        assert found["flex-narrative"].triggers == []

    @pytest.mark.asyncio
    async def test_discovered_via_agent_skill_paths(self):
        """Discovery through the exact path FlexDashboard.skill_paths declares."""
        import importlib.util
        import sys

        agents_dir = _REPO_ROOT / "agents"
        flex_dir = agents_dir / "flex_dashboard"

        def _load_package(name, init_path, search_dir):
            if name in sys.modules:
                return sys.modules[name]
            spec = importlib.util.spec_from_file_location(
                name, init_path, submodule_search_locations=[str(search_dir)]
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        def _load_module(name, path):
            if name in sys.modules:
                return sys.modules[name]
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        _load_package("agents", agents_dir / "__init__.py", agents_dir)
        _load_package("agents.flex_dashboard", flex_dir / "__init__.py", flex_dir)
        _load_module("agents.flex_dashboard.normalize", flex_dir / "normalize.py")
        _load_module("agents.flex_dashboard.transformers", flex_dir / "transformers.py")
        module = _load_module("flex_dashboard_agent_under_test", agents_dir / "flex_dashboard.py")

        loader = SkillsDirectoryLoader(paths=list(module.FlexDashboard.skill_paths))
        found = {s.name for s in await loader.discover()}
        assert {"widget", "infographic", "flex-narrative"} <= found
