"""Tests for FEAT-470 TASK-2542 (`parrot.outputs.a2ui.recipes.migrate`)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from parrot.outputs.a2ui.builders import build_infographic
from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.recipes.migrate import (
    MigrationReport,
    migrate_layout,
    migrate_store,
)
from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec
from parrot.outputs.a2ui.recipes.store import FileRecipeStore

_REPO_ROOT = Path(__file__).resolve().parents[6]
_EXAMPLE_YAML = _REPO_ROOT / "examples" / "infographic_recipes" / "budget-variance-daily.yaml"


class TestMigrateLayout:
    def test_migrate_layout_promotes_top_level_props_and_bindings(self):
        v1_layout = {
            "component": "Infographic",
            "properties": {
                "title": "T",
                "sections": [
                    {
                        "heading": "S",
                        "text": {"$bind": "/narrative", "optional": True},
                        "components": [
                            {
                                "component": "KPICard",
                                "properties": {
                                    "label": "L",
                                    "value": {"$bind": "/result/value"},
                                },
                            }
                        ],
                    }
                ],
            },
        }

        v2_layout = migrate_layout(v1_layout, from_version=1)

        assert v2_layout["component"] == "Infographic"
        assert v2_layout["title"] == "T"
        assert "properties" not in v2_layout
        assert "id" not in v2_layout
        assert v2_layout["metadata"]["extensions"]["parrot_optional"] == ["/narrative"]

        section = v2_layout["sections"][0]
        assert section["text"] == {"path": "/narrative"}
        # Nested Infographic section-component descriptors keep their OWN
        # "properties" wrapper — that is the composite's own authored shape,
        # not the wire Component shape this outer layout mirrors.
        kpi = section["components"][0]
        assert kpi["properties"]["value"] == {"path": "/result/value"}

    def test_migrate_layout_v2_is_a_passthrough(self):
        v2_layout = {"component": "Infographic", "title": "T"}
        assert migrate_layout(v2_layout, from_version=2) == v2_layout
        # Returned value is a distinct copy, not the same object.
        assert migrate_layout(v2_layout, from_version=2) is not v2_layout

    @pytest.mark.parametrize("bad_version", [0, -1, 3, 99])
    def test_migrate_layout_rejects_out_of_range_version(self, bad_version):
        with pytest.raises(ValueError, match="schema_version"):
            migrate_layout({"component": "Infographic"}, from_version=bad_version)

    def test_migrate_layout_handles_layout_without_properties(self):
        """A v1 layout with no `properties` key at all (e.g. `LayoutSpec(component=...)`
        with nothing else declared) still migrates cleanly."""
        v2_layout = migrate_layout({"component": "Report"}, from_version=1)
        assert v2_layout == {"component": "Report"}

    def test_example_recipe_v1_migrates_to_validating_v2(self):
        """Acceptance criterion: the repo's v1 recipe YAML loads, and
        `migrate_layout` produces a v2 layout that validates with
        `validate_envelope`."""
        raw = yaml.safe_load(_EXAMPLE_YAML.read_text())
        # The canonical example is v2 as of this task; reconstruct its v1
        # ancestor shape (nested "properties" + legacy "$bind") to exercise
        # the migration path end-to-end against a genuine v1 recipe.
        v1_layout = {
            "component": "Infographic",
            "properties": {
                "title": raw["layout"]["title"],
                "subtitle": raw["layout"]["subtitle"],
                "sections": [
                    {
                        k: (
                            {"$bind": v["path"], "optional": True}
                            if k == "text"
                            else v
                        )
                        for k, v in section.items()
                    }
                    for section in raw["layout"]["sections"]
                ],
            },
        }

        v2_layout = migrate_layout(v1_layout, from_version=1)

        envelope = build_infographic(
            title=v2_layout["title"],
            sections=v2_layout["sections"],
            subtitle=v2_layout.get("subtitle"),
            data_model={},
        )
        validate_envelope(envelope)  # raises on any catalog/structure problem


def _v1_yaml_text(name: str) -> str:
    return f"""
schema_version: 1
name: {name}
title: Legacy {name}
owner: null
layout:
  component: Infographic
  properties:
    title: "Legacy Title {name}"
updated_at: "2020-01-01T00:00:00+00:00"
"""


class TestMigrateStore:
    async def test_migrate_store_reports_migrated_and_already_current(self, tmp_path):
        store = FileRecipeStore(tmp_path)
        (tmp_path / "legacy-a.yaml").write_text(_v1_yaml_text("legacy-a"))
        (tmp_path / "legacy-b.yaml").write_text(_v1_yaml_text("legacy-b"))
        current = InfographicRecipe(
            name="current-c",
            title="Current C",
            layout=LayoutSpec(component="Infographic", title="Already v2"),
            updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        await store.save(current)

        report = await migrate_store(store)

        assert isinstance(report, MigrationReport)
        assert report.dry_run is False
        assert sorted(report.migrated) == ["legacy-a", "legacy-b"]
        assert report.already_current == ["current-c"]
        assert report.errors == {}

        # Persisted to disk as v2.
        assert await store._raw_schema_version("legacy-a") == 2
        assert await store._raw_schema_version("legacy-b") == 2
        migrated = await store.get("legacy-a")
        assert migrated.layout.props["title"] == "Legacy Title legacy-a"

    async def test_migrate_store_idempotent_dry_run(self, tmp_path):
        store = FileRecipeStore(tmp_path)
        (tmp_path / "legacy-a.yaml").write_text(_v1_yaml_text("legacy-a"))

        dry_report = await migrate_store(store, dry_run=True)
        assert dry_report.dry_run is True
        assert dry_report.migrated == ["legacy-a"]
        # dry_run never writes — the file on disk is untouched.
        assert await store._raw_schema_version("legacy-a") == 1

        # Running dry_run again reports the exact same (idempotent) outcome.
        dry_report_again = await migrate_store(store, dry_run=True)
        assert dry_report_again.migrated == ["legacy-a"]
        assert await store._raw_schema_version("legacy-a") == 1

        # A real (non-dry) sweep now actually migrates it...
        real_report = await migrate_store(store)
        assert real_report.migrated == ["legacy-a"]
        assert await store._raw_schema_version("legacy-a") == 2

        # ...and a second real sweep is a no-op (idempotent: already current).
        second_report = await migrate_store(store)
        assert second_report.migrated == []
        assert second_report.already_current == ["legacy-a"]

    async def test_migrate_store_collects_errors_without_aborting(self, tmp_path):
        store = FileRecipeStore(tmp_path)
        (tmp_path / "legacy-a.yaml").write_text(_v1_yaml_text("legacy-a"))
        # A recipe whose on-disk schema_version is out of range: migrating it
        # must be reported as an error, not raise out of migrate_store and
        # abort the rest of the sweep.
        (tmp_path / "broken.yaml").write_text(_v1_yaml_text("broken").replace(
            "schema_version: 1", "schema_version: 99"
        ))

        report = await migrate_store(store)

        assert report.migrated == ["legacy-a"]
        assert "broken" in report.errors
        assert await store._raw_schema_version("legacy-a") == 2
