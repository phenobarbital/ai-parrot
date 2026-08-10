"""``setup_saas_api(app)`` — the single wiring entry point for the SaaS plane.

Builds the shared services, publishes them on the application, installs the
tenant-resolution middleware and registers the routes.

**Where to call it.** From ``Main.configure()`` in the root ``app.py``,
*between* ``AuthHandler().setup(self.app)`` and ``setup_pbac(...)``. That
position is load-bearing, not stylistic:

* ``setup_pbac`` appends ``abac_middleware`` last, and aiohttp runs
  first-registered outermost — so anything registered after it executes
  *inside* ABAC, after the authorization decision has been made. Registering
  before it is what lets a policy read ``request["tenant"]``.
* Registering after ``AuthHandler.setup`` is what gives the optional
  session-claim strategy a session to read.

``self.app`` inside ``configure()`` is a real ``aiohttp.web.Application`` and
``configure()`` runs long before start-up, so adding middleware there is
legitimate.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from aiohttp import web
from navconfig.logging import logging

from .. import conf
from ..tenancy.middleware import (
    DEFAULT_EXEMPT_PREFIXES,
    DEFAULT_STRATEGIES,
    tenant_resolution_middleware,
)
from ..tenancy.repository import TenantRepository
from ..tenancy.runtime import TenantRuntime, TenantRuntimeCache
from .tenants import (
    APP_TENANT_REPOSITORY,
    APP_TENANT_RUNTIMES,
    TenantCollectionView,
    TenantItemView,
    setup_tenant_routes,
)

#: Key under which the secret store is published.
APP_SECRET_STORE = "saas_secret_store"

logger = logging.getLogger("parrot_saas.handlers.setup")


async def _default_runtime_builder(tenant) -> TenantRuntime:
    """Build a bare runtime for a tenant.

    Deliberately minimal at this stage: the agents (BYOK) and the compiled
    coupon ruleset are wired in by their own features. What already matters is
    the concurrency bound, because the flow scheduler enforces none of its own.

    Args:
        tenant: The tenant to serve.

    Returns:
        A runtime with a per-tenant concurrency semaphore.
    """
    import asyncio

    return TenantRuntime(
        tenant=tenant,
        semaphore=asyncio.Semaphore(conf.SAAS_TENANT_MAX_CONCURRENT_RUNS),
    )


def _apply_auth(*views: type) -> None:
    """Apply navigator-auth's decorators to the control-plane views.

    Applied here rather than at class definition so the views stay importable
    and unit-testable without a configured auth stack. Production always gets
    them: :func:`setup_saas_api` defaults ``require_auth`` to ``True``.
    """
    from navigator_auth.decorators import is_authenticated, user_session

    for view in views:
        is_authenticated()(view)
        user_session()(view)


def setup_saas_api(
    app: web.Application,
    *,
    dsn: Optional[str] = None,
    schema: Optional[str] = None,
    secret_store: Optional[Any] = None,
    runtime_builder: Optional[Any] = None,
    strategies: Sequence[str] = DEFAULT_STRATEGIES,
    exempt_prefixes: Iterable[str] = DEFAULT_EXEMPT_PREFIXES,
    exempt_patterns: Iterable[str] = (),
    require_auth: bool = True,
    install_middleware: bool = True,
) -> web.Application:
    """Wire the SaaS control plane into an aiohttp application.

    Args:
        app: The application (navigator wrapper or plain aiohttp).
        dsn: Postgres DSN. Defaults to ``conf.SAAS_PG_DSN``.
        schema: Schema owning the SaaS tables. Defaults to
            ``conf.SAAS_PG_SCHEMA``.
        secret_store: Pre-built secret store. When omitted, an encrypted
            Postgres store is constructed lazily on first use, so a
            deployment without vault keys still starts and fails only where
            secrets are actually touched.
        runtime_builder: Coroutine building a per-tenant runtime.
        strategies: Tenant resolution strategies, in order.
        exempt_prefixes: Path prefixes skipping tenant resolution.
        exempt_patterns: Glob patterns skipping tenant resolution — for
            signature-authenticated webhooks.
        require_auth: Apply navigator-auth's decorators to the control-plane
            views. Only turn this off in tests.
        install_middleware: Register the tenant middleware. Off only for tests
            that exercise the routes directly.

    Returns:
        The underlying aiohttp application.
    """
    _app: web.Application = app.get_app() if hasattr(app, "get_app") else app

    resolved_dsn = dsn or conf.SAAS_PG_DSN
    resolved_schema = schema or conf.SAAS_PG_SCHEMA

    repository = TenantRepository(resolved_dsn, schema=resolved_schema)
    runtimes = TenantRuntimeCache(
        runtime_builder or _default_runtime_builder,
        max_size=conf.SAAS_TENANT_RUNTIME_MAX,
        ttl=conf.SAAS_TENANT_RUNTIME_TTL,
    )

    _app[APP_TENANT_REPOSITORY] = repository
    _app[APP_TENANT_RUNTIMES] = runtimes
    if secret_store is not None:
        _app[APP_SECRET_STORE] = secret_store

    if require_auth:
        _apply_auth(TenantCollectionView, TenantItemView)

    if install_middleware:
        _app.middlewares.append(
            tenant_resolution_middleware(
                repository=repository,
                cache=runtimes,
                strategies=strategies,
                exempt_prefixes=exempt_prefixes,
                exempt_patterns=exempt_patterns,
            )
        )

    setup_tenant_routes(_app)

    async def _on_startup(application: web.Application) -> None:
        """Create the SaaS schema if it does not exist."""
        from ..db.schema import ensure_schema

        conn = await repository.connection()
        await ensure_schema(conn, schema=resolved_schema)

    async def _on_cleanup(application: web.Application) -> None:
        """Release the runtime cache, repository and secret store."""
        await runtimes.aclose_all()
        await repository.aclose()
        store = application.get(APP_SECRET_STORE)
        if store is not None and hasattr(store, "aclose"):
            await store.aclose()

    _app.on_startup.append(_on_startup)
    _app.on_cleanup.append(_on_cleanup)

    logger.info(
        "SaaS API wired (schema=%s, strategies=%s, auth=%s)",
        resolved_schema,
        list(strategies),
        require_auth,
    )
    return _app


__all__ = ("APP_SECRET_STORE", "setup_saas_api")
