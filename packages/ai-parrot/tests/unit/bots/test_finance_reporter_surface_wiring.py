"""Surface/refresh wiring tests for `FinanceReporter`.

Covers the three gaps this agent had against the FEAT-492 rehydration plane
and the FEAT-491 (`agents/flex_dashboard.py`) precedent:

- it never defaulted an ``artifact_store``, so the real discovery path left
  ``_infographic_toolkit`` as ``None`` and every tier-2 call raised;
- nothing ever called ``publish_surface``, so no ``navigator.ui_surfaces``
  row existed for a finance profile (nothing bookmarkable/refreshable);
- it exposed no ``refresh_dashboard`` agent function for the renderer's
  ``callAgentFunction`` lane.

Module loading mirrors `test_finance_reporter_descriptors.py` — see its
header for why a plain `import agents.finance_reporter` is unreliable here.
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_FINANCE_REPORTER_PATH = _REPO_ROOT / "agents" / "finance_reporter.py"


def _load_finance_reporter():
    module_name = "agents.finance_reporter"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _FINANCE_REPORTER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {_FINANCE_REPORTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def module():
    return _load_finance_reporter()


@pytest.fixture(scope="module")
def FinanceReporter(module):
    return module.FinanceReporter


class TestDefaultArtifactStore:
    """The boot path — `AgentRegistry` / `agents.yaml` pass no stores."""

    def test_bare_construction_wires_a_toolkit(self, FinanceReporter):
        agent = FinanceReporter(name="finance-reporter-bare")
        assert agent._infographic_toolkit is not None

    def test_explicit_artifact_store_is_not_overridden(self, FinanceReporter):
        sentinel = MagicMock(name="artifact-store")
        agent = FinanceReporter(name="finance-reporter-explicit", artifact_store=sentinel)
        assert agent._infographic_toolkit is not None
        assert agent._infographic_toolkit._artifact_store is sentinel

    def test_recipe_store_reaches_the_toolkit(self, FinanceReporter):
        recipe_store = MagicMock(name="recipe-store")
        agent = FinanceReporter(name="finance-reporter-recipes", recipe_store=recipe_store)
        assert agent._require_recipe_store() is recipe_store


class TestProfileResolution:
    def test_report_profile(self, FinanceReporter):
        name, descriptor, kind, title = FinanceReporter._profile("report")
        assert name == FinanceReporter.REPORT_RECIPE_NAME
        assert kind == "infographic"
        assert descriptor.layout.component == "Report"
        assert title

    def test_dashboard_profile(self, FinanceReporter):
        name, descriptor, kind, title = FinanceReporter._profile("dashboard")
        assert name == FinanceReporter.DASHBOARD_RECIPE_NAME
        assert kind == "dashboard"
        assert descriptor.layout.component == "Infographic"
        assert title

    def test_unknown_profile_raises(self, FinanceReporter):
        with pytest.raises(ValueError, match="Unknown profile"):
            FinanceReporter._profile("kpi")

    def test_profiles_use_distinct_recipe_names(self, FinanceReporter):
        assert FinanceReporter.REPORT_RECIPE_NAME != FinanceReporter.DASHBOARD_RECIPE_NAME


class TestPublishProfileSurface:
    """`publish_profile_surface` bridges RecipeRunner -> ui_surfaces."""

    @pytest.fixture
    def agent(self, FinanceReporter):
        agent = FinanceReporter(name="finance-reporter-surface", recipe_store=MagicMock())
        agent.publish_surface = AsyncMock(return_value="surface-123")
        return agent

    def _patch_runner(self, module, monkeypatch, artifact):
        runner = MagicMock()
        runner.run = AsyncMock(return_value=artifact)
        monkeypatch.setattr(module, "RecipeRunner", MagicMock(return_value=runner))
        return runner

    @pytest.mark.asyncio
    async def test_replays_with_include_envelope_and_persists(self, module, agent, monkeypatch):
        artifact = SimpleNamespace(metadata={"source_envelope": {"surfaceId": "x"}}, artifact_id="a1", content=b"<html>")
        runner = self._patch_runner(module, monkeypatch, artifact)
        pctx = MagicMock(name="pctx")

        surface_id = await agent.publish_profile_surface("dashboard", pctx=pctx)

        assert surface_id == "surface-123"
        # G8 bridge: the envelope must come off the run, not a second round-trip.
        _, run_kwargs = runner.run.call_args
        assert run_kwargs["include_envelope"] is True
        assert run_kwargs["pctx"] is pctx

    @pytest.mark.asyncio
    async def test_persisted_row_is_refreshable(self, module, agent, monkeypatch):
        artifact = SimpleNamespace(metadata={"source_envelope": {"surfaceId": "x"}}, artifact_id="a1", content=b"")
        self._patch_runner(module, monkeypatch, artifact)

        await agent.publish_profile_surface("dashboard", pctx=MagicMock())

        _, kwargs = agent.publish_surface.call_args
        # recipe_name is what makes UISurfaceRecord.refreshable True.
        assert kwargs["recipe_name"] == agent.DASHBOARD_RECIPE_NAME
        assert kwargs["kind"] == "dashboard"

    @pytest.mark.asyncio
    async def test_params_recorded_as_stored_tier(self, module, agent, monkeypatch):
        artifact = SimpleNamespace(metadata={"source_envelope": {}}, artifact_id="a1", content=b"")
        self._patch_runner(module, monkeypatch, artifact)

        await agent.publish_profile_surface("report", pctx=MagicMock(), params={"snapshot_col": "d"})

        _, kwargs = agent.publish_surface.call_args
        assert kwargs["recipe_params"] == {"snapshot_col": "d"}

    @pytest.mark.asyncio
    async def test_missing_envelope_raises_rather_than_persisting_nothing(self, module, agent, monkeypatch):
        artifact = SimpleNamespace(metadata={}, artifact_id="a1", content=b"")
        self._patch_runner(module, monkeypatch, artifact)

        with pytest.raises(RuntimeError, match="source_envelope"):
            await agent.publish_profile_surface("dashboard", pctx=MagicMock())
        agent.publish_surface.assert_not_awaited()


class TestRefreshTool:
    def test_tool_name_matches_the_renderer_lane(self, module):
        assert module.RefreshFinanceSurfaceTool.name == "refresh_dashboard"

    def test_build_refresh_tool_registers_it(self, FinanceReporter):
        agent = FinanceReporter(name="finance-reporter-refresh", recipe_store=MagicMock())
        tool = agent.build_refresh_tool(pctx=MagicMock())
        assert tool.name == "refresh_dashboard"
        assert agent.tool_manager.get_tool("refresh_dashboard") is not None

    def test_build_refresh_tool_requires_a_recipe_store(self, FinanceReporter):
        agent = FinanceReporter(name="finance-reporter-no-store")
        with pytest.raises(RuntimeError, match="recipe store"):
            agent.build_refresh_tool(pctx=MagicMock())

    @pytest.mark.asyncio
    async def test_execute_replays_the_selected_profile(self, module):
        runner = MagicMock()
        runner.run = AsyncMock(return_value=SimpleNamespace(artifact_id="a9", content=b"1234"))
        tool = module.RefreshFinanceSurfaceTool(runner=runner, pctx=MagicMock())

        result = await tool._execute(profile="report")

        assert result["recipe"] == module.FinanceReporter.REPORT_RECIPE_NAME
        assert result["artifact_id"] == "a9"
        assert result["bytes"] == 4

    @pytest.mark.asyncio
    async def test_per_call_pctx_wins_over_construction_pctx(self, module):
        """A shared agent must not leak one caller's data-plane scope."""
        runner = MagicMock()
        runner.run = AsyncMock(return_value=SimpleNamespace(artifact_id="a", content=b""))
        ctor_pctx, call_pctx = MagicMock(name="ctor"), MagicMock(name="call")
        tool = module.RefreshFinanceSurfaceTool(runner=runner, pctx=ctor_pctx)
        tool._current_pctx = call_pctx

        await tool._execute()

        _, kwargs = runner.run.call_args
        assert kwargs["pctx"] is call_pctx
