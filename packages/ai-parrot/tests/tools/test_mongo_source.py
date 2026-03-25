"""
Unit tests for MongoSource DataSource subclass.

Tests cover:
- prefetch_schema() — calls find_one and infers types, excludes _id
- fetch(filter, projection) — queries collection with filter and projection
- fetch() without filter raises ValueError (required_filter=True default)
- fetch() without projection raises ValueError
- cache_key format
- describe() includes collection and database name
"""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.dataset_manager.sources.mongo import MongoSource, _infer_mongo_types


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_mongo_conn():
    """Mock asyncdb mongo connection."""
    conn = AsyncMock()
    conn.find_one = AsyncMock(return_value={
        "_id": "abc123",
        "order_id": "123",
        "amount": 99.99,
        "status": "shipped",
    })
    conn.query = AsyncMock(return_value=[
        {"order_id": "123", "amount": 99.99, "status": "shipped"},
        {"order_id": "456", "amount": 49.99, "status": "pending"},
    ])
    return conn


@pytest.fixture
def mock_mongo_driver(mock_mongo_conn):
    """Mock asyncdb mongo driver that returns mock_mongo_conn."""
    driver = MagicMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_mongo_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    driver.connection = AsyncMock(return_value=cm)
    return driver


@pytest.fixture
def mongo_source():
    """MongoSource instance for testing."""
    return MongoSource(
        collection="orders",
        name="orders",
        database="mydb",
        dsn="mongodb://localhost:27017",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestInferMongoTypes:
    def test_excludes_id_field(self):
        """_infer_mongo_types excludes _id field."""
        doc = {"_id": "abc", "order_id": "123", "amount": 99.99}
        result = _infer_mongo_types(doc)
        assert "_id" not in result
        assert "order_id" in result

    def test_infers_string_type(self):
        """_infer_mongo_types infers str type."""
        doc = {"name": "Alice"}
        result = _infer_mongo_types(doc)
        assert result["name"] == "str"

    def test_infers_float_type(self):
        """_infer_mongo_types infers float type."""
        doc = {"amount": 99.99}
        result = _infer_mongo_types(doc)
        assert result["amount"] == "float"

    def test_infers_int_type(self):
        """_infer_mongo_types infers int type."""
        doc = {"count": 42}
        result = _infer_mongo_types(doc)
        assert result["count"] == "int"


class TestMongoSourceCacheKey:
    def test_cache_key_format(self, mongo_source):
        """cache_key format: mongo:{database}:{collection}."""
        assert mongo_source.cache_key == "mongo:mydb:orders"

    def test_cache_key_different_db_and_collection(self):
        source = MongoSource(
            collection="users",
            name="users",
            database="proddb",
        )
        assert source.cache_key == "mongo:proddb:users"


class TestMongoSourceDescribe:
    def test_describe_includes_collection(self, mongo_source):
        """describe() includes collection name."""
        desc = mongo_source.describe()
        assert "orders" in desc

    def test_describe_includes_database(self, mongo_source):
        """describe() includes database name."""
        desc = mongo_source.describe()
        assert "mydb" in desc

    def test_describe_mentions_filter_requirement(self, mongo_source):
        """describe() mentions filter requirement."""
        desc = mongo_source.describe()
        assert "filter" in desc.lower()

    def test_describe_includes_field_count_after_prefetch(self, mongo_source):
        """describe() shows field count after schema is set."""
        mongo_source._schema = {"order_id": "str", "amount": "float"}
        desc = mongo_source.describe()
        assert "2 fields" in desc


class TestMongoSourcePrefetchSchema:
    @pytest.mark.asyncio
    async def test_prefetch_schema_excludes_id(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """prefetch_schema calls find_one and excludes _id field."""
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.prefetch_schema()

        assert "_id" not in result
        assert "order_id" in result
        assert "amount" in result
        assert "status" in result

    @pytest.mark.asyncio
    async def test_prefetch_schema_infers_types(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """prefetch_schema infers Python type names from document."""
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.prefetch_schema()

        assert result["order_id"] == "str"
        assert result["amount"] == "float"
        assert result["status"] == "str"

    @pytest.mark.asyncio
    async def test_prefetch_schema_stores_in_schema(
        self, mongo_source, mock_mongo_driver
    ):
        """prefetch_schema stores result in self._schema."""
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            await mongo_source.prefetch_schema()

        assert len(mongo_source._schema) == 3  # order_id, amount, status (no _id)

    @pytest.mark.asyncio
    async def test_prefetch_schema_empty_collection(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """prefetch_schema handles empty collection (find_one returns None)."""
        mock_mongo_conn.find_one = AsyncMock(return_value=None)
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.prefetch_schema()

        assert result == {}
        assert mongo_source._schema == {}

    @pytest.mark.asyncio
    async def test_prefetch_schema_raises_on_driver_error(
        self, mongo_source
    ):
        """prefetch_schema raises RuntimeError when driver fails."""
        failing_driver = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=ConnectionError("Cannot connect"))
        cm.__aexit__ = AsyncMock(return_value=False)
        failing_driver.connection = AsyncMock(return_value=cm)

        with patch.object(mongo_source, "_get_driver", return_value=failing_driver):
            with pytest.raises(RuntimeError, match="failed to prefetch schema"):
                await mongo_source.prefetch_schema()


class TestMongoSourceFetch:
    @pytest.mark.asyncio
    async def test_fetch_with_filter_and_projection(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """fetch(filter={...}, projection={...}) queries collection and returns DataFrame."""
        filter_dict = {"status": "shipped"}
        projection = {"order_id": 1, "amount": 1, "_id": 0}

        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.fetch(filter=filter_dict, projection=projection)

        mock_mongo_conn.query.assert_called_once_with(
            filter_dict,
            collection="orders",
            database="mydb",
            projection=projection,
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_no_filter_raises(self, mongo_source):
        """fetch() without filter raises ValueError (required_filter=True)."""
        with pytest.raises(ValueError, match="requires a 'filter' parameter"):
            await mongo_source.fetch(projection={"order_id": 1})

    @pytest.mark.asyncio
    async def test_fetch_empty_filter_raises(self, mongo_source):
        """fetch(filter={}) raises ValueError — empty filter not allowed."""
        with pytest.raises(ValueError, match="requires a 'filter' parameter"):
            await mongo_source.fetch(filter={}, projection={"order_id": 1})

    @pytest.mark.asyncio
    async def test_fetch_no_projection_raises(self, mongo_source):
        """fetch(filter={...}) without projection raises ValueError."""
        with pytest.raises(ValueError, match="requires a 'projection' parameter"):
            await mongo_source.fetch(filter={"status": "active"})

    @pytest.mark.asyncio
    async def test_fetch_no_filter_allowed_when_required_filter_false(
        self, mock_mongo_driver, mock_mongo_conn
    ):
        """fetch() without filter is allowed when required_filter=False."""
        source = MongoSource(
            collection="orders",
            name="orders",
            database="mydb",
            required_filter=False,
        )
        with patch.object(source, "_get_driver", return_value=mock_mongo_driver):
            result = await source.fetch(projection={"order_id": 1})

        assert isinstance(result, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_df_on_none(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """fetch() returns empty DataFrame when query returns None."""
        mock_mongo_conn.query = AsyncMock(return_value=None)
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.fetch(
                filter={"status": "active"},
                projection={"order_id": 1},
            )

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_df_on_empty_list(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """fetch() returns empty DataFrame when query returns empty list."""
        mock_mongo_conn.query = AsyncMock(return_value=[])
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.fetch(
                filter={"status": "active"},
                projection={"order_id": 1},
            )

        assert isinstance(result, pd.DataFrame)
        assert result.empty

    @pytest.mark.asyncio
    async def test_fetch_excludes_id_from_results(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """fetch() removes _id field from result documents."""
        mock_mongo_conn.query = AsyncMock(return_value=[
            {"_id": "abc", "order_id": "123", "amount": 99.99},
        ])
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.fetch(
                filter={"status": "shipped"},
                projection={"order_id": 1, "amount": 1, "_id": 0},
            )

        assert "_id" not in result.columns
        assert "order_id" in result.columns

    @pytest.mark.asyncio
    async def test_fetch_handles_dataframe_result(
        self, mongo_source, mock_mongo_driver, mock_mongo_conn
    ):
        """fetch() handles when driver returns a DataFrame directly."""
        mock_mongo_conn.query = AsyncMock(
            return_value=pd.DataFrame({"order_id": ["123"], "amount": [99.99]})
        )
        with patch.object(mongo_source, "_get_driver", return_value=mock_mongo_driver):
            result = await mongo_source.fetch(
                filter={"status": "shipped"},
                projection={"order_id": 1, "amount": 1},
            )

        assert isinstance(result, pd.DataFrame)
        assert "order_id" in result.columns
