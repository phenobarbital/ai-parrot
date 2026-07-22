"""Tool-exposure + tool-output tests for FEAT-324 Module 6 recipe tools on
`InfographicToolkit` (mocked store/runner — the real store/runner are
TASK-1868/1869's own test suites)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RecipeParam,
    RecipeRunError,
    TransformStep,
)
from parrot.auth.permission import PermissionContext, UserSession
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError
from parrot.tools.infographic_recipes.runner import RecipeRunException
from parrot.tools.infographic_toolkit import _RECIPE_TOOL_NAMES, InfographicToolkit


@pytest.fixture
def fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return store


@pytest.fixture
def fake_recipe_store():
    store = MagicMock()
    store.save = AsyncMock(return_value=None)
    store.list = AsyncMock(return_value=[])
    store.get = AsyncMock()
    return store


@pytest.fixture
def fake_recipe_runner():
    runner = MagicMock()
    runner.run = AsyncMock()
    runner.dry_run = AsyncMock(return_value=[])
    return runner


def _sample_recipe(**overrides) -> InfographicRecipe:
    defaults = dict(
        name="test-recipe",
        title="Test Recipe",
        owner="user-1",
        params=[RecipeParam(name="month", default="current_month")],
        data_sources=[DataSourceSpec(dataset="ledger", alias="snapshots")],
        transforms=[
            TransformStep(
                transformer="division_breakdown", inputs=["snapshots"], output_key="db"
            )
        ],
        layout=LayoutSpec(component="Infographic", properties={}),
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return InfographicRecipe(**defaults)


class TestRecipeTools:
    def test_tools_absent_without_store(self, fake_artifact_store):
        tk = InfographicToolkit(artifact_store=fake_artifact_store)
        tool_names = {t.name for t in tk.get_tools()}
        for recipe_tool in _RECIPE_TOOL_NAMES:
            assert recipe_tool not in tool_names
        # Existing template tools remain present (regression guard).
        assert "infographic_render" in tool_names
        assert "infographic_list_templates" in tool_names

    def test_tools_present_with_store(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        tool_names = {t.name for t in tk.get_tools()}
        for recipe_tool in _RECIPE_TOOL_NAMES:
            assert recipe_tool in tool_names

    async def test_run_recipe_returns_structured_error(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        error = RecipeRunError(recipe="test-recipe", stage="gate", detail="missing column")
        fake_recipe_runner.run.side_effect = RecipeRunException(error)

        result = await tk.infographic_run_recipe("test-recipe")

        assert result["status"] == "error"
        assert result["error"]["stage"] == "gate"
        assert result["error"]["detail"] == "missing column"

    async def test_run_recipe_success(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        artifact = MagicMock(
            artifact_id="a1", mime_type="text/html", title="T", filename="f.html"
        )
        fake_recipe_runner.run.return_value = artifact

        result = await tk.infographic_run_recipe("test-recipe", params={"month": "2026-06"})

        assert result == {
            "status": "ok",
            "artifact_id": "a1",
            "mime_type": "text/html",
            "title": "T",
            "filename": "f.html",
        }
        # pctx/recipe_owner are ALWAYS threaded through so replay honors the
        # same PBAC/data-plane guards a live chat call would (spec G8).
        fake_recipe_runner.run.assert_awaited_once()
        call_args, call_kwargs = fake_recipe_runner.run.call_args
        assert call_args == ("test-recipe",)
        assert call_kwargs["params"] == {"month": "2026-06"}
        assert call_kwargs["pctx"] is not None
        assert call_kwargs["recipe_owner"] == "_anon"  # no bot bound -> _resolve_scope sentinel

    async def test_run_recipe_uses_dispatch_injected_permission_context(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        """When invoked through the real toolkit-dispatch path (`_pre_execute`
        injects `_permission_context`), `infographic_run_recipe` must use THAT
        real context — not the `build_principal_context` fallback — so
        DatasetManager's PBAC guards see the invoker's actual roles/tenant."""
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        artifact = MagicMock(
            artifact_id="a1", mime_type="text/html", title="T", filename="f.html"
        )
        fake_recipe_runner.run.return_value = artifact

        real_pctx = PermissionContext(
            session=UserSession(user_id="alice", tenant_id="acme", roles=frozenset({"finance.read"}))
        )
        # Mirrors ToolkitTool._execute: _pre_execute runs BEFORE the tool
        # body, _post_execute AFTER — always injecting _permission_context.
        await tk._pre_execute("infographic_run_recipe", _permission_context=real_pctx)
        try:
            await tk.infographic_run_recipe("test-recipe")
        finally:
            await tk._post_execute("infographic_run_recipe", None)

        call_kwargs = fake_recipe_runner.run.call_args.kwargs
        assert call_kwargs["pctx"] is real_pctx

    async def test_run_recipe_without_runner_configured(self, fake_artifact_store):
        tk = InfographicToolkit(artifact_store=fake_artifact_store)
        # Bypass exclusion (unit-test the method body directly).
        result = await tk.infographic_run_recipe("test-recipe")
        assert result["status"] == "error"

    async def test_get_recipe_contract_lists_datasets_columns_params(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        fake_recipe_store.get.return_value = _sample_recipe()

        result = await tk.infographic_get_recipe_contract("test-recipe")

        assert result["status"] == "ok"
        assert result["datasets"] == [{"alias": "snapshots", "dataset": "ledger"}]
        assert result["params"] == [
            {"name": "month", "default": "current_month", "description": None}
        ]
        assert result["transforms"][0]["transformer"] == "division_breakdown"
        assert "requires_columns" in result["transforms"][0]

    async def test_get_recipe_contract_missing_recipe(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        fake_recipe_store.get.side_effect = RecipeNotFoundError("test-recipe", [])

        result = await tk.infographic_get_recipe_contract("test-recipe")
        assert result["status"] == "error"

    async def test_list_recipes_passthrough(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        fake_recipe_store.list.return_value = [{"name": "test-recipe", "title": "Test"}]

        result = await tk.infographic_list_recipes()
        assert result == [{"name": "test-recipe", "title": "Test"}]

    async def test_list_recipes_without_store(self, fake_artifact_store):
        tk = InfographicToolkit(artifact_store=fake_artifact_store)
        result = await tk.infographic_list_recipes()
        assert result == []

    async def test_save_recipe_success(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        fake_recipe_store.get.return_value = _sample_recipe()

        result = await tk.infographic_save_recipe(
            name="test-recipe",
            title="Test Recipe",
            layout_component="Infographic",
            layout_properties={"title": "T", "sections": []},
            dataset_names={"snapshots": "ledger"},
            transform_steps=[
                {"transformer": "division_breakdown", "inputs": ["snapshots"], "output_key": "db"}
            ],
        )

        assert result["status"] == "ok"
        fake_recipe_store.save.assert_awaited_once()
        fake_recipe_runner.dry_run.assert_awaited_once()

    async def test_save_recipe_rejects_adhoc_provenance(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        result = await tk.infographic_save_recipe(
            name="test-recipe",
            title="Test Recipe",
            layout_component="Infographic",
            layout_properties={"title": "T", "sections": []},
            dataset_names={},
            transform_steps=[],
        )
        assert result["status"] == "error"
        fake_recipe_store.save.assert_not_awaited()

    async def test_save_recipe_dirty_dry_run_rejected(
        self, fake_artifact_store, fake_recipe_store, fake_recipe_runner
    ):
        tk = InfographicToolkit(
            artifact_store=fake_artifact_store,
            recipe_store=fake_recipe_store,
            recipe_runner=fake_recipe_runner,
        )
        fake_recipe_runner.dry_run.return_value = [
            RecipeRunError(recipe="test-recipe", stage="gate", detail="missing column")
        ]

        result = await tk.infographic_save_recipe(
            name="test-recipe",
            title="Test Recipe",
            layout_component="Infographic",
            layout_properties={"title": "T", "sections": []},
            dataset_names={"snapshots": "ledger"},
            transform_steps=[
                {"transformer": "division_breakdown", "inputs": ["snapshots"], "output_key": "db"}
            ],
        )
        assert result["status"] == "error"
        assert "errors" in result
        fake_recipe_store.save.assert_not_awaited()

    async def test_save_recipe_without_store(self, fake_artifact_store):
        tk = InfographicToolkit(artifact_store=fake_artifact_store)
        result = await tk.infographic_save_recipe(
            name="test-recipe",
            title="Test Recipe",
            layout_component="Infographic",
            layout_properties={"title": "T", "sections": []},
            dataset_names={"snapshots": "ledger"},
            transform_steps=[
                {"transformer": "division_breakdown", "inputs": ["snapshots"], "output_key": "db"}
            ],
        )
        assert result["status"] == "error"
