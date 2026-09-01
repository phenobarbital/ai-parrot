"""End-to-end integration tests for FEAT-491 (Module 7): FlexDashboard's
publish / deterministic-replay / refresh-RPC path.

Proves the feature's headline claims end-to-end (pipeline-wide properties a
unit test cannot establish):

- ``test_flex_dashboard_publish_replay`` — publish → ``RecipeRunner.run()``
  twice → byte-identical HTML, with NO narrator configured (spec §5:
  "Recipe replays deterministically with NO narrator configured").
- ``test_flex_dashboard_filtered_replay`` — a params override (month /
  pay_code) produces a deterministic filtered variant, distinct from the
  unfiltered replay.
- ``test_flex_refresh_rpc`` — ``A2UIRuntime`` surface-state
  push → ``callAgentFunction`` → ``refresh_dashboard`` honors per-surface
  filter state; explicit args win.

Uses synthetic in-memory frames for all six Flex aliases (spec §7: slug
data is prod-only — NOTHING here touches QuerySource) via
``DatasetManager.add_dataframe``, mirroring
``tests/integration/test_finance_reporter_narrative_e2e.py``'s established
fixture approach. No live LLM call anywhere — no narrator is configured at
all (the recipe's narrative step is proven optional by its own absence).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("parrot.outputs.a2ui_renderers.interactive_html")

import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.recipes.store import FileRecipeStore
from parrot.outputs.a2ui.runtime import (
    A2UICallContext,
    A2UIRuntime,
    FunctionCallRecord,
    SurfaceState,
)
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends import build_overflow_store
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.tools.infographic_recipes.runner import RecipeRunner
from parrot.tools.infographic_sections import GapReport

# Worktree-safe file-path loading — same technique as this feature's unit
# tests (see test_flex_dashboard_agent.py's longer comment for why
# "agents.flex_dashboard" is reserved for the real package and the agent
# FILE is loaded under its own distinct synthetic name).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENTS_DIR = _REPO_ROOT / "agents"
_FLEX_DIR = _AGENTS_DIR / "flex_dashboard"
_EXAMPLES_DIR = _REPO_ROOT / "examples" / "agents" / "a2ui"


def _load_package(name: str, init_path: Path, search_dir: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, init_path, submodule_search_locations=[str(search_dir)])
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load package {name!r} from {init_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


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


def _load_flex_dashboard_class():
    _load_package("agents", _AGENTS_DIR / "__init__.py", _AGENTS_DIR)
    _load_package("agents.flex_dashboard", _FLEX_DIR / "__init__.py", _FLEX_DIR)
    _load_module("agents.flex_dashboard.normalize", _FLEX_DIR / "normalize.py")
    _load_module("agents.flex_dashboard.transformers", _FLEX_DIR / "transformers.py")
    module = _load_module("flex_dashboard_agent_module_e2e", _AGENTS_DIR / "flex_dashboard.py")
    return module.FlexDashboard


FlexDashboard = _load_flex_dashboard_class()

sys.path.insert(0, str(_EXAMPLES_DIR))
from flex_synthetic_data import build_flex_frames

RECIPE_NAME = FlexDashboard.DASHBOARD_RECIPE_NAME

#: The interactive-html renderer mints per-render DOM element ids
#: (uuid4-derived) — normalize them before a byte-identity comparison (same
#: technique as `examples/agents/a2ui/deterministic_refresh_dashboard.py`
#: and `flex_dashboard_demo.py`).
_VOLATILE_DOM_ID = re.compile(rb"(chart|tabs|nested)-[0-9a-f]{8}")


def _normalize_render(content: bytes) -> bytes:
    return _VOLATILE_DOM_ID.sub(rb"\1-x", content)


@pytest.fixture
def flex_frames() -> dict[str, Any]:
    return build_flex_frames()


@pytest.fixture
async def recipe_store(tmp_path):
    return FileRecipeStore(tmp_path / "recipes")


@pytest.fixture
async def wired_agent(tmp_path, recipe_store, flex_frames):
    """A FlexDashboard with all six aliases registered as in-memory frames."""
    backend = ConversationSQLiteBackend(path=str(tmp_path / "artifacts.db"))
    await backend.initialize()
    artifact_store = ArtifactStore(backend, build_overflow_store())
    agent = FlexDashboard(
        name="flex-dashboard-e2e",
        artifact_store=artifact_store,
        recipe_store=recipe_store,
        injection_detection=False,
    )
    # Bypass register_datasets() (live QuerySource slugs, prod-only, spec §7)
    # — register the SAME six aliases as in-memory frames instead.
    for alias, frame in flex_frames.items():
        agent._dataset_manager.add_dataframe(alias, frame)
    return agent


@pytest.fixture
def pctx():
    return build_principal_context("e2e-user", channel="test")


@pytest.fixture
async def published_recipe(wired_agent, recipe_store):
    recipe = await wired_agent.publish_recipe(RECIPE_NAME, FlexDashboard.dashboard_descriptor(), overwrite=True)
    assert not isinstance(
        recipe, GapReport
    ), f"expected a full recipe, got a GapReport: {getattr(recipe, 'gaps', None)}"
    recipe.params = FlexDashboard.recipe_params()
    await recipe_store.save(recipe)
    return recipe


class TestFlexDashboardPublishReplay:
    async def test_publish_recipe_succeeds_not_gapreport(self, published_recipe):
        assert published_recipe.name == RECIPE_NAME
        transformer_names = {t.transformer for t in published_recipe.transforms}
        assert transformer_names == {
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
        }

    async def test_flex_dashboard_publish_replay(self, wired_agent, recipe_store, published_recipe, pctx):
        """Two replays with identical (default) params produce byte-identical
        HTML — no narrator configured, proving the narrative step is
        genuinely optional (spec §5)."""
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager)

        first = await runner.run(RECIPE_NAME, pctx=pctx)
        second = await runner.run(RECIPE_NAME, pctx=pctx)

        assert first.content
        assert _normalize_render(first.content) == _normalize_render(second.content)


class TestFlexDashboardFilteredReplay:
    async def test_flex_dashboard_filtered_replay(self, wired_agent, recipe_store, published_recipe, pctx):
        """A params override (month/pay_code) gives a deterministic filtered
        variant — repeated with the SAME override still byte-identical, and
        different from the unfiltered default replay."""
        runner = RecipeRunner(recipe_store, wired_agent._dataset_manager)

        default = await runner.run(RECIPE_NAME, pctx=pctx)
        filtered_a = await runner.run(RECIPE_NAME, params={"month": "2025-10", "pay_code": "Field Time"}, pctx=pctx)
        filtered_b = await runner.run(RECIPE_NAME, params={"month": "2025-10", "pay_code": "Field Time"}, pctx=pctx)

        assert _normalize_render(filtered_a.content) == _normalize_render(filtered_b.content)
        assert _normalize_render(filtered_a.content) != _normalize_render(default.content)


class TestFlexRefreshRpc:
    async def test_refresh_tool_direct_args(self, wired_agent, published_recipe, pctx):
        """`build_refresh_tool` wires a RecipeRunner + pctx; explicit args
        drive a filtered re-render."""
        refresh_tool = wired_agent.build_refresh_tool(pctx)

        result = await refresh_tool.execute(month="2025-10")

        assert result.result["filters"] == {"month": "2025-10"}
        assert result.result["filter_source"] == "args"
        assert result.result["bytes"] > 0

    async def test_refresh_rpc_honors_surface_state(self, wired_agent, published_recipe, pctx):
        """`A2UIRuntime` surface-state push -> `callAgentFunction` ->
        `refresh_dashboard`; explicit args win over the persisted state."""

        class InMemorySurfaceStore:
            def __init__(self) -> None:
                self._store: dict[tuple, SurfaceState] = {}

            async def get(self, session_id: str, surface_id: str):
                return self._store.get((session_id, surface_id))

            async def put(self, session_id: str, state: SurfaceState) -> None:
                self._store[(session_id, state.surface_id)] = state

            async def delete(self, session_id: str, surface_id: str) -> None:
                self._store.pop((session_id, surface_id), None)

        class InMemoryPendingCalls:
            def __init__(self) -> None:
                self._store: dict[tuple, FunctionCallRecord] = {}

            async def add(self, session_id: str, record: FunctionCallRecord) -> None:
                self._store[(session_id, record.function_call_id)] = record

            async def resolve(self, session_id, function_call_id, value, error):
                return self._store.pop((session_id, function_call_id), None)

        surface_id = f"{RECIPE_NAME}-infographic"
        session_id = "sess-e2e"

        # `build_refresh_tool` already registers the tool on the agent's
        # ToolManager — do not add it again (would raise a name collision).
        wired_agent.build_refresh_tool(pctx)

        surfaces = InMemorySurfaceStore()
        runtime = A2UIRuntime(
            executor=ToolManagerExecutor(wired_agent.tool_manager),
            surfaces=surfaces,
            pending=InMemoryPendingCalls(),
        )
        ctx = A2UICallContext(
            agent_id="flex_dashboard",
            user_id="e2e-user",
            session_id=session_id,
            surface_id=surface_id,
            transport="http",
            permission_context=pctx,
        )

        # Push inline filter state via `action` + `dataModel`.
        action_env = {
            "version": "v1.0",
            "action": {
                "name": "filters_changed",
                "surfaceId": surface_id,
                "sourceComponentId": "filter-bar",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "context": {},
                "dataModel": {"filters": {"month": "2025-09", "flex_type": "Flex"}},
            },
        }
        await runtime.dispatch(action_env, ctx)
        stored = await surfaces.get(session_id, surface_id)
        assert stored.data_model["filters"] == {"month": "2025-09", "flex_type": "Flex"}

        # `callAgentFunction` -> `ToolManagerExecutor.call` ->
        # `ToolManager.execute_tool` does NOT itself inject surface state
        # (verified: it only forwards `permission_context`) — an explicit
        # arg via `callAgentFunction` always reaches the tool as a plain
        # arg. The "no args -> filters come from the surface state" lane is
        # a DIRECT `execute(_a2ui_surface_state=...)` call instead (the
        # same reserved kwarg `AbstractBot.ask(a2ui_surface_state=...)`
        # uses for every tool in an A2UI-triggered turn) — mirrors
        # `examples/agents/a2ui/deterministic_refresh_dashboard.py`'s own
        # Step 5 / `flex_dashboard_demo.py`'s lane_rpc Step 5.
        refresh_tool = wired_agent.tool_manager.get_tool("refresh_dashboard")
        result = await refresh_tool.execute(_a2ui_surface_state=stored)
        assert result.result["filters"] == {"month": "2025-09", "flex_type": "Flex"}
        assert result.result["filter_source"] == "surface_state"

        # callAgentFunction WITH explicit args reaches the tool as plain args.
        from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID

        call_env = {
            "version": "v1.0",
            "callAgentFunction": {
                "surfaceId": surface_id,
                "functionCallId": "fc-1",
                "callFunction": {
                    "call": "refresh_dashboard",
                    "args": {"month": "2025-10"},
                    "catalogId": DEFAULT_CATALOG_ID,
                },
            },
        }
        res = await runtime.dispatch(call_env, ctx)
        value = res.messages[0]["agentFunctionResponse"]["value"]
        assert value["filters"]["month"] == "2025-10"
        assert value["filter_source"] == "args"
