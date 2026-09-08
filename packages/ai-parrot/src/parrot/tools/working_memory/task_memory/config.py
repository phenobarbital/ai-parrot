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

from typing import Any, FrozenSet, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Limits

__all__ = (
    "MIB",
    "DEFAULT_REDACTED_KEYS",
    "TaskMemoryConfig",
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
