"""Unit tests for DbSnippetStore — FEAT-459 / TASK-3165 (fake pool, no live DB)."""

from __future__ import annotations

from datetime import datetime

import pytest

from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource, SnippetStatus
from parrot_formdesigner.services.snippets.db_store import DbSnippetStore


class _FakePool:
    def __init__(self, row: dict | None = None, *, raise_on_fetch: bool = False) -> None:
        self._row = row
        self._raise_on_fetch = raise_on_fetch
        self.fetchrow_calls = 0

    async def fetchrow(self, query, *args):
        self.fetchrow_calls += 1
        if self._raise_on_fetch:
            raise ConnectionError("db unreachable")
        return self._row

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        return "OK"


def test_tier_cap_denies_brokered_by_default() -> None:
    store = DbSnippetStore(_FakePool())
    with pytest.raises(ValueError, match="capped at tier 2"):
        store.check_tier_cap("acme", CapabilityManifest(tier=CapabilityTier.BROKERED))


def test_tier_cap_allows_when_tenant_overridden() -> None:
    store = DbSnippetStore(_FakePool(), tier3_tier4_tenants=frozenset({"acme"}))
    store.check_tier_cap("acme", CapabilityManifest(tier=CapabilityTier.BROKERED))  # no raise


def test_tier_cap_allows_helpers_for_any_tenant() -> None:
    store = DbSnippetStore(_FakePool())
    store.check_tier_cap("any-tenant", CapabilityManifest(tier=CapabilityTier.HELPERS))  # no raise


async def test_db_store_read_through_cache() -> None:
    # Construct a fake row dict matching the migration's columns
    fake_row = {
        "status": "published",
        "version": 1,
        "approved_by": "admin@example.com",
        "approved_at": datetime.now(),
        "handler_ref": "x.onBeforeSubmit",
        "event": "onBeforeSubmit",
        "tenant": "acme",
        "manifest": {"tier": "helpers"},
        "python_source": "def handler(ctx): pass",
        "python_sha256": "abc123",
        "client_source": None,
        "client_sha256": None,
    }
    pool = _FakePool(row=fake_row)
    store = DbSnippetStore(pool)

    # First call should hit the pool
    result1 = await store.get_published(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert result1 is not None
    assert pool.fetchrow_calls == 1

    # Second call for the same key should use cache, not hit pool again
    result2 = await store.get_published(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert result2 is not None
    assert pool.fetchrow_calls == 1  # Still 1, not 2

    # Both results should be the same object (from cache)
    assert result1 is result2


async def test_resolve_current_fails_soft_on_storage_error() -> None:
    store = DbSnippetStore(_FakePool(raise_on_fetch=True))
    result = await store.resolve_current(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert result is None


async def test_resolve_current_returns_none_for_global_tenant() -> None:
    store = DbSnippetStore(_FakePool())
    result = await store.resolve_current(tenant=None, handler_ref="x.onBeforeSubmit")
    assert result is None


def test_invalidate_clears_cache_entry() -> None:
    # Create a fake SnippetBundle and prime the cache
    fake_bundle = SnippetBundle(
        source=SnippetSource.DB,
        status=SnippetStatus.PUBLISHED,
        version=1,
        approved_by="admin@example.com",
        approved_at=datetime.now(),
        handler_ref="x.onBeforeSubmit",
        event="onBeforeSubmit",
        tenant="acme",
        manifest=CapabilityManifest(tier=CapabilityTier.HELPERS),
        python_source="def handler(ctx): pass",
        python_sha256="abc123",
    )

    store = DbSnippetStore(_FakePool())
    cache_key = ("acme", "x.onBeforeSubmit")
    store._cache[cache_key] = fake_bundle

    # Verify the cache entry exists
    assert cache_key in store._cache

    # Invalidate
    store.invalidate(tenant="acme", handler_ref="x.onBeforeSubmit")

    # Verify it's gone
    assert cache_key not in store._cache
