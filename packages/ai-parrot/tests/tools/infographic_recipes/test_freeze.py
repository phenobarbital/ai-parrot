"""Freeze-path tests for FEAT-324 Module 6
(`parrot.tools.infographic_recipes.freeze.freeze_session_envelope`)."""

import pytest

from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.recipes.models import RecipeRunError
from parrot.tools.infographic_recipes.freeze import (
    FreezeProvenanceError,
    FreezeValidationError,
    freeze_session_envelope,
)


class _FakeRunner:
    def __init__(self, errors=None):
        self._errors = errors or []
        self.dry_run_calls = []

    async def dry_run(self, recipe):
        self.dry_run_calls.append(recipe)
        return self._errors


def _envelope():
    return build_infographic(title="Test", sections=[{"heading": "s1"}])


class TestFreeze:
    async def test_freeze_normalizes_and_dry_runs(self):
        runner = _FakeRunner(errors=[])
        recipe = await freeze_session_envelope(
            _envelope(),
            dataset_names={"snapshots": "budget_ledger"},
            transform_steps=[
                {
                    "transformer": "division_breakdown",
                    "inputs": ["snapshots"],
                    "params": {},
                    "output_key": "division_breakdown",
                }
            ],
            name="test-recipe",
            title="Test Recipe",
            runner=runner,
            owner="user-1",
        )

        assert recipe.name == "test-recipe"
        assert recipe.owner == "user-1"
        assert len(recipe.data_sources) == 1
        assert recipe.data_sources[0].dataset == "budget_ledger"
        assert recipe.data_sources[0].alias == "snapshots"
        assert recipe.transforms[0].transformer == "division_breakdown"
        assert recipe.layout.component == "Infographic"
        assert len(runner.dry_run_calls) == 1

    async def test_freeze_rejects_dirty_dry_run_with_all_errors(self):
        errors = [
            RecipeRunError(recipe="test-recipe", stage="gate", detail="missing column"),
            RecipeRunError(recipe="test-recipe", stage="layout", detail="bad bind"),
        ]
        runner = _FakeRunner(errors=errors)

        with pytest.raises(FreezeValidationError) as exc_info:
            await freeze_session_envelope(
                _envelope(),
                dataset_names={"snapshots": "budget_ledger"},
                transform_steps=[
                    {
                        "transformer": "division_breakdown",
                        "inputs": ["snapshots"],
                        "output_key": "division_breakdown",
                    }
                ],
                name="test-recipe",
                title="Test Recipe",
                runner=runner,
            )
        assert len(exc_info.value.errors) == 2

    async def test_freeze_rejects_adhoc_provenance_no_datasets(self):
        runner = _FakeRunner()
        with pytest.raises(FreezeProvenanceError, match="dataset provenance"):
            await freeze_session_envelope(
                _envelope(),
                dataset_names={},
                transform_steps=[
                    {"transformer": "x", "inputs": [], "output_key": "y"}
                ],
                name="test-recipe",
                title="Test Recipe",
                runner=runner,
            )

    async def test_freeze_rejects_adhoc_provenance_no_transforms(self):
        runner = _FakeRunner()
        with pytest.raises(FreezeProvenanceError, match="transform-step provenance"):
            await freeze_session_envelope(
                _envelope(),
                dataset_names={"snapshots": "budget_ledger"},
                transform_steps=[],
                name="test-recipe",
                title="Test Recipe",
                runner=runner,
            )

    async def test_freeze_rejects_multi_component_envelope(self):
        runner = _FakeRunner()
        envelope = build_surface("Card", {"title": "A"}, surface_id="a")
        # Manually append a second component to violate the single-surface rule.
        second = build_surface("Card", {"title": "B"}, surface_id="b").components[0]
        envelope = envelope.model_copy(update={"components": [*envelope.components, second]})

        with pytest.raises(FreezeProvenanceError, match="single-component"):
            await freeze_session_envelope(
                envelope,
                dataset_names={"snapshots": "budget_ledger"},
                transform_steps=[
                    {"transformer": "x", "inputs": [], "output_key": "y"}
                ],
                name="test-recipe",
                title="Test Recipe",
                runner=runner,
            )
