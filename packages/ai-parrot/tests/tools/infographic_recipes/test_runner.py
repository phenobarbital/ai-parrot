"""Pipeline/order/binding/error tests for FEAT-324 Module 5
(`parrot.tools.infographic_recipes.runner.RecipeRunner`).

Uses a fake in-memory recipe store, a fake `DatasetManager` (fetch_dataset /
get_dataset_entry / list_datasets / get_metadata stubs), and a fake renderer
registered via `register_a2ui_renderer` (the real interactive-html renderer
is TASK-1871's concern; this task's tests fake it, per the task's own scope).
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import parrot.tools.infographic_recipes.runner as runner_module
from parrot.auth.context import _pctx_var
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RecipeParam,
    RenderSpec,
    TransformStep,
)
from parrot.outputs.a2ui.recipes.transformers import transformer_registry
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner


# ── Fake renderer (registered once at import time) ─────────────────────────

_RENDERED_ENVELOPES: list = []


@register_a2ui_renderer(
    "fake-recorder",
    RendererCapabilities(
        interactive=True, supports_actions=False, supports_updates=False, output="text/html"
    ),
)
class _FakeRenderer(AbstractA2UIRenderer):
    async def render(self, envelope, *, bake: bool = True) -> RenderedArtifact:
        _RENDERED_ENVELOPES.append(envelope)
        return RenderedArtifact(
            artifact_id="fake-artifact-1",
            mime_type="text/html",
            content=b"<html></html>",
            filename="fake.html",
            title="Fake Render",
            surface="fake-recorder",
        )


@pytest.fixture(autouse=True)
def _clear_rendered_envelopes():
    _RENDERED_ENVELOPES.clear()
    yield
    _RENDERED_ENVELOPES.clear()


# ── Fake DatasetManager ──────────────────────────────────────────────────


class _FakeDatasetManager:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
        self.fetch_calls: list[dict] = []
        self.pctx_seen_during_fetch: list = []

    async def fetch_dataset(self, name, sql=None, conditions=None, force_refresh=False):
        self.fetch_calls.append(
            {"name": name, "sql": sql, "conditions": conditions, "force_refresh": force_refresh}
        )
        self.pctx_seen_during_fetch.append(_pctx_var.get())
        if name not in self._frames:
            return {"error": f"Dataset {name!r} not found.", "available": sorted(self._frames)}
        return {"status": "success"}

    def get_dataset_entry(self, name):
        if name not in self._frames:
            return None
        return SimpleNamespace(df=self._frames[name])

    async def list_datasets(self):
        return [{"name": n} for n in sorted(self._frames)]

    async def get_metadata(self, name, **kwargs):
        if name not in self._frames:
            return {"error": f"Dataset {name!r} not found."}
        return {"columns": {c: {} for c in self._frames[name].columns}}


# ── Fake recipe store ────────────────────────────────────────────────────


class _FakeStore:
    def __init__(self, recipes: dict[str, InfographicRecipe]) -> None:
        self._recipes = recipes
        self.get_calls: list[tuple[str, object]] = []

    async def get(self, name, owner=None):
        self.get_calls.append((name, owner))
        if name not in self._recipes:
            raise KeyError(name)
        return self._recipes[name]

    async def save(self, recipe):  # pragma: no cover - unused here
        self._recipes[recipe.name] = recipe

    async def list(self, owner=None):  # pragma: no cover - unused here
        return list(self._recipes)

    async def delete(self, name, owner=None):  # pragma: no cover - unused here
        del self._recipes[name]


# ── Fixtures ─────────────────────────────────────────────────────────────


_TEST_TRANSFORM_CALLS = {"double": 0, "increment": 0}


def _double(inputs, params):
    _TEST_TRANSFORM_CALLS["double"] += 1
    return {"value": float(inputs["snapshots"]["value"].sum()) * 2}


def _increment(inputs, params):
    # 'doubled_step' is the PRIOR step's output_key: its stored data_model
    # value is that step's full dict result ({"value": ...}), never unwrapped.
    _TEST_TRANSFORM_CALLS["increment"] += 1
    return {"result": inputs["doubled_step"]["value"] + float(params.get("add", 1))}


# Module-level registration: same function objects every test run, so
# TransformerRegistry's idempotent-reregistration rule (same name + same
# func = no-op) holds even though this module is re-imported across the
# whole suite's collection.
transformer_registry.register(
    "test_double_step", _double, requires_columns={"snapshots": ["value"]}
)
transformer_registry.register("test_increment_step", _increment, requires_columns={})


@pytest.fixture(autouse=True)
def _register_test_transformers():
    """Reset the shared call counters before each test."""
    _TEST_TRANSFORM_CALLS["double"] = 0
    _TEST_TRANSFORM_CALLS["increment"] = 0
    yield _TEST_TRANSFORM_CALLS


@pytest.fixture
def frames():
    return {"snapshots": pd.DataFrame({"value": [1.0, 2.0, 3.0]})}


@pytest.fixture
def dataset_manager(frames):
    return _FakeDatasetManager(frames)


def _make_recipe(**overrides) -> InfographicRecipe:
    defaults = dict(
        name="test-recipe",
        title="Test Recipe",
        data_sources=[DataSourceSpec(dataset="snapshots", alias="snapshots")],
        transforms=[
            TransformStep(
                transformer="test_double_step",
                inputs=["snapshots"],
                output_key="doubled_step",
            ),
            TransformStep(
                transformer="test_increment_step",
                inputs=["doubled_step"],
                params={"add": 5},
                output_key="result",
            ),
        ],
        layout=LayoutSpec(
            component="Infographic",
            properties={"title": {"$bind": "/result"}, "sections": []},
        ),
        render=RenderSpec(profile="fake-recorder"),
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return InfographicRecipe(**defaults)


@pytest.fixture
def store(dataset_manager):
    recipe = _make_recipe()
    return _FakeStore({recipe.name: recipe})


@pytest.fixture
def runner(store, dataset_manager):
    return RecipeRunner(store, dataset_manager)


class TestRecipeRunner:
    async def test_runner_pipeline_order_and_binding(self, runner, dataset_manager, _register_test_transformers):
        artifact = await runner.run("test-recipe")

        assert isinstance(artifact, RenderedArtifact)
        assert _register_test_transformers == {"double": 1, "increment": 1}
        assert len(_RENDERED_ENVELOPES) == 1
        envelope = _RENDERED_ENVELOPES[0]
        # doubled = sum([1,2,3]) * 2 = 12.0; result = 12.0 + 5 = 17.0
        assert envelope.data_model["doubled_step"] == {"value": 12.0}
        assert envelope.data_model["result"] == {"result": 17.0}

    async def test_runner_unknown_transformer(self, dataset_manager):
        recipe = _make_recipe(
            transforms=[
                TransformStep(transformer="does-not-exist", inputs=["snapshots"], output_key="x")
            ],
            layout=LayoutSpec(component="Infographic", properties={"sections": []}),
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        with pytest.raises(RecipeRunException) as exc_info:
            await runner.run(recipe.name)
        assert exc_info.value.error.stage == "gate"
        assert "Unknown transformer" in exc_info.value.error.detail

    async def test_runner_dataset_not_registered(self, dataset_manager):
        recipe = _make_recipe(
            data_sources=[DataSourceSpec(dataset="missing-dataset", alias="snapshots")]
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        with pytest.raises(RecipeRunException) as exc_info:
            await runner.run(recipe.name)
        assert exc_info.value.error.stage == "data"
        assert "missing-dataset" in exc_info.value.error.detail

    async def test_gate_failure_aborts_before_transforms(self, dataset_manager, _register_test_transformers):
        # 'value' column absent -> gate must fail BEFORE test_double_step runs.
        bad_frames = {"snapshots": pd.DataFrame({"other_col": [1, 2, 3]})}
        bad_dm = _FakeDatasetManager(bad_frames)
        recipe = _make_recipe()
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, bad_dm)

        with pytest.raises(RecipeRunException) as exc_info:
            await runner.run(recipe.name)

        assert exc_info.value.error.stage == "gate"
        assert "value" in exc_info.value.error.missing_columns
        assert _register_test_transformers == {"double": 0, "increment": 0}
        assert _RENDERED_ENVELOPES == []

    async def test_bind_drift_detected_before_render(self, dataset_manager):
        recipe = _make_recipe(
            layout=LayoutSpec(
                component="Infographic",
                properties={"title": {"$bind": "/does_not_exist"}, "sections": []},
            )
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        with pytest.raises(RecipeRunException) as exc_info:
            await runner.run(recipe.name)

        assert exc_info.value.error.stage == "layout"
        assert "does_not_exist" in exc_info.value.error.detail
        assert _RENDERED_ENVELOPES == []

    async def test_dry_run_collects_all_errors(self, dataset_manager):
        recipe = _make_recipe(
            transforms=[
                TransformStep(transformer="does-not-exist", inputs=["snapshots"], output_key="x")
            ],
            layout=LayoutSpec(
                component="Infographic",
                properties={"title": {"$bind": "/undeclared_key"}, "sections": []},
            ),
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        errors = await runner.dry_run(recipe)

        stages = {e.stage for e in errors}
        assert "gate" in stages
        assert "layout" in stages
        assert len(errors) >= 2
        assert dataset_manager.fetch_calls == []  # dry_run never fetches data

    async def test_dry_run_catches_delivery_missing_recipients(self, dataset_manager):
        """A malformed render.delivery (missing 'recipients') should surface at
        dry_run/freeze time, not silently fail at the first scheduled run
        (delivery is best-effort — no exception would otherwise be raised)."""
        recipe = _make_recipe(render=RenderSpec(profile="fake-recorder", delivery={"provider": "email"}))
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        errors = await runner.dry_run(recipe)

        assert any(e.stage == "render" and "recipients" in e.detail for e in errors)

    async def test_pctx_propagated_and_reset(self, runner, dataset_manager):
        sentinel_pctx = object()
        assert _pctx_var.get() is None

        await runner.run("test-recipe", pctx=sentinel_pctx)

        assert dataset_manager.pctx_seen_during_fetch == [sentinel_pctx]
        assert _pctx_var.get() is None  # reset after the fetch step

    async def test_recipe_owner_scopes_the_store_lookup(self, store, dataset_manager):
        """`run(recipe_owner=...)` must reach `store.get(name, owner=...)` —
        omitting it silently makes owner-scoped recipes unrunnable (they were
        SAVED under a real owner, but replay always looked them up under
        owner=None)."""
        runner = RecipeRunner(store, dataset_manager)

        await runner.run("test-recipe", recipe_owner="alice")

        assert store.get_calls == [("test-recipe", "alice")]

    async def test_recipe_owner_defaults_to_none(self, store, dataset_manager):
        runner = RecipeRunner(store, dataset_manager)

        await runner.run("test-recipe")

        assert store.get_calls == [("test-recipe", None)]

    async def test_sql_param_substitution_rejects_injection_shaped_values(
        self, dataset_manager
    ):
        """A resolved param containing quotes/semicolons/comment markers must
        never be substituted into a DataSourceSpec.sql template — TableSource
        executes `sql` close to verbatim and documents itself as NOT a
        security boundary; recipe `params` overrides are a new, less-trusted
        input to that path."""
        recipe = _make_recipe(
            data_sources=[
                DataSourceSpec(
                    dataset="snapshots",
                    alias="snapshots",
                    sql="SELECT * FROM ledger WHERE division = '{division}'",
                )
            ],
            params=[RecipeParam(name="division", default="Sales")],
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        with pytest.raises(RecipeRunException) as exc_info:
            await runner.run(recipe.name, params={"division": "Sales'; DROP TABLE ledger; --"})

        assert exc_info.value.error.stage == "data"
        assert "unsafe" in exc_info.value.error.detail.lower()
        assert dataset_manager.fetch_calls == []  # aborted BEFORE any fetch

    async def test_sql_param_substitution_allows_benign_values(self, dataset_manager):
        recipe = _make_recipe(
            data_sources=[
                DataSourceSpec(
                    dataset="snapshots",
                    alias="snapshots",
                    sql="SELECT * FROM ledger WHERE division = '{division}'",
                )
            ],
            params=[RecipeParam(name="division", default="Sales")],
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        await runner.run(recipe.name, params={"division": "Ops"})

        assert dataset_manager.fetch_calls[0]["sql"] == "SELECT * FROM ledger WHERE division = 'Ops'"

    async def test_params_override_reaches_transform(self, dataset_manager):
        recipe = _make_recipe(
            transforms=[
                TransformStep(
                    transformer="test_double_step",
                    inputs=["snapshots"],
                    output_key="doubled_step",
                ),
                TransformStep(
                    transformer="test_increment_step",
                    inputs=["doubled_step"],
                    params={"add": "{bonus}"},
                    output_key="result",
                ),
            ],
            params=[],
        )
        # Recipe needs a declared param to accept the override; rebuild with one.
        from parrot.outputs.a2ui.recipes.models import RecipeParam

        recipe = recipe.model_copy(update={"params": [RecipeParam(name="bonus", default="1")]})
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        artifact = await runner.run(recipe.name, params={"bonus": "100"})
        assert isinstance(artifact, RenderedArtifact)
        envelope = _RENDERED_ENVELOPES[-1]
        # doubled = sum([1,2,3]) * 2 = 12.0; "add" param template "{bonus}" is
        # substituted to "100" (the override) before reaching the transformer.
        assert envelope.data_model["result"] == {"result": 12.0 + 100.0}

    async def test_unknown_renderer_profile_raises_import_error(self, dataset_manager):
        recipe = _make_recipe(render=RenderSpec(profile="totally-unknown-profile"))
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)

        with pytest.raises(ImportError, match="pip install"):
            await runner.run(recipe.name)

    async def test_delivery_skipped_when_not_configured(self, runner, monkeypatch):
        called = []

        async def _fake_deliver(*args, **kwargs):
            called.append((args, kwargs))
            return {}

        monkeypatch.setattr(runner_module, "deliver_artifact", _fake_deliver)
        await runner.run("test-recipe")
        assert called == []

    async def test_delivery_invoked_when_configured(self, dataset_manager, monkeypatch):
        recipe = _make_recipe(
            render=RenderSpec(
                profile="fake-recorder", delivery={"recipients": ["a@example.com"]}
            )
        )
        store = _FakeStore({recipe.name: recipe})
        owner = object()
        runner = RecipeRunner(store, dataset_manager, owner=owner)

        called = []

        async def _fake_deliver(owner_arg, artifact, **kwargs):
            called.append((owner_arg, artifact, kwargs))
            return {}

        monkeypatch.setattr(runner_module, "deliver_artifact", _fake_deliver)
        await runner.run(recipe.name)

        assert len(called) == 1
        called_owner, called_artifact, called_kwargs = called[0]
        assert called_owner is owner
        assert called_kwargs["recipients"] == ["a@example.com"]

    async def test_delivery_skipped_without_owner_logs_warning(self, dataset_manager, monkeypatch):
        recipe = _make_recipe(
            render=RenderSpec(
                profile="fake-recorder", delivery={"recipients": ["a@example.com"]}
            )
        )
        store = _FakeStore({recipe.name: recipe})
        runner = RecipeRunner(store, dataset_manager)  # no owner

        called = []

        async def _fake_deliver(*args, **kwargs):
            called.append((args, kwargs))
            return {}

        monkeypatch.setattr(runner_module, "deliver_artifact", _fake_deliver)
        await runner.run(recipe.name)
        assert called == []
