"""Unit tests for InfographicAuthoringMixin.publish_recipe (FEAT-326, TASK-1885)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.outputs.a2ui.recipes.models import InfographicRecipe
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
