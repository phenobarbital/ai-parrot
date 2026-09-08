"""Configuration for recoverable task memory (FEAT-538).

Task memory is **opt-in**. With no configuration the toolkit behaves
exactly as it does today: legacy schemas, legacy raw-result behaviour, no
task tools, no observer, no journal (spec AC13).

Every knob is read from ``navconfig`` under the ``TASK_MEMORY_*`` prefix
by :meth:`TaskMemoryConfig.from_env`, but a caller may also construct the
model directly — tests do, and so does any host that configures the
toolkit programmatically. Importing this module never touches the
network, a database or a file.

.. warning::

   Delivery A is **not durable**. Setting ``durable=True`` expresses an
   intent; it is honoured only once Delivery B's PostgreSQL store is
   wired in, and the store factory — not this module — performs the
   lazy backend availability check. Nothing here downgrades a durability
   request silently.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, FrozenSet, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Limits

__all__ = (
    "MIB",
    "DEFAULT_REDACTED_KEYS",
    "TaskMemoryConfig",
    "TaskMemoryRuntime",
    "DurableStartupError",
)

#: One mebibyte, for readable byte defaults.
MIB: int = 1024 * 1024

#: Key names always denied in journal payloads and offloaded content.
#: Stage 0 normalization is *not* a secret-redaction policy — this is
#: the additional redactor the spec requires on top of it.
DEFAULT_REDACTED_KEYS: FrozenSet[str] = frozenset(
    {
        "token",
        "secret",
        "password",
        "authorization",
        "api_key",
    }
)


class TaskMemoryConfig(BaseModel):
    """Opt-in configuration for the task-memory subsystem.

    Defaults reproduce the specification's §2 limits and §2 *Retention
    and Redaction* table exactly. Where Phase 0 (TASK-2970) measured a
    default, the measurement is cited on the field.

    Attributes:
        enabled: Master switch. ``False`` preserves every existing public
            schema, output, guardrail, permission and compression
            behaviour byte for byte.
        durable: Whether the PostgreSQL-backed durable stores are used.
            Delivery A rejects ``True``.
        best_effort_tracking: Explicit opt-in to continuing when the
            journal is unavailable. Degradation is then surfaced in the
            result (D8); it is never silent.
        snapshot_max_bytes: RAM snapshot cap. Governs the *optional* RAM
            copy only — in durable mode supported artifacts below the cap
            are still written through to durable storage, so raising it
            buys retained bytes, not durability.
        memory_cache_max_bytes: Byte-accounted LRU ceiling for retained
            in-memory artifact payloads.
        max_rehydrate_bytes: Hard ceiling for ``wm_get_result
            (include_raw=True)``. ``0`` means never rehydrate. A caller
            may lower this per call but can never raise it.
        raw_page_limit_default: Default page size for tabular raw reads.
        raw_page_limit_max: Maximum page size for tabular raw reads.
        recall_max_tokens: Default token budget for one recall.
        recall_max_tokens_ceiling: Largest budget a caller may request.
        recall_recent_calls_limit: Default number of recent calls in a
            recall.
        recall_recent_calls_ceiling: Largest recent-call count a caller
            may request.
        recall_cache_ttl_seconds: TTL for the recall cache.
        lease_ttl_seconds: TTL for a task append lease, renewed only by
            its owner.
        context_ttl_seconds: TTL for the cached turn context. The context
            cache is never authoritative for task state.
        inactivity_pause_days: Days without activity before an active
            task is paused. Reads do not reset activity.
        abandoned_cancel_days: Days after an inactivity pause before the
            task is cancelled, measured from that pause.
        terminal_retention_days: Days a terminal task's journal and
            projection are retained, measured from ``terminal_at``.
        unpinned_version_ttl_hours: How long an unpinned, non-current
            artifact version survives.
        orphan_blob_grace_hours: How long an orphan blob survives before
            sweeping, and only when nothing references it.
        journal_soft_limit: Event count above which recall stops
            retaining optional recent-call material.
        journal_hard_limit: Event count above which new foreground work
            is refused. History is never silently discarded.
        journal_reserved_events: Headroom above the hard limit kept for
            terminal, recovery and retention events.
        max_open_tasks_per_scope: Simultaneously open tasks per scope.
        archive_uri: Where terminal journals are archived as JSONL. With
            no URI, terminal deletion is deliberately irreversible (OQ1).
        extra_redacted_keys: Additional denied key names, merged with
            :data:`DEFAULT_REDACTED_KEYS`.
        validator_names: Code-registered completion validators available
            to ``validated`` completion policies.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    durable: bool = False
    best_effort_tracking: bool = False

    # ── snapshots and payloads ───────────────────────────────────────
    #: 64 MiB — confirmed by TASK-2970: fingerprinting a 64 MiB numeric
    #: frame costs ~2.3 s, a 256 MiB one ~9.5 s (OQ3 resolved).
    snapshot_max_bytes: int = Field(default=64 * MIB, ge=0)
    memory_cache_max_bytes: int = Field(default=512 * MIB, ge=0)
    max_rehydrate_bytes: int = Field(default=2_000_000, ge=0)
    raw_page_limit_default: int = Field(default=100, ge=1)
    raw_page_limit_max: int = Field(default=1_000, ge=1)

    # ── recall ───────────────────────────────────────────────────────
    recall_max_tokens: int = Field(default=2_500, ge=1)
    recall_max_tokens_ceiling: int = Field(default=16_000, ge=1)
    recall_recent_calls_limit: int = Field(default=8, ge=0)
    recall_recent_calls_ceiling: int = Field(default=100, ge=0)
    recall_cache_ttl_seconds: int = Field(default=600, ge=0)

    # ── redis key TTLs ───────────────────────────────────────────────
    lease_ttl_seconds: int = Field(default=30, ge=1)
    context_ttl_seconds: int = Field(default=86_400, ge=1)

    # ── retention ────────────────────────────────────────────────────
    inactivity_pause_days: int = Field(default=7, ge=1)
    abandoned_cancel_days: int = Field(default=30, ge=1)
    terminal_retention_days: int = Field(default=90, ge=1)
    unpinned_version_ttl_hours: int = Field(default=24, ge=1)
    orphan_blob_grace_hours: int = Field(default=1, ge=1)

    # ── journal capacity ─────────────────────────────────────────────
    journal_soft_limit: int = Field(default=50_000, ge=1)
    journal_hard_limit: int = Field(default=100_000, ge=1)
    journal_reserved_events: int = Field(default=1_000, ge=0)

    # ── scope capacity ───────────────────────────────────────────────
    max_open_tasks_per_scope: int = Field(default=Limits.MAX_OPEN_TASKS_PER_SCOPE, ge=1)

    # ── archive and redaction ────────────────────────────────────────
    #: PostgreSQL DSN. REQUIRED when ``durable`` is true — there is no
    #: silent fallback to the in-memory store, because a deployment that
    #: asked for durability and quietly got a dict is the worst outcome
    #: available: it looks healthy right up until the restart.
    dsn: Optional[str] = None
    #: Connection-pool bounds for the durable store.
    pool_min_size: int = Field(default=1, ge=1)
    pool_max_size: int = Field(default=10, ge=1)
    #: Root path segment for durable blobs.
    blob_prefix: str = "task_memory"
    #: Seconds between in-process retention sweeps. A host running a
    #: qworker should schedule ``run_once`` there instead and leave this
    #: loop stopped.
    retention_interval_seconds: float = Field(default=3600.0, gt=0)

    archive_uri: Optional[str] = None
    extra_redacted_keys: Tuple[str, ...] = ()
    validator_names: Tuple[str, ...] = (
        "artifact_exists",
        "artifact_fingerprint_matches",
        "artifact_non_empty",
        "no_pending_tool_failures",
    )

    @field_validator("extra_redacted_keys", "validator_names")
    @classmethod
    def _lowercase_names(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Normalize configured names to lower case.

        Args:
            value: The configured names.

        Returns:
            The normalized tuple.
        """
        return tuple(name.strip().lower() for name in value if name.strip())

    @model_validator(mode="after")
    def _check_consistency(self) -> "TaskMemoryConfig":
        """Validate cross-field invariants.

        Returns:
            The validated configuration.

        Raises:
            ValueError: If a ceiling is below its default or the journal
                soft limit is above the hard limit.

        Note:
            ``durable=True`` is accepted here but is only *honoured* once
            the Delivery B PostgreSQL store is wired in. The store
            factory performs the lazy ``asyncpg`` availability check and
            raises :class:`~parrot.tools.working_memory.task_memory.
            models.TaskMemoryUnavailable` when the backend is missing.
            Configuration validation deliberately does not guess at
            backend availability.
        """
        if self.journal_soft_limit > self.journal_hard_limit:
            raise ValueError(
                f"journal_soft_limit ({self.journal_soft_limit}) must not exceed "
                f"journal_hard_limit ({self.journal_hard_limit})"
            )
        if self.recall_max_tokens > self.recall_max_tokens_ceiling:
            raise ValueError(
                f"recall_max_tokens ({self.recall_max_tokens}) must not exceed "
                f"recall_max_tokens_ceiling ({self.recall_max_tokens_ceiling})"
            )
        if self.recall_recent_calls_limit > self.recall_recent_calls_ceiling:
            raise ValueError(
                f"recall_recent_calls_limit ({self.recall_recent_calls_limit}) must not exceed "
                f"recall_recent_calls_ceiling ({self.recall_recent_calls_ceiling})"
            )
        if self.raw_page_limit_default > self.raw_page_limit_max:
            raise ValueError(
                f"raw_page_limit_default ({self.raw_page_limit_default}) must not exceed "
                f"raw_page_limit_max ({self.raw_page_limit_max})"
            )
        if self.durable and not self.dsn:
            raise ValueError(
                "durable=True requires a dsn: task memory will not silently fall back to the "
                "in-memory store, because a deployment that asked for durability and got a dict "
                "looks healthy until the first restart"
            )
        if self.pool_min_size > self.pool_max_size:
            raise ValueError(
                f"pool_min_size ({self.pool_min_size}) must not exceed pool_max_size ({self.pool_max_size})"
            )
        if self.abandoned_cancel_days <= self.inactivity_pause_days:
            raise ValueError(
                "abandoned_cancel_days must be greater than inactivity_pause_days; "
                "cancellation is measured from the inactivity pause"
            )
        return self

    # ── derived accessors ────────────────────────────────────────────

    @property
    def redacted_keys(self) -> FrozenSet[str]:
        """Every denied key name: the built-ins plus configured additions."""
        return DEFAULT_REDACTED_KEYS | frozenset(self.extra_redacted_keys)

    def resolve_rehydrate_bytes(self, requested: Optional[int]) -> int:
        """Clamp a caller's raw-read budget to the configured ceiling.

        The configuration is a **hard ceiling**: a caller may lower it but
        cannot raise it. ``0`` means never rehydrate, and no request can
        reopen that.

        Args:
            requested: The caller's requested budget, or ``None`` to use
                the configured value.

        Returns:
            The effective byte budget.

        Raises:
            ValueError: If ``requested`` is negative.
        """
        if requested is None:
            return self.max_rehydrate_bytes
        if requested < 0:
            raise ValueError(f"max_rehydrate_bytes must be >= 0, got {requested}")
        return min(requested, self.max_rehydrate_bytes)

    def resolve_page_limit(self, requested: Optional[int]) -> int:
        """Clamp a tabular page size to the configured maximum.

        Args:
            requested: The caller's requested page size, or ``None``.

        Returns:
            The effective page size.

        Raises:
            ValueError: If ``requested`` is not positive.
        """
        if requested is None:
            return self.raw_page_limit_default
        if requested < 1:
            raise ValueError(f"limit must be >= 1, got {requested}")
        return min(requested, self.raw_page_limit_max)

    def is_journal_exhausted(self, event_count: int, *, reserved: bool = False) -> bool:
        """Whether the journal may still accept an event.

        Foreground work is refused before the reserved headroom is
        consumed, so terminal, recovery and retention events remain
        appendable. History is never silently discarded.

        Args:
            event_count: Events already appended to the task.
            reserved: Whether the event being appended is a reserved kind
                (terminal, recovery or retention).

        Returns:
            ``True`` when the append must be refused.
        """
        ceiling = self.journal_hard_limit + self.journal_reserved_events if reserved else self.journal_hard_limit
        return event_count >= ceiling

    @classmethod
    def from_env(cls, **overrides: Any) -> "TaskMemoryConfig":
        """Build a configuration from ``TASK_MEMORY_*`` navconfig values.

        Every field is optional: an absent variable keeps this class's
        default. Explicit ``overrides`` win over the environment, which
        is what lets a host configure the toolkit programmatically
        without unsetting variables.

        Args:
            **overrides: Field values that take precedence over the
                environment.

        Returns:
            The resolved configuration.
        """
        from navconfig import config

        def _int(name: str, default: int) -> int:
            return int(config.getint(f"TASK_MEMORY_{name}", fallback=default))

        def _bool(name: str, default: bool) -> bool:
            return bool(config.getboolean(f"TASK_MEMORY_{name}", fallback=default))

        def _str(name: str, default: Optional[str]) -> Optional[str]:
            value = config.get(f"TASK_MEMORY_{name}", fallback=default)
            return value or None

        defaults = cls.model_fields
        values: dict[str, Any] = {
            "enabled": _bool("ENABLED", defaults["enabled"].default),
            "durable": _bool("DURABLE", defaults["durable"].default),
            "best_effort_tracking": _bool("BEST_EFFORT_TRACKING", defaults["best_effort_tracking"].default),
            "snapshot_max_bytes": _int("SNAPSHOT_MAX_BYTES", defaults["snapshot_max_bytes"].default),
            "memory_cache_max_bytes": _int("MEMORY_CACHE_MAX_BYTES", defaults["memory_cache_max_bytes"].default),
            "max_rehydrate_bytes": _int("MAX_REHYDRATE_BYTES", defaults["max_rehydrate_bytes"].default),
            "raw_page_limit_default": _int("RAW_PAGE_LIMIT_DEFAULT", defaults["raw_page_limit_default"].default),
            "raw_page_limit_max": _int("RAW_PAGE_LIMIT_MAX", defaults["raw_page_limit_max"].default),
            "recall_max_tokens": _int("RECALL_MAX_TOKENS", defaults["recall_max_tokens"].default),
            "recall_max_tokens_ceiling": _int(
                "RECALL_MAX_TOKENS_CEILING", defaults["recall_max_tokens_ceiling"].default
            ),
            "recall_recent_calls_limit": _int(
                "RECALL_RECENT_CALLS_LIMIT", defaults["recall_recent_calls_limit"].default
            ),
            "recall_recent_calls_ceiling": _int(
                "RECALL_RECENT_CALLS_CEILING", defaults["recall_recent_calls_ceiling"].default
            ),
            "recall_cache_ttl_seconds": _int("RECALL_CACHE_TTL", defaults["recall_cache_ttl_seconds"].default),
            "lease_ttl_seconds": _int("LEASE_TTL", defaults["lease_ttl_seconds"].default),
            "context_ttl_seconds": _int("CONTEXT_TTL", defaults["context_ttl_seconds"].default),
            "inactivity_pause_days": _int("INACTIVITY_PAUSE_DAYS", defaults["inactivity_pause_days"].default),
            "abandoned_cancel_days": _int("ABANDONED_CANCEL_DAYS", defaults["abandoned_cancel_days"].default),
            "terminal_retention_days": _int("TERMINAL_RETENTION_DAYS", defaults["terminal_retention_days"].default),
            "unpinned_version_ttl_hours": _int(
                "UNPINNED_VERSION_TTL_HOURS", defaults["unpinned_version_ttl_hours"].default
            ),
            "orphan_blob_grace_hours": _int("ORPHAN_BLOB_GRACE_HOURS", defaults["orphan_blob_grace_hours"].default),
            "journal_soft_limit": _int("JOURNAL_SOFT_LIMIT", defaults["journal_soft_limit"].default),
            "journal_hard_limit": _int("JOURNAL_HARD_LIMIT", defaults["journal_hard_limit"].default),
            "journal_reserved_events": _int("JOURNAL_RESERVED_EVENTS", defaults["journal_reserved_events"].default),
            "max_open_tasks_per_scope": _int("MAX_OPEN_TASKS_PER_SCOPE", defaults["max_open_tasks_per_scope"].default),
            "archive_uri": _str("ARCHIVE_URI", None),
        }

        raw_keys = _str("EXTRA_REDACTED_KEYS", None)
        if raw_keys:
            values["extra_redacted_keys"] = tuple(part for part in (p.strip() for p in raw_keys.split(",")) if part)

        values.update(overrides)
        return cls(**values)


class DurableStartupError(RuntimeError):
    """A durable deployment could not satisfy its own prerequisites.

    Raised at startup rather than at the first append. The alternative —
    degrading to the in-memory store — is precisely the failure this
    feature exists to prevent: the deployment looks healthy, and the loss
    only becomes visible after the restart that was supposed to be
    survivable.
    """


class TaskMemoryRuntime:
    """Owns the durable backend graph and its background scheduling.

    This lives in the configuration module because it is the wiring the
    configuration describes: one place that turns a
    :class:`TaskMemoryConfig` into connected stores, and back again on
    shutdown. It builds **one** task store and **one** artifact store
    over it, so the toolkit, the observer and the plan factory all share
    the same backend and the same transaction coordinator (D1). Nothing
    here constructs a sibling artifact store.

    Ownership is tracked deliberately. A runtime handed a pool or a file
    manager by its host did not create them and must not close them:
    shutting down a bot should not tear down a connection pool the rest
    of the application is still using.

    Args:
        config: The resolved configuration.
        file_manager: Blob backend. Required when ``durable`` is true.
        association: Optional association store, for durable selection.
        pool: An existing asyncpg pool to borrow rather than create.
        archive: Optional :class:`ArchiveWriter`. Supplied by the host
            because the packaged writer is scope-bound while this runtime
            is not; see :meth:`_build_sweeper`.
    """

    def __init__(
        self,
        config: TaskMemoryConfig,
        *,
        file_manager: Optional[Any] = None,
        association: Optional[Any] = None,
        pool: Optional[Any] = None,
        archive: Optional[Any] = None,
    ) -> None:
        """Initialize the runtime without connecting to anything."""
        self.config = config
        self.association = association
        self._file_manager = file_manager
        self._archive = archive
        self._pool = pool
        #: A borrowed pool is not ours to close.
        self._owns_pool = pool is None
        self._owns_file_manager = False
        self.store: Optional[Any] = None
        self.artifacts: Optional[Any] = None
        self.blobs: Optional[Any] = None
        self.sweeper: Optional[Any] = None
        self.periodic: Optional[Any] = None
        self._started = False
        self._scopes: List[Any] = []
        self.logger = logging.getLogger(f"{__name__}.TaskMemoryRuntime")

    # ── lifecycle ────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Whether the runtime has completed startup."""
        return self._started

    async def start(self, *, start_scheduler: bool = True) -> "TaskMemoryRuntime":
        """Connect the backends and verify their prerequisites.

        Idempotent. Every prerequisite is checked BEFORE anything is
        scheduled, so a misconfigured deployment fails during startup
        with a message naming what is missing, rather than at the first
        append with something unreadable from inside a transaction.

        Args:
            start_scheduler: Whether to run the in-process retention
                loop. A host scheduling :meth:`run_once` from a qworker
                should pass ``False`` and leave the loop stopped.

        Returns:
            This runtime.

        Raises:
            DurableStartupError: If a durable prerequisite is missing.
        """
        if self._started:
            return self
        if not self.config.enabled:
            # Disabled is not an error and not a durable deployment; it
            # simply builds nothing.
            self._started = True
            return self

        if self.config.durable:
            await self._build_durable()
        else:
            self._build_in_memory()

        if start_scheduler and self.sweeper is not None:
            from .retention import PeriodicRetention

            self.periodic = PeriodicRetention(
                self.sweeper,
                lambda: tuple(self._scopes),
                interval_seconds=self.config.retention_interval_seconds,
            )
            await self.periodic.start()

        self._started = True
        return self

    async def _build_durable(self) -> None:
        """Construct and verify the PostgreSQL-backed graph.

        Raises:
            DurableStartupError: If asyncpg, the schema, the migration or
                the blob backend is unavailable.
        """
        from .models import TaskMemoryUnavailable

        if self._file_manager is None:
            raise DurableStartupError(
                "durable task memory requires a file_manager for blob storage; "
                "pass one explicitly (a shared persistent mount — a pod-local directory "
                "or TempFileManager is not durable)"
            )

        try:
            from .store.postgres import PostgresArtifactStore, PostgresTaskMemoryStore
        except ImportError as exc:  # pragma: no cover - import guard
            raise DurableStartupError(f"durable task memory could not import its PostgreSQL store: {exc}") from exc

        store = PostgresTaskMemoryStore(
            self.config.dsn,
            pool=self._pool,
            min_size=self.config.pool_min_size,
            max_size=self.config.pool_max_size,
            config=self.config,
        )
        try:
            # Names the missing table or migration; this is the check that
            # turns "you did not run the migration" into a startup error
            # instead of a confusing failure inside the first append.
            await store.verify_schema()
        except TaskMemoryUnavailable as exc:
            await self._safe_close(store)
            raise DurableStartupError(f"durable task memory prerequisites are not met: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - connection failures are startup failures
            await self._safe_close(store)
            raise DurableStartupError(f"durable task memory could not reach its database: {exc}") from exc

        from .blob import ArtifactBlobStore

        self.store = store
        self.blobs = ArtifactBlobStore(self._file_manager, prefix=self.config.blob_prefix)
        # ONE artifact store, over the SAME task store — which is what
        # makes them share a pool and a transaction coordinator.
        self.artifacts = PostgresArtifactStore(store, blobs=self.blobs, config=self.config)
        self.sweeper = self._build_sweeper(durable=True)

    def _build_in_memory(self) -> None:
        """Construct the non-durable graph (Delivery A)."""
        from .artifacts import InMemoryArtifactStore
        from .store.memory import InMemoryTaskMemoryStore

        self.store = InMemoryTaskMemoryStore(config=self.config)
        self.artifacts = InMemoryArtifactStore()
        self.sweeper = self._build_sweeper(durable=False)

    def _build_sweeper(self, *, durable: bool) -> Any:
        """Build the retention sweeper for the constructed backends.

        Args:
            durable: Whether the durable capabilities should be attached.

        Returns:
            The sweeper.
        """
        from .retention import RetentionSweeper

        # The archive writer is supplied by the host, not built here.
        # `JsonlArchiveWriter` binds a SCOPE at construction, while this
        # runtime is deliberately scope-agnostic (it sweeps whatever
        # scopes are tracked). Constructing one here could only bind a
        # single scope and would then archive every other scope's journal
        # under it — worse than not archiving at all, because the
        # verification step would still pass.
        archive = self._archive
        if durable and self.config.archive_uri and archive is None:
            self.logger.warning(
                "archive_uri is configured but no archive writer was supplied; terminal journals "
                "will NOT be archived. Pass archive= to TaskMemoryRuntime to enable it."
            )

        return RetentionSweeper(
            self.store,
            artifacts=self.artifacts,
            config=self.config,
            archive=archive,
            purge=self.store if durable and hasattr(self.store, "purge_task") else None,
        )

    def track_scope(self, scope: Any) -> None:
        """Register a scope for periodic sweeping.

        Args:
            scope: The scope to sweep on each cycle.
        """
        if scope not in self._scopes:
            self._scopes.append(scope)

    async def run_once(self, scopes: Optional[Sequence[Any]] = None) -> Any:
        """Run one retention sweep. The host-scheduler entry point.

        Exposed so a deployment with its own scheduler (a qworker, a
        cron) can drive retention without this package taking a queue
        dependency.

        Args:
            scopes: Scopes to sweep; the tracked scopes when omitted.

        Returns:
            The sweep report, or ``None`` when nothing is configured.
        """
        if self.sweeper is None:
            return None
        return await self.sweeper.run_once(tuple(scopes) if scopes is not None else tuple(self._scopes))

    def task_memory(self, scope: Any, **kwargs: Any) -> Any:
        """Build a composition root over the SHARED stores.

        Args:
            scope: The trusted runtime scope.
            **kwargs: Forwarded to :class:`TaskMemory`.

        Returns:
            The composition root.

        Raises:
            DurableStartupError: If the runtime has not been started.
        """
        if self.store is None or self.artifacts is None:
            raise DurableStartupError("task memory runtime has not been started; call await runtime.start() first")
        from .tools import TaskMemory

        kwargs.setdefault("association", self.association)
        return TaskMemory(self.store, self.artifacts, scope, self.config, **kwargs)

    async def stop(self) -> None:
        """Stop scheduling and close only what this runtime owns.

        Safe to call from a cancelled shutdown: each step is independent
        and reports rather than raises, so one failing close cannot skip
        the rest and leak the others.
        """
        if self.periodic is not None:
            try:
                await self.periodic.stop()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                self.logger.warning("task-memory retention loop did not stop cleanly", exc_info=True)
            self.periodic = None

        await self._release_leases()

        # The store is ALWAYS closed; it tracks pool ownership itself and
        # leaves a borrowed pool open. Gating this on the runtime's own
        # flag instead would skip the store's cleanup entirely whenever a
        # pool was borrowed, which is a different leak rather than a fix.
        await self._safe_close(self.store)
        if not self._owns_pool:
            self.logger.debug("task-memory pool was borrowed; the store leaves it open for its owner")
        if self._owns_file_manager:
            await self._safe_close(self._file_manager)

        self.store = None
        self.artifacts = None
        self.blobs = None
        self.sweeper = None
        self._started = False

    async def _release_leases(self) -> None:
        """Release leases this runtime owns, best effort."""
        association = self.association
        if association is None or not hasattr(association, "release_call"):
            return
        try:
            releaser = getattr(association, "release_owned", None)
            if releaser is not None:
                await releaser()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            self.logger.warning("task-memory lease release failed during shutdown", exc_info=True)

    async def _safe_close(self, resource: Optional[Any]) -> None:
        """Close a resource without letting shutdown fail.

        Args:
            resource: The resource, which may be ``None`` or may not have
                a ``close``.
        """
        closer = getattr(resource, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - shutdown must not raise
            self.logger.warning("task-memory resource did not close cleanly", exc_info=True)
