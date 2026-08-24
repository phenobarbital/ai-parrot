"""Unit tests for InfographicAuthoringMixin.publish_recipe (FEAT-326, TASK-1885)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec, NarrativeSpec
from parrot.outputs.a2ui.recipes.store import FileRecipeStore
from parrot.outputs.a2ui.recipes.transformers import (
    infographic_transformer,
    transformer_registry,
)
from parrot.tools.infographic_sections import (
    GapReport,
    SectionDescriptor,
    SectionSpec,
)


class _AuthoringAgent(InfographicAuthoringMixin, PandasAgent):
    pass


# Register two transformers used by the "full coverage" descriptors. The
# registry is idempotent for the SAME function object, so re-import is safe.
@infographic_transformer("feat326_totals")
def _feat326_totals(inputs: dict, params: dict) -> dict:  # pragma: no cover - not executed here
    return {}


@infographic_transformer("feat326_breakdown")
def _feat326_breakdown(inputs: dict, params: dict) -> dict:  # pragma: no cover
    return {}


def _fake_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    return store


def _two_dataset_descriptor():
    """Two sections over DIFFERENT datasets, plus a chained third step.

    `feat326_breakdown` consumes the first step's `output_key` (`days`), the
    shape `narrative_facts` uses — `publish_recipe` must exclude it from
    `data_sources`, so a stray `dataset_sql` entry for it has nothing to
    attach to.
    """
    return SectionDescriptor(
        template="budget.html",
        mode="data-splice",
        sections=[
            SectionSpec(name="feat326_totals", target="/days", datasets=["proj", "other"],
                        shape="mapping"),
            SectionSpec(name="feat326_breakdown", target="/divs", datasets=["days"],
                        shape="records"),
        ],
    )


@pytest.fixture
def agent(tmp_path):
    return _AuthoringAgent(
        name="publisher",
        artifact_store=_fake_store(),
        recipe_store=FileRecipeStore(tmp_path),
    )


def _covered_descriptor():
    return SectionDescriptor(
        template="budget.html",
        mode="data-splice",
        sections=[
            SectionSpec(name="feat326_totals", target="/days", datasets=["proj"],
                        shape="mapping"),
            SectionSpec(name="feat326_breakdown", target="/divs", datasets=["proj"],
                        shape="records"),
        ],
    )


def _gap_descriptor():
    return SectionDescriptor(
        template="budget.html",
        mode="data-splice",
        sections=[
            SectionSpec(name="feat326_totals", target="/days", datasets=["proj"],
                        shape="mapping"),
            SectionSpec(name="unregistered_section", target="/x", datasets=["proj"],
                        shape="records"),
        ],
    )


class TestPublishRecipe:
    async def test_full_coverage_saves_recipe(self, agent):
        recipe = await agent.publish_recipe("daily", _covered_descriptor())
        assert isinstance(recipe, InfographicRecipe)
        # Persisted and retrievable.
        stored = await agent._require_recipe_store().get("daily")
        assert {s.transformer for s in stored.transforms} == {
            "feat326_totals", "feat326_breakdown"
        }

    async def test_recipe_carries_descriptor_and_delivery(self, agent):
        delivery = {"provider": "email", "recipients": ["a@b.com"]}
        recipe = await agent.publish_recipe(
            "daily2", _covered_descriptor(), delivery=delivery
        )
        assert recipe.section_descriptor is not None
        assert recipe.section_descriptor.template == "budget.html"
        assert recipe.render.delivery == delivery

    async def test_gap_report_blocks_save(self, agent):
        store = agent._require_recipe_store()
        store.save = AsyncMock(side_effect=AssertionError("must not save"))
        result = await agent.publish_recipe("gappy", _gap_descriptor())
        assert isinstance(result, GapReport)
        store.save.assert_not_called()

    async def test_gap_report_lists_proposed_names_and_source(self, agent):
        result = await agent.publish_recipe("gappy2", _gap_descriptor())
        assert isinstance(result, GapReport)
        assert result.covered == ["feat326_totals"]
        assert len(result.gaps) == 1
        gap = result.gaps[0]
        assert gap.section == "unregistered_section"
        assert gap.proposed_name == "unregistered_section"
        assert "@infographic_transformer" in gap.suggested_source
        assert "raise NotImplementedError" in gap.suggested_source

    async def test_name_collision_requires_overwrite(self, agent):
        await agent.publish_recipe("dup", _covered_descriptor())
        with pytest.raises(ValueError, match="already exists"):
            await agent.publish_recipe("dup", _covered_descriptor())
        # overwrite=True succeeds.
        recipe = await agent.publish_recipe(
            "dup", _covered_descriptor(), overwrite=True
        )
        assert isinstance(recipe, InfographicRecipe)

    def test_registry_read_only_transformers_present(self):
        # publication only READS the registry.
        assert transformer_registry.get("feat326_totals") is not None


_REPORT_LAYOUT = LayoutSpec(
    component="Report",
    properties={
        "title": "Budget Variance",
        "summary": {"$bind": "/narrative/headline", "optional": True},
        "sections": [{"heading": "Snapshot", "components": []}],
    },
)


class TestPublishRecipeLayout:
    """FEAT-420 Module 7: `descriptor.layout`/`descriptor.narrative` carry-through."""

    async def test_descriptor_layout_used_verbatim(self, agent):
        descriptor = _covered_descriptor().model_copy(update={"layout": _REPORT_LAYOUT})
        recipe = await agent.publish_recipe("r-layout", descriptor)
        assert isinstance(recipe, InfographicRecipe)
        assert recipe.layout == _REPORT_LAYOUT

    async def test_absent_layout_preserves_legacy_shape(self, agent):
        """Regression: identical to pre-feature behaviour."""
        recipe = await agent.publish_recipe("r-legacy", _covered_descriptor())
        assert isinstance(recipe, InfographicRecipe)
        assert recipe.layout.component == "Infographic"
        assert recipe.layout.properties == {"template": "budget.html"}

    async def test_narrative_carried_through(self, agent):
        descriptor = _covered_descriptor().model_copy(
            update={
                "layout": _REPORT_LAYOUT,
                "narrative": NarrativeSpec(
                    skill="budget-narrative", facts_key="narrative_facts"
                ),
            }
        )
        recipe = await agent.publish_recipe("r-narr", descriptor)
        assert isinstance(recipe, InfographicRecipe)
        assert recipe.narrative.skill == "budget-narrative"
        assert recipe.narrative.facts_key == "narrative_facts"

    async def test_narrative_absent_by_default(self, agent):
        recipe = await agent.publish_recipe("r-no-narr", _covered_descriptor())
        assert isinstance(recipe, InfographicRecipe)
        assert recipe.narrative is None

    async def test_gap_report_still_wins_over_layout(self, agent):
        """An unmapped section must still block the save, layout notwithstanding."""
        descriptor = _gap_descriptor().model_copy(update={"layout": _REPORT_LAYOUT})
        store = agent._require_recipe_store()
        store.save = AsyncMock(side_effect=AssertionError("must not save"))
        result = await agent.publish_recipe("r-gap", descriptor)
        assert isinstance(result, GapReport)
        store.save.assert_not_called()


class TestPublishRecipeDatasetSQL:
    """`descriptor.dataset_sql` → `DataSourceSpec.sql` carry-through.

    Without this, a recipe over a `TableSource` publishes fine but every
    replay aborts at the `data` stage: that source rejects any fetch with no
    explicit SQL (no `SELECT *` on a database table).
    """

    _SQL = "SELECT a, b FROM troc.t ORDER BY a"

    async def test_dataset_sql_lands_on_data_source(self, agent):
        descriptor = _covered_descriptor().model_copy(
            update={"dataset_sql": {"proj": self._SQL}}
        )
        recipe = await agent.publish_recipe("r-sql", descriptor)
        assert isinstance(recipe, InfographicRecipe)
        assert [ds.alias for ds in recipe.data_sources] == ["proj"]
        assert recipe.data_sources[0].sql == self._SQL

    async def test_absent_dataset_sql_leaves_sql_none(self, agent):
        """Regression: identical to pre-feature behaviour."""
        recipe = await agent.publish_recipe("r-nosql", _covered_descriptor())
        assert recipe.data_sources[0].sql is None

    async def test_sql_applied_only_to_its_own_alias(self, agent):
        descriptor = _two_dataset_descriptor().model_copy(
            update={"dataset_sql": {"proj": self._SQL}}
        )
        recipe = await agent.publish_recipe("r-sql-one", descriptor)
        by_alias = {ds.alias: ds for ds in recipe.data_sources}
        assert set(by_alias) == {"proj", "other"}
        assert by_alias["proj"].sql == self._SQL
        assert by_alias["other"].sql is None

    async def test_sql_for_a_chained_output_key_is_inert(self, agent):
        """A `dataset_sql` entry naming a prior step's output_key changes nothing."""
        descriptor = _two_dataset_descriptor().model_copy(
            update={"dataset_sql": {"days": self._SQL}}
        )
        recipe = await agent.publish_recipe("r-sql-chained", descriptor)
        assert "days" not in {ds.alias for ds in recipe.data_sources}
        assert all(ds.sql is None for ds in recipe.data_sources)

    async def test_sql_survives_the_store_round_trip(self, agent):
        """The runner reads `ds.sql` off the RELOADED recipe, not the returned one."""
        descriptor = _covered_descriptor().model_copy(
            update={"dataset_sql": {"proj": self._SQL}}
        )
        await agent.publish_recipe("r-sql-rt", descriptor)
        stored = await agent._require_recipe_store().get("r-sql-rt")
        assert stored.data_sources[0].sql == self._SQL
        assert stored.section_descriptor.dataset_sql == {"proj": self._SQL}
