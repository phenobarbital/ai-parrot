"""Recoverable task memory for :class:`WorkingMemoryToolkit` (FEAT-538).

Working memory retains *named intermediate results*. It does not retain a
task's goal, constraints, plan, evidence, decisions or unresolved
failures as a recoverable unit — so after conversation compaction or a
process/REPL restart an agent cannot tell what is done, which result is
authoritative, or what is safe to run next. Mutable aliases are not
evidence of completed work.

This package adds that missing unit:

- **The journal is the source of truth**; ``TaskState`` is a pure,
  versioned reducer projection of it (D6). Replay never re-executes
  validators or tools.
- **Evidence is versioned.** Registering an artifact allocates
  ``artifact_id@version``; overwriting an alias moves the alias and
  increments the version, so older evidence stays valid and resolvable.
- **Attribution is turn-scoped and declared** (D3): ``declared``,
  ``plan``, ``none`` or ``ambiguous``. Attribution never completes a
  step, and a successful tool call is never evidence on its own.
- **Recall is bounded, deterministic and read-only** (D5). It appends no
  events, loads no data, and runs no tools.

Layout::

    models.py    domain models, enums, limits and typed errors
    config.py    opt-in TASK_MEMORY_* configuration

Every symbol re-exported here is leaf-safe: importing this package pulls
in stdlib, ``pydantic`` and ``orjson`` only, never a concrete backend,
``pandas`` or the toolkit itself. Concrete backends are imported lazily
by the components that need them.

.. warning::

   **Delivery A is not durable.** It provides in-process continuity.
   Durable multi-pod continuity — PostgreSQL, blob write-through, crash
   reconciliation, retention scheduling — arrives with Delivery B. Do
   not describe Delivery A as recoverable across a restart.
"""

from .config import DEFAULT_REDACTED_KEYS, MIB, TaskMemoryConfig
from .models import (
    SCHEMA_VERSION,
    Actor,
    AddConstraint,
    AddStep,
    ArtifactAvailability,
    ArtifactDescriptor,
    ArtifactKind,
    ArtifactPayload,
    Attribution,
    CallOutcome,
    CompletionMode,
    CompletionPolicy,
    CompletionSource,
    Constraint,
    CursorError,
    DeactivateConstraint,
    Decision,
    DecisionPayload,
    DegradedPayload,
    EventType,
    EvidenceRef,
    InitialStepSpec,
    InvocationRecord,
    JournalEvent,
    LimitExceeded,
    Limits,
    PlanChange,
    PlanChanges,
    PlanConstraintSpec,
    PlanStepPatch,
    PlanStepSpec,
    PlanUpdatePayload,
    PlanValidationError,
    ReducerError,
    ReplBinding,
    ResumeHint,
    ResumeHintPayload,
    RetentionPayload,
    RevisionConflict,
    ScopeViolation,
    SetPlanComplete,
    StepPayload,
    StepStatus,
    SupersedeStep,
    TaskContext,
    TaskLifecyclePayload,
    TaskMemoryError,
    TaskMemoryUnavailable,
    TaskScope,
    TaskState,
    TaskStatus,
    TaskStep,
    ToolCallPayload,
    UnknownValidatorError,
    UpdateConstraint,
    UpdateStep,
    new_id,
    serialized_bytes,
    utc_now,
)

__all__ = (
    "SCHEMA_VERSION",
    "MIB",
    "DEFAULT_REDACTED_KEYS",
    "TaskMemoryConfig",
    "Actor",
    "AddConstraint",
    "AddStep",
    "ArtifactAvailability",
    "ArtifactDescriptor",
    "ArtifactKind",
    "ArtifactPayload",
    "Attribution",
    "CallOutcome",
    "CompletionMode",
    "CompletionPolicy",
    "CompletionSource",
    "Constraint",
    "CursorError",
    "Decision",
    "DecisionPayload",
    "DeactivateConstraint",
    "DegradedPayload",
    "EventType",
    "EvidenceRef",
    "InitialStepSpec",
    "InvocationRecord",
    "JournalEvent",
    "LimitExceeded",
    "Limits",
    "PlanChange",
    "PlanChanges",
    "PlanConstraintSpec",
    "PlanStepPatch",
    "PlanStepSpec",
    "PlanUpdatePayload",
    "PlanValidationError",
    "ReducerError",
    "ReplBinding",
    "ResumeHint",
    "ResumeHintPayload",
    "RetentionPayload",
    "RevisionConflict",
    "ScopeViolation",
    "SetPlanComplete",
    "StepPayload",
    "StepStatus",
    "SupersedeStep",
    "TaskContext",
    "TaskLifecyclePayload",
    "TaskMemoryError",
    "TaskMemoryUnavailable",
    "TaskScope",
    "TaskState",
    "TaskStatus",
    "TaskStep",
    "ToolCallPayload",
    "UnknownValidatorError",
    "UpdateConstraint",
    "UpdateStep",
    "new_id",
    "serialized_bytes",
    "utc_now",
)
