"""Tenant-aware metric registry: MetricView overlay + MetricRegistry service (FEAT-756 M3)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from parrot.metrics.errors import MetricNotFound
from parrot.metrics.matching import MetricMatcher
from parrot.metrics.models import MetricDefinition, MetricMatch
from parrot.metrics.store import MetricStore

_LOGGER = logging.getLogger(__name__)


class MetricView:
    """Read-only overlay of a tenant namespace over the global one (SkillView twin, tenancy.py:146)."""

    def __init__(
        self,
        global_defs: Sequence[MetricDefinition],
        tenant_defs: Sequence[MetricDefinition] = (),
        *,
        tenant: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._global = list(global_defs)
        self._tenant_defs = list(tenant_defs)
        self.tenant = tenant
        self.logger = logger or _LOGGER
        self._by_id: dict[str, MetricDefinition] = {}
        self._ordered: list[MetricDefinition] = []
        self.report: dict[str, list[str]] = {"shadowed": [], "dropped": [], "alias_dropped": []}

    def compose(self) -> "MetricView":
        """Compose C1/C2/C3 tenant overlays without mutating source definitions."""
        self.report = {"shadowed": [], "dropped": [], "alias_dropped": []}
        global_by_id = {definition.id: definition for definition in self._global}
        locked_ids = {definition.id for definition in self._global if definition.global_only}
        kept_tenant: list[MetricDefinition] = []

        for definition in self._tenant_defs:
            if definition.id in locked_ids:
                self.logger.warning(
                    "Tenant metric %s conflicts with global_only metric; dropping tenant metric", definition.id
                )
                self.report["dropped"].append(definition.id)
                continue
            if definition.id in global_by_id:
                self.report["shadowed"].append(definition.id)
            kept_tenant.append(definition)

        tenant_ids = {definition.id for definition in kept_tenant}
        tenant_aliases = {alias.casefold() for definition in kept_tenant for alias in definition.aliases}
        surviving_globals: list[MetricDefinition] = []
        for definition in self._global:
            if definition.id in tenant_ids:
                continue
            aliases = [alias for alias in definition.aliases if alias.casefold() not in tenant_aliases]
            removed_aliases = [alias for alias in definition.aliases if alias.casefold() in tenant_aliases]
            if removed_aliases:
                self.report["alias_dropped"].extend(removed_aliases)
                definition = definition.model_copy(update={"aliases": aliases})
            surviving_globals.append(definition)

        self._ordered = [*surviving_globals, *kept_tenant]
        self._by_id = {definition.id: definition for definition in self._ordered}
        return self

    def get(self, metric_id: str) -> MetricDefinition | None:
        """Return the effective metric identified by ``metric_id``."""
        return self._by_id.get(metric_id)

    def list(self, *, program: str | None = None) -> list[MetricDefinition]:
        """Return effective metrics, optionally restricted to one program."""
        return [definition for definition in self._ordered if program is None or definition.program == program]

    def terms(self) -> dict[str, list[str]]:
        """Return ``{metric_id: matching_terms()}`` for the matcher bank."""
        return {definition.id: definition.matching_terms() for definition in self._ordered}


@dataclass(frozen=True)
class _TenantDefs:
    """One TTL-stamped load of a tenant's global and tenant definitions."""

    stamp: float
    global_defs: list[MetricDefinition]
    tenant_defs: list[MetricDefinition]

    @property
    def has_private(self) -> bool:
        """Whether any loaded definition is owner-only."""
        return any(definition.visibility == "private" for definition in (*self.global_defs, *self.tenant_defs))


class MetricRegistry:
    """List, describe, and resolve metrics for one tenant-aware agent.

    Effective views are cached per tenant (and per caller when the tenant has ``private``
    metrics) for ``cache_ttl`` seconds, so definitions written through another lane (e.g. the
    ``/api/v1/metrics`` REST handler) reach running agents without a restart. ``cache_ttl=None``
    caches until :meth:`invalidate` is called.

    ``private`` metrics are visible only to their owner: every read takes the caller's
    ``user_id`` and hides another user's private metrics (no caller → no private metrics).
    """

    #: Upper bound on cached tenants/views; a cache is cleared when it is exceeded.
    max_cached_views: int = 256

    def __init__(
        self,
        store: MetricStore,
        *,
        matcher: MetricMatcher | None = None,
        default_tenant: str | None = None,
        visibility_filter: Callable[[MetricDefinition], bool] | None = None,
        cache_ttl: float | None = 60.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store = store
        self._matcher = matcher
        self.default_tenant = default_tenant
        self._visibility_filter = visibility_filter
        self.cache_ttl = cache_ttl
        self.logger = logger or _LOGGER
        self._loaded: dict[str | None, _TenantDefs] = {}
        self._views: dict[tuple[str | None, str | None], tuple[float, MetricView]] = {}
        self._bank_terms: dict[str, list[str]] | None = None

    def _fresh(self, stamp: float) -> bool:
        """Whether a cache entry created at ``stamp`` is still within ``cache_ttl``."""
        return self.cache_ttl is None or time.monotonic() - stamp < self.cache_ttl

    @staticmethod
    def _owner_visible(definition: MetricDefinition, user_id: str | None) -> bool:
        """Hide ``private`` definitions from everyone but their owner."""
        if definition.visibility != "private":
            return True
        return user_id is not None and definition.owner == user_id

    async def _load(self, tenant: str | None) -> _TenantDefs:
        """Return the tenant's filtered store lists, reloading them once ``cache_ttl`` has elapsed."""
        cached = self._loaded.get(tenant)
        if cached is not None and self._fresh(cached.stamp):
            return cached

        global_defs = await self.store.list(tenant=None)
        tenant_defs = await self.store.list(tenant=tenant) if tenant else []
        if self._visibility_filter is not None:
            global_defs = [definition for definition in global_defs if self._visibility_filter(definition)]
            tenant_defs = [definition for definition in tenant_defs if self._visibility_filter(definition)]
        loaded = _TenantDefs(time.monotonic(), global_defs, tenant_defs)
        if len(self._loaded) >= self.max_cached_views:
            self._loaded.clear()
            self._views.clear()
        self._loaded[tenant] = loaded
        return loaded

    async def view(self, tenant: str | None, *, user_id: str | None = None) -> MetricView:
        """Compose and cache the caller's effective metric view for ``tenant``."""
        loaded = await self._load(tenant)
        # Without private metrics every caller of the tenant shares one view.
        key = (tenant, user_id if loaded.has_private else None)
        cached = self._views.get(key)
        if cached is not None and cached[0] == loaded.stamp:
            return cached[1]

        global_defs = [definition for definition in loaded.global_defs if self._owner_visible(definition, key[1])]
        tenant_defs = [definition for definition in loaded.tenant_defs if self._owner_visible(definition, key[1])]
        view = MetricView(global_defs, tenant_defs, tenant=tenant, logger=self.logger).compose()
        if len(self._views) >= self.max_cached_views:
            self._views.clear()
        self._views[key] = (loaded.stamp, view)
        return view

    async def list(
        self, *, tenant: str | None = None, program: str | None = None, user_id: str | None = None
    ) -> list[MetricDefinition]:
        """Return metrics visible to ``user_id`` in the effective tenant namespace."""
        return (await self.view(tenant or self.default_tenant, user_id=user_id)).list(program=program)

    async def describe(
        self, metric_id: str, *, tenant: str | None = None, user_id: str | None = None
    ) -> MetricDefinition:
        """Return one effective, caller-visible metric or raise ``MetricNotFound``."""
        found = (await self.view(tenant or self.default_tenant, user_id=user_id)).get(metric_id)
        if found is None:
            raise MetricNotFound(metric_id)
        return found

    async def resolve(
        self, question: str, *, tenant: str | None = None, user_id: str | None = None
    ) -> MetricMatch | None:
        """Resolve a question through the matcher without allowing failures to escape."""
        try:
            effective_tenant = tenant or self.default_tenant
            view = await self.view(effective_tenant, user_id=user_id)
            if self._matcher is None:
                self._matcher = MetricMatcher()
            terms = view.terms()
            if terms != self._bank_terms:
                self._matcher.configure(terms)
                self._bank_terms = terms
            matched = await asyncio.to_thread(self._matcher.match, question)
            if matched is None:
                return None
            metric_id, score, lane, ambiguous = matched
            metric = view.get(metric_id)
            if metric is None:
                return None
            return MetricMatch(
                metric=metric,
                score=score,
                lane=lane,
                ambiguous=ambiguous,
                tenant=effective_tenant,
                requested_period=MetricMatcher.parse_period(question),
                requested_dimension=MetricMatcher.parse_dimension(question, metric.dimensions),
            )
        except Exception as exc:
            self.logger.warning("metric resolve failed for %r: %s", question, exc)
            return None

    def invalidate(self, tenant: str | None = None) -> None:
        """Drop the cached views of one tenant, or every cached view when tenant is omitted."""
        if tenant is None:
            self._loaded.clear()
            self._views.clear()
        else:
            self._loaded.pop(tenant, None)
            for key in [key for key in self._views if key[0] == tenant]:
                del self._views[key]
        self._bank_terms = None
