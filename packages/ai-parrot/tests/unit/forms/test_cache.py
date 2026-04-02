"""Unit tests for FormCache."""

import asyncio
import pytest
from parrot.forms import (
    FieldType,
    FormCache,
    FormField,
    FormSchema,
    FormSection,
)


@pytest.fixture
def cache():
    """FormCache with 1-second TTL for fast expiry tests."""
    return FormCache(ttl_seconds=1)


@pytest.fixture
def long_ttl_cache():
    """FormCache with long TTL (won't expire in tests)."""
    return FormCache(ttl_seconds=3600)


@pytest.fixture
def sample_form():
    """Sample FormSchema."""
    return FormSchema(
        form_id="cached-form",
        title="Cached",
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(field_id="f", field_type=FieldType.TEXT, label="F")
                ],
            )
        ],
    )


@pytest.fixture
def another_form():
    """Second sample FormSchema."""
    return FormSchema(
        form_id="other-form",
        title="Other",
        sections=[
            FormSection(
                section_id="s2",
                fields=[
                    FormField(field_id="g", field_type=FieldType.EMAIL, label="G")
                ],
            )
        ],
    )


class TestFormCacheBasic:
    """Tests for basic get/set behavior."""

    async def test_set_and_get(self, long_ttl_cache, sample_form):
        """set() then get() returns the form."""
        await long_ttl_cache.set(sample_form)
        result = await long_ttl_cache.get("cached-form")
        assert result is not None
        assert result.form_id == "cached-form"

    async def test_miss_returns_none(self, long_ttl_cache):
        """Cache miss returns None."""
        result = await long_ttl_cache.get("nonexistent")
        assert result is None

    async def test_set_multiple(self, long_ttl_cache, sample_form, another_form):
        """Multiple forms can be stored independently."""
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.set(another_form)
        assert await long_ttl_cache.get("cached-form") is not None
        assert await long_ttl_cache.get("other-form") is not None

    async def test_set_overwrites(self, long_ttl_cache, sample_form):
        """Setting the same form_id overwrites the existing entry."""
        await long_ttl_cache.set(sample_form)
        updated = sample_form.model_copy(update={"title": "Updated"})
        await long_ttl_cache.set(updated)
        result = await long_ttl_cache.get("cached-form")
        assert result.title == "Updated"


class TestFormCacheTTL:
    """Tests for TTL expiration."""

    async def test_ttl_expiry(self, cache, sample_form):
        """Entries expire after TTL."""
        await cache.set(sample_form)
        # Wait for TTL to expire (1 second + buffer)
        await asyncio.sleep(1.1)
        result = await cache.get("cached-form")
        assert result is None


class TestFormCacheInvalidation:
    """Tests for invalidation."""

    async def test_invalidate_single(self, long_ttl_cache, sample_form):
        """invalidate() removes a specific form."""
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.invalidate("cached-form")
        result = await long_ttl_cache.get("cached-form")
        assert result is None

    async def test_invalidate_nonexistent(self, long_ttl_cache):
        """Invalidating a nonexistent form does not raise."""
        await long_ttl_cache.invalidate("nonexistent")  # Should not raise

    async def test_invalidate_all(self, long_ttl_cache, sample_form, another_form):
        """invalidate_all() clears all cached forms."""
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.set(another_form)
        await long_ttl_cache.invalidate_all()
        assert await long_ttl_cache.get("cached-form") is None
        assert await long_ttl_cache.get("other-form") is None


class TestFormCacheSize:
    """Tests for size tracking."""

    async def test_size_empty(self, long_ttl_cache):
        """Empty cache has size 0."""
        assert await long_ttl_cache.size() == 0

    async def test_size_after_set(self, long_ttl_cache, sample_form, another_form):
        """size() reflects number of unexpired entries."""
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.set(another_form)
        assert await long_ttl_cache.size() == 2

    async def test_size_after_invalidate(self, long_ttl_cache, sample_form):
        """size() decreases after invalidation."""
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.invalidate("cached-form")
        assert await long_ttl_cache.size() == 0


class TestFormCacheCallbacks:
    """Tests for invalidation callbacks."""

    async def test_on_invalidate_callback(self, long_ttl_cache, sample_form):
        """on_invalidate callback is called when a form is invalidated."""
        invalidated = []

        async def handler(form_id: str):
            invalidated.append(form_id)

        long_ttl_cache.on_invalidate(handler)
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.invalidate("cached-form")
        assert "cached-form" in invalidated

    async def test_multiple_callbacks(self, long_ttl_cache, sample_form):
        """Multiple callbacks are all invoked on invalidation."""
        events_a: list[str] = []
        events_b: list[str] = []

        async def handler_a(form_id: str):
            events_a.append(form_id)

        async def handler_b(form_id: str):
            events_b.append(form_id)

        long_ttl_cache.on_invalidate(handler_a)
        long_ttl_cache.on_invalidate(handler_b)
        await long_ttl_cache.set(sample_form)
        await long_ttl_cache.invalidate("cached-form")
        assert "cached-form" in events_a
        assert "cached-form" in events_b
