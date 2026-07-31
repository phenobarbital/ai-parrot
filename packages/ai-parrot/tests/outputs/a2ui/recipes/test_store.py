"""Shared contract test suite for FEAT-324 Module 4 recipe stores
(`FileRecipeStore` + `DBRecipeStore`, both `AbstractRecipeStore`).

`DBRecipeStore()` with no `redis_url` degrades to its in-memory fallback
(`_use_redis` is False), which serves as the "fake connection" test double
for the Redis backend — mirroring how `SkillRegistry` degrades when Redis is
unavailable, without requiring a live Redis server in CI.
"""

from datetime import datetime, timezone

import pytest

from parrot.outputs.a2ui.recipes.models import InfographicRecipe, LayoutSpec
from parrot.outputs.a2ui.recipes.store import (
    DBRecipeStore,
    FileRecipeStore,
    RecipeNotFoundError,
    RecipeSchemaVersionError,
)


def _make_recipe(name: str = "budget-variance-daily", owner: str | None = None) -> InfographicRecipe:
    return InfographicRecipe(
        name=name,
        title="Daily Budget Variance",
        owner=owner,
        layout=LayoutSpec(component="Infographic", properties={}),
        updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # store.save() overwrites this
    )


@pytest.fixture(params=["file", "db"])
def store(request, tmp_path):
    if request.param == "file":
        return FileRecipeStore(tmp_path)
    return DBRecipeStore(redis_url=None)  # in-memory fallback (no live Redis needed)


class TestRecipeStoreContract:
    async def test_save_get_roundtrip(self, store):
        recipe = _make_recipe()
        await store.save(recipe)
        loaded = await store.get(recipe.name)
        assert loaded.name == recipe.name
        assert loaded.title == recipe.title

    async def test_save_bumps_updated_at(self, store):
        recipe = _make_recipe()
        before = datetime.now(timezone.utc)
        await store.save(recipe)
        loaded = await store.get(recipe.name)
        assert loaded.updated_at >= before
        assert loaded.updated_at != recipe.updated_at

    async def test_overwrite_bumps_updated_at_again(self, store):
        recipe = _make_recipe()
        await store.save(recipe)
        first = await store.get(recipe.name)

        await store.save(recipe)
        second = await store.get(recipe.name)

        assert second.updated_at >= first.updated_at
        listing = await store.list()
        assert len([r for r in listing if r["name"] == recipe.name]) == 1

    async def test_owner_scope_isolation(self, store):
        # Same recipe NAME, two different owner scopes: each owner's copy
        # must be independently readable, and a THIRD owner (who never
        # saved anything under this name) must see it as not found.
        shared = _make_recipe(owner=None)
        scoped = _make_recipe(owner="alice")
        await store.save(shared)
        await store.save(scoped)

        loaded_shared = await store.get(shared.name, owner=None)
        loaded_scoped = await store.get(scoped.name, owner="alice")
        assert loaded_shared.owner is None
        assert loaded_scoped.owner == "alice"

        with pytest.raises(RecipeNotFoundError):
            await store.get(scoped.name, owner="bob")

    async def test_missing_recipe_lists_available(self, store):
        recipe = _make_recipe()
        await store.save(recipe)

        with pytest.raises(RecipeNotFoundError) as exc_info:
            await store.get("does-not-exist")
        assert recipe.name in exc_info.value.available

    async def test_delete(self, store):
        recipe = _make_recipe()
        await store.save(recipe)
        await store.delete(recipe.name)

        with pytest.raises(RecipeNotFoundError):
            await store.get(recipe.name)

    async def test_delete_missing_raises(self, store):
        with pytest.raises(RecipeNotFoundError):
            await store.delete("does-not-exist")

    async def test_list_returns_lightweight_summaries(self, store):
        recipe = _make_recipe()
        await store.save(recipe)

        listing = await store.list()
        assert len(listing) == 1
        summary = listing[0]
        assert set(summary) == {"name", "title", "description", "owner", "updated_at"}
        assert summary["name"] == recipe.name


async def test_file_store_rejects_path_traversal(tmp_path):
    store = FileRecipeStore(tmp_path)
    recipe = _make_recipe(name="../../etc/passwd")
    with pytest.raises(ValueError, match="Invalid recipe name"):
        await store.save(recipe)


async def test_file_store_rejects_path_traversal_owner(tmp_path):
    store = FileRecipeStore(tmp_path)
    recipe = _make_recipe(owner="../escape")
    with pytest.raises(ValueError, match="Invalid owner"):
        await store.save(recipe)


async def test_file_store_writes_one_yaml_per_recipe(tmp_path):
    store = FileRecipeStore(tmp_path)
    recipe = _make_recipe()
    await store.save(recipe)
    assert (tmp_path / f"{recipe.name}.yaml").exists()


async def test_file_store_owner_scoped_subdirectory(tmp_path):
    store = FileRecipeStore(tmp_path)
    recipe = _make_recipe(owner="alice")
    await store.save(recipe)
    assert (tmp_path / "alice" / f"{recipe.name}.yaml").exists()


async def test_schema_version_mismatch_raises(tmp_path):
    store = FileRecipeStore(tmp_path)
    recipe = _make_recipe()
    await store.save(recipe)

    # Simulate a future/incompatible schema_version written to disk.
    path = tmp_path / f"{recipe.name}.yaml"
    text = path.read_text().replace("schema_version: 1", "schema_version: 2")
    path.write_text(text)

    with pytest.raises(RecipeSchemaVersionError, match="schema_version"):
        await store.get(recipe.name)


async def test_db_store_crud():
    store = DBRecipeStore(redis_url=None)
    recipe = _make_recipe()
    await store.save(recipe)
    loaded = await store.get(recipe.name)
    assert loaded.name == recipe.name

    listing = await store.list()
    assert any(r["name"] == recipe.name for r in listing)

    await store.delete(recipe.name)
    with pytest.raises(RecipeNotFoundError):
        await store.get(recipe.name)


class _FakeRedis:
    """Minimal fake standing in for `redis.asyncio.Redis` to exercise the
    REAL Redis code path (`_use_redis=True`) without a live server."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.mget_calls = 0
        self.get_calls = 0
        self.ping_calls = 0

    async def ping(self):
        self.ping_calls += 1
        return True

    async def set(self, key, value):
        self.data[key] = value

    async def get(self, key):
        self.get_calls += 1
        return self.data.get(key)

    async def mget(self, keys):
        self.mget_calls += 1
        return [self.data.get(k) for k in keys]

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def delete(self, key):
        return 1 if self.data.pop(key, None) is not None else 0

    async def srem(self, key, member):
        self.sets.get(key, set()).discard(member)


async def test_db_store_list_uses_single_mget_not_n_plus_one():
    """`list()` must batch-fetch via a single MGET, not one GET per recipe."""
    store = DBRecipeStore(redis_url=None)
    fake_redis = _FakeRedis()
    # Bypass configure()'s real connection attempt — inject the fake directly.
    store._use_redis = True
    store._redis = fake_redis
    store._configured = True

    for i in range(3):
        await store.save(_make_recipe(name=f"recipe-{i}"))

    fake_redis.get_calls = 0  # reset (save() doesn't call get, but be explicit)
    listing = await store.list()

    assert len(listing) == 3
    assert fake_redis.mget_calls == 1
    assert fake_redis.get_calls == 0  # no per-recipe GETs


async def test_db_store_configure_is_idempotent_under_concurrency():
    """Concurrent first-callers must only attempt ONE Redis connection."""
    import asyncio

    store = DBRecipeStore(redis_url="redis://fake:6379/0")
    store._use_redis = True  # pretend REDIS_AVAILABLE was True at construction

    connect_attempts = 0

    class _FakeRedisModule:
        @staticmethod
        def from_url(*args, **kwargs):
            nonlocal connect_attempts
            connect_attempts += 1
            return _FakeRedis()

    import parrot.outputs.a2ui.recipes.store as store_module

    original_redis = store_module.Redis
    store_module.Redis = _FakeRedisModule
    try:
        await asyncio.gather(*(store.configure() for _ in range(10)))
    finally:
        store_module.Redis = original_redis

    assert connect_attempts == 1
    assert store._configured is True
