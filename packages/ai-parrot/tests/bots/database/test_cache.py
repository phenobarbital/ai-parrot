import warnings
from datetime import datetime, timedelta

import pytest

from parrot.bots.database.cache import (
    CacheManager,
    CachePartition,
    CachePartitionConfig,
)
from parrot.bots.database.models import Completeness, TableMetadata


def _make(
    schema: str,
    table: str,
    completeness: Completeness = Completeness.FULL,
    age_seconds: int = 0,
    columns: list | None = None,
) -> TableMetadata:
    return TableMetadata(
        schema=schema,
        tablename=table,
        table_type="BASE TABLE",
        full_name=f"{schema}.{table}",
        completeness=completeness,
        loaded_at=datetime.utcnow() - timedelta(seconds=age_seconds),
        columns=columns if columns is not None else [{"name": "id", "type": "int"}],
    )


@pytest.fixture
def partition() -> CachePartition:
    """In-memory CachePartition with no Redis or vector store."""
    return CachePartition(namespace="test", lru_maxsize=200, lru_ttl=1800)


class TestCachePartitionConfig:
    def test_default_ttl_by_completeness(self):
        cfg = CachePartitionConfig(namespace="x")
        assert cfg.ttl_by_completeness[int(Completeness.NAME_ONLY)] == 86400
        assert cfg.ttl_by_completeness[int(Completeness.WITH_COLUMNS)] == 21600
        assert cfg.ttl_by_completeness[int(Completeness.FULL)] == 3600


class TestCacheGet:
    async def test_get_respects_required_level(self, partition: CachePartition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.NAME_ONLY, columns=[])
        )
        assert await partition.get("s", "t", required=Completeness.FULL) is None
        assert await partition.get("s", "t", required=Completeness.NAME_ONLY) is not None

    async def test_get_respects_max_age(self, partition: CachePartition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.FULL, age_seconds=10_000)
        )
        # default max_age for FULL is 3600s; 10_000 > 3600
        assert await partition.get("s", "t", required=Completeness.FULL) is None

    async def test_get_returns_fresh_entry(self, partition: CachePartition):
        await partition.store_table_metadata(_make("s", "t", Completeness.FULL))
        result = await partition.get("s", "t", required=Completeness.FULL)
        assert result is not None
        assert result.tablename == "t"

    async def test_get_explicit_max_age_overrides_default(self, partition: CachePartition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.FULL, age_seconds=100)
        )
        # Explicit max_age of 50s — should reject the 100s-old entry
        assert await partition.get("s", "t", max_age=timedelta(seconds=50)) is None
        # Explicit max_age of 200s — should accept
        assert await partition.get("s", "t", max_age=timedelta(seconds=200)) is not None

    async def test_get_missing_returns_none(self, partition: CachePartition):
        assert await partition.get("nope", "nope") is None


class TestCacheSearch:
    async def test_search_sorts_by_score(self, partition: CachePartition):
        await partition.store_table_metadata(_make("altice", "store_inventory"))
        await partition.store_table_metadata(_make("altice", "store_groups"))
        await partition.store_table_metadata(_make("pokemon", "stores"))

        out = await partition.search(["altice", "pokemon"], "stores", limit=10)
        # Exact match "stores" must rank above "store_inventory"
        assert out[0].tablename == "stores"

    async def test_completeness_min_excludes_stubs(self, partition: CachePartition):
        await partition.store_table_metadata(
            _make("s", "t", Completeness.NAME_ONLY, columns=[])
        )
        out = await partition.search(["s"], "t", completeness_min=Completeness.WITH_COLUMNS)
        assert out == []

    async def test_search_returns_matching_tables(self, partition: CachePartition):
        await partition.store_table_metadata(_make("public", "customers"))
        await partition.store_table_metadata(_make("public", "orders"))
        out = await partition.search(["public"], "customers", limit=5)
        assert any(m.tablename == "customers" for m in out)


class TestCacheList:
    async def test_list_filters_by_completeness(self, partition: CachePartition):
        await partition.store_table_metadata(_make("s", "full_t", Completeness.FULL))
        await partition.store_table_metadata(
            _make("s", "stub_t", Completeness.NAME_ONLY, columns=[])
        )
        out = await partition.list(["s"], completeness_min=Completeness.WITH_COLUMNS)
        names = {m.tablename for m in out}
        assert "full_t" in names
        assert "stub_t" not in names

    async def test_list_all_schemas(self, partition: CachePartition):
        await partition.store_table_metadata(_make("s1", "t1"))
        await partition.store_table_metadata(_make("s2", "t2"))
        out = await partition.list(["s1", "s2"])
        assert len(out) == 2

    async def test_list_respects_limit(self, partition: CachePartition):
        for i in range(5):
            await partition.store_table_metadata(_make("s", f"t{i}"))
        out = await partition.list(["s"], limit=3)
        assert len(out) == 3


class TestPerCompletenessTTL:
    async def test_name_only_outlives_full_ttl(self, partition: CachePartition):
        """NAME_ONLY default TTL (24h) is longer than FULL (1h)."""
        meta = _make("s", "t", Completeness.NAME_ONLY, age_seconds=3700, columns=[])
        await partition.store_table_metadata(meta)
        # Past FULL TTL (3600s) but within NAME_ONLY TTL (86400s) — still served
        got = await partition.get("s", "t", required=Completeness.NAME_ONLY)
        assert got is not None

    async def test_full_entry_expires_after_ttl(self, partition: CachePartition):
        meta = _make("s", "t", Completeness.FULL, age_seconds=4000)
        await partition.store_table_metadata(meta)
        # 4000s > FULL TTL (3600s)
        assert await partition.get("s", "t", required=Completeness.FULL) is None


class TestDeprecation:
    async def test_get_table_metadata_warns(self, partition: CachePartition):
        await partition.store_table_metadata(_make("s", "t"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await partition.get_table_metadata("s", "t")
            assert any(issubclass(x.category, DeprecationWarning) for x in w)

    async def test_search_similar_tables_warns(self, partition: CachePartition):
        await partition.store_table_metadata(_make("s", "t"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await partition.search_similar_tables(["s"], "t")
            assert any(issubclass(x.category, DeprecationWarning) for x in w)

    async def test_get_table_metadata_still_works(self, partition: CachePartition):
        await partition.store_table_metadata(_make("s", "t"))
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = await partition.get_table_metadata("s", "t")
        assert result is not None


class _FakeStore:
    """Minimal stand-in for an AbstractStore with an async ``disconnect``."""

    def __init__(self) -> None:
        self.disconnected = False

    async def disconnect(self) -> None:
        self.disconnected = True


class TestCacheManagerClose:
    async def test_close_disposes_owned_vector_store(self):
        store = _FakeStore()
        manager = CacheManager(vector_store=store)
        await manager.close()
        assert store.disconnected is True
        # Reference dropped so the engine can be GC'd cleanly.
        assert manager.vector_store is None

    async def test_close_skips_unowned_vector_store(self):
        store = _FakeStore()
        manager = CacheManager(vector_store=store, owns_vector_store=False)
        await manager.close()
        assert store.disconnected is False
        assert manager.vector_store is store

    async def test_close_without_vector_store_is_noop(self):
        manager = CacheManager()
        await manager.close()  # must not raise

    async def test_close_swallows_disconnect_errors(self):
        class _Boom:
            async def disconnect(self):
                raise RuntimeError("boom")

        manager = CacheManager(vector_store=_Boom())
        await manager.close()  # error is logged, not raised
        assert manager.vector_store is None
