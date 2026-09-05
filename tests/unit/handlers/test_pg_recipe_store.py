"""Unit tests for ``PgRecipeStore`` (FEAT-528 TASK-2870).

Runs against the scratch Postgres fixture (``NAVIGATOR_PG_DSN``); skipped
when the env var is not set. Must not require Redis and must not touch
``navigator.ui_surfaces``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from parrot.handlers.models.recipes import PgRecipeStore
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    TransformStep,
)
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError, RecipeSchemaVersionError

pytestmark = pytest.mark.integration


@pytest.fixture
def recipe() -> InfographicRecipe:
    """A minimal schema_version=2 recipe: one data source, one transform."""
    return InfographicRecipe(
        name="test-recipe-2870",
        title="Test Recipe",
        description="A minimal recipe for PgRecipeStore tests.",
        owner=None,
        data_sources=[DataSourceSpec(dataset="ds1", alias="frame1")],
        transforms=[TransformStep(transformer="day_totals", inputs=["frame1"], output_key="totals")],
        layout=LayoutSpec(component="Infographic"),
        updated_at=datetime.now(UTC),
    )


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


async def test_pg_recipe_store_roundtrip(pg_store, recipe):
    await pg_store.save(recipe)
    loaded = await pg_store.get(recipe.name)
    assert loaded.name == recipe.name
    assert loaded.title == recipe.title
    assert loaded.data_sources == recipe.data_sources
    assert loaded.transforms == recipe.transforms


async def test_pg_recipe_store_upsert_bumps_updated_at(pg_store, recipe):
    await pg_store.save(recipe)
    first = await pg_store.get(recipe.name)

    updated_recipe = recipe.model_copy(update={"title": "Updated Title"})
    await pg_store.save(updated_recipe)
    second = await pg_store.get(recipe.name)

    assert second.title == "Updated Title"
    assert second.updated_at >= first.updated_at

    rows = await pg_store.list()
    matching = [r for r in rows if r["name"] == recipe.name]
    assert len(matching) == 1


async def test_pg_recipe_store_owner_scoping(pg_store, recipe):
    recipe_a = recipe.model_copy(update={"owner": "owner-a"})
    recipe_b = recipe.model_copy(update={"owner": "owner-b"})
    await pg_store.save(recipe_a)
    await pg_store.save(recipe_b)

    loaded_a = await pg_store.get(recipe.name, owner="owner-a")
    loaded_b = await pg_store.get(recipe.name, owner="owner-b")
    assert loaded_a.owner == "owner-a"
    assert loaded_b.owner == "owner-b"

    listed_a = await pg_store.list(owner="owner-a")
    assert {r["name"] for r in listed_a} == {recipe.name}

    # owner=None maps to '' consistently — no collision with scoped owners.
    with pytest.raises(RecipeNotFoundError):
        await pg_store.get(recipe.name, owner=None)


async def test_pg_recipe_store_get_missing_raises(pg_store):
    with pytest.raises(RecipeNotFoundError):
        await pg_store.get("nope")


async def test_pg_recipe_store_delete_missing_raises(pg_store):
    with pytest.raises(RecipeNotFoundError):
        await pg_store.delete("nope")


async def test_pg_recipe_store_list_summaries(pg_store, recipe):
    await pg_store.save(recipe)
    summaries = await pg_store.list()
    assert len(summaries) == 1
    summary = summaries[0]
    assert set(summary.keys()) == {"name", "title", "description", "owner", "updated_at"}
    assert summary["name"] == recipe.name
    assert summary["title"] == recipe.title


async def test_pg_recipe_store_schema_version_gate(pg_store, recipe):
    # get() derives the gated version from the JSONB `recipe` payload itself
    # (spec: `_load_and_migrate(row["recipe"], ...)`), not the denormalised
    # `schema_version` column — mutate the embedded value to exercise the gate.
    await pg_store.save(recipe)
    db = pg_store._get_db()
    async with await db.connection() as conn:
        await conn.execute(
            f"UPDATE {pg_store.schema}.infographic_recipes "
            "SET recipe = jsonb_set(recipe, '{schema_version}', '99') "
            "WHERE name = $1 AND owner = $2",
            recipe.name,
            "",
        )
    with pytest.raises(RecipeSchemaVersionError):
        await pg_store.get(recipe.name)

    async with await db.connection() as conn:
        await conn.execute(
            f"UPDATE {pg_store.schema}.infographic_recipes "
            "SET recipe = jsonb_set(recipe, '{schema_version}', '1') "
            "WHERE name = $1 AND owner = $2",
            recipe.name,
            "",
        )
    loaded = await pg_store.get(recipe.name)
    assert loaded.name == recipe.name


async def test_pg_recipe_store_ensure_schema_idempotent(pg_store):
    # pg_store fixture already called ensure_schema() once; call again.
    await pg_store.ensure_schema()
    assert pg_store._schema_ensured is True


def test_bad_schema_name_rejected():
    with pytest.raises(ValueError):
        PgRecipeStore("postgres://x", schema="navigator; DROP TABLE")
