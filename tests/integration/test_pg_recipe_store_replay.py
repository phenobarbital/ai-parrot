"""Integration tests: publish/replay + REST lane through ``PgRecipeStore``
(FEAT-528 TASK-2873).

Proves ``PgRecipeStore`` is a drop-in ``AbstractRecipeStore`` at every real
call site named by the spec (§5): ``RecipeRunner`` (direct replay, a
SEPARATE store instance from the one that published), ``register_recipe_
routes`` + the REST lane (a real ``aiohttp.web.Application`` with the same
three views ``manager.py`` registers), ``InfographicAuthoringMixin
.publish_recipe`` (the REAL bound mixin method, via a lightweight stand-in
instance — never a mock of `publish_recipe` itself), and
``UISurfacesHandler``'s refresh path (its own ``_recipe_runner()`` reuses
the SAME process-wide singleton ``register_recipe_routes`` configures, so
resolving it there and replaying through it demonstrates that call site
without recreating the whole ``ui_surfaces`` plane — this suite must never
touch ``navigator.ui_surfaces``, per the task's own scope).

Render profile note: ``recipe.render.profile`` is deliberately ``"ssr_html"``,
NOT the model's own default ``"interactive-html"`` — ``get_a2ui_renderer``
resolves a renderer's satellite module via
``f"parrot.outputs.a2ui_renderers.{name}"`` (verified,
``outputs/a2ui/renderers/__init__.py``), and ``"interactive-html"`` is the
ONLY renderer name that does not match its own module filename
(``interactive_html.py``, underscore) — every other renderer's registered
name equals its filename exactly (``echarts``, ``ssr_html``, ``pdf``,
``adaptive_cards``, ``folium_map``, verified against the installed
``ai-parrot-visualizations`` package). This is a pre-existing, unrelated
core defect (recorded in the task's Completion Note per its own "no
production change" instruction) — using a working profile sidesteps it
without touching production code.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from aiohttp.web_urldispatcher import MatchInfoError

from parrot.auth.permission import build_principal_context
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.handlers.infographic_recipes import (
    RecipeHandler,
    configure_recipe_runner,
    register_recipe_routes,
)
from parrot.handlers.models.recipes import PgRecipeStore
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RenderSpec,
    TransformStep,
)
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.infographic_recipes import RecipeRunner
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec

pytestmark = pytest.mark.integration


def _recipe(name: str) -> InfographicRecipe:
    """A minimal, generic (non-flex) recipe over the stock ``day_totals``
    transformer (`library.py`), so this suite never depends on the flex
    agent."""
    return InfographicRecipe(
        name=name,
        title="Test Recipe",
        render=RenderSpec(profile="ssr_html"),
        data_sources=[DataSourceSpec(dataset="snapshots", alias="snapshots")],
        transforms=[TransformStep(transformer="day_totals", inputs=["snapshots"], output_key="totals")],
        layout=LayoutSpec(
            component="Infographic",
            title="Test",
            sections=[
                {
                    "heading": "Totals",
                    "components": [
                        {
                            "component": "KPICard",
                            "properties": {"label": "Revenue", "value": {"path": "/totals/rev_actual"}},
                        }
                    ],
                }
            ],
        ),
        updated_at=datetime.now(UTC),
    )


def _snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "division": ["East", "West"],
            "project": ["p1", "p2"],
            "rev_actual": [100.0, 200.0],
            "rev_budget": [90.0, 210.0],
            "ebitda_actual": [10.0, 20.0],
            "ebitda_budget": [9.0, 21.0],
        }
    )


def _dataset_manager() -> DatasetManager:
    dm = DatasetManager(generate_guide=False)
    dm.add_dataframe("snapshots", _snapshot_frame())
    return dm


@pytest.fixture
async def pg_store(pg_dsn):
    if not pg_dsn:
        pytest.skip("NAVIGATOR_PG_DSN not set")
    store = PgRecipeStore(pg_dsn)
    await store.ensure_schema()
    db = store._get_db()
    async with await db.connection() as conn:
        await conn.execute(f"TRUNCATE {store.schema}.infographic_recipes")
    yield store
    async with await db.connection() as conn:
        await conn.execute(f"TRUNCATE {store.schema}.infographic_recipes")


class TestPublishReplayThroughPgStore:
    async def test_recipe_publish_and_replay_through_pg_store(self, pg_store, pg_dsn):
        """Publish via store A, replay via a SEPARATE store B instance — the
        row is the only state carried between them."""
        recipe = _recipe("test-2873-replay")
        await pg_store.save(recipe)

        store_b = PgRecipeStore(pg_dsn)
        dataset_manager = _dataset_manager()
        runner = RecipeRunner(store_b, dataset_manager)
        pctx = build_principal_context("test-user", channel="test")

        artifact = await runner.run("test-2873-replay", pctx=pctx, include_envelope=True)

        envelope = artifact.metadata["source_envelope"]
        assert envelope["dataModel"]["totals"]["rev_actual"] == 300.0
        assert envelope["components"][0]["sections"][0]["heading"] == "Totals"


class TestRegisterRecipeRoutesWithPgStore:
    async def test_integration_routes_registered(self, pg_store):
        """``register_recipe_routes`` + the three literal ``manager.py``
        views resolve on a REAL ``aiohttp.web.Application`` (mirrors
        ``test_ui_surfaces_e2e.py::test_integration_routes_registered``)."""
        app = web.Application()
        recipe_runner = register_recipe_routes(app, recipe_store=pg_store, dataset_manager=_dataset_manager())
        assert app["recipe_store"] is pg_store
        assert app["recipe_runner"] is recipe_runner

        router = app.router
        router.add_view("/api/v1/infographic_recipes", RecipeHandler)
        router.add_view("/api/v1/infographic_recipes/{name}", RecipeHandler)
        router.add_view("/api/v1/infographic_recipes/{name}/run", RecipeHandler)

        router.freeze()
        for method, path in [
            ("GET", "/api/v1/infographic_recipes"),
            ("GET", "/api/v1/infographic_recipes/some-name"),
            ("POST", "/api/v1/infographic_recipes/some-name/run"),
        ]:
            match_info = await router.resolve(make_mocked_request(method, path))
            assert not isinstance(match_info, MatchInfoError), f"{method} {path} did not resolve"

    async def test_register_recipe_routes_with_pg_store(self, pg_store):
        """``GET`` lists the saved recipe; ``POST .../run`` answers with the
        runner's shape — the same ``RecipeHandler`` logic
        ``test_infographic_recipes.py`` unit-tests against a mock store, now
        driven against a REAL ``PgRecipeStore``."""
        recipe = _recipe("test-2873-rest").model_copy(update={"owner": "user-1"})
        await pg_store.save(recipe)

        dataset_manager = _dataset_manager()
        recipe_runner = RecipeRunner(pg_store, dataset_manager)
        app = {"recipe_store": pg_store, "recipe_runner": recipe_runner}

        def _handler(match_info=None, path="", json_body=None, user_id="user-1"):
            h = RecipeHandler.__new__(RecipeHandler)
            import logging

            h.logger = logging.getLogger("test.recipe_handler.pg")
            h._request = SimpleNamespace(
                app=app,
                match_info=match_info or {},
                path=path,
                user=SimpleNamespace(user_id=user_id) if user_id else None,
                json=AsyncMock(return_value=json_body) if json_body is not None else AsyncMock(side_effect=ValueError),
            )
            return h

        def _unwrap(method):
            while hasattr(method, "__wrapped__"):
                method = method.__wrapped__
            return method

        # GET list -> the recipe published above.
        h_list = _handler()
        resp_list = await _unwrap(RecipeHandler.get)(h_list)
        assert resp_list.status == 200
        body_list = json.loads(resp_list.body)
        assert any(r["name"] == "test-2873-rest" for r in body_list["recipes"])

        # POST .../run -> the runner's artifact metadata shape.
        h_run = _handler(match_info={"name": "test-2873-rest"}, path="/api/v1/infographic_recipes/test-2873-rest/run")
        resp_run = await _unwrap(RecipeHandler.post)(h_run)
        assert resp_run.status == 200
        body_run = json.loads(resp_run.body)
        assert body_run["status"] == "success"
        assert body_run["artifact"]["mime_type"] == "text/html"


class _MiniAuthoringBot(InfographicAuthoringMixin):
    """Lightweight REAL instance of the mixin (same technique
    ``test_ui_surfaces_e2e.py::_MiniBot`` uses for ``publish_surface``) —
    ``publish_recipe`` only needs ``self.logger`` and a
    ``self._infographic_toolkit`` carrying a ``._recipe_store``, so this
    skips constructing a full (heavier, ``ai-parrot-visualizations``-
    needing) ``InfographicToolkit`` while still exercising the REAL,
    unmocked ``publish_recipe`` bound method."""

    def __init__(self, name: str, recipe_store: PgRecipeStore) -> None:
        import logging

        self.name = name
        self.logger = logging.getLogger(f"test.pg_recipe_store.{name}")
        self._infographic_toolkit = SimpleNamespace(_recipe_store=recipe_store)


class TestPublishRecipeViaInfographicAuthoringMixin:
    async def test_publish_recipe_via_mixin_with_pg_store(self, pg_store):
        """The REAL ``InfographicAuthoringMixin.publish_recipe`` (not a
        mock, not a reimplementation) against a real ``PgRecipeStore``."""
        bot = _MiniAuthoringBot("mini-authoring-bot", pg_store)
        descriptor = SectionDescriptor(
            template="unused-with-layout",
            mode="data-splice",
            sections=[
                SectionSpec(name="day_totals", target="/totals", datasets=["snapshots"], shape="mapping")
            ],
            layout=LayoutSpec(
                component="Infographic",
                title="Test",
                sections=[
                    {
                        "heading": "Totals",
                        "components": [
                            {
                                "component": "KPICard",
                                "properties": {"label": "Revenue", "value": {"path": "/totals/rev_actual"}},
                            }
                        ],
                    }
                ],
            ),
        )

        result = await bot.publish_recipe("test-2873-publish-recipe", descriptor, overwrite=True)

        assert isinstance(result, InfographicRecipe)
        saved = await pg_store.get("test-2873-publish-recipe")
        assert saved.transforms[0].transformer == "day_totals"
        assert saved.data_sources[0].dataset == "snapshots"


class TestUISurfacesHandlerRefreshResolvesPgBackedRunner:
    async def test_ui_surfaces_handler_recipe_runner_is_pg_backed(self, pg_store):
        """``UISurfacesHandler._recipe_runner()`` reuses the SAME process-wide
        singleton ``register_recipe_routes`` configures (``infographic_
        recipes.py``'s ``configure_recipe_runner``/``get_recipe_runner``) —
        resolving it here and replaying through it demonstrates the refresh
        call site is PgRecipeStore-backed without recreating the whole
        ``ui_surfaces`` plane (never touched by this suite)."""
        from parrot.handlers.ui_surfaces import UISurfacesHandler

        recipe = _recipe("test-2873-ui-surfaces-refresh")
        await pg_store.save(recipe)

        app = web.Application()
        register_recipe_routes(app, recipe_store=pg_store, dataset_manager=_dataset_manager())
        try:
            h = UISurfacesHandler.__new__(UISurfacesHandler)
            h._request = SimpleNamespace(app=app)
            runner = h._recipe_runner()
            assert runner is not None
            assert runner.store is pg_store

            pctx = build_principal_context("test-user", channel="ui_surfaces")
            artifact = await runner.run(
                "test-2873-ui-surfaces-refresh", pctx=pctx, recipe_owner=None, include_envelope=True
            )
            assert artifact.metadata["source_envelope"]["dataModel"]["totals"]["rev_actual"] == 300.0
        finally:
            configure_recipe_runner(None)
