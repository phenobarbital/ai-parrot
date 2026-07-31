"""Recipe ``section_descriptor`` model + store round-trip (FEAT-326, TASK-1885)."""
from __future__ import annotations

from datetime import datetime, timezone

from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec
from parrot.outputs.a2ui.recipes.store import (
    FileRecipeStore,
    SUPPORTED_SCHEMA_VERSION,
)
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec


def _descriptor():
    return SectionDescriptor(
        template="budget.html",
        mode="data-splice",
        sections=[SectionSpec(name="day_totals", target="/days", shape="mapping")],
    )


def _recipe(**overrides):
    base = dict(
        name="r1",
        title="R1",
        layout=LayoutSpec(component="Infographic", properties={}),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return InfographicRecipe(**base)


class TestRecipeSchema:
    def test_section_descriptor_optional_default_none(self):
        recipe = _recipe()
        assert recipe.section_descriptor is None
        # Additive change must NOT bump the schema version.
        assert recipe.schema_version == SUPPORTED_SCHEMA_VERSION == 1

    async def test_roundtrip_through_file_store(self, tmp_path):
        store = FileRecipeStore(tmp_path)
        recipe = _recipe(name="withdesc", section_descriptor=_descriptor())
        await store.save(recipe)
        loaded = await store.get("withdesc")
        assert loaded.section_descriptor is not None
        assert loaded.section_descriptor.template == "budget.html"
        assert loaded.section_descriptor.mode == "data-splice"
        assert loaded.section_descriptor.sections[0].name == "day_totals"

    async def test_legacy_recipe_without_field_loads(self, tmp_path):
        # Write a YAML recipe that predates the section_descriptor field.
        store = FileRecipeStore(tmp_path)
        legacy = _recipe(name="legacy")
        yaml_text = legacy.to_yaml()
        assert "section_descriptor" in yaml_text  # dumped as null
        # Simulate a truly-legacy file: strip the field entirely.
        stripped = "\n".join(
            line for line in yaml_text.splitlines()
            if not line.startswith("section_descriptor")
        )
        path = tmp_path / "legacy.yaml"
        path.write_text(stripped, encoding="utf-8")
        loaded = await store.get("legacy")
        assert loaded.section_descriptor is None
