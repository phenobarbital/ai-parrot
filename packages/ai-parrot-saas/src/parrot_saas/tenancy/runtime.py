"""Per-tenant live state, and the bounded cache that owns its lifetime.

A :class:`TenantRuntime` holds what cannot be shared across tenants: LLM
clients constructed with that tenant's own API key, a ``ToolManager`` whose
cached credential state must not leak, and a compiled navrules ruleset.

FEAT-183 rejected per-tenant ``FormRegistry`` instances, and that rejection
does not transfer here. A ``FormSchema`` is inert data that can live in one
dict keyed by ``(tenant, form_id)``; a live Anthropic client built with a
customer's key cannot. There is no single-instance formulation — you need N
clients regardless — so this fleets deliberately, and bounds it.

Two lifetime hazards are handled explicitly, because both fail quietly:

* **Eviction must not kill a run in flight.** Flow nodes hold their agent by
  reference, so closing a runtime underneath an executing flow would surface
  as a confusing client error rather than as an eviction. Runs take a lease
  (:meth:`TenantRuntime.acquire`) and the cache skips any runtime with active
  leases.
* **``ToolManager.clone()`` drops the guards.** It carries tools, resolver and
  broker across, but not ``_grant_guard`` or ``_confirmation_guard`` — a clone
  silently runs without those checks unless they are reapplied.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional

from navconfig.logging import logging

from .context import TenantContext
from .registry import TenantAgentRegistry

logger = logging.getLogger("parrot_saas.tenancy.runtime")


@dataclass
class TenantRuntime:
    """Live, tenant-scoped state shared by everything serving one tenant.

    Attributes:
        tenant: The tenant this runtime serves.
        tool_manager: A per-tenant clone of the process-wide template.
        agent_registry: Lookup for this tenant's configured agents.
        agents: Configured agents by role (``"triage"``, ``"reply_draft"``).
        ruleset: Compiled navrules ``RuleSet`` for coupon eligibility.
        ruleset_version: Version the ruleset was compiled from; compared
            against the stored version to rebuild lazily after a rule edit.
        semaphore: Bounds concurrent flow runs for this tenant. The scheduler
            enforces no concurrency cap of its own, so ingestion throttles
            here.
        created_at: Monotonic creation time.
        last_used_at: Monotonic time of the most recent lease.
    """

    tenant: TenantContext
    tool_manager: Optional[Any] = None
    agent_registry: Optional[TenantAgentRegistry] = None
    agents: Dict[str, Any] = field(default_factory=dict)
    ruleset: Optional[Any] = None
    ruleset_version: int = 0
    semaphore: Optional[asyncio.Semaphore] = None
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)

    _leases: int = field(default=0, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Fill in the per-tenant registry when one was not supplied."""
        if self.agent_registry is None:
            self.agent_registry = TenantAgentRegistry(
                self.tenant.tenant_id, self.agents
            )

    @property
    def tenant_id(self) -> str:
        """Slug of the tenant this runtime serves."""
        return self.tenant.tenant_id

    @property
    def in_use(self) -> bool:
        """Whether any run currently holds a lease."""
        return self._leases > 0

    @property
    def closed(self) -> bool:
        """Whether :meth:`aclose` has already run."""
        return self._closed

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator["TenantRuntime"]:
        """Hold a lease for the duration of a run.

        While any lease is held the cache will not evict this runtime, so a
        long flow cannot have its agents closed underneath it. Also acquires
        the concurrency semaphore when one is configured.

        Yields:
            This runtime.

        Raises:
            RuntimeError: If the runtime has already been closed.
        """
        if self._closed:
            raise RuntimeError(
                f"tenant runtime for {self.tenant_id!r} is closed"
            )
        self._leases += 1
        self.last_used_at = time.monotonic()
        try:
            if self.semaphore is not None:
                async with self.semaphore:
                    yield self
            else:
                yield self
        finally:
            self._leases -= 1
            self.last_used_at = time.monotonic()

    async def aclose(self) -> None:
        """Release everything this runtime holds.

        Idempotent: eviction, shutdown and an explicit invalidate can all
        reach it, and a second call must not raise.

        ``cleanup`` is tried first and is the one that matters. Bots have no
        ``aclose`` or ``close`` at all, and ``AbstractBot.shutdown`` is an
        empty stub (``BasicAgent`` overrides it only to disconnect MCP), so a
        teardown that stopped at ``shutdown`` would leak the tenant's LLM
        connection pool on every eviction. ``AbstractBot.cleanup`` closes the
        client and its session, the vector store and the knowledge bases, and
        disconnects MCP as well — a strict superset.
        """
        if self._closed:
            return
        self._closed = True

        for name, agent in list(self.agents.items()):
            for method in ("cleanup", "aclose", "close", "shutdown"):
                closer = getattr(agent, method, None)
                if closer is None:
                    continue
                try:
                    result = closer()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:  # noqa: BLE001 - teardown is best-effort
                    logger.warning(
                        "closing agent %s for tenant %s failed: %s",
                        name,
                        self.tenant_id,
                        exc,
                    )
                break

        if self.tool_manager is not None:
            for method in ("close_executors", "cleanup_toolkits"):
                closer = getattr(self.tool_manager, method, None)
                if closer is None:
                    continue
                try:
                    await closer()
                except Exception as exc:  # noqa: BLE001 - teardown is best-effort
                    logger.warning(
                        "tool_manager.%s() failed for tenant %s: %s",
                        method,
                        self.tenant_id,
                        exc,
                    )
        logger.debug("tenant runtime closed: %s", self.tenant_id)


#: Signature of the callable that builds a runtime for a tenant.
RuntimeBuilder = Callable[[TenantContext], Awaitable[TenantRuntime]]


class TenantRuntimeCache:
    """Bounded, concurrency-safe cache of per-tenant runtimes.

    Args:
        builder: Coroutine building a runtime for a tenant.
        max_size: Maximum live runtimes. Each holds open HTTP clients, so this
            bounds file descriptors and memory.
        ttl: Seconds of inactivity after which a runtime becomes evictable.
    """

    def __init__(
        self,
        builder: RuntimeBuilder,
        *,
        max_size: int = 64,
        ttl: float = 1800.0,
    ) -> None:
        self._builder = builder
        self._max_size = max_size
        self._ttl = ttl
        self._runtimes: Dict[str, TenantRuntime] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()
        self.logger = logging.getLogger("parrot_saas.tenancy.cache")

    def __len__(self) -> int:
        """Number of live runtimes."""
        return len(self._runtimes)

    def __contains__(self, tenant_id: str) -> bool:
        """Whether a runtime is currently cached for ``tenant_id``."""
        return tenant_id in self._runtimes

    async def _lock_for(self, tenant_id: str) -> asyncio.Lock:
        """Return the per-tenant build lock, creating it once."""
        async with self._guard:
            return self._locks.setdefault(tenant_id, asyncio.Lock())

    async def get(self, tenant: TenantContext) -> TenantRuntime:
        """Return the tenant's runtime, building it if necessary.

        Concurrency-safe: a burst of simultaneous requests for a cold tenant
        builds exactly one runtime. The double check inside the lock is what
        makes that true — without it, every waiter would build its own on
        acquiring the lock.

        Args:
            tenant: The tenant to serve.

        Returns:
            The live runtime.
        """
        existing = self._runtimes.get(tenant.tenant_id)
        if existing is not None and not existing.closed:
            existing.last_used_at = time.monotonic()
            return existing

        lock = await self._lock_for(tenant.tenant_id)
        async with lock:
            existing = self._runtimes.get(tenant.tenant_id)
            if existing is not None and not existing.closed:
                existing.last_used_at = time.monotonic()
                return existing

            runtime = await self._builder(tenant)
            self._runtimes[tenant.tenant_id] = runtime
            self.logger.info("built tenant runtime: %s", tenant.tenant_id)

        # Protect the runtime we are about to hand back. Without this, a cache
        # at capacity whose other entries are all busy would evict the only
        # evictable runtime — the one just built — and the caller would receive
        # a closed runtime.
        await self._evict_if_needed(protect=tenant.tenant_id)
        return runtime

    async def invalidate(self, tenant_id: str) -> bool:
        """Drop a tenant's runtime so the next request rebuilds it.

        Called when configuration, secrets or rules change.

        Args:
            tenant_id: Tenant to invalidate.

        Returns:
            ``True`` if a runtime was dropped.
        """
        runtime = self._runtimes.pop(tenant_id, None)
        if runtime is None:
            return False
        await self._close_when_idle(runtime)
        return True

    async def _evict_if_needed(self, *, protect: Optional[str] = None) -> None:
        """Evict expired and surplus runtimes.

        Two things are never evicted:

        * a runtime with an active lease — a run in flight holds its agents by
          reference, so closing underneath it would surface as a provider
          error rather than as an eviction;
        * ``protect`` — the runtime the caller is about to be handed.

        When nothing is evictable the cache deliberately exceeds its capacity.
        Breaching a soft memory bound is recoverable; severing a live run is
        not.

        Args:
            protect: Tenant whose runtime must survive this pass.
        """
        now = time.monotonic()

        for tenant_id, runtime in list(self._runtimes.items()):
            if runtime.in_use or tenant_id == protect:
                continue
            if now - runtime.last_used_at > self._ttl:
                self._runtimes.pop(tenant_id, None)
                await self._close_when_idle(runtime)
                self.logger.info("evicted idle tenant runtime: %s", tenant_id)

        while len(self._runtimes) > self._max_size:
            evictable = [
                (tid, rt)
                for tid, rt in self._runtimes.items()
                if not rt.in_use and tid != protect
            ]
            if not evictable:
                self.logger.warning(
                    "tenant runtime cache is over capacity (%d/%d) but no "
                    "runtime is evictable; deferring",
                    len(self._runtimes),
                    self._max_size,
                )
                return
            tenant_id, runtime = min(evictable, key=lambda kv: kv[1].last_used_at)
            self._runtimes.pop(tenant_id, None)
            await self._close_when_idle(runtime)
            self.logger.info("evicted LRU tenant runtime: %s", tenant_id)

    async def _close_when_idle(self, runtime: TenantRuntime) -> None:
        """Close a runtime, deferring while a run still holds a lease."""
        if runtime.in_use:
            asyncio.create_task(self._close_later(runtime))
            return
        await runtime.aclose()

    async def _close_later(
        self, runtime: TenantRuntime, *, poll: float = 1.0, attempts: int = 60
    ) -> None:
        """Wait for a runtime's leases to drain, then close it."""
        for _ in range(attempts):
            if not runtime.in_use:
                await runtime.aclose()
                return
            await asyncio.sleep(poll)
        self.logger.warning(
            "tenant runtime %s still in use after %.0fs; closing anyway",
            runtime.tenant_id,
            poll * attempts,
        )
        await runtime.aclose()

    async def aclose_all(self) -> None:
        """Close every runtime. Intended for the app's ``on_cleanup``."""
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        self._locks.clear()
        for runtime in runtimes:
            await runtime.aclose()


def clone_tool_manager(
    template: Any,
    *,
    broker: Optional[Any] = None,
    grant_guard: Optional[Any] = None,
    confirmation_guard: Optional[Any] = None,
    include_search_tool: bool = False,
) -> Any:
    """Clone a template ``ToolManager`` for one tenant, restoring its guards.

    ``ToolManager.clone()`` exists for exactly this — its docstring names
    per-user session isolation over HTTP so that "credential state cached on
    the manager cannot leak across concurrent users". It shares the tool
    instances (identical LLM schemas, nothing re-parsed), the resolver, the
    broker and the compression registry, and gives the clone fresh dataframe,
    MCP and compression state.

    **It does not carry ``_grant_guard`` or ``_confirmation_guard``.** A clone
    therefore runs without bounded-approval and sensitive-action confirmation
    unless they are reapplied — a silent security downgrade, since nothing
    fails and no warning is logged. Reapplying them is the whole reason this
    helper exists rather than calling ``clone()`` directly.

    Args:
        template: The process-wide template manager.
        broker: Per-tenant credential broker, typically built over the
            tenant-scoped ``SecretStoreVault``.
        grant_guard: Guard to reapply; defaults to the template's.
        confirmation_guard: Guard to reapply; defaults to the template's.
        include_search_tool: Forwarded to ``clone()``.

    Returns:
        The tenant's own tool manager.
    """
    clone = template.clone(include_search_tool=include_search_tool)

    grant = grant_guard if grant_guard is not None else getattr(
        template, "_grant_guard", None
    )
    confirmation = confirmation_guard if confirmation_guard is not None else (
        getattr(template, "_confirmation_guard", None)
    )
    if grant is not None and hasattr(clone, "set_grant_guard"):
        clone.set_grant_guard(grant)
    if confirmation is not None and hasattr(clone, "set_confirmation_guard"):
        clone.set_confirmation_guard(confirmation)
    if broker is not None and hasattr(clone, "set_broker"):
        clone.set_broker(broker)
    return clone


__all__ = (
    "RuntimeBuilder",
    "TenantRuntime",
    "TenantRuntimeCache",
    "clone_tool_manager",
)
