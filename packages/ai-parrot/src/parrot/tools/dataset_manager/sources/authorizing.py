"""AuthorizingDataSource — DataSource decorator for FEAT-228.

Wraps any :class:`~parrot.tools.dataset_manager.sources.base.DataSource` with
the full data-plane authorization + RLS enforcement chain (Spec §2, Module 7).

This is the keystone of Option D (enforcement at source construction time).
Its ``fetch()`` method runs the complete enforcement chain before delegating
to the inner source:

0. Sensitive-driver pre-check: if the driver is classed sensitive, reject any
   non-:class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`.
1. Get ``PermissionContext`` from the provider.  ``None`` → fail-open.
2. Resolve physical resources from the inner source via ``resolve_physical_resources``.
3. Call ``guard.authorize_source(ctx, resources)`` (raises on denial).
4. Collect RLS predicates from the guard.
5. Inject RLS predicates into a request-scoped copy of the inner source/query.
6. Delegate to the request-scoped source's ``fetch()``.

Transparent delegation:
- ``describe()`` → delegates to inner.
- ``cache_key`` → delegates to inner.
- ``has_builtin_cache`` → delegates to inner.
- ``prefetch_schema()`` → delegates to inner.
"""
from __future__ import annotations

import copy
import logging
from typing import Callable, Optional, TYPE_CHECKING

import pandas as pd

from parrot.tools.dataset_manager.sources.base import DataSource

if TYPE_CHECKING:
    from parrot.auth.dataplane_guard import DataPlanePolicyGuard
    from parrot.auth.permission import PermissionContext
    from parrot.auth.rls_registry import RlsPredicate
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources


class AuthorizingDataSource(DataSource):
    """Decorator that wraps a DataSource with authorization + RLS enforcement.

    The ``fetch()`` method runs the full enforcement chain before delegating
    to the inner source's ``fetch()``.  All other :class:`DataSource`
    properties are transparently delegated.

    Args:
        inner: The wrapped :class:`DataSource` instance.
        guard: :class:`~parrot.auth.dataplane_guard.DataPlanePolicyGuard`
            that performs PBAC evaluation and RLS predicate collection.
        pctx_provider: Callable with no arguments that returns the current
            :class:`~parrot.auth.permission.PermissionContext` (typically
            ``lambda: _pctx_var.get(None)``).  Called at ``fetch()`` time
            so the context is fresh for each invocation.
    """

    def __init__(
        self,
        inner: DataSource,
        guard: "DataPlanePolicyGuard",
        pctx_provider: Callable[[], Optional["PermissionContext"]],
    ) -> None:
        super().__init__(routing_meta=getattr(inner, "routing_meta", None))
        self._inner = inner
        self._guard = guard
        self._pctx_provider = pctx_provider
        self._logger = logging.getLogger(__name__)

    # ──────────────────────────────────────────────────────────────────────
    # Enforcement chain
    # ──────────────────────────────────────────────────────────────────────

    async def fetch(self, **params) -> pd.DataFrame:
        """Run the enforcement chain then delegate to inner.fetch().

        Enforcement steps:
        0. Sensitive-driver pre-check: reject non-slug sources.
        1. Get PermissionContext from provider; None → fail-open.
        2. Resolve physical resources.
        3. Authorize (raises AuthorizationRequired on denial).
        4. Collect RLS predicates.
        5. Inject RLS into a request-scoped copy of the inner source/query.
        6. Delegate to the request-scoped source's fetch().

        Args:
            **params: Keyword arguments forwarded to ``inner.fetch()``.

        Returns:
            :class:`pandas.DataFrame` returned by the inner source.

        Raises:
            AuthorizationRequired: When the guard denies access.
            ReadOnlyViolation: When a DML/DDL statement is detected.
        """
        from parrot.tools.dataset_manager.sources.resolver import (
            resolve_physical_resources,
            ReadOnlyViolation,
        )
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
        from parrot.auth.exceptions import AuthorizationRequired

        # Step 0: sensitive driver pre-check
        driver = getattr(self._inner, "driver", None)
        if driver and self._guard.is_sensitive_driver(driver):
            if not isinstance(self._inner, QuerySlugSource):
                self._logger.warning(
                    "AuthorizingDataSource DENY sensitive driver '%s': "
                    "only QuerySlugSource allowed",
                    driver,
                )
                raise AuthorizationRequired(
                    tool_name="dataplane_authz",
                    message=(
                        f"Driver '{driver}' is classed sensitive: "
                        "only registered query slugs are accepted"
                    ),
                )

        # Step 1: get permission context
        ctx = self._pctx_provider()
        if ctx is None:
            return await self._inner.fetch(**params)  # fail-open

        # Step 2: resolve physical resources
        # ParseError on guarded driver → fail-closed.
        import sqlglot

        try:
            resources = resolve_physical_resources(self._inner)
        except ReadOnlyViolation:
            raise
        except sqlglot.errors.ParseError as exc:
            if driver and self._guard.is_sensitive_driver(driver):
                raise AuthorizationRequired(
                    tool_name="dataplane_authz",
                    message=f"SQL parse error on sensitive driver '{driver}': {exc}",
                ) from exc
            # Unguarded driver — let the error propagate
            raise

        # Step 3–4: authorize (raises on denial) + collect RLS predicates
        await self._guard.authorize_source(ctx, resources)
        predicates = await self._guard.rls_predicates(ctx, resources)

        # Step 5: inject RLS into a request-scoped copy (never mutate self._inner — issue:90cf04ce8edd)
        target = self._apply_rls(predicates, resources) if predicates else self._inner

        # Step 6: delegate to the (possibly scoped) inner source
        return await target.fetch(**params)

    def _apply_rls(
        self,
        predicates: "list[RlsPredicate]",
        resources: "PhysicalResources",
    ) -> DataSource:
        """Return a request-scoped copy of the inner source with RLS applied.

        Strategy (Spec §2 Module 5):
        - :class:`~parrot.tools.dataset_manager.sources.sql.SQLQuerySource`:
          rewrite ``sql`` attribute with wrapped query.
        - :class:`~parrot.tools.dataset_manager.sources.table.TableSource`:
          extend ``_permanent_filter``.
        - :class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`:
          extend ``_permanent_filter``.
        - :class:`~parrot.tools.dataset_manager.sources.mongo.MongoSource`:
          merge the Mongo filter into the copy's ``required_filter``.

        Args:
            predicates: Rendered RLS predicates to inject.
            resources: Physical resources (provides dialect context for SQL).

        Returns:
            A shallow copy of the inner source carrying this request's RLS state.
        """
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
        from parrot.tools.dataset_manager.sources.rls import (
            inject_rls_sql,
            inject_rls_table_source,
            inject_rls_query_slug,
        )
        from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect

        scoped = copy.copy(self._inner)
        if hasattr(scoped, "_permanent_filter"):
            scoped._permanent_filter = dict(self._inner._permanent_filter)

        if isinstance(self._inner, SQLQuerySource):
            dialect = driver_to_dialect(scoped.driver) or "generic"
            rewritten_sql, _bound_params = inject_rls_sql(scoped.sql, dialect, predicates)
            scoped.sql = rewritten_sql
            self._logger.debug(
                "AuthorizingDataSource: injected RLS into SQLQuerySource "
                "(driver=%s, %d predicates)",
                scoped.driver,
                len(predicates),
            )
        elif isinstance(self._inner, TableSource):
            inject_rls_table_source(scoped, predicates)
            self._logger.debug(
                "AuthorizingDataSource: injected RLS into TableSource "
                "(table=%s, %d predicates)",
                scoped.table,
                len(predicates),
            )
        elif isinstance(self._inner, QuerySlugSource):
            inject_rls_query_slug(scoped, predicates)
            self._logger.debug(
                "AuthorizingDataSource: injected RLS into QuerySlugSource "
                "(slug=%s, %d predicates)",
                scoped.slug,
                len(predicates),
            )
        else:
            # Try to detect MongoSource and apply Mongo RLS filter.
            # We use a lazy import + isinstance check to avoid hard dependency.
            try:
                from parrot.tools.dataset_manager.sources.mongo import MongoSource
                from parrot.tools.dataset_manager.sources.rls import inject_rls_mongo

                if isinstance(self._inner, MongoSource):
                    mongo_filter = inject_rls_mongo(scoped, predicates)
                    if mongo_filter:
                        # MongoSource exposes `required_filter` which is merged
                        # into every query.  Merge the RLS $and conditions.
                        existing = getattr(scoped, "required_filter", None) or {}
                        if existing:
                            scoped.required_filter = {"$and": [existing, mongo_filter]}
                        else:
                            scoped.required_filter = mongo_filter
                    self._logger.debug(
                        "AuthorizingDataSource: injected RLS into MongoSource "
                        "(%d predicates)",
                        len(predicates),
                    )
                    return scoped
            except ImportError:
                pass

            # TODO: FEAT-228 post-fetch RLS deferred — Airtable and Smartsheet
            # sources return a DataFrame after fetch; applying inject_rls_postfetch
            # here requires a pre/post split in fetch() that is not yet implemented.
            # For now, non-SQL/Table/Slug/Mongo sources receive no RLS filtering.
            # Track in: https://github.com/your-org/ai-parrot/issues/FEAT-228
            self._logger.debug(
                "AuthorizingDataSource: RLS injection not supported for source type %s "
                "(post-fetch RLS for Airtable/Smartsheet is deferred — FEAT-228 TODO)",
                type(self._inner).__name__,
            )

        return scoped

    # ──────────────────────────────────────────────────────────────────────
    # Transparent delegation to inner source
    # ──────────────────────────────────────────────────────────────────────

    def describe(self) -> str:
        """Delegate to inner source."""
        return self._inner.describe()

    @property
    def has_builtin_cache(self) -> bool:
        """Delegate to inner source."""
        return self._inner.has_builtin_cache

    @property
    def cache_key(self) -> str:
        """Delegate to inner source."""
        return self._inner.cache_key

    async def prefetch_schema(self):
        """Delegate schema prefetch to inner source."""
        return await self._inner.prefetch_schema()
