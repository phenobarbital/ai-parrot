"""Unit tests for FEAT-499 TASK-2753: builders carry `LayoutSpec.metadata`
onto the root wire `Component`, and `RecipeRunner._assemble_envelope_or_raise`
threads `recipe.layout.metadata` into both builder branches.
"""

import pytest
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.models import ComponentMetadata
from parrot.outputs.a2ui.recipes.models import LayoutSpec
from parrot.tools.infographic_recipes.runner import RecipeRunner


@pytest.fixture
def optional_metadata():
    return ComponentMetadata(extensions={"parrot_optional": ["/narrative"]})


class TestBuildersCarryMetadata:
    def test_build_surface_sets_metadata_on_root(self, optional_metadata):
        env = build_surface("Report", {"title": "t"}, surface_id="s", metadata=optional_metadata)
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_build_infographic_sets_metadata_on_root(self, optional_metadata):
        env = build_infographic(title="t", sections=[], surface_id="s", metadata=optional_metadata)
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_default_emits_no_metadata(self):
        env = build_surface("Report", {"title": "t"}, surface_id="s")
        assert env.components[0].metadata is None

    def test_default_infographic_emits_no_metadata(self):
        env = build_infographic(title="t", sections=[], surface_id="s")
        assert env.components[0].metadata is None

    def test_explicit_metadata_wins_over_properties_key(self, optional_metadata):
        env = build_surface(
            "Report",
            {"title": "t", "metadata": {"extensions": {"parrot_optional": ["/ignored"]}}},
            surface_id="s",
            metadata=optional_metadata,
        )
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_properties_metadata_key_passes_through_when_no_explicit_metadata(self):
        """Existing hand-authored callers that pass a `metadata` key inside
        `properties` (and no explicit `metadata=` kwarg) keep working
        untouched — this is the pre-existing behaviour, unaffected by the
        new parameter."""
        env = build_surface(
            "Report",
            {"title": "t", "metadata": {"extensions": {"parrot_optional": ["/narrative"]}}},
            surface_id="s",
        )
        assert env.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]


class TestRunnerThreadsLayoutMetadata:
    @pytest.fixture
    def runner(self):
        return RecipeRunner(store=None, dataset_manager=None)

    def test_infographic_branch_threads_metadata(self, runner, optional_metadata):
        recipe = _make_recipe(
            layout=LayoutSpec(component="Infographic", title="t", sections=[], metadata=optional_metadata)
        )
        envelope = runner._assemble_envelope_or_raise(recipe, {})
        assert envelope.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_generic_branch_threads_metadata(self, runner, optional_metadata):
        recipe = _make_recipe(layout=LayoutSpec(component="Report", title="t", metadata=optional_metadata))
        envelope = runner._assemble_envelope_or_raise(recipe, {})
        assert envelope.components[0].metadata.extensions.root["parrot_optional"] == ["/narrative"]

    def test_infographic_branch_no_metadata_unaffected(self, runner):
        recipe = _make_recipe(layout=LayoutSpec(component="Infographic", title="t", sections=[]))
        envelope = runner._assemble_envelope_or_raise(recipe, {})
        assert envelope.components[0].metadata is None

    def test_generic_branch_no_metadata_unaffected(self, runner):
        recipe = _make_recipe(layout=LayoutSpec(component="Report", title="t"))
        envelope = runner._assemble_envelope_or_raise(recipe, {})
        assert envelope.components[0].metadata is None


def _make_recipe(*, layout: LayoutSpec):
    from datetime import UTC, datetime

    from parrot.outputs.a2ui.recipes.models import InfographicRecipe, RenderSpec

    return InfographicRecipe(
        name="test-metadata-recipe",
        title="Test Metadata Recipe",
        data_sources=[],
        transforms=[],
        layout=layout,
        render=RenderSpec(profile="interactive-html"),
        updated_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
