"""Unit tests for `RecipeRunner.run(include_envelope=...)` (FEAT-492, TASK-2701).

Minimal pipeline harness (fake in-memory recipe store + fake `DatasetManager`
+ fake renderer registered via `register_a2ui_renderer`), following the same
fixture shape as `tests/tools/infographic_recipes/test_runner.py` — kept
self-contained here rather than importing from that module, since this
task's scope is limited to the new `include_envelope` flag.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RenderSpec,
    TransformStep,
)
from parrot.outputs.a2ui.recipes.transformers import transformer_registry
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.tools.infographic_recipes.runner import RecipeRunner

# ── Fake renderer (registered once at import time) ─────────────────────────

_DELIVERED_ARTIFACTS: list = []


@register_a2ui_renderer(
    "fake-envelope-recorder",
    RendererCapabilities(interactive=True, supports_actions=False, supports_updates=False, output="text/html"),
)
class _FakeRenderer(AbstractA2UIRenderer):
    async def render(self, envelope, *, bake: bool = True) -> RenderedArtifact:
        return RenderedArtifact(
            artifact_id="fake-artifact-envelope-1",
            mime_type="text/html",
            content=b"<html></html>",
            filename="fake.html",
            title="Fake Render",
            surface="fake-envelope-recorder",
        )


@pytest.fixture(autouse=True)
def _clear_delivered_artifacts():
    _DELIVERED_ARTIFACTS.clear()
    yield
    _DELIVERED_ARTIFACTS.clear()


# ── Fake DatasetManager / recipe store ──────────────────────────────────────


class _FakeDatasetManager:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    async def fetch_dataset(self, name, sql=None, conditions=None, force_refresh=False):
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


class _FakeStore:
    def __init__(self, recipes: dict[str, InfographicRecipe]) -> None:
        self._recipes = recipes

    async def get(self, name, owner=None):
        if name not in self._recipes:
            raise KeyError(name)
        return self._recipes[name]

    async def save(self, recipe):  # pragma: no cover - unused here
        self._recipes[recipe.name] = recipe

    async def list(self, owner=None):  # pragma: no cover - unused here
        return list(self._recipes)

    async def delete(self, name, owner=None):  # pragma: no cover - unused here
        del self._recipes[name]


def _passthrough(inputs, params):
    return {"value": float(inputs["snapshots"]["value"].sum())}


transformer_registry.register("test_envelope_passthrough", _passthrough, requires_columns={"snapshots": ["value"]})


def _make_recipe(**overrides) -> InfographicRecipe:
    defaults = {
        "name": "test-envelope-recipe",
        "title": "Test Envelope Recipe",
        "data_sources": [DataSourceSpec(dataset="snapshots", alias="snapshots")],
        "transforms": [
            TransformStep(
                transformer="test_envelope_passthrough",
                inputs=["snapshots"],
                output_key="total",
            ),
        ],
        "layout": LayoutSpec(component="Infographic", title={"path": "/total"}, sections=[]),
        "render": RenderSpec(profile="fake-envelope-recorder"),
        "updated_at": datetime(2026, 7, 22, tzinfo=UTC),
    }
    defaults.update(overrides)
    return InfographicRecipe(**defaults)


@pytest.fixture
def dataset_manager():
    return _FakeDatasetManager({"snapshots": pd.DataFrame({"value": [1.0, 2.0, 3.0]})})


@pytest.fixture
def store():
    recipe = _make_recipe()
    return _FakeStore({recipe.name: recipe})


@pytest.fixture
def runner(store, dataset_manager):
    return RecipeRunner(store, dataset_manager)


class TestIncludeEnvelope:
    async def test_include_envelope_attaches_valid_dump(self, runner):
        artifact = await runner.run("test-envelope-recipe", include_envelope=True)

        assert "source_envelope" in artifact.metadata
        dump = artifact.metadata["source_envelope"]
        assert dump["surfaceId"] == "test-envelope-recipe-infographic"
        assert dump["dataModel"]["total"] == {"value": 6.0}

    async def test_default_run_has_no_source_envelope_key(self, runner):
        artifact = await runner.run("test-envelope-recipe")

        assert "source_envelope" not in artifact.metadata

    async def test_envelope_dump_rehydrates_via_create_surface(self, runner):
        artifact = await runner.run("test-envelope-recipe", include_envelope=True)

        dump = artifact.metadata["source_envelope"]
        rehydrated = CreateSurface.model_validate(dump)
        assert rehydrated.surface_id == "test-envelope-recipe-infographic"

    async def test_delivery_receives_artifact_with_envelope_key(self, runner, monkeypatch):
        seen: dict = {}

        original_deliver = runner._deliver_best_effort

        async def _spy_deliver(recipe, artifact):
            seen["metadata"] = dict(artifact.metadata)
            await original_deliver(recipe, artifact)

        monkeypatch.setattr(runner, "_deliver_best_effort", _spy_deliver)

        await runner.run("test-envelope-recipe", include_envelope=True)

        assert "source_envelope" in seen["metadata"]
