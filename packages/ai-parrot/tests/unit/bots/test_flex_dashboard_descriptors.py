"""Descriptor validity + refresh-tool tests for `FlexDashboard` (FEAT-491 TASK-2697)."""

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

# Worktree-safe file-path loading — same technique used across this
# feature's other test files (see test_flex_dashboard_agent.py's longer
# comment for why "agents.flex_dashboard" is reserved for the real
# package and the agent FILE is loaded under its own distinct name).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_AGENTS_DIR = _REPO_ROOT / "agents"
_AGENT_FILE = _AGENTS_DIR / "flex_dashboard.py"


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_flex_dashboard_module():
    # FEAT-528 Module 2: no pre-registration needed any more — the agent
    # file loads its own transformers via `load_transformer_module` under
    # its own synthetic name (see test_flex_dashboard_agent.py's longer
    # comment). Pre-loading "agents.flex_dashboard.transformers" under the
    # real dotted name here would make that call re-execute the module
    # under a DIFFERENT name, double-registering every transformer.
    return _load_module("flex_dashboard_agent_under_test", _AGENT_FILE)


@pytest.fixture(scope="module")
def flex_dashboard_module():
    return _load_flex_dashboard_module()


@pytest.fixture(scope="module")
def descriptor(flex_dashboard_module):
    return flex_dashboard_module.FlexDashboard.dashboard_descriptor()


_EXPECTED_SECTION_ORDER = [
    "payroll_hero",
    "worked_hours_by_month",
    "payroll_by_month",
    "revenue_by_month",
    "payroll_pct_by_month",
    "pay_code_hours",
    "pay_code_allocation",
    "rep_utilization_by_region",
    "proximity_staffing",
    "flex_narrative_facts",
]


class TestDashboardDescriptor:
    def test_every_section_resolves_to_a_transformer(self, descriptor):
        """This is what makes publish_recipe return a recipe, not a GapReport."""
        for section in descriptor.sections:
            name = re.sub(r"\W+", "_", section.name).strip("_")
            transformer_registry.get(name)  # raises KeyError if unmapped

    def test_section_order(self, descriptor):
        names = [s.name for s in descriptor.sections]
        assert names == _EXPECTED_SECTION_ORDER

    def test_layout_is_infographic(self, descriptor):
        assert descriptor.layout.component == "Infographic"

    def test_layout_satisfies_catalog_required_keys(self, descriptor):
        props = descriptor.layout.props
        assert "title" in props and "sections" in props

    def test_hero_bindings(self, descriptor):
        props = descriptor.layout.props
        hero_section = props["sections"][0]
        bindings = {c["properties"]["label"]: c["properties"]["value"]["path"] for c in hero_section["components"]}
        assert bindings == {
            "Worked Hours": "/payroll_hero/worked_hours_total",
            "Payroll": "/payroll_hero/payroll_total",
            "P&L Revenue": "/payroll_hero/revenue_total",
            "Payroll % to Revenue": "/payroll_hero/payroll_pct",
        }

    def test_declares_narrative(self, flex_dashboard_module, descriptor):
        assert descriptor.narrative.skill == flex_dashboard_module.FlexDashboard.narrative_skill
        assert descriptor.narrative.facts_key == "flex_narrative_facts"

    def test_no_narrative_layout_binding(self, descriptor):
        """A no-narrator replay must not abort at the drift check.

        Deviation (TASK-2699 finding): unlike FinanceReporter's identical-
        looking ``"text": {"path": "/narrative"}`` pattern, this layout
        deliberately binds NOTHING to ``/narrative`` —
        ``RecipeRunner._assemble_envelope_or_raise``'s Infographic path
        (``build_infographic`` -> ``build_surface``) never threads
        ``layout.metadata`` (and therefore never
        ``metadata.extensions.parrot_optional``) onto the built wire
        ``Component``, so ANY layout-level binding to an absent
        ``/narrative`` key raises ``BakeError`` unconditionally at render
        time regardless of what the descriptor declares — a pre-existing,
        cross-cutting core bug confirmed reproducible on `dev`
        independently of this feature (FinanceReporter's own
        `test_dashboard_profile_replay` AND
        `test_report_profile_replay_no_narrator` are both currently broken
        by it too). The narrative step therefore has no VISUAL binding
        here; ``narrative=NarrativeSpec(...)`` is still declared (see
        `test_declares_narrative`) so a configured narrator still runs and
        populates `/narrative` in the data model — it is just never read
        back into the layout.
        """
        layout = descriptor.layout
        found = []

        def walk(v):
            if isinstance(v, dict):
                if "path" in v and "/narrative" in str(v["path"]):
                    found.append(v["path"])
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(layout.props)
        assert found == [], f"unexpected narrative binding(s) in layout: {found}"

    def test_narrative_facts_last_and_inputs_are_output_keys(self, descriptor):
        names = [s.name for s in descriptor.sections]
        assert names[-1] == "flex_narrative_facts"
        last = descriptor.sections[-1]
        for dep in ("payroll_hero", "worked_hours_by_month", "rep_utilization_by_region"):
            assert dep in last.datasets
            assert names.index(dep) < len(names) - 1

    def test_frozen_dataset_aliases_used_verbatim(self, descriptor):
        by_name = {s.name: s for s in descriptor.sections}
        assert by_name["payroll_hero"].datasets == ["hours", "finance"]
        assert by_name["proximity_staffing"].datasets == ["msl", "employees"]
        assert by_name["rep_utilization_by_region"].datasets == [
            "rep_utilization",
            "region_utilization",
        ]

    def test_recipe_params_have_concrete_defaults(self, flex_dashboard_module):
        """resolve_params() raises when a declared param has no default and
        no override — every declared param here must have one."""
        for param in flex_dashboard_module.FlexDashboard.recipe_params():
            assert param.default is not None, f"{param.name} has no default"

    def test_descriptor_param_templates_match_declared_params(self, flex_dashboard_module, descriptor):
        declared_names = {p.name for p in flex_dashboard_module.FlexDashboard.recipe_params()}
        template_names = set(descriptor.params)
        assert template_names == declared_names


class TestRefreshDashboardTool:
    @pytest.mark.asyncio
    async def test_refresh_tool_args_win_over_surface_state(self, flex_dashboard_module):
        RefreshDashboardTool = flex_dashboard_module.RefreshDashboardTool

        fake_artifact = SimpleNamespace(artifact_id="art-1", content=b"<html/>")
        runner = SimpleNamespace(run=AsyncMock(return_value=fake_artifact))
        tool = RefreshDashboardTool(runner=runner, pctx="fake-pctx")

        surface_state = SimpleNamespace(data_model={"filters": {"month": "2025-09", "pay_code": "Field Time"}})

        # `_execute` looks up `current_a2ui_surface_state` as a name in
        # `agents/flex_dashboard.py`'s OWN module namespace (imported there
        # via `from parrot.tools.abstract import ... current_a2ui_surface_state`)
        # — patch it there directly.
        original = flex_dashboard_module.current_a2ui_surface_state
        flex_dashboard_module.current_a2ui_surface_state = lambda: surface_state
        try:
            result = await tool._execute(month="2025-10")
        finally:
            flex_dashboard_module.current_a2ui_surface_state = original

        # Explicit arg (month="2025-10") wins over surface state ("2025-09");
        # surface state fills in the rest (pay_code).
        assert result["filters"]["month"] == "2025-10"
        assert result["filters"]["pay_code"] == "Field Time"
        assert result["filter_source"] == "args"
        runner.run.assert_awaited_once()
        _, kwargs = runner.run.call_args
        assert kwargs["pctx"] == "fake-pctx"

    @pytest.mark.asyncio
    async def test_refresh_tool_defaults_with_no_state_no_args(self, flex_dashboard_module):
        RefreshDashboardTool = flex_dashboard_module.RefreshDashboardTool

        fake_artifact = SimpleNamespace(artifact_id="art-2", content=b"<html/>")
        runner = SimpleNamespace(run=AsyncMock(return_value=fake_artifact))
        tool = RefreshDashboardTool(runner=runner, pctx="fake-pctx")

        original = flex_dashboard_module.current_a2ui_surface_state
        flex_dashboard_module.current_a2ui_surface_state = lambda: None
        try:
            result = await tool._execute()
        finally:
            flex_dashboard_module.current_a2ui_surface_state = original

        assert result["filters"] == {}
        assert result["filter_source"] == "defaults"

    def test_distinct_recipe_name_constant(self, flex_dashboard_module):
        assert flex_dashboard_module.FlexDashboard.DASHBOARD_RECIPE_NAME == "flex-program-dashboard"

    @pytest.mark.asyncio
    async def test_per_call_pctx_wins_over_constructor_pctx(self, flex_dashboard_module):
        """Code-review finding (adopted): on a shared/pooled agent, the
        PER-CALL PermissionContext (injected by ``AbstractTool.execute()``
        onto ``self._current_pctx`` from the ``_permission_context`` kwarg
        — e.g. via ``ToolManagerExecutor.call`` ->
        ``ToolManager.execute_tool``) must win over the ``pctx`` captured
        when the tool was built, so a refresh never runs under a stale or
        another caller's principal."""
        RefreshDashboardTool = flex_dashboard_module.RefreshDashboardTool

        fake_artifact = SimpleNamespace(artifact_id="art-3", content=b"<html/>")
        runner = SimpleNamespace(run=AsyncMock(return_value=fake_artifact))
        tool = RefreshDashboardTool(runner=runner, pctx="construction-time-pctx")

        original = flex_dashboard_module.current_a2ui_surface_state
        flex_dashboard_module.current_a2ui_surface_state = lambda: None
        try:
            # Simulate what AbstractTool.execute() does before calling
            # _execute(): stash the per-call pctx on the instance.
            tool._current_pctx = "per-call-pctx"
            await tool._execute()
        finally:
            flex_dashboard_module.current_a2ui_surface_state = original

        _, kwargs = runner.run.call_args
        assert kwargs["pctx"] == "per-call-pctx"

    @pytest.mark.asyncio
    async def test_falls_back_to_constructor_pctx_without_per_call_context(self, flex_dashboard_module):
        """Direct/demo calls (never routed through ToolManager.execute_tool)
        never get `_current_pctx` set — the constructor pctx is the only
        one available and must still be used."""
        RefreshDashboardTool = flex_dashboard_module.RefreshDashboardTool

        fake_artifact = SimpleNamespace(artifact_id="art-4", content=b"<html/>")
        runner = SimpleNamespace(run=AsyncMock(return_value=fake_artifact))
        tool = RefreshDashboardTool(runner=runner, pctx="construction-time-pctx")

        original = flex_dashboard_module.current_a2ui_surface_state
        flex_dashboard_module.current_a2ui_surface_state = lambda: None
        try:
            await tool._execute()
        finally:
            flex_dashboard_module.current_a2ui_surface_state = original

        _, kwargs = runner.run.call_args
        assert kwargs["pctx"] == "construction-time-pctx"


class TestPublishDashboardRecipe:
    @pytest.mark.asyncio
    async def test_publish_dashboard_recipe_persists_params(self, flex_dashboard_module):
        """Code-review finding (adopted): `publish_recipe()` alone never
        persists `RecipeParam` declarations — `publish_dashboard_recipe()`
        must do both steps atomically."""
        FlexDashboard = flex_dashboard_module.FlexDashboard

        published = SimpleNamespace(params=[])
        recipe_store = SimpleNamespace(save=AsyncMock())

        class _FakeAgent:
            DASHBOARD_RECIPE_NAME = FlexDashboard.DASHBOARD_RECIPE_NAME
            dashboard_descriptor = staticmethod(FlexDashboard.dashboard_descriptor)
            recipe_params = staticmethod(FlexDashboard.recipe_params)
            publish_recipe = AsyncMock(return_value=published)
            _require_recipe_store = lambda self: recipe_store

            publish_dashboard_recipe = FlexDashboard.publish_dashboard_recipe

        agent = _FakeAgent()
        result = await agent.publish_dashboard_recipe(overwrite=True)

        assert result is published
        assert result.params == FlexDashboard.recipe_params()
        recipe_store.save.assert_awaited_once_with(published)

    @pytest.mark.asyncio
    async def test_publish_dashboard_recipe_returns_gap_report_unsaved(self, flex_dashboard_module):
        FlexDashboard = flex_dashboard_module.FlexDashboard
        GapReport = flex_dashboard_module.GapReport

        gap_report = GapReport(gaps=[], covered=[])
        recipe_store = SimpleNamespace(save=AsyncMock())

        class _FakeAgent:
            DASHBOARD_RECIPE_NAME = FlexDashboard.DASHBOARD_RECIPE_NAME
            dashboard_descriptor = staticmethod(FlexDashboard.dashboard_descriptor)
            recipe_params = staticmethod(FlexDashboard.recipe_params)
            publish_recipe = AsyncMock(return_value=gap_report)
            _require_recipe_store = lambda self: recipe_store

            publish_dashboard_recipe = FlexDashboard.publish_dashboard_recipe

        agent = _FakeAgent()
        result = await agent.publish_dashboard_recipe()

        assert result is gap_report
        recipe_store.save.assert_not_awaited()
