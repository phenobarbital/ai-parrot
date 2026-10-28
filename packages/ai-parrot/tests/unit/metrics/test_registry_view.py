"""Tests for tenant-aware metric view composition and registry resolution."""

from __future__ import annotations

import logging

import pytest

from parrot.metrics.errors import MetricNotFound
from parrot.metrics.matching import MetricMatcher
from parrot.metrics.models import MetricDefinition
from parrot.metrics.registry import MetricRegistry, MetricView
from parrot.metrics.store import InMemoryMetricStore


def test_metric_view_c1_shadow_by_id(worked_hours_def: MetricDefinition) -> None:
    """A tenant definition replaces a global definition with the same id."""
    tenant_definition = worked_hours_def.model_copy(update={"tenant": "acme", "name": "Acme Worked Hours"})

    view = MetricView([worked_hours_def], [tenant_definition], tenant="acme").compose()

    assert view.get("worked_hours") == tenant_definition
    assert view.list() == [tenant_definition]
    assert view.report["shadowed"] == ["worked_hours"]
    assert worked_hours_def.name == "Worked Hours"


def test_metric_view_c2_alias_collision_tenant_wins(worked_hours_def: MetricDefinition) -> None:
    """Tenant aliases remove colliding aliases from surviving global definitions."""
    global_definition = worked_hours_def.model_copy(
        update={"id": "global_hours", "aliases": ["Hours Worked", "global"]}
    )
    tenant_definition = worked_hours_def.model_copy(
        update={"id": "tenant_hours", "tenant": "acme", "aliases": ["hours worked", "tenant"]}
    )

    view = MetricView([global_definition], [tenant_definition], tenant="acme").compose()

    assert view.get("global_hours").aliases == ["global"]
    assert global_definition.aliases == ["Hours Worked", "global"]
    assert view.report["alias_dropped"] == ["Hours Worked"]


def test_metric_view_c3_global_only_drops_tenant(
    worked_hours_def: MetricDefinition, caplog: pytest.LogCaptureFixture
) -> None:
    """A global-only definition cannot be shadowed by a tenant definition."""
    locked = worked_hours_def.model_copy(update={"global_only": True})
    tenant_definition = worked_hours_def.model_copy(update={"tenant": "acme", "name": "Tenant Hours"})

    with caplog.at_level(logging.WARNING):
        view = MetricView([locked], [tenant_definition], tenant="acme").compose()

    assert view.list() == [locked]
    assert view.report["dropped"] == ["worked_hours"]
    assert "global_only" in caplog.text


def test_metric_view_c5_c6_single_namespace(worked_hours_def: MetricDefinition) -> None:
    """Global-only and tenant-only namespaces each compose unchanged."""
    tenant_definition = worked_hours_def.model_copy(update={"tenant": "acme"})

    assert MetricView([worked_hours_def]).compose().list() == [worked_hours_def]
    assert MetricView([], [tenant_definition], tenant="acme").compose().list() == [tenant_definition]


async def test_registry_describe_not_found() -> None:
    """Describe raises the declared error for a metric absent from the view."""
    registry = MetricRegistry(InMemoryMetricStore())

    with pytest.raises(MetricNotFound):
        await registry.describe("missing")


async def test_registry_resolve_alias(worked_hours_def: MetricDefinition) -> None:
    """Alias resolution includes the requested period and dimension."""
    registry = MetricRegistry(InMemoryMetricStore([worked_hours_def]), matcher=MetricMatcher(enable_embeddings=False))

    match = await registry.resolve("hours worked this month by cost center")

    assert match is not None
    assert match.metric == worked_hours_def
    assert match.lane == "alias"
    assert match.requested_period == "this_month"
    assert match.requested_dimension == "cost center"


async def test_registry_resolve_never_raises(
    worked_hours_def: MetricDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matcher failures are logged and converted to a non-match."""
    matcher = MetricMatcher(enable_embeddings=False)
    registry = MetricRegistry(InMemoryMetricStore([worked_hours_def]), matcher=matcher)

    def raise_match(question: str) -> None:
        raise RuntimeError("matcher failure")

    monkeypatch.setattr(matcher, "match", raise_match)

    assert await registry.resolve("hours worked this month") is None


async def test_registry_hides_private_metrics_from_non_owners(worked_hours_def: MetricDefinition) -> None:
    """Private metrics are listed, described and resolved only for their owner."""
    private = worked_hours_def.model_copy(update={"tenant": "acme", "visibility": "private", "owner": "u1"})
    registry = MetricRegistry(
        InMemoryMetricStore([private]), matcher=MetricMatcher(enable_embeddings=False), default_tenant="acme"
    )

    assert await registry.list(user_id="u2") == []
    assert await registry.list() == []
    with pytest.raises(MetricNotFound):
        await registry.describe("worked_hours", user_id="u2")
    assert await registry.resolve("hours worked this month", user_id="u2") is None

    assert [d.id for d in await registry.list(user_id="u1")] == ["worked_hours"]
    assert (await registry.describe("worked_hours", user_id="u1")) == private
    match = await registry.resolve("hours worked this month", user_id="u1")
    assert match is not None and match.metric == private
    assert await registry.resolve("hours worked this month", user_id="u2") is None


async def test_registry_view_cache_expires_after_ttl(
    worked_hours_def: MetricDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Definitions written after the first read appear once cache_ttl elapses."""
    import parrot.metrics.registry as registry_module

    clock = [1000.0]
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: clock[0])
    store = InMemoryMetricStore()
    registry = MetricRegistry(store, cache_ttl=30.0)

    assert await registry.list() == []
    await store.save(worked_hours_def)
    clock[0] += 10
    assert await registry.list() == []
    clock[0] += 25
    assert [d.id for d in await registry.list()] == ["worked_hours"]


async def test_registry_invalidate_drops_cached_views(worked_hours_def: MetricDefinition) -> None:
    """invalidate() forces a reload even without a TTL."""
    store = InMemoryMetricStore()
    registry = MetricRegistry(store, cache_ttl=None, default_tenant="acme")

    assert await registry.list() == []
    await store.save(worked_hours_def)
    assert await registry.list() == []
    registry.invalidate("acme")
    assert [d.id for d in await registry.list()] == ["worked_hours"]
