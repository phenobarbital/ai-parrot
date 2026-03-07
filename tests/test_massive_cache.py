"""
Unit tests for MassiveCache layer.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.massive.cache import MassiveCache


@pytest.fixture
def mock_tool_cache():
    """Mock the underlying ToolCache."""
    with patch("parrot.tools.massive.cache.ToolCache") as mock_class:
        mock_instance = MagicMock()
        mock_instance.get = AsyncMock(return_value=None)
        mock_instance.set = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_instance._get_redis = AsyncMock()
        mock_instance._build_key = MagicMock(return_value="test_key")
        mock_class.return_value = mock_instance
        yield mock_instance


class TestMassiveCacheInit:
    """Tests for MassiveCache initialization."""

    def test_init_creates_tool_cache(self, mock_tool_cache):
        """Creates underlying ToolCache with correct prefix."""
        cache = MassiveCache()
        assert cache._cache is not None

    def test_init_with_custom_ttl(self, mock_tool_cache):
        """Custom default TTL is stored."""
        cache = MassiveCache(default_ttl=600)
        assert cache._default_ttl == 600


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_make_key_basic(self, mock_tool_cache):
        """Basic key generation."""
        cache = MassiveCache()
        key = cache._make_key("options_chain", underlying="AAPL")
        assert "massive" in key
        assert "options_chain" in key
        assert "underlying=AAPL" in key

    def test_make_key_multiple_params(self, mock_tool_cache):
        """Key with multiple parameters."""
        cache = MassiveCache()
        key = cache._make_key("options_chain", underlying="AAPL", limit=100, contract_type="call")
        assert "underlying=AAPL" in key
        assert "limit=100" in key
        assert "contract_type=call" in key

    def test_make_key_ignores_none(self, mock_tool_cache):
        """None parameters excluded from key."""
        cache = MassiveCache()
        key1 = cache._make_key("options_chain", underlying="AAPL", contract_type=None)
        key2 = cache._make_key("options_chain", underlying="AAPL")
        assert key1 == key2

    def test_make_key_sorted_params(self, mock_tool_cache):
        """Parameters are sorted for consistent keys."""
        cache = MassiveCache()
        key1 = cache._make_key("options_chain", underlying="AAPL", limit=100)
        key2 = cache._make_key("options_chain", limit=100, underlying="AAPL")
        assert key1 == key2

    def test_make_key_different_endpoints(self, mock_tool_cache):
        """Different endpoints produce different keys."""
        cache = MassiveCache()
        key1 = cache._make_key("options_chain", symbol="AAPL")
        key2 = cache._make_key("short_interest", symbol="AAPL")
        assert key1 != key2

    def test_make_key_different_params(self, mock_tool_cache):
        """Different params produce different keys."""
        cache = MassiveCache()
        key1 = cache._make_key("options_chain", underlying="AAPL", limit=100)
        key2 = cache._make_key("options_chain", underlying="AAPL", limit=200)
        assert key1 != key2


class TestTTLConfiguration:
    """Tests for per-endpoint TTL configuration."""

    def test_ttl_options_chain(self, mock_tool_cache):
        """Options chain TTL is 15 minutes."""
        cache = MassiveCache()
        assert cache.get_ttl("options_chain") == 900

    def test_ttl_short_interest(self, mock_tool_cache):
        """Short interest TTL is 12 hours."""
        cache = MassiveCache()
        assert cache.get_ttl("short_interest") == 43200

    def test_ttl_short_volume(self, mock_tool_cache):
        """Short volume TTL is 6 hours."""
        cache = MassiveCache()
        assert cache.get_ttl("short_volume") == 21600

    def test_ttl_earnings(self, mock_tool_cache):
        """Earnings TTL is 24 hours."""
        cache = MassiveCache()
        assert cache.get_ttl("earnings") == 86400

    def test_ttl_analyst_ratings(self, mock_tool_cache):
        """Analyst ratings TTL is 4 hours."""
        cache = MassiveCache()
        assert cache.get_ttl("analyst_ratings") == 14400

    def test_ttl_unknown_endpoint(self, mock_tool_cache):
        """Unknown endpoint uses default TTL."""
        cache = MassiveCache(default_ttl=600)
        assert cache.get_ttl("unknown_endpoint") == 600


class TestCacheGet:
    """Tests for cache.get() method."""

    @pytest.mark.asyncio
    async def test_get_cache_miss(self, mock_tool_cache):
        """Returns None on cache miss."""
        mock_tool_cache.get.return_value = None
        cache = MassiveCache()
        result = await cache.get("options_chain", underlying="AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cache_hit(self, mock_tool_cache):
        """Returns cached data on hit."""
        cached_data = {"underlying": "AAPL", "contracts": []}
        mock_tool_cache.get.return_value = cached_data
        cache = MassiveCache()
        result = await cache.get("options_chain", underlying="AAPL")
        assert result == cached_data

    @pytest.mark.asyncio
    async def test_get_filters_none_params(self, mock_tool_cache):
        """None parameters are filtered before calling ToolCache."""
        mock_tool_cache.get.return_value = None
        cache = MassiveCache()
        await cache.get("options_chain", underlying="AAPL", contract_type=None)

        mock_tool_cache.get.assert_called_once()
        call_kwargs = mock_tool_cache.get.call_args[1]
        assert "contract_type" not in call_kwargs


class TestCacheSet:
    """Tests for cache.set() method."""

    @pytest.mark.asyncio
    async def test_set_with_endpoint_ttl(self, mock_tool_cache):
        """Uses endpoint-specific TTL."""
        cache = MassiveCache()
        data = {"data": "test"}

        await cache.set("options_chain", data, underlying="AAPL")

        mock_tool_cache.set.assert_called_once()
        call_args = mock_tool_cache.set.call_args
        assert call_args.kwargs.get("ttl") == 900  # 15 min for options_chain

    @pytest.mark.asyncio
    async def test_set_different_endpoints_different_ttl(self, mock_tool_cache):
        """Different endpoints use different TTLs."""
        cache = MassiveCache()
        data = {"data": "test"}

        # Options chain
        await cache.set("options_chain", data, underlying="AAPL")
        call_args = mock_tool_cache.set.call_args
        assert call_args.kwargs.get("ttl") == 900

        mock_tool_cache.set.reset_mock()

        # Short interest
        await cache.set("short_interest", data, symbol="GME")
        call_args = mock_tool_cache.set.call_args
        assert call_args.kwargs.get("ttl") == 43200

    @pytest.mark.asyncio
    async def test_set_filters_none_params(self, mock_tool_cache):
        """None parameters are filtered before calling ToolCache."""
        cache = MassiveCache()
        data = {"data": "test"}

        await cache.set("options_chain", data, underlying="AAPL", contract_type=None)

        call_kwargs = mock_tool_cache.set.call_args[1]
        assert "contract_type" not in call_kwargs


class TestCacheInvalidate:
    """Tests for cache invalidation methods."""

    @pytest.mark.asyncio
    async def test_invalidate_single_entry(self, mock_tool_cache):
        """Invalidates a single cache entry."""
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 1
        mock_tool_cache._get_redis.return_value = mock_redis

        cache = MassiveCache()
        result = await cache.invalidate("options_chain", underlying="AAPL")

        assert result is True
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_returns_false_on_miss(self, mock_tool_cache):
        """Returns False when key doesn't exist."""
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 0
        mock_tool_cache._get_redis.return_value = mock_redis

        cache = MassiveCache()
        result = await cache.invalidate("options_chain", underlying="NONEXISTENT")

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_endpoint_scans_keys(self, mock_tool_cache):
        """invalidate_endpoint uses SCAN to find matching keys."""
        mock_redis = AsyncMock()
        # Simulate scan returning 3 keys
        async def mock_scan_iter(match=None, count=None):
            for key in ["key1", "key2", "key3"]:
                yield key
        mock_redis.scan_iter = mock_scan_iter
        mock_redis.delete = AsyncMock()
        mock_tool_cache._get_redis.return_value = mock_redis

        cache = MassiveCache()
        count = await cache.invalidate_endpoint("options_chain")

        assert count == 3
        assert mock_redis.delete.call_count == 3


class TestCacheClose:
    """Tests for cache close method."""

    @pytest.mark.asyncio
    async def test_close_closes_underlying_cache(self, mock_tool_cache):
        """Close delegates to underlying ToolCache."""
        cache = MassiveCache()
        await cache.close()
        mock_tool_cache.close.assert_called_once()
