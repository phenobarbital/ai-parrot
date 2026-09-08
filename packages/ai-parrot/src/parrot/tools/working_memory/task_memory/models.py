"""Domain models for recoverable task memory (FEAT-538, Delivery A).

This is a **leaf module**: it imports stdlib, ``pydantic`` and ``orjson``
only. It must never import a concrete backend (PostgreSQL, Redis, a REPL
worker), ``pandas``, or the working-memory toolkit — the dependency runs
the other way. Keeping it leaf-safe is what lets the store, reducer,
observer and tool layers all share one vocabulary without an import cycle.

Everything here follows the specification's §2 *Data Models*:

- Pydantic v2 models with ``schema_version = 1`` and ``extra="forbid"``.
- Timezone-aware UTC timestamps; naive datetimes are rejected, never
  silently localized.
- Runtime identities from stdlib :func:`uuid.uuid4` — Python 3.11 rules
  out assuming a stdlib ``uuid7`` and no ULID dependency is introduced.
- Bounded collections and text. Exceeding a bound raises the typed
  :class:`LimitExceeded` **before** any mutation is attempted.
- Derived state (a task's active/ready step ids) is computed, never
  persisted as a duplicate list.

.. warning::

   Delivery A is **not durable**. These models describe in-process
   continuity; durability arrives with Delivery B's PostgreSQL store,
   blob write-through and crash reconciliation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

import orjson
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = (
    # version
    "SCHEMA_VERSION",
    # enums
    "Actor",
    "Attribution",
    "ArtifactAvailability",
    "ArtifactKind",
    "CallOutcome",
    "CompletionMode",
    "CompletionSource",
    "EventType",
    "StepStatus",
    "TaskStatus",
    # limits + errors
    "Limits",
    "TaskMemoryError",
    "LimitExceeded",
    "RevisionConflict",
    "ReducerError",
    "ScopeViolation",
    "PlanValidationError",
    "UnknownValidatorError",
    "CursorError",
    "TaskMemoryUnavailable",
    # core models
    "TaskScope",
    "EvidenceRef",
    "Constraint",
    "CompletionPolicy",
    "TaskStep",
    "Decision",
    "ResumeHint",
    "TaskState",
    "ArtifactDescriptor",
    "ReplBinding",
    "TaskContext",
    "InvocationRecord",
    # journal
    "JournalEvent",
    "EventPayload",
    "TaskLifecyclePayload",
    "PlanUpdatePayload",
    "PlanStepSpec",
    "PlanStepPatch",
    "PlanConstraintSpec",
    "DecisionPayload",
    "ResumeHintPayload",
    "StepPayload",
    "ToolCallPayload",
    "ArtifactPayload",
    "DegradedPayload",
    "RetentionPayload",
    "PAYLOAD_FAMILY_BY_EVENT",
    # plan changes
    "InitialStepSpec",
    "AddStep",
    "UpdateStep",
    "SupersedeStep",
    "AddConstraint",
    "UpdateConstraint",
    "DeactivateConstraint",
    "SetPlanComplete",
    "PlanChange",
    "PlanChanges",
    # helpers
    "new_id",
    "utc_now",
    "serialized_bytes",
)

#: Schema version stamped on every persisted domain model. A document
#: carrying any other value is rejected rather than best-effort parsed.
SCHEMA_VERSION: int = 1


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def new_id() -> str:
    """Return a fresh runtime identity.

    Returns:
        A ``uuid4`` hex string. Deliberately stdlib: Python 3.11 has no
        ``uuid7`` and this feature introduces no ULID dependency.
    """
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        ``datetime.now(timezone.utc)``.
    """
    return datetime.now(timezone.utc)


def serialized_bytes(value: Any) -> int:
    """Return the canonical serialized UTF-8 size of ``value`` in bytes.

    Payload limits are byte limits, not Pydantic dictionary-item counts
    (spec §2). ``orjson`` with sorted keys is the canonical serializer
    used throughout the feature.

    Args:
        value: Any JSON-serializable value.

    Returns:
        Length in bytes of the canonical encoding.

    Raises:
        LimitExceeded: If the value cannot be serialized at all, which
            makes its size unbounded and therefore unacceptable.
    """
    try:
        return len(orjson.dumps(value, option=orjson.OPT_SORT_KEYS, default=str))
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise LimitExceeded("payload", -1, -1, f"value is not serializable: {exc}") from exc


def _require_utc(value: datetime) -> datetime:
    """Validate that ``value`` is timezone aware and normalize it to UTC.

    Args:
        value: The datetime to check.

    Returns:
        The same instant expressed in UTC.

    Raises:
        ValueError: If ``value`` is naive.
    """
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware UTC; naive datetimes are rejected")
    return value.astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────


class TaskStatus(str, Enum):
    """Lifecycle state of a task (spec §2)."""

    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Whether this status accepts no further ordinary mutation."""
        return self in _TERMINAL_TASK_STATUSES


_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


class StepStatus(str, Enum):
    """Lifecycle state of a plan step (spec §2)."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"

    @property
    def is_terminal(self) -> bool:
        """Whether this step will not transition again on its own."""
        return self in _TERMINAL_STEP_STATUSES


_TERMINAL_STEP_STATUSES = frozenset({StepStatus.COMPLETED, StepStatus.CANCELLED, StepStatus.SUPERSEDED})


class ArtifactAvailability(str, Enum):
    """Where an artifact version's bytes currently are.

    ``missing``/``expired`` describe the *payload*. Invalidation and
    ``binding_invalid`` are separate descriptor flags — a stale REPL
    binding is not proof that durable bytes disappeared (spec §2).
    """

    MEMORY = "memory"
    PERSISTED = "persisted"
    MISSING = "missing"
    EXPIRED = "expired"


class ArtifactKind(str, Enum):
    """Evidence type of an artifact version.

    Only ``DATAFRAME``, ``JSON`` and ``TEXT`` are *supported evidence*:
    they have a reproducible canonical fingerprint. ``BINARY`` and
    ``OBJECT`` can be catalogued but never carry a verified fingerprint.
    """

    DATAFRAME = "dataframe"
    JSON = "json"
    TEXT = "text"
    BINARY = "binary"
    OBJECT = "object"

    @property
    def is_supported_evidence(self) -> bool:
        """Whether this kind can produce a verifiable fingerprint."""
        return self in _SUPPORTED_EVIDENCE_KINDS


_SUPPORTED_EVIDENCE_KINDS = frozenset({ArtifactKind.DATAFRAME, ArtifactKind.JSON, ArtifactKind.TEXT})


class Actor(str, Enum):
    """Who caused an event (spec §2)."""

    AGENT = "agent"
    RUNTIME = "runtime"
    VALIDATOR = "validator"
    SWEEPER = "sweeper"


class Attribution(str, Enum):
    """How an invocation was attributed to a step (D3).

    Attribution never completes a step; it only records what the runtime
    could truthfully say about which step a call belonged to.
    """

    DECLARED = "declared"
    PLAN = "plan"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


class CompletionMode(str, Enum):
    """How a step is allowed to be completed."""

    VALIDATED = "validated"
    AGENT_ASSERTED = "agent_asserted"


class CompletionSource(str, Enum):
    """How a step actually *was* completed.

    Recall always labels ``AGENT_ASSERTED`` as the weaker source.
    """

    VALIDATED = "validated"
    AGENT_ASSERTED = "agent_asserted"


class CallOutcome(str, Enum):
    """Typed outcome of one physical dispatch attempt.

    ``NOT_EXECUTED`` covers the manager's early returns (unknown tool,
    guard denial, authorization required): the dispatch was unsuccessful
    but no tool body ran. ``UNKNOWN`` covers a started call whose terminal
    result could not be established — it is never automatically retried.
    """

    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    NOT_EXECUTED = "not_executed"

    @property
    def is_resolved(self) -> bool:
        """Whether this outcome settles the attempt's disposition."""
        return self not in _UNRESOLVED_OUTCOMES


_UNRESOLVED_OUTCOMES = frozenset({CallOutcome.UNKNOWN, CallOutcome.CANCELLED})


class EventType(str, Enum):
    """Every journal event type (spec §2).

    The list carries forward the proposal's events and adds the explicit
    ``task_blocked``, ``step_cancelled`` and ``retention_scheduled``
    variants for transitions that were otherwise unrepresented.
    Supersession is recorded inside ``plan_updated``.
    """

    TASK_STARTED = "task_started"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_BLOCKED = "task_blocked"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"

    PLAN_UPDATED = "plan_updated"
    DECISION_RECORDED = "decision_recorded"
    RESUME_HINT_UPDATED = "resume_hint_updated"

    TOOL_STARTED = "tool_started"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    TOOL_CANCELLED = "tool_cancelled"
    TOOL_OUTCOME_UNKNOWN = "tool_outcome_unknown"

    ARTIFACT_REGISTERED = "artifact_registered"
    ARTIFACT_INVALIDATED = "artifact_invalidated"

    STEP_STARTED = "step_started"
    STEP_BLOCKED = "step_blocked"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_REOPENED = "step_reopened"
    STEP_CANCELLED = "step_cancelled"

    TRACKING_DEGRADED = "tracking_degraded"
    RETENTION_SCHEDULED = "retention_scheduled"

    @property
    def is_reserved(self) -> bool:
        """Whether this event may use the reserved journal headroom.

        Terminal, recovery and retention events must remain appendable
        even when the ordinary journal cap is exhausted (spec §2
        Retention), so foreground work is refused before they are.
        """
        return self in _RESERVED_EVENT_TYPES


_RESERVED_EVENT_TYPES = frozenset(
    {
        EventType.TASK_COMPLETED,
        EventType.TASK_FAILED,
        EventType.TASK_CANCELLED,
        EventType.TOOL_OUTCOME_UNKNOWN,
        EventType.TRACKING_DEGRADED,
        EventType.RETENTION_SCHEDULED,
    }
)


# ─────────────────────────────────────────────────────────────
# Limits and errors
# ─────────────────────────────────────────────────────────────


class Limits:
    """Initial configurable limits from spec §2 *Data Models*.

    These are the hard structural bounds enforced by the models
    themselves. Operational thresholds that an operator may tune per
    deployment live in :class:`~parrot.tools.working_memory.task_memory.
    config.TaskMemoryConfig` instead.
    """

    #: Maximum simultaneously open (non-terminal) tasks in one scope.
    MAX_OPEN_TASKS_PER_SCOPE: int = 100
    #: Maximum steps in one task's plan, superseded ones included.
    MAX_STEPS_PER_TASK: int = 1_000
    #: Maximum *active* constraints per task.
    MAX_ACTIVE_CONSTRAINTS: int = 100
    #: Maximum *active* decisions per task.
    MAX_ACTIVE_DECISIONS: int = 1_000
    #: Maximum dependency references on one step.
    MAX_STEP_DEPENDENCIES: int = 100
    #: Maximum evidence references on one step.
    MAX_STEP_EVIDENCE_REFS: int = 100
    #: Maximum length of any identifier field.
    MAX_IDENTIFIER: int = 128
    #: Maximum length of a free-text reason or note.
    MAX_REASON: int = 2_000
    #: Maximum serialized size of a captured schema summary.
    MAX_SCHEMA_SUMMARY_BYTES: int = 4 * 1024
    #: Maximum serialized UTF-8 size of one journal event payload.
    MAX_EVENT_PAYLOAD_BYTES: int = 8 * 1024
    #: Maximum length of a task goal.
    MAX_GOAL: int = 2_000
    #: Maximum length of a constraint's text.
    MAX_CONSTRAINT_TEXT: int = 500
    #: Maximum length of a step title.
    MAX_STEP_TITLE: int = 120
    #: Maximum length of a step description.
    MAX_STEP_DESCRIPTION: int = 2_000
    #: Maximum length of a decision's text and of its reason.
    MAX_DECISION_TEXT: int = 500
    #: Maximum length of a resume hint.
    MAX_HINT_TEXT: int = 500
    #: Maximum registered validator names on one completion policy.
    MAX_POLICY_VALIDATORS: int = 16
    #: Maximum expected output aliases on one completion policy.
    MAX_POLICY_EXPECTED_OUTPUTS: int = 32
    #: Maximum length of an opaque pagination cursor.
    MAX_CURSOR: int = 512


class TaskMemoryError(Exception):
    """Base class for every task-memory domain error."""


class LimitExceeded(TaskMemoryError):
    """A bounded field or collection exceeded its configured limit.

    Raised *before* any mutation is attempted, so a rejected command
    leaves the task exactly as it was.

    Attributes:
        field: Name of the offending field or collection.
        limit: The configured bound.
        actual: The observed size.
    """

    def __init__(self, field: str, limit: int, actual: int, detail: str = "") -> None:
        """Initialize the error.

        Args:
            field: Name of the offending field or collection.
            limit: The configured bound.
            actual: The observed size.
            detail: Optional extra explanation.
        """
        self.field = field
        self.limit = limit
        self.actual = actual
        message = f"{field} exceeds limit: {actual} > {limit}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


class RevisionConflict(TaskMemoryError):
    """An ``expected_revision`` did not match the task's current revision.

    Attributes:
        task_id: The task the command targeted.
        expected: The revision the caller believed was current.
        current: The task's actual revision.
    """

    def __init__(self, task_id: str, expected: int, current: int) -> None:
        """Initialize the error.

        Args:
            task_id: The task the command targeted.
            expected: The revision the caller believed was current.
            current: The task's actual revision.
        """
        self.task_id = task_id
        self.expected = expected
        self.current = current
        super().__init__(f"revision conflict on {task_id}: expected {expected}, current {current}")


class ReducerError(TaskMemoryError):
    """An event could not be reduced: malformed, unsupported, or out of order."""


class ScopeViolation(TaskMemoryError):
    """A read or write crossed a bot/user/session boundary."""


class PlanValidationError(TaskMemoryError):
    """A plan change was rejected: cycle, duplicate id, missing dependency, or illegal status."""


class UnknownValidatorError(TaskMemoryError):
    """A completion policy named a validator that is not code-registered."""


class CursorError(TaskMemoryError):
    """A pagination cursor was malformed, out of scope, or out of bounds."""


class TaskMemoryUnavailable(TaskMemoryError):
    """Durable task memory could not persist a required record.

    Raised *before* execution when a durable ``tool_started`` cannot be
    written (D8). Best-effort operation requires explicit opt-in and
    reports ``tracking_degraded`` instead.
    """


# ─────────────────────────────────────────────────────────────
# Base model
# ─────────────────────────────────────────────────────────────


class _TaskModel(BaseModel):
    """Shared configuration for every task-memory model.

    ``extra="forbid"`` matters here: an unrecognised field in a persisted
    document means the writer used a schema this reader does not
    understand, and silently dropping it would corrupt a projection.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)


class _VersionedModel(_TaskModel):
    """A task-memory model that carries an explicit schema version."""

    schema_version: int = Field(default=SCHEMA_VERSION, description="Document schema version.")

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, value: int) -> int:
        """Reject any schema version this build does not implement.

        Args:
            value: The declared version.

        Returns:
            The validated version.

        Raises:
            ValueError: If the version is not :data:`SCHEMA_VERSION`.
        """
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {value}; this build implements {SCHEMA_VERSION}")
        return value


# ─────────────────────────────────────────────────────────────
# Scope and references
# ─────────────────────────────────────────────────────────────


class TaskScope(_TaskModel):
    """Trusted runtime identity every read and write is checked against.

    Supplied by the runtime, never by a tool argument — a model-authored
    scope would be a cross-user read primitive. ``chatbot_id`` is the
    bot's stable ``memory_key_id``, so attribution and storage location
    always agree.

    Attributes:
        chatbot_id: The bot's stable ``memory_key_id``.
        user_id: Owner of the conversation.
        session_id: The conversation session.
    """

    chatbot_id: str = Field(min_length=1, max_length=Limits.MAX_IDENTIFIER)
    user_id: str = Field(min_length=1, max_length=Limits.MAX_IDENTIFIER)
    session_id: str = Field(min_length=1, max_length=Limits.MAX_IDENTIFIER)

    def cache_key(self) -> str:
        """Return a collision-safe encoded key for this scope.

        Components are percent-encoded so that a value containing the
        separator cannot forge a different scope's key.

        Returns:
            An opaque, stable, collision-safe string.
        """
        from urllib.parse import quote

        parts = (quote(self.chatbot_id, safe=""), quote(self.user_id, safe=""), quote(self.session_id, safe=""))
        return ":".join(parts)

    def matches(self, other: "TaskScope") -> bool:
        """Whether ``other`` is exactly this scope.

        Args:
            other: The scope to compare against.

        Returns:
            ``True`` when every component is equal.
        """
        return (
            self.chatbot_id == other.chatbot_id
            and self.user_id == other.user_id
            and self.session_id == other.session_id
        )


class EvidenceRef(_TaskModel):
    """An immutable reference to one exact artifact version.

    Bare aliases are rejected at the journal boundary: evidence must name
    ``artifact_id@version`` so that overwriting an alias later cannot
    retroactively change what a completed step proved.

    Attributes:
        artifact_id: Stable identity of the artifact.
        version: 1-based version number within that identity.
    """

    artifact_id: str = Field(min_length=1, max_length=Limits.MAX_IDENTIFIER)
    version: int = Field(ge=1)

    def __str__(self) -> str:
        """Return the canonical ``artifact_id@version`` form."""
        return f"{self.artifact_id}@{self.version}"

    @classmethod
    def parse(cls, value: str) -> "EvidenceRef":
        """Parse a canonical ``artifact_id@version`` string.

        Args:
            value: The reference text.

        Returns:
            The parsed reference.

        Raises:
            ValueError: If ``value`` is a bare alias or otherwise
                malformed. A bare alias is rejected deliberately — it is
                mutable, and mutable aliases are not evidence.
        """
        artifact_id, separator, raw_version = value.rpartition("@")
        if not separator or not artifact_id:
            raise ValueError(f"not an exact evidence reference (expected 'artifact_id@version'): {value!r}")
        if not raw_version.isdigit():
            raise ValueError(f"evidence reference version must be a positive integer: {value!r}")
        return cls(artifact_id=artifact_id, version=int(raw_version))


# ─────────────────────────────────────────────────────────────
# Task structure
# ─────────────────────────────────────────────────────────────


class Constraint(_TaskModel):
    """One standing constraint on a task.

    Attributes:
        constraint_id: Runtime identity.
        text: The constraint itself.
        active: Whether it still applies. Deactivated constraints are
            retained for history rather than deleted.
        revision: Task revision at which this constraint last changed.
    """

    constraint_id: str = Field(default_factory=new_id, max_length=Limits.MAX_IDENTIFIER)
    text: str = Field(min_length=1, max_length=Limits.MAX_CONSTRAINT_TEXT)
    active: bool = True
    revision: int = Field(default=0, ge=0)


class CompletionPolicy(_TaskModel):
    """How a step is permitted to be marked complete.

    Attributes:
        mode: ``validated`` runs every named validator and binds every
            expected output to an exact artifact version. ``agent_asserted``
            requires at least one accessible evidence reference plus the
            required note, and is always labeled as the weaker source.
        validators: Code-registered validator names. Unknown names are
            rejected by the service, which owns the registry.
        expected_outputs: Aliases that must resolve to exact artifact
            versions at completion time.
        require_note: Whether a completion note is mandatory. Always
            ``True`` per spec §2 — kept explicit rather than implied.
    """

    mode: CompletionMode = CompletionMode.AGENT_ASSERTED
    validators: Tuple[str, ...] = ()
    expected_outputs: Tuple[str, ...] = ()
    require_note: bool = True

    @field_validator("validators")
    @classmethod
    def _check_validators(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Bound the validator list and each name's length.

        Args:
            value: Declared validator names.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If too many names, or a name is too long.
        """
        if len(value) > Limits.MAX_POLICY_VALIDATORS:
            raise LimitExceeded("validators", Limits.MAX_POLICY_VALIDATORS, len(value))
        for name in value:
            if len(name) > Limits.MAX_IDENTIFIER:
                raise LimitExceeded("validator name", Limits.MAX_IDENTIFIER, len(name))
        return value

    @field_validator("expected_outputs")
    @classmethod
    def _check_expected_outputs(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Bound the expected-output alias list.

        Args:
            value: Declared output aliases.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If too many aliases, or an alias is too long.
        """
        if len(value) > Limits.MAX_POLICY_EXPECTED_OUTPUTS:
            raise LimitExceeded("expected_outputs", Limits.MAX_POLICY_EXPECTED_OUTPUTS, len(value))
        for alias in value:
            if len(alias) > Limits.MAX_IDENTIFIER:
                raise LimitExceeded("expected output alias", Limits.MAX_IDENTIFIER, len(alias))
        return value

    @field_validator("require_note")
    @classmethod
    def _check_require_note(cls, value: bool) -> bool:
        """Reject an attempt to make the completion note optional.

        Args:
            value: The declared flag.

        Returns:
            ``True``.

        Raises:
            ValueError: If ``value`` is ``False``.
        """
        if value is not True:
            raise ValueError("require_note is always True (spec §2 CompletionPolicy)")
        return value


class TaskStep(_TaskModel):
    """One step in a task's plan.

    Attributes:
        step_id: Runtime identity. Immutable once created.
        title: Short human-readable label.
        description: Longer explanation of what the step must achieve.
        required: Whether the task can complete without this step.
        depends_on: Step ids that must be ``completed`` before this one
            is ready. Superseded, failed or blocked dependencies do not
            satisfy readiness.
        status: Current lifecycle state.
        completion_policy: How this step may be completed.
        evidence_refs: Exact artifact versions bound as evidence.
        attempt_count: Physical attributed attempts, counted once each on
            their terminal event.
        blocked_reason: Why the step is blocked, when it is.
        created_revision: Task revision at which the step was added.
        updated_revision: Task revision at which it last changed.
        completion_source: How it was actually completed, when it was.
        completion_note: The note recorded at completion.
    """

    step_id: str = Field(default_factory=new_id, max_length=Limits.MAX_IDENTIFIER)
    title: str = Field(min_length=1, max_length=Limits.MAX_STEP_TITLE)
    description: str = Field(default="", max_length=Limits.MAX_STEP_DESCRIPTION)
    required: bool = True
    depends_on: Tuple[str, ...] = ()
    status: StepStatus = StepStatus.PENDING
    completion_policy: CompletionPolicy = Field(default_factory=CompletionPolicy)
    evidence_refs: Tuple[EvidenceRef, ...] = ()
    attempt_count: int = Field(default=0, ge=0)
    blocked_reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    created_revision: int = Field(default=0, ge=0)
    updated_revision: int = Field(default=0, ge=0)
    completion_source: Optional[CompletionSource] = None
    completion_note: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)

    @field_validator("depends_on")
    @classmethod
    def _check_dependencies(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Bound and de-duplicate the dependency list.

        Args:
            value: Declared dependency step ids.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If there are too many dependencies.
            PlanValidationError: If an id repeats.
        """
        if len(value) > Limits.MAX_STEP_DEPENDENCIES:
            raise LimitExceeded("depends_on", Limits.MAX_STEP_DEPENDENCIES, len(value))
        if len(set(value)) != len(value):
            raise PlanValidationError("duplicate dependency ids on a step")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _check_evidence(cls, value: Tuple[EvidenceRef, ...]) -> Tuple[EvidenceRef, ...]:
        """Bound the evidence reference list.

        Args:
            value: Declared evidence references.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If there are too many references.
        """
        if len(value) > Limits.MAX_STEP_EVIDENCE_REFS:
            raise LimitExceeded("evidence_refs", Limits.MAX_STEP_EVIDENCE_REFS, len(value))
        return value

    @model_validator(mode="after")
    def _check_self_dependency(self) -> "TaskStep":
        """Reject a step that depends on itself.

        Returns:
            The validated step.

        Raises:
            PlanValidationError: If the step lists its own id.
        """
        if self.step_id in self.depends_on:
            raise PlanValidationError(f"step {self.step_id} depends on itself")
        return self


class Decision(_TaskModel):
    """A recorded decision affecting the task.

    Attributes:
        decision_id: Runtime identity.
        text: What was decided.
        reason: Why.
        actor: Who decided.
        affected_step_ids: Steps the decision bears on.
        revision: Task revision at which it was recorded.
        active: Whether it still stands. Superseded decisions are retained.
    """

    decision_id: str = Field(default_factory=new_id, max_length=Limits.MAX_IDENTIFIER)
    text: str = Field(min_length=1, max_length=Limits.MAX_DECISION_TEXT)
    reason: str = Field(default="", max_length=Limits.MAX_DECISION_TEXT)
    actor: Actor = Actor.AGENT
    affected_step_ids: Tuple[str, ...] = ()
    revision: int = Field(default=0, ge=0)
    active: bool = True

    @field_validator("affected_step_ids")
    @classmethod
    def _check_affected(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Bound the affected-step list.

        Args:
            value: Declared step ids.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If there are too many ids.
        """
        if len(value) > Limits.MAX_STEP_DEPENDENCIES:
            raise LimitExceeded("affected_step_ids", Limits.MAX_STEP_DEPENDENCIES, len(value))
        return value


class ResumeHint(_TaskModel):
    """The agent's own note about what to do next.

    ``stale`` is *derived*, not authored: any later event touching the
    hint's step, that step's dependencies, or its evidence marks it
    stale. The reducer sets it; nothing else should.

    Attributes:
        text: The next action.
        step_id: Optional step the hint refers to.
        actor: Who recorded it.
        revision: Task revision at which it was recorded.
        stale: Whether later events have invalidated it.
    """

    text: str = Field(min_length=1, max_length=Limits.MAX_HINT_TEXT)
    step_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    actor: Actor = Actor.AGENT
    revision: int = Field(default=0, ge=0)
    stale: bool = False


class TaskState(_VersionedModel):
    """The pure reducer projection of a task's journal (D6).

    The journal is the source of truth; this is a derived, versioned view
    of it. Active and ready step ids are computed properties, never
    persisted fields — a stored duplicate would be a second source of
    truth that could disagree with ``steps``.

    Attributes:
        task_id: Runtime identity.
        scope: The trusted scope this task belongs to.
        goal: What the task is trying to achieve.
        constraints: Standing constraints, active and retired.
        status: Task lifecycle state.
        plan_complete: Whether the plan is declared complete. A task
            cannot complete while this is ``False``.
        plan_revision: Advances only on a plan change.
        revision: Advances on every accepted state-changing batch.
        steps: The plan, in insertion order.
        decisions: Recorded decisions, active and retired.
        resume_hint: The current hint, if any.
        created_at: When the task was started.
        updated_at: When it last changed.
        terminal_at: When it reached a terminal status, if it has.
        last_event_seq: Highest journal sequence folded into this state.
        reducer_version: Version of the reducer that produced it.
    """

    task_id: str = Field(default_factory=new_id, max_length=Limits.MAX_IDENTIFIER)
    scope: TaskScope
    goal: str = Field(min_length=1, max_length=Limits.MAX_GOAL)
    constraints: Tuple[Constraint, ...] = ()
    status: TaskStatus = TaskStatus.ACTIVE
    plan_complete: bool = False
    plan_revision: int = Field(default=0, ge=0)
    revision: int = Field(default=0, ge=0)
    steps: Tuple[TaskStep, ...] = ()
    decisions: Tuple[Decision, ...] = ()
    resume_hint: Optional[ResumeHint] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    terminal_at: Optional[datetime] = None
    last_event_seq: int = Field(default=0, ge=0)
    reducer_version: int = Field(default=SCHEMA_VERSION, ge=1)

    @field_validator("created_at", "updated_at", "terminal_at")
    @classmethod
    def _check_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Require timezone-aware UTC timestamps.

        Args:
            value: The timestamp, or ``None``.

        Returns:
            The normalized timestamp.
        """
        return None if value is None else _require_utc(value)

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, value: Tuple[TaskStep, ...]) -> Tuple[TaskStep, ...]:
        """Bound the plan and reject duplicate step ids.

        Args:
            value: The plan's steps.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If the plan is too large.
            PlanValidationError: If a step id repeats.
        """
        if len(value) > Limits.MAX_STEPS_PER_TASK:
            raise LimitExceeded("steps", Limits.MAX_STEPS_PER_TASK, len(value))
        ids = [step.step_id for step in value]
        if len(set(ids)) != len(ids):
            raise PlanValidationError("duplicate step ids in plan")
        return value

    @model_validator(mode="after")
    def _check_active_collections(self) -> "TaskState":
        """Bound the *active* constraint and decision collections.

        Retired entries are retained for history and do not count against
        the limits, which is why this cannot be a plain field bound.

        Returns:
            The validated state.

        Raises:
            LimitExceeded: If too many constraints or decisions are active.
        """
        active_constraints = sum(1 for c in self.constraints if c.active)
        if active_constraints > Limits.MAX_ACTIVE_CONSTRAINTS:
            raise LimitExceeded("active constraints", Limits.MAX_ACTIVE_CONSTRAINTS, active_constraints)
        active_decisions = sum(1 for d in self.decisions if d.active)
        if active_decisions > Limits.MAX_ACTIVE_DECISIONS:
            raise LimitExceeded("active decisions", Limits.MAX_ACTIVE_DECISIONS, active_decisions)
        return self

    # ── derived views (never persisted) ──────────────────────────────

    @property
    def steps_by_id(self) -> Dict[str, TaskStep]:
        """Return the plan indexed by step id."""
        return {step.step_id: step for step in self.steps}

    @property
    def active_step_ids(self) -> Tuple[str, ...]:
        """Ids of steps that are still live work.

        Derived, never stored: a step is active while it is neither
        terminal nor failed. ``failed`` is included because a failed step
        remains actionable — failure does not retire it.
        """
        return tuple(s.step_id for s in self.steps if not s.status.is_terminal)

    @property
    def ready_step_ids(self) -> Tuple[str, ...]:
        """Ids of pending steps whose dependencies are all completed.

        Derived, never stored. Superseded, failed and blocked
        dependencies do **not** satisfy readiness (spec §2 Reducer
        Rules) — only ``completed`` does.
        """
        by_id = self.steps_by_id
        ready: List[str] = []
        for step in self.steps:
            if step.status is not StepStatus.PENDING:
                continue
            deps = [by_id.get(dep) for dep in step.depends_on]
            if any(dep is None or dep.status is not StepStatus.COMPLETED for dep in deps):
                continue
            ready.append(step.step_id)
        return tuple(ready)

    @property
    def active_constraints(self) -> Tuple[Constraint, ...]:
        """The constraints that still apply."""
        return tuple(c for c in self.constraints if c.active)

    @property
    def active_decisions(self) -> Tuple[Decision, ...]:
        """The decisions that still stand."""
        return tuple(d for d in self.decisions if d.active)

    @property
    def can_complete(self) -> bool:
        """Whether the completion guard would currently pass.

        A task completes only with ``plan_complete=True`` and every
        required, non-superseded step completed. An exhausted partial
        plan stays active and reports ``plan_incomplete``.
        """
        if not self.plan_complete:
            return False
        required = [s for s in self.steps if s.required and s.status is not StepStatus.SUPERSEDED]
        return bool(required) and all(s.status is StepStatus.COMPLETED for s in required)


# ─────────────────────────────────────────────────────────────
# Journal payloads
# ─────────────────────────────────────────────────────────────


class _Payload(_TaskModel):
    """Base for typed journal payloads."""


class TaskLifecyclePayload(_Payload):
    """Payload for a task-level transition.

    Covers ``task_started``/``paused``/``resumed``/``blocked``/
    ``completed``/``failed``/``cancelled``.

    Attributes:
        kind: Discriminator.
        status: The status the task moved to.
        goal: The goal, recorded on ``task_started``.
        reason: Why the transition happened.
    """

    kind: Literal["task_lifecycle"] = "task_lifecycle"
    status: TaskStatus
    goal: Optional[str] = Field(default=None, max_length=Limits.MAX_GOAL)
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)


class PlanStepSpec(_TaskModel):
    """A step as recorded in a ``plan_updated`` event.

    The journal is the source of truth (D6), so a plan event must carry
    enough to *reconstruct* the step. An id-only payload would make the
    projection, not the journal, the real source of truth — replay could
    not rebuild a step it had never seen defined.

    Attributes:
        step_id: Runtime identity, already resolved by the service.
        title: Short human-readable label.
        description: Longer explanation.
        required: Whether the task can complete without this step.
        depends_on: Runtime step ids this one depends on.
        completion_policy: How the step may be completed.
    """

    step_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    title: str = Field(min_length=1, max_length=Limits.MAX_STEP_TITLE)
    description: str = Field(default="", max_length=Limits.MAX_STEP_DESCRIPTION)
    required: bool = True
    depends_on: Tuple[str, ...] = ()
    completion_policy: CompletionPolicy = Field(default_factory=CompletionPolicy)


class PlanStepPatch(_TaskModel):
    """The fields a ``plan_updated`` event changes on an existing step.

    ``None`` means "leave unchanged" — the patch records exactly what the
    revision altered, so replay reproduces the same result without
    needing the pre-image.

    Attributes:
        step_id: The step to update. Identities are immutable.
        title: New title, when it changed.
        description: New description, when it changed.
        required: New required flag, when it changed.
        depends_on: Replacement dependency list, when it changed.
        completion_policy: Replacement policy, when it changed.
    """

    step_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    title: Optional[str] = Field(default=None, min_length=1, max_length=Limits.MAX_STEP_TITLE)
    description: Optional[str] = Field(default=None, max_length=Limits.MAX_STEP_DESCRIPTION)
    required: Optional[bool] = None
    depends_on: Optional[Tuple[str, ...]] = None
    completion_policy: Optional[CompletionPolicy] = None


class PlanConstraintSpec(_TaskModel):
    """A constraint as recorded in a ``plan_updated`` event.

    Attributes:
        constraint_id: Runtime identity, already resolved by the service.
        text: The constraint.
    """

    constraint_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    text: str = Field(min_length=1, max_length=Limits.MAX_CONSTRAINT_TEXT)


class PlanUpdatePayload(_Payload):
    """Payload for ``plan_updated``.

    Supersession is recorded here rather than as its own event type, so
    one plan revision is one event.

    The payload carries full step and constraint **definitions**, not
    just ids, because the journal is the source of truth: a reducer
    replaying from an empty state must be able to rebuild the plan.

    Attributes:
        kind: Discriminator.
        added_steps: Steps introduced by this revision, in order.
        updated_steps: Patches applied to existing steps.
        superseded_step_ids: Steps retired by this revision. They keep
            their evidence and history and never satisfy a dependent's
            readiness afterwards.
        added_constraints: Constraints introduced.
        updated_constraints: Constraints reworded.
        deactivated_constraint_ids: Constraints retired. Retained for
            history rather than deleted.
        plan_complete: New value of the plan-complete flag, when set.
        reason: Why the plan changed.
    """

    kind: Literal["plan_update"] = "plan_update"
    added_steps: Tuple[PlanStepSpec, ...] = ()
    updated_steps: Tuple[PlanStepPatch, ...] = ()
    superseded_step_ids: Tuple[str, ...] = ()
    added_constraints: Tuple[PlanConstraintSpec, ...] = ()
    updated_constraints: Tuple[PlanConstraintSpec, ...] = ()
    deactivated_constraint_ids: Tuple[str, ...] = ()
    plan_complete: Optional[bool] = None
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)

    @property
    def added_step_ids(self) -> Tuple[str, ...]:
        """Ids of the steps this revision introduced."""
        return tuple(step.step_id for step in self.added_steps)

    @property
    def updated_step_ids(self) -> Tuple[str, ...]:
        """Ids of the steps this revision patched."""
        return tuple(patch.step_id for patch in self.updated_steps)

    @property
    def added_constraint_ids(self) -> Tuple[str, ...]:
        """Ids of the constraints this revision introduced."""
        return tuple(c.constraint_id for c in self.added_constraints)

    @property
    def touched_step_ids(self) -> Tuple[str, ...]:
        """Every step id this revision added, patched or superseded."""
        return self.added_step_ids + self.updated_step_ids + self.superseded_step_ids

    @property
    def is_empty(self) -> bool:
        """Whether this revision changes nothing at all."""
        return not (
            self.added_steps
            or self.updated_steps
            or self.superseded_step_ids
            or self.added_constraints
            or self.updated_constraints
            or self.deactivated_constraint_ids
            or self.plan_complete is not None
        )


class DecisionPayload(_Payload):
    """Payload for ``decision_recorded``.

    Attributes:
        kind: Discriminator.
        decision_id: Identity of the recorded decision.
        text: What was decided.
        reason: Why.
        affected_step_ids: Steps the decision bears on.
        active: Whether the decision stands or retires an earlier one.
    """

    kind: Literal["decision"] = "decision"
    decision_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    text: str = Field(min_length=1, max_length=Limits.MAX_DECISION_TEXT)
    reason: str = Field(default="", max_length=Limits.MAX_DECISION_TEXT)
    affected_step_ids: Tuple[str, ...] = ()
    active: bool = True


class ResumeHintPayload(_Payload):
    """Payload for ``resume_hint_updated``.

    Attributes:
        kind: Discriminator.
        text: The next action.
        step_id: Optional step the hint refers to.
    """

    kind: Literal["resume_hint"] = "resume_hint"
    text: str = Field(min_length=1, max_length=Limits.MAX_HINT_TEXT)
    step_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)


class StepPayload(_Payload):
    """Payload for a step-level transition.

    Covers ``step_started``/``blocked``/``completed``/``failed``/
    ``reopened``/``cancelled``.

    Attributes:
        kind: Discriminator.
        step_id: The step that transitioned.
        status: The status it moved to.
        evidence_refs: Exact artifact versions bound at completion.
        completion_source: How it was completed, when it was.
        note: The completion or transition note.
        reason: Why it blocked or failed (e.g. ``upstream_reopened``).
        validator_results: Recorded validator outcomes. Replay consumes
            these; it never re-runs a validator.
    """

    kind: Literal["step"] = "step"
    step_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    status: StepStatus
    evidence_refs: Tuple[EvidenceRef, ...] = ()
    completion_source: Optional[CompletionSource] = None
    note: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    validator_results: Tuple[Tuple[str, bool], ...] = ()


class ToolCallPayload(_Payload):
    """Payload for a tool-call lifecycle event.

    Covers ``tool_started``/``succeeded``/``failed``/``cancelled``/
    ``outcome_unknown``.

    Attributes:
        kind: Discriminator.
        call_id: Identity of this physical attempt.
        tool_name: The dispatched tool.
        attempt: 1-based attempt number.
        executed: Whether a tool body actually ran. ``False`` for an
            unknown tool, a guard denial or an authorization requirement.
        outcome: Typed outcome, absent on ``tool_started``.
        error: Condensed, redacted error text.
        elapsed_ms: Wall-clock duration.
        artifact_refs: Artifact versions produced by this attempt.
        counted: Whether this event is the one that increments the
            step's attempt count. Exactly one terminal event per
            physical attempt sets it.
    """

    kind: Literal["tool_call"] = "tool_call"
    call_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    tool_name: str = Field(max_length=Limits.MAX_IDENTIFIER)
    attempt: int = Field(default=1, ge=1)
    executed: bool = True
    outcome: Optional[CallOutcome] = None
    error: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    elapsed_ms: Optional[int] = Field(default=None, ge=0)
    artifact_refs: Tuple[EvidenceRef, ...] = ()
    counted: bool = False


class ArtifactPayload(_Payload):
    """Payload for ``artifact_registered`` / ``artifact_invalidated``.

    Attributes:
        kind: Discriminator.
        ref: The exact artifact version.
        alias: The working-memory key it was published under.
        artifact_kind: Evidence type.
        availability: Where its bytes are.
        fingerprint: Canonical content fingerprint, when computable.
        fingerprint_algorithm: Algorithm identity and version.
        evidence_verifiable: Whether the fingerprint actually proves
            content integrity. ``False`` for nested mutable or otherwise
            unsupported values, even when a fingerprint was computable.
        byte_size: Recorded payload size.
        reason: Why it was invalidated, when it was.
    """

    kind: Literal["artifact"] = "artifact"
    ref: EvidenceRef
    alias: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    artifact_kind: Optional[ArtifactKind] = None
    availability: Optional[ArtifactAvailability] = None
    fingerprint: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    fingerprint_algorithm: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    evidence_verifiable: bool = False
    byte_size: Optional[int] = Field(default=None, ge=0)
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)


class DegradedPayload(_Payload):
    """Payload for ``tracking_degraded``.

    Recorded when best-effort tracking is explicitly enabled and a write
    could not be persisted. It is a truthful gap marker — it never
    invents the events that were lost.

    Attributes:
        kind: Discriminator.
        component: What degraded (``journal``, ``tee``, ``association``…).
        detail: Human-readable explanation.
        recovered: Whether the gap was later reconciled.
    """

    kind: Literal["degraded"] = "degraded"
    component: str = Field(max_length=Limits.MAX_IDENTIFIER)
    detail: str = Field(default="", max_length=Limits.MAX_REASON)
    recovered: bool = False


class RetentionPayload(_Payload):
    """Payload for ``retention_scheduled``.

    Retention appends its intent before doing destructive work, so the
    intent is auditable even though terminal deletion necessarily removes
    the journal that recorded it (spec §2 Retention).

    Attributes:
        kind: Discriminator.
        policy: Which retention rule fired.
        action: What it intends to do.
        due_at: When the action becomes due.
        target_refs: Artifact versions the action targets.
        archive_uri: Where the archive will be written, when configured.
    """

    kind: Literal["retention"] = "retention"
    policy: str = Field(max_length=Limits.MAX_IDENTIFIER)
    action: str = Field(max_length=Limits.MAX_IDENTIFIER)
    due_at: Optional[datetime] = None
    target_refs: Tuple[EvidenceRef, ...] = ()
    archive_uri: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)

    @field_validator("due_at")
    @classmethod
    def _check_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Require a timezone-aware UTC due date.

        Args:
            value: The timestamp, or ``None``.

        Returns:
            The normalized timestamp.
        """
        return None if value is None else _require_utc(value)


#: Discriminated union of every typed journal payload.
EventPayload = Annotated[
    Union[
        TaskLifecyclePayload,
        PlanUpdatePayload,
        DecisionPayload,
        ResumeHintPayload,
        StepPayload,
        ToolCallPayload,
        ArtifactPayload,
        DegradedPayload,
        RetentionPayload,
    ],
    Field(discriminator="kind"),
]


#: Which payload family each event type must carry. An event whose
#: payload family does not match is rejected — a mismatched payload is a
#: malformed event, and the reducer must never guess at one.
PAYLOAD_FAMILY_BY_EVENT: Dict[EventType, str] = {
    EventType.TASK_STARTED: "task_lifecycle",
    EventType.TASK_PAUSED: "task_lifecycle",
    EventType.TASK_RESUMED: "task_lifecycle",
    EventType.TASK_BLOCKED: "task_lifecycle",
    EventType.TASK_COMPLETED: "task_lifecycle",
    EventType.TASK_FAILED: "task_lifecycle",
    EventType.TASK_CANCELLED: "task_lifecycle",
    EventType.PLAN_UPDATED: "plan_update",
    EventType.DECISION_RECORDED: "decision",
    EventType.RESUME_HINT_UPDATED: "resume_hint",
    EventType.TOOL_STARTED: "tool_call",
    EventType.TOOL_SUCCEEDED: "tool_call",
    EventType.TOOL_FAILED: "tool_call",
    EventType.TOOL_CANCELLED: "tool_call",
    EventType.TOOL_OUTCOME_UNKNOWN: "tool_call",
    EventType.ARTIFACT_REGISTERED: "artifact",
    EventType.ARTIFACT_INVALIDATED: "artifact",
    EventType.STEP_STARTED: "step",
    EventType.STEP_BLOCKED: "step",
    EventType.STEP_COMPLETED: "step",
    EventType.STEP_FAILED: "step",
    EventType.STEP_REOPENED: "step",
    EventType.STEP_CANCELLED: "step",
    EventType.TRACKING_DEGRADED: "degraded",
    EventType.RETENTION_SCHEDULED: "retention",
}


class JournalEvent(_VersionedModel):
    """One immutable entry in a task's journal — the source of truth (D6).

    Attributes:
        event_id: Globally unique runtime identity. The store
            deduplicates on this before allocating a sequence number:
            an identical redelivery is a no-op, and reuse with a
            different payload is rejected.
        task_id: The task this event belongs to.
        seq: Backend-assigned contiguous sequence. ``0`` means "not yet
            appended" — the backend, not the caller, allocates it.
        occurred_at: Timezone-aware UTC timestamp.
        event_type: What happened.
        actor: Who caused it.
        turn_id: The conversation turn it happened in.
        plan_revision: Plan revision in force when it happened.
        step_id: Step correlation, when known.
        call_id: Physical attempt correlation, when applicable.
        parent_call_id: Parent aggregate (e.g. a plan node) when nested.
        attribution: How the step correlation was established.
        payload: The typed, bounded payload.
    """

    event_id: str = Field(default_factory=new_id, max_length=Limits.MAX_IDENTIFIER)
    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    seq: int = Field(default=0, ge=0)
    occurred_at: datetime = Field(default_factory=utc_now)
    event_type: EventType
    actor: Actor = Actor.RUNTIME
    turn_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    plan_revision: int = Field(default=0, ge=0)
    step_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    call_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    parent_call_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    attribution: Attribution = Attribution.NONE
    payload: EventPayload

    @field_validator("occurred_at")
    @classmethod
    def _check_utc(cls, value: datetime) -> datetime:
        """Require a timezone-aware UTC timestamp.

        Args:
            value: The timestamp.

        Returns:
            The normalized timestamp.
        """
        return _require_utc(value)

    @model_validator(mode="after")
    def _check_payload(self) -> "JournalEvent":
        """Validate the payload's family and serialized byte size.

        Returns:
            The validated event.

        Raises:
            ReducerError: If the payload family does not match the event
                type.
            LimitExceeded: If the serialized payload exceeds
                :data:`Limits.MAX_EVENT_PAYLOAD_BYTES`. This is a byte
                limit on the canonical UTF-8 encoding, not a count of
                dictionary items.
        """
        expected = PAYLOAD_FAMILY_BY_EVENT[self.event_type]
        actual = self.payload.kind
        if actual != expected:
            raise ReducerError(f"event {self.event_type.value} requires a {expected!r} payload, got {actual!r}")

        size = serialized_bytes(self.payload.model_dump(mode="json"))
        if size > Limits.MAX_EVENT_PAYLOAD_BYTES:
            raise LimitExceeded(
                "event payload",
                Limits.MAX_EVENT_PAYLOAD_BYTES,
                size,
                "serialized UTF-8 bytes",
            )
        return self


# ─────────────────────────────────────────────────────────────
# Artifacts, bindings and invocations
# ─────────────────────────────────────────────────────────────


class ReplBinding(_TaskModel):
    """A live binding of an artifact version into a REPL worker.

    A PID alone is not a generation identity: a recycled worker with the
    same PID would be treated as the same generation, so the worker's own
    session/generation id is what makes a binding checkable.

    Attributes:
        worker_session_id: Identity of the worker process generation.
        worker_generation: Monotonic generation counter within a session.
        variable_name: Name the artifact is bound to inside the worker.
        ref: The exact artifact version bound.
    """

    worker_session_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    worker_generation: int = Field(default=0, ge=0)
    variable_name: str = Field(max_length=Limits.MAX_IDENTIFIER)
    ref: EvidenceRef


class ArtifactDescriptor(_VersionedModel):
    """Read projection of one versioned catalog entry (D1).

    Shared by DataFrame (``CatalogEntry``) and generic (``GenericEntry``)
    entries. Contains **no data rows and no raw payload**, and building
    one never calls ``compact_summary()``, ``describe()`` or an arbitrary
    object's ``repr()`` — recall must stay cheap and must not leak data.

    Attributes:
        ref: Artifact identity and version.
        alias: Current working-memory key, when it still has one.
        scope: Owning scope.
        task_id: Owning task, when associated.
        producer_call_id: The physical attempt that produced it.
        attribution: How that attempt was attributed.
        kind: Evidence type.
        availability: Where the bytes are.
        fingerprint: Canonical content fingerprint, when computable.
        fingerprint_algorithm: Algorithm identity and version, e.g.
            ``"blake2b-8/v1"``.
        evidence_verifiable: Whether the fingerprint actually proves
            content integrity. ``False`` for unsupported or nested
            mutable values — a computable fingerprint over a nested
            object is not integrity proof.
        invalidated: Whether this version's evidence has been invalidated.
        binding_invalid: Whether its REPL binding is stale. Independent
            of ``availability``: a stale binding does not mean the
            durable payload disappeared.
        byte_size: Recorded payload size in bytes.
        shape: Captured shape, e.g. ``(rows, cols)``.
        schema_summary: Bounded captured schema description.
        storage_ref: Backend storage reference, when persisted.
        repl_binding: Current REPL binding, when one exists.
        created_at: When this version was registered.
        invalidated_at: When it was invalidated, if it was.
    """

    ref: EvidenceRef
    alias: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    scope: TaskScope
    task_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    producer_call_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    attribution: Attribution = Attribution.NONE
    kind: ArtifactKind = ArtifactKind.OBJECT
    availability: ArtifactAvailability = ArtifactAvailability.MEMORY
    fingerprint: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    fingerprint_algorithm: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    evidence_verifiable: bool = False
    invalidated: bool = False
    binding_invalid: bool = False
    byte_size: Optional[int] = Field(default=None, ge=0)
    shape: Optional[Tuple[int, ...]] = None
    schema_summary: Optional[Dict[str, Any]] = None
    storage_ref: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    repl_binding: Optional[ReplBinding] = None
    created_at: datetime = Field(default_factory=utc_now)
    invalidated_at: Optional[datetime] = None

    @field_validator("created_at", "invalidated_at")
    @classmethod
    def _check_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Require timezone-aware UTC timestamps.

        Args:
            value: The timestamp, or ``None``.

        Returns:
            The normalized timestamp.
        """
        return None if value is None else _require_utc(value)

    @field_validator("schema_summary")
    @classmethod
    def _check_schema_summary(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Bound the captured schema summary's serialized size.

        Args:
            value: The summary, or ``None``.

        Returns:
            The validated summary.

        Raises:
            LimitExceeded: If the summary serializes above
                :data:`Limits.MAX_SCHEMA_SUMMARY_BYTES`.
        """
        if value is None:
            return None
        size = serialized_bytes(value)
        if size > Limits.MAX_SCHEMA_SUMMARY_BYTES:
            raise LimitExceeded("schema_summary", Limits.MAX_SCHEMA_SUMMARY_BYTES, size, "serialized UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def _check_verifiability(self) -> "ArtifactDescriptor":
        """Refuse to claim verifiable evidence without the means to prove it.

        Returns:
            The validated descriptor.

        Raises:
            ValueError: If ``evidence_verifiable`` is set without a
                fingerprint, or for an unsupported evidence kind.
        """
        if self.evidence_verifiable:
            if not self.fingerprint:
                raise ValueError("evidence_verifiable requires a fingerprint")
            if not self.kind.is_supported_evidence:
                raise ValueError(f"kind {self.kind.value!r} cannot carry verifiable evidence")
        return self


class TaskContext(_TaskModel):
    """Immutable per-invocation snapshot of the turn's task context (D3).

    A frozen snapshot is taken at each dispatch. A later declaration does
    not retroactively change an earlier dispatch's snapshot — attribution
    is never guessed after the fact.

    Attributes:
        scope: Trusted runtime scope.
        task_id: The selected task, when one is selected.
        plan_revision: Plan revision in force at dispatch.
        turn_id: The conversation turn.
        declared_step_ids: Steps declared for this turn at dispatch time.
            Zero gives task-level ``none``; exactly one gives
            ``declared``; more than one gives task-level ``ambiguous``.
        parent_call_id: Parent aggregate call, when nested.
        plan_run_id: Explicit plan-run correlation.
        plan_node_id: Explicit plan-node correlation. A plan node id is
            **not** automatically a domain step id.
        plan_item_index: Fan-out index within a plan node.
        plan_attempt: Attempt number within the plan node's retry policy.
        mapped_step_id: Step id an explicit plan-to-step mapping resolved
            to. Present only when such a mapping was configured.
    """

    scope: TaskScope
    task_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    plan_revision: int = Field(default=0, ge=0)
    turn_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    declared_step_ids: Tuple[str, ...] = ()
    parent_call_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    plan_run_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    plan_node_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    plan_item_index: Optional[int] = Field(default=None, ge=0)
    plan_attempt: Optional[int] = Field(default=None, ge=1)
    mapped_step_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)

    @property
    def attribution(self) -> Attribution:
        """Resolve this snapshot's attribution.

        An explicit plan-to-task-step mapping overrides the declaration
        count. Without one, an unmapped plan call stays task-level with
        ``plan`` provenance rather than being attributed to a guessed
        step.

        Returns:
            The resolved :class:`Attribution`.
        """
        if self.mapped_step_id is not None:
            return Attribution.PLAN
        if self.plan_node_id is not None:
            return Attribution.PLAN
        count = len(self.declared_step_ids)
        if count == 0:
            return Attribution.NONE
        if count == 1:
            return Attribution.DECLARED
        return Attribution.AMBIGUOUS

    @property
    def attributed_step_id(self) -> Optional[str]:
        """The step this invocation is attributed to, if exactly one.

        Returns ``None`` for ``none``, ``ambiguous`` and unmapped plan
        calls — all three are task-level, and attribution never
        completes a step regardless.
        """
        if self.mapped_step_id is not None:
            return self.mapped_step_id
        if self.plan_node_id is not None:
            return None
        if len(self.declared_step_ids) == 1:
            return self.declared_step_ids[0]
        return None


class InvocationRecord(_TaskModel):
    """One physical dispatch attempt, captured once by the observer (D5).

    ``invocation`` is the existing compaction
    :class:`~parrot.memory.compaction.models.ToolInvocation` — preserved
    unchanged as the shared normalized payload. Correlation, cancellation
    and unknown outcomes live *here*, not as new members of that model's
    enum, because the same record feeds both the journal and
    ``ConversationTurn.tool_invocations``.

    The dataclass is kept as an opaque object rather than re-declared as a
    Pydantic model, so this module stays leaf-safe and the compaction
    serializer keeps ownership of its own shape.

    Attributes:
        call_id: Identity of this physical attempt.
        attempt: 1-based attempt number.
        parent_call_id: Parent aggregate call, when nested. A parent is
            distinguishable from its children and is not counted as a
            second execution of each child.
        tool_name: The dispatched tool.
        context: Frozen task context captured at dispatch.
        outcome: Typed outcome of the attempt.
        executed: Whether a tool body actually ran.
        error: Condensed, redacted error text.
        elapsed_ms: Wall-clock duration.
        started_at: When the attempt began.
        finished_at: When it terminated, if it did.
        artifact_receipts: Artifact versions this attempt produced.
        invocation: The canonical compaction ``ToolInvocation``, or
            ``None`` before the terminal result is known.
        degraded: Whether tracking for this attempt is degraded.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=False)

    call_id: str = Field(default_factory=new_id, max_length=Limits.MAX_IDENTIFIER)
    attempt: int = Field(default=1, ge=1)
    parent_call_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    tool_name: str = Field(max_length=Limits.MAX_IDENTIFIER)
    context: TaskContext
    outcome: Optional[CallOutcome] = None
    executed: bool = False
    error: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    elapsed_ms: Optional[int] = Field(default=None, ge=0)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    artifact_receipts: Tuple[EvidenceRef, ...] = ()
    invocation: Optional[Any] = None
    degraded: bool = False

    @field_validator("started_at", "finished_at")
    @classmethod
    def _check_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Require timezone-aware UTC timestamps.

        Args:
            value: The timestamp, or ``None``.

        Returns:
            The normalized timestamp.
        """
        return None if value is None else _require_utc(value)

    @property
    def terminal_event_type(self) -> Optional[EventType]:
        """The journal event type this attempt's outcome maps to.

        Returns:
            The matching :class:`EventType`, or ``None`` while the
            attempt is still in flight.
        """
        return _TERMINAL_EVENT_BY_OUTCOME.get(self.outcome) if self.outcome else None


_TERMINAL_EVENT_BY_OUTCOME: Dict[CallOutcome, EventType] = {
    CallOutcome.SUCCESS: EventType.TOOL_SUCCEEDED,
    CallOutcome.ERROR: EventType.TOOL_FAILED,
    CallOutcome.DENIED: EventType.TOOL_FAILED,
    CallOutcome.NOT_EXECUTED: EventType.TOOL_FAILED,
    CallOutcome.CANCELLED: EventType.TOOL_CANCELLED,
    CallOutcome.UNKNOWN: EventType.TOOL_OUTCOME_UNKNOWN,
}


# ─────────────────────────────────────────────────────────────
# Plan change commands
# ─────────────────────────────────────────────────────────────


class InitialStepSpec(_TaskModel):
    """A step in an *initial* plan, addressed by a request-local label.

    An initial plan cannot reference runtime step ids because none exist
    yet. Labels are resolved to runtime ids **before** anything is
    appended, so a malformed initial plan is rejected without mutating
    the task.

    Attributes:
        label: Request-local label, unique within this request.
        title: Short human-readable label.
        description: Longer explanation.
        required: Whether the task can complete without this step.
        depends_on_labels: Labels of steps this one depends on. Resolved
            to runtime ids by the service.
        completion_policy: How the step may be completed.
    """

    label: str = Field(min_length=1, max_length=Limits.MAX_IDENTIFIER)
    title: str = Field(min_length=1, max_length=Limits.MAX_STEP_TITLE)
    description: str = Field(default="", max_length=Limits.MAX_STEP_DESCRIPTION)
    required: bool = True
    depends_on_labels: Tuple[str, ...] = ()
    completion_policy: CompletionPolicy = Field(default_factory=CompletionPolicy)

    @field_validator("depends_on_labels")
    @classmethod
    def _check_labels(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        """Bound and de-duplicate the label dependency list.

        Args:
            value: Declared dependency labels.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If there are too many dependencies.
            PlanValidationError: If a label repeats.
        """
        if len(value) > Limits.MAX_STEP_DEPENDENCIES:
            raise LimitExceeded("depends_on_labels", Limits.MAX_STEP_DEPENDENCIES, len(value))
        if len(set(value)) != len(value):
            raise PlanValidationError("duplicate dependency labels on a step")
        return value


class AddStep(_TaskModel):
    """Add a step to an existing plan.

    Attributes:
        op: Discriminator.
        label: Request-local label so that steps added in the same batch
            can depend on one another before their ids exist.
        title: Short human-readable label.
        description: Longer explanation.
        required: Whether the task can complete without this step.
        depends_on: Existing runtime step ids this one depends on.
        depends_on_labels: Labels of steps added in the same batch.
        completion_policy: How the step may be completed.
    """

    op: Literal["add_step"] = "add_step"
    label: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    title: str = Field(min_length=1, max_length=Limits.MAX_STEP_TITLE)
    description: str = Field(default="", max_length=Limits.MAX_STEP_DESCRIPTION)
    required: bool = True
    depends_on: Tuple[str, ...] = ()
    depends_on_labels: Tuple[str, ...] = ()
    completion_policy: CompletionPolicy = Field(default_factory=CompletionPolicy)


class UpdateStep(_TaskModel):
    """Update an existing step's mutable fields.

    Completed criteria and inputs cannot be edited in place: the service
    rejects such an update and requires an explicit reopen instead.

    Attributes:
        op: Discriminator.
        step_id: The step to update. Immutable identity.
        title: New title, when changing it.
        description: New description, when changing it.
        required: New required flag, when changing it.
        depends_on: Replacement dependency list, when changing it.
        completion_policy: Replacement policy, when changing it.
    """

    op: Literal["update_step"] = "update_step"
    step_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    title: Optional[str] = Field(default=None, min_length=1, max_length=Limits.MAX_STEP_TITLE)
    description: Optional[str] = Field(default=None, max_length=Limits.MAX_STEP_DESCRIPTION)
    required: Optional[bool] = None
    depends_on: Optional[Tuple[str, ...]] = None
    completion_policy: Optional[CompletionPolicy] = None


class SupersedeStep(_TaskModel):
    """Retire a step without deleting it.

    A removed step becomes ``superseded`` and keeps its evidence and
    history. Superseded steps never satisfy a dependent's readiness.

    Attributes:
        op: Discriminator.
        step_id: The step to retire.
        reason: Why it was retired.
        replaced_by_label: Label of the step replacing it, when the same
            batch adds one.
    """

    op: Literal["supersede_step"] = "supersede_step"
    step_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)
    replaced_by_label: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)


class AddConstraint(_TaskModel):
    """Add a standing constraint.

    Attributes:
        op: Discriminator.
        text: The constraint.
    """

    op: Literal["add_constraint"] = "add_constraint"
    text: str = Field(min_length=1, max_length=Limits.MAX_CONSTRAINT_TEXT)


class UpdateConstraint(_TaskModel):
    """Reword an existing constraint.

    Attributes:
        op: Discriminator.
        constraint_id: The constraint to update.
        text: Its new text.
    """

    op: Literal["update_constraint"] = "update_constraint"
    constraint_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    text: str = Field(min_length=1, max_length=Limits.MAX_CONSTRAINT_TEXT)


class DeactivateConstraint(_TaskModel):
    """Retire a constraint without deleting it.

    Attributes:
        op: Discriminator.
        constraint_id: The constraint to retire.
        reason: Why.
    """

    op: Literal["deactivate_constraint"] = "deactivate_constraint"
    constraint_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)


class SetPlanComplete(_TaskModel):
    """Declare the plan complete (or incomplete again).

    Attributes:
        op: Discriminator.
        plan_complete: The new flag value.
    """

    op: Literal["set_plan_complete"] = "set_plan_complete"
    plan_complete: bool = True


#: Discriminated union of every plan-change operation.
PlanChange = Annotated[
    Union[
        AddStep,
        UpdateStep,
        SupersedeStep,
        AddConstraint,
        UpdateConstraint,
        DeactivateConstraint,
        SetPlanComplete,
    ],
    Field(discriminator="op"),
]


class PlanChanges(_TaskModel):
    """An ordered batch of plan changes, validated before any is applied.

    Dependencies, criteria and inputs are validated across the whole
    batch first; a batch that would produce a cycle, a duplicate id or a
    missing dependency is rejected in full.

    Attributes:
        changes: The operations to apply, in order.
    """

    changes: Tuple[PlanChange, ...] = ()

    @field_validator("changes")
    @classmethod
    def _check_batch(cls, value: Tuple[PlanChange, ...]) -> Tuple[PlanChange, ...]:
        """Bound the batch and reject duplicate request-local labels.

        Args:
            value: The batch's operations.

        Returns:
            The validated tuple.

        Raises:
            LimitExceeded: If the batch is larger than a whole plan.
            PlanValidationError: If two added steps share a label.
        """
        if len(value) > Limits.MAX_STEPS_PER_TASK:
            raise LimitExceeded("plan changes", Limits.MAX_STEPS_PER_TASK, len(value))
        labels = [c.label for c in value if isinstance(c, AddStep) and c.label is not None]
        if len(set(labels)) != len(labels):
            raise PlanValidationError("duplicate request-local labels in plan changes")
        return value

    @property
    def is_empty(self) -> bool:
        """Whether the batch contains no operations."""
        return not self.changes
