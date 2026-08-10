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

#: Key under which the memoising secret-store factory is published. Handlers
#: that need a store should call this rather than reading ``APP_SECRET_STORE``,
#: which is absent until the store has actually been built.
APP_SECRET_STORE_FACTORY = "saas_secret_store_factory"

logger = logging.getLogger("parrot_saas.handlers.setup")


def _make_runtime_builder(
    secret_store_factory: Any,
    tool_manager_template: Optional[Any] = None,
):
    """Build the default per-tenant runtime builder.

    The secret store arrives as a *factory* rather than an instance so that a
    deployment without vault keys still starts: the store is only constructed
    when a tenant actually needs its credentials.

    Args:
        secret_store_factory: Zero-argument callable returning the store, or
            ``None`` when no store is configured.
        tool_manager_template: Template manager cloned per tenant, if any.

    Returns:
        A coroutine function suitable for :class:`TenantRuntimeCache`.
    """

    async def _build(tenant) -> TenantRuntime:
        """Build a tenant's runtime, agents included.

        Agent construction is **tolerant** here. This runs inside the tenant
        middleware, on the way to serving a request — including the request a
        freshly onboarded tenant makes to upload its very first API key. If a
        missing credential were fatal at this point, that tenant would be
        trapped behind a 500 with no way to fix it. Roles whose credential is
        absent are simply left out, and the flow's LLM nodes fall back to
        their deterministic paths. The ingest path builds with ``strict=True``
        instead, because it is about to run the flow for real.

        Args:
            tenant: The tenant to serve.

        Returns:
            A runtime with a per-tenant concurrency semaphore and whatever
            agents the tenant's stored credentials allow.
        """
        import asyncio

        from ..tenancy.runtime import clone_tool_manager

        tool_manager = (
            clone_tool_manager(tool_manager_template)
            if tool_manager_template is not None
            else None
        )

        agents: dict = {}
        store = None
        if secret_store_factory is not None:
            try:
                store = secret_store_factory()
            except Exception as exc:  # noqa: BLE001 - misconfiguration, not a bug
                # No vault master key, unreachable database, and so on. This
                # must not take the request down: the runtime is built on the
                # way to serving *any* tenant-scoped route, so a deployment
                # with no KEK configured would otherwise 500 on all of them
                # rather than only where secrets are actually touched. Loud,
                # because running without a secret store is a real problem.
                logger.error(
                    "no secret store available for tenant %s (%s); its agents "
                    "cannot be built and its flow will use the deterministic "
                    "fallbacks",
                    tenant.tenant_id,
                    exc,
                )
        if store is not None:
            from ..llm.builder import build_tenant_agents

            agents = await build_tenant_agents(
                tenant=tenant,
                secret_store=store,
                tool_manager=tool_manager,
                strict=False,
            )

        return TenantRuntime(
            tenant=tenant,
            tool_manager=tool_manager,
            agents=agents,
            semaphore=asyncio.Semaphore(conf.SAAS_TENANT_MAX_CONCURRENT_RUNS),
        )

    return _build


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
    tool_manager_template: Optional[Any] = None,
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
        runtime_builder: Coroutine building a per-tenant runtime. Overrides the
            default builder entirely, including its BYOK agent construction.
        tool_manager_template: Process-wide ``ToolManager`` cloned per tenant
            by the default builder. Omitted, tenants run without tools — which
            is all the Community Manager flow needs today.
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

    # The store is resolved through a memoising factory rather than built here.
    # ``EnvelopeCipher.from_environment()`` raises when no master key is
    # configured — correct behaviour, but it must not stop the application
    # booting, since the control plane has plenty to do without touching a
    # secret. This defers the failure to the first request that needs one.
    _store_holder: dict = {"store": secret_store}

    def _secret_store() -> Any:
        """Return the secret store, constructing it on first use."""
        if _store_holder["store"] is None:
            from parrot.security.secrets.postgres import (
                EncryptedPostgresSecretStore,
            )

            _store_holder["store"] = EncryptedPostgresSecretStore(
                resolved_dsn, schema=resolved_schema
            )
            _app[APP_SECRET_STORE] = _store_holder["store"]
        return _store_holder["store"]

    runtimes = TenantRuntimeCache(
        runtime_builder
        or _make_runtime_builder(_secret_store, tool_manager_template),
        max_size=conf.SAAS_TENANT_RUNTIME_MAX,
        ttl=conf.SAAS_TENANT_RUNTIME_TTL,
    )

    _app[APP_TENANT_REPOSITORY] = repository
    _app[APP_TENANT_RUNTIMES] = runtimes
    _app[APP_SECRET_STORE_FACTORY] = _secret_store
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


__all__ = ("APP_SECRET_STORE", "APP_SECRET_STORE_FACTORY", "setup_saas_api")
