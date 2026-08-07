"""Round-trip and validation tests for FEAT-324 Module 1 recipe models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.recipes import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    NarrativeSpec,
    RecipeParam,
    RenderSpec,
    ScheduleSpec,
    TransformStep,
)


def _sample_recipe() -> InfographicRecipe:
    return InfographicRecipe(
        name="budget-variance-daily",
        title="Daily Budget Variance",
        description="Reproduces the reference budget-variance dashboard.",
        owner="finance-team",
        params=[RecipeParam(name="month", default="current_month")],
        data_sources=[
            DataSourceSpec(
                dataset="ledger",
                alias="ledger_df",
                sql="SELECT * FROM ledger WHERE month = '{month}'",
            )
        ],
        transforms=[
            TransformStep(
                transformer="division_breakdown",
                inputs=["ledger_df"],
                params={},
                output_key="division_breakdown",
            )
        ],
        layout=LayoutSpec(
            component="Infographic",
            properties={"title": {"$bind": "/title"}},
        ),
        render=RenderSpec(profile="interactive-html"),
        schedule=ScheduleSpec(principal="svc-budget-bot"),
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )


def test_recipe_roundtrip_json_yaml():
    recipe = _sample_recipe()

    json_text = recipe.model_dump_json()
    from_json = InfographicRecipe.model_validate_json(json_text)
    assert from_json == recipe

    yaml_text = recipe.to_yaml()
    from_yaml = InfographicRecipe.from_yaml(yaml_text)
    assert from_yaml == recipe


def test_recipe_defaults():
    recipe = InfographicRecipe(
        name="minimal",
        title="Minimal Recipe",
        layout=LayoutSpec(component="Infographic", properties={}),
        updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    assert recipe.schema_version == 1
    assert recipe.params == []
    assert recipe.data_sources == []
    assert recipe.transforms == []
    assert recipe.schedule is None
    assert recipe.render.profile == "interactive-html"


def test_recipe_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        InfographicRecipe(
            name="bad",
            title="Bad Recipe",
            layout=LayoutSpec(component="Infographic", properties={}),
            updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            not_a_field="oops",
        )


class TestNarrativeSpecAdditive:
    """FEAT-420 Module 3: `NarrativeSpec` + `InfographicRecipe.narrative`."""

    def test_recipe_without_narrative_still_validates(self):
        r = InfographicRecipe(
            name="n",
            title="T",
            layout=LayoutSpec(component="Report"),
            updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        assert r.narrative is None
        assert r.schema_version == 1

    def test_recipe_with_narrative_roundtrips(self):
        r = InfographicRecipe(
            name="n",
            title="T",
            layout=LayoutSpec(component="Report"),
            updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            narrative=NarrativeSpec(skill="budget-narrative", facts_key="narrative_facts"),
        )
        again = InfographicRecipe.model_validate(r.model_dump())
        assert again.narrative.skill == "budget-narrative"
        assert again.narrative.facts_key == "narrative_facts"
        assert again.narrative.output_key == "narrative"
        assert again.schema_version == 1

    def test_narrative_spec_stores_no_code(self):
        """G1: only a skill name — no prompt/template/model fields."""
        forbidden = {"prompt", "template", "source", "code", "llm", "model", "provider"}
        assert not (forbidden & set(NarrativeSpec.model_fields))

    def test_existing_example_recipe_still_loads(self):
        """Regression: the pre-feature YAML example must keep validating."""
        from pathlib import Path

        y = Path("examples/infographic_recipes/budget-variance-daily.yaml").read_text()
        assert InfographicRecipe.from_yaml(y).schema_version == 1
