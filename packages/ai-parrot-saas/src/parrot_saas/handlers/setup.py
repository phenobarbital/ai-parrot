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
from .deployments import (
    APP_DEPLOYERS,
    APP_DEPLOYMENT_REPOSITORY,
    DeploymentApplyView,
    DeploymentPlanView,
    DeploymentView,
    default_deployers,
    setup_deployment_routes,
)
from .runs import (
    APP_RUN_LAUNCHER,
    APP_RUN_REPOSITORY,
    RunCollectionView,
    RunItemView,
    RunResumeView,
    setup_run_routes,
)
from .coupons import (
    APP_COUPON_DELIVERY,
    APP_COUPON_ISSUER,
    APP_COUPON_REPOSITORY,
    CouponCollectionView,
    CouponRedeemView,
    OfferCollectionView,
    OfferItemView,
    setup_coupon_routes,
)
from .rules import (
    APP_RULE_REPOSITORY,
    RuleCollectionView,
    RuleEvaluateView,
    RuleItemView,
    setup_rule_routes,
)
from .reviews import (
    APP_GUEST_REPOSITORY,
    APP_INGEST_SERVICE,
    APP_REVIEW_REPOSITORY,
    APP_REVIEW_SOURCES,
    ReviewCollectionView,
    ReviewItemView,
    ReviewSimulateView,
    setup_review_routes,
)
from .secrets import (
    APP_SECRET_STORE_FACTORY,
    SecretCollectionView,
    SecretItemView,
    SecretRotateView,
    setup_secret_routes,
)
from .tenants import (
    APP_TENANT_REPOSITORY,
    APP_TENANT_RUNTIMES,
    TenantCollectionView,
    TenantItemView,
    setup_tenant_routes,
)

#: Key under which the secret store is published. Absent until the store has
#: actually been built — handlers should go through ``APP_SECRET_STORE_FACTORY``
#: (defined alongside the views that use it, in :mod:`.secrets`).
APP_SECRET_STORE = "saas_secret_store"

logger = logging.getLogger("parrot_saas.handlers.setup")


def _make_runtime_builder(
    secret_store_factory: Any,
    tool_manager_template: Optional[Any] = None,
    rule_repository: Optional[Any] = None,
):
    """Build the default per-tenant runtime builder.

    The secret store arrives as a *factory* rather than an instance so that a
    deployment without vault keys still starts: the store is only constructed
    when a tenant actually needs its credentials.

    Args:
        secret_store_factory: Zero-argument callable returning the store, or
            ``None`` when no store is configured.
        tool_manager_template: Template manager cloned per tenant, if any.
        rule_repository: Repository the tenant's eligibility ruleset is
            compiled from, if any.

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

        ruleset = None
        if rule_repository is not None:
            from ..rules.builder import build_ruleset
            from ..rules.repository import PostgresRuleStorage

            try:
                specs = await PostgresRuleStorage(
                    rule_repository, tenant.tenant_id
                ).load()
                # build_ruleset skips rules it cannot compile rather than
                # raising: one bad row a tenant saved must not take their whole
                # flow down, and an empty ruleset reads as "no coupon", which
                # is the safe answer.
                ruleset = build_ruleset(specs)
            except Exception as exc:  # noqa: BLE001 - degrade, do not 500
                logger.error(
                    "could not load the eligibility ruleset for tenant %s: %s",
                    tenant.tenant_id,
                    exc,
                )

        return TenantRuntime(
            tenant=tenant,
            tool_manager=tool_manager,
            agents=agents,
            ruleset=ruleset,
            semaphore=asyncio.Semaphore(conf.SAAS_TENANT_MAX_CONCURRENT_RUNS),
        )

    return _build


class _LazyStore:
    """Resolve the secret store on use rather than at wiring time.

    ``setup_saas_api`` deliberately defers building the encrypted store —
    ``EnvelopeCipher.from_environment()`` raises with no master key, and that
    must not stop the application booting. Anything holding the store therefore
    has to hold the factory instead.
    """

    __slots__ = ("_factory",)

    def __init__(self, factory: Any) -> None:
        self._factory = factory

    async def put(self, tenant_id: str, key: str, value: str) -> Any:
        """Store a secret, resolving the backing store on first use."""
        return await self._factory().put(tenant_id, key, value)

    async def delete(self, tenant_id: str, key: str) -> bool:
        """Remove a secret."""
        return await self._factory().delete(tenant_id, key)


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
    review_sources: Optional[Any] = None,
    run_launcher: Optional[Any] = None,
    job_manager: Optional[Any] = None,
    checkpoint_runs: bool = False,
    checkpoint_store: Optional[Any] = None,
    durable_runs: bool = False,
    durable_store: Optional[Any] = None,
    result_storage: Optional[Any] = None,
    deployers: Optional[dict] = None,
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
        review_sources: Mapping of adapter name to ``ReviewSource``. Defaults
            to the in-memory mock plus the signed generic webhook.
        run_launcher: Coroutine started for each newly admitted review. Without
            one, reviews are stored and a warning says no flow ran — see
            ``parrot_saas.reviews.ingest.null_run_launcher``.
        job_manager: Job manager used to run launches off the request. Defaults
            to ``app['job_manager']`` when the jobs subsystem is configured;
            without one the launcher is awaited inline.
        checkpoint_runs: Checkpoint each node of a flow run. Off by default:
            it costs a store round trip per node, and it only earns that back
            once resume works for this graph's custom node types.
        checkpoint_store: Ephemeral checkpoint store (name or instance).
        durable_runs: Also write checkpoints through to a durable store.
        durable_store: The durable store (name or instance).
        result_storage: ``ResultStorage`` for the execution audit rows.
            Defaults to Postgres on the SaaS DSN.
        deployers: Mapping of tenancy mode to :class:`TenantDeployer`.
            Defaults to a shared deployer only; add ``dedicated`` to enable
            Pulumi provisioning.
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

    from ..coupons.issuer import CouponIssuer
    from ..coupons.repository import CouponRepository
    from ..rules.repository import RuleRepository

    rule_repository = RuleRepository(resolved_dsn, schema=resolved_schema)
    coupon_repository = CouponRepository(resolved_dsn, schema=resolved_schema)
    coupon_issuer = CouponIssuer(coupon_repository)

    runtimes = TenantRuntimeCache(
        runtime_builder
        or _make_runtime_builder(
            _secret_store, tool_manager_template, rule_repository
        ),
        max_size=conf.SAAS_TENANT_RUNTIME_MAX,
        ttl=conf.SAAS_TENANT_RUNTIME_TTL,
    )

    _app[APP_TENANT_REPOSITORY] = repository
    _app[APP_TENANT_RUNTIMES] = runtimes
    _app[APP_SECRET_STORE_FACTORY] = _secret_store
    _app[APP_RULE_REPOSITORY] = rule_repository
    _app[APP_COUPON_REPOSITORY] = coupon_repository
    _app[APP_COUPON_ISSUER] = coupon_issuer

    if review_sources is None:
        from ..reviews.mock import MockReviewSource
        from ..reviews.webhook import GenericWebhookReviewSource

        review_sources = {
            "mock": MockReviewSource(),
            "webhook": GenericWebhookReviewSource(),
        }
    _app[APP_REVIEW_SOURCES] = review_sources

    from ..reviews.ingest import ReviewIngestService
    from ..reviews.repository import GuestRepository, ReviewRepository

    review_repository = ReviewRepository(resolved_dsn, schema=resolved_schema)
    guest_repository = GuestRepository(resolved_dsn, schema=resolved_schema)
    _app[APP_REVIEW_REPOSITORY] = review_repository
    _app[APP_GUEST_REPOSITORY] = guest_repository

    # Built here rather than per run: it holds provider connection options
    # (SMTP credentials, an SMS token) that belong to the deployment, not to a
    # tenant, and it resolves the guest's contact handle itself at send time so
    # that no address ever enters the flow's shared state.
    from ..coupons.delivery import CouponDelivery

    _app[APP_COUPON_DELIVERY] = CouponDelivery(
        guest_repository=guest_repository,
        coupon_repository=coupon_repository,
    )

    from parrot.bots.flows.core.storage.backends.postgres import (
        PostgresResultStorage,
    )

    from ..runs.repository import RunRepository

    run_repository = RunRepository(resolved_dsn, schema=resolved_schema)
    _app[APP_RUN_REPOSITORY] = run_repository

    from ..provisioning.repository import DeploymentRepository
    from ..provisioning.shared import SharedDeployer

    deployment_repository = DeploymentRepository(
        resolved_dsn, schema=resolved_schema
    )
    _app[APP_DEPLOYMENT_REPOSITORY] = deployment_repository
    # The dedicated deployer is opt-in: it shells out to the Pulumi CLI and
    # talks to a Docker daemon, neither of which a shared-only deployment has
    # any reason to require. Absent, a dedicated tenant's provision request is
    # a 503 naming the modes that *are* configured — which is a wiring mistake
    # someone can read, rather than a stack trace.
    if deployers is None:
        dedicated = None
        if conf.SAAS_ENABLE_DEDICATED:
            from ..provisioning.pulumi_deployer import PulumiDeployer

            # The secret store is passed as the *factory*'s product rather than
            # the factory: the deployer only touches it after a stack is up, by
            # which point a missing vault key is a real failure to report — not
            # something to defer past, as it is on the request path.
            dedicated = PulumiDeployer(secret_store=_LazyStore(_secret_store))
        deployers = default_deployers(
            shared=SharedDeployer(
                rules=rule_repository,
                coupons=coupon_repository,
                runtimes=runtimes,
            ),
            dedicated=dedicated,
        )
    _app[APP_DEPLOYERS] = deployers

    if run_launcher is None:
        # Without this the ingest path stores reviews and warns that nothing
        # ran. Building the runner here rather than leaving that default in
        # place is what turns an admitted review into an answered one.
        from ..flows.community_manager.runner import CommunityManagerRunner

        run_launcher = CommunityManagerRunner(
            runtimes=runtimes,
            runs=run_repository,
            reviews=review_repository,
            guests=guest_repository,
            coupons=coupon_repository,
            issuer=coupon_issuer,
            delivery=_app[APP_COUPON_DELIVERY],
            review_sources=review_sources,
            checkpoint=checkpoint_runs,
            checkpoint_store=checkpoint_store,
            durable=durable_runs,
            durable_store=durable_store,
            # AgentsFlow sets no result storage of its own — only AgentCrew
            # does — so the execution audit rows would otherwise go to the
            # process-wide default backend rather than this plane's database.
            result_storage=result_storage
            or PostgresResultStorage(resolved_dsn),
        )
    _app[APP_INGEST_SERVICE] = ReviewIngestService(
        reviews=review_repository,
        guests=guest_repository,
        # Resolved at wiring time, so a deployment that configures the jobs
        # subsystem after this call gets the inline path. app.py configures it
        # first (line 131), long before the SaaS plane.
        job_manager=job_manager or _app.get("job_manager"),
        run_launcher=run_launcher,
    )
    # Published so the resume route reaches the same runner the ingest path
    # uses — one object, one runtime cache, one set of repositories.
    _app[APP_RUN_LAUNCHER] = run_launcher
    if secret_store is not None:
        _app[APP_SECRET_STORE] = secret_store

    if require_auth:
        _apply_auth(
            TenantCollectionView,
            TenantItemView,
            SecretCollectionView,
            SecretItemView,
            SecretRotateView,
            # ReviewWebhookView is deliberately absent: it authenticates with
            # an HMAC signature, not a session, and applying the decorators
            # would make every platform delivery a 401.
            ReviewCollectionView,
            ReviewItemView,
            ReviewSimulateView,
            RuleCollectionView,
            RuleEvaluateView,
            RuleItemView,
            OfferCollectionView,
            OfferItemView,
            CouponCollectionView,
            CouponRedeemView,
            RunCollectionView,
            RunItemView,
            RunResumeView,
            DeploymentView,
            DeploymentPlanView,
            DeploymentApplyView,
        )

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
    setup_secret_routes(_app)
    setup_review_routes(_app)
    setup_rule_routes(_app)
    setup_coupon_routes(_app)
    setup_run_routes(_app)
    setup_deployment_routes(_app)

    async def _on_startup(application: web.Application) -> None:
        """Create the SaaS schema if it does not exist."""
        from ..db.schema import ensure_schema

        async with repository.acquire() as conn:
            await ensure_schema(conn, schema=resolved_schema)

    async def _on_cleanup(application: web.Application) -> None:
        """Release the runtime cache, repository and secret store."""
        await runtimes.aclose_all()
        await repository.aclose()
        await review_repository.aclose()
        await guest_repository.aclose()
        await rule_repository.aclose()
        await coupon_repository.aclose()
        await run_repository.aclose()
        await deployment_repository.aclose()
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


__all__ = (
    "APP_COUPON_DELIVERY",
    "APP_DEPLOYERS",
    "APP_DEPLOYMENT_REPOSITORY",
    "APP_COUPON_ISSUER",
    "APP_COUPON_REPOSITORY",
    "APP_INGEST_SERVICE",
    "APP_GUEST_REPOSITORY",
    "APP_REVIEW_REPOSITORY",
    "APP_RULE_REPOSITORY",
    "APP_RUN_LAUNCHER",
    "APP_RUN_REPOSITORY",
    "APP_REVIEW_SOURCES",
    "APP_SECRET_STORE",
    "APP_SECRET_STORE_FACTORY",
    "setup_saas_api",
)
