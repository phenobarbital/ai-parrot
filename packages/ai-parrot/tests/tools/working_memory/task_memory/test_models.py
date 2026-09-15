"""Unit tests for the task-memory domain models (FEAT-538 / TASK-2971).

Three required cases from the task's Test Specification:

- ``test_bounds`` — overlong strings, oversized collections, oversized
  serialized UTF-8 event payloads and unknown enum/schema versions are
  all rejected, and rejection happens before any mutation.
- ``test_roundtrip`` — every event payload variant survives a
  serialize/deserialize round trip with its typed fields intact, and the
  derived active/ready step lists are *not* persisted duplicate state.
- ``test_defaults`` — configuration defaults match the specification.

Each is implemented as a group of focused ``test_bounds_*`` /
``test_roundtrip_*`` / ``test_defaults_*`` functions plus an aggregate
function carrying the required name, so a failure names the specific
invariant that broke rather than just the group.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import orjson
import pytest
from parrot.tools.working_memory.task_memory import (
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
    SetPlanComplete,
    StepPayload,
    StepStatus,
    SupersedeStep,
    TaskContext,
    TaskLifecyclePayload,
    TaskMemoryConfig,
    TaskScope,
    TaskState,
    TaskStatus,
    TaskStep,
    ToolCallPayload,
    UpdateStep,
)
from parrot.tools.working_memory.task_memory.config import MIB
from pydantic import ValidationError

# ─────────────────────────────────────────────────────────────
# Fixtures (local — the shared fixture task is not yet complete)
# ─────────────────────────────────────────────────────────────


@pytest.fixture()
def scope() -> TaskScope:
    """Return a deterministic trusted scope."""
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


@pytest.fixture()
def plan() -> tuple[TaskStep, ...]:
    """Return a three-step plan: load → clean → report."""
    load = TaskStep(step_id="s-load", title="Load raw data")
    clean = TaskStep(step_id="s-clean", title="Clean data", depends_on=("s-load",))
    report = TaskStep(step_id="s-report", title="Write report", depends_on=("s-clean",))
    return (load, clean, report)


@pytest.fixture()
def task(scope: TaskScope, plan: tuple[TaskStep, ...]) -> TaskState:
    """Return an active task carrying the three-step plan."""
    return TaskState(
        task_id="t-1",
        scope=scope,
        goal="Produce the quarterly report",
        constraints=(Constraint(constraint_id="c-1", text="Never mutate the source file"),),
        steps=plan,
    )


def _with_status(task: TaskState, step_id: str, status: StepStatus) -> TaskState:
    """Return ``task`` with one step's status replaced.

    Args:
        task: The task to derive from.
        step_id: The step to change.
        status: Its new status.

    Returns:
        A new :class:`TaskState`.
    """
    steps = tuple(s.model_copy(update={"status": status}) if s.step_id == step_id else s for s in task.steps)
    return task.model_copy(update={"steps": steps})


# ─────────────────────────────────────────────────────────────
# Bounds
# ─────────────────────────────────────────────────────────────


def test_bounds_rejects_overlong_strings(scope: TaskScope) -> None:
    """Every bounded text field rejects a value one character too long."""
    with pytest.raises(ValidationError):
        TaskState(scope=scope, goal="g" * (Limits.MAX_GOAL + 1))
    with pytest.raises(ValidationError):
        Constraint(text="c" * (Limits.MAX_CONSTRAINT_TEXT + 1))
    with pytest.raises(ValidationError):
        TaskStep(title="t" * (Limits.MAX_STEP_TITLE + 1))
    with pytest.raises(ValidationError):
        TaskStep(title="ok", description="d" * (Limits.MAX_STEP_DESCRIPTION + 1))
    with pytest.raises(ValidationError):
        Decision(text="d" * (Limits.MAX_DECISION_TEXT + 1))
    with pytest.raises(ValidationError):
        ResumeHint(text="h" * (Limits.MAX_HINT_TEXT + 1))
    with pytest.raises(ValidationError):
        TaskScope(chatbot_id="b" * (Limits.MAX_IDENTIFIER + 1), user_id="u", session_id="s")


def test_bounds_rejects_empty_required_text(scope: TaskScope) -> None:
    """Required text fields reject the empty string, not just overlong ones."""
    with pytest.raises(ValidationError):
        TaskState(scope=scope, goal="")
    with pytest.raises(ValidationError):
        TaskStep(title="")
    with pytest.raises(ValidationError):
        TaskScope(chatbot_id="", user_id="u", session_id="s")


def test_bounds_rejects_oversized_collections(scope: TaskScope) -> None:
    """Collection limits raise the typed LimitExceeded, not a bare ValueError."""
    too_many_deps = tuple(f"d{i}" for i in range(Limits.MAX_STEP_DEPENDENCIES + 1))
    with pytest.raises(LimitExceeded) as excinfo:
        TaskStep(title="ok", depends_on=too_many_deps)
    assert excinfo.value.field == "depends_on"
    assert excinfo.value.limit == Limits.MAX_STEP_DEPENDENCIES
    assert excinfo.value.actual == Limits.MAX_STEP_DEPENDENCIES + 1

    too_many_refs = tuple(EvidenceRef(artifact_id=f"a{i}", version=1) for i in range(Limits.MAX_STEP_EVIDENCE_REFS + 1))
    with pytest.raises(LimitExceeded):
        TaskStep(title="ok", evidence_refs=too_many_refs)

    with pytest.raises(LimitExceeded):
        CompletionPolicy(validators=tuple(f"v{i}" for i in range(Limits.MAX_POLICY_VALIDATORS + 1)))

    too_many_steps = tuple(TaskStep(step_id=f"s{i}", title="x") for i in range(Limits.MAX_STEPS_PER_TASK + 1))
    with pytest.raises(LimitExceeded):
        TaskState(scope=scope, goal="g", steps=too_many_steps)


def test_bounds_counts_active_entries_only(scope: TaskScope) -> None:
    """Retired constraints are retained for history and do not count against the active limit."""
    retired = tuple(
        Constraint(constraint_id=f"c{i}", text="x", active=False) for i in range(Limits.MAX_ACTIVE_CONSTRAINTS + 50)
    )
    state = TaskState(scope=scope, goal="g", constraints=retired)
    assert len(state.constraints) == Limits.MAX_ACTIVE_CONSTRAINTS + 50
    assert state.active_constraints == ()

    over_active = tuple(Constraint(constraint_id=f"a{i}", text="x") for i in range(Limits.MAX_ACTIVE_CONSTRAINTS + 1))
    with pytest.raises(LimitExceeded) as excinfo:
        TaskState(scope=scope, goal="g", constraints=over_active)
    assert excinfo.value.field == "active constraints"


def test_bounds_event_payload_is_measured_in_utf8_bytes() -> None:
    """The journal payload limit is serialized UTF-8 bytes, not dict-item count."""
    # A few dict items, but far past the byte ceiling.
    huge_reason = "x" * (Limits.MAX_EVENT_PAYLOAD_BYTES + 10)
    with pytest.raises(ValidationError):
        # Rejected by the field's own max_length first.
        TaskLifecyclePayload(status=TaskStatus.ACTIVE, reason=huge_reason)

    # Assemble a payload that passes every field bound yet still exceeds
    # the payload byte ceiling once serialized: many short refs.
    refs = tuple(EvidenceRef(artifact_id="a" * 100, version=n + 1) for n in range(100))
    payload = RetentionPayload(policy="terminal", action="archive", target_refs=refs)
    assert len(orjson.dumps(payload.model_dump(mode="json"))) > Limits.MAX_EVENT_PAYLOAD_BYTES

    with pytest.raises(LimitExceeded) as excinfo:
        JournalEvent(task_id="t-1", event_type=EventType.RETENTION_SCHEDULED, payload=payload)
    assert excinfo.value.field == "event payload"
    assert "serialized UTF-8 bytes" in str(excinfo.value)


def test_bounds_multibyte_payload_counts_bytes_not_characters() -> None:
    """A payload of multibyte characters is measured by its byte length."""
    # Each '✓' is 3 UTF-8 bytes: well under the char count, over the byte cap.
    chars = (Limits.MAX_EVENT_PAYLOAD_BYTES // 3) + 50
    assert chars < Limits.MAX_EVENT_PAYLOAD_BYTES  # would pass a naive char check
    refs = tuple(EvidenceRef(artifact_id="✓" * 40, version=n + 1) for n in range(80))
    payload = RetentionPayload(policy="p", action="a", target_refs=refs)
    with pytest.raises(LimitExceeded):
        JournalEvent(task_id="t-1", event_type=EventType.RETENTION_SCHEDULED, payload=payload)


def test_bounds_rejects_schema_summary_over_4kib(scope: TaskScope) -> None:
    """A captured schema summary above 4 KiB is rejected before it is stored."""
    summary = {f"column_{i}": "float64" * 4 for i in range(400)}
    with pytest.raises(LimitExceeded) as excinfo:
        ArtifactDescriptor(ref=EvidenceRef(artifact_id="a", version=1), scope=scope, schema_summary=summary)
    assert excinfo.value.field == "schema_summary"


def test_bounds_rejects_unknown_schema_version(scope: TaskScope) -> None:
    """A document from an unknown schema version is rejected, not best-effort parsed."""
    with pytest.raises(ValidationError):
        TaskState(scope=scope, goal="g", schema_version=SCHEMA_VERSION + 1)
    with pytest.raises(ValidationError):
        JournalEvent(
            task_id="t-1",
            event_type=EventType.TASK_STARTED,
            payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE),
            schema_version=99,
        )


def test_bounds_rejects_unknown_enum_members() -> None:
    """Unknown enum values are rejected rather than coerced."""
    with pytest.raises(ValidationError):
        TaskStep(title="ok", status="almost-done")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Decision(text="d", actor="intern")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        CompletionPolicy(mode="probably")  # type: ignore[arg-type]


def test_bounds_rejects_extra_fields(scope: TaskScope) -> None:
    """An unrecognised field means an unknown writer schema; it is not dropped silently."""
    with pytest.raises(ValidationError):
        TaskState(scope=scope, goal="g", surprise=1)  # type: ignore[call-arg]


def test_bounds_rejects_naive_timestamps(scope: TaskScope) -> None:
    """Naive datetimes are rejected, never silently localized."""
    with pytest.raises(ValidationError):
        TaskState(scope=scope, goal="g", created_at=datetime(2026, 1, 1, 12, 0, 0))
    with pytest.raises(ValidationError):
        JournalEvent(
            task_id="t",
            event_type=EventType.TASK_STARTED,
            payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE),
            occurred_at=datetime(2026, 1, 1),
        )


def test_bounds_normalizes_aware_timestamps_to_utc(scope: TaskScope) -> None:
    """A non-UTC aware timestamp is normalized, preserving the instant."""
    plus_two = timezone(timedelta(hours=2))
    state = TaskState(scope=scope, goal="g", created_at=datetime(2026, 1, 1, 14, 0, tzinfo=plus_two))
    assert state.created_at.tzinfo == timezone.utc
    assert state.created_at == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_bounds_rejects_bare_alias_as_evidence() -> None:
    """A bare alias is not evidence: it is mutable, so parsing rejects it."""
    with pytest.raises(ValueError, match="not an exact evidence reference"):
        EvidenceRef.parse("sales_clean")
    with pytest.raises(ValueError, match="positive integer"):
        EvidenceRef.parse("sales_clean@latest")
    ref = EvidenceRef.parse("sales_clean@3")
    assert (ref.artifact_id, ref.version) == ("sales_clean", 3)
    assert str(ref) == "sales_clean@3"
    with pytest.raises(ValidationError):
        EvidenceRef(artifact_id="a", version=0)


def test_bounds_rejects_self_dependency_and_duplicates() -> None:
    """Structural plan errors raise the typed PlanValidationError."""
    with pytest.raises(PlanValidationError, match="depends on itself"):
        TaskStep(step_id="s1", title="x", depends_on=("s1",))
    with pytest.raises(PlanValidationError, match="duplicate dependency ids"):
        TaskStep(title="x", depends_on=("a", "a"))
    with pytest.raises(PlanValidationError, match="duplicate step ids"):
        TaskState(
            scope=TaskScope(chatbot_id="b", user_id="u", session_id="s"),
            goal="g",
            steps=(TaskStep(step_id="dup", title="a"), TaskStep(step_id="dup", title="b")),
        )
    with pytest.raises(PlanValidationError, match="duplicate request-local labels"):
        PlanChanges(changes=(AddStep(label="x", title="a"), AddStep(label="x", title="b")))
    with pytest.raises(PlanValidationError, match="duplicate dependency labels"):
        InitialStepSpec(label="a", title="t", depends_on_labels=("z", "z"))


def test_bounds_rejects_optional_completion_note() -> None:
    """``require_note`` cannot be turned off; the note is always mandatory."""
    with pytest.raises(ValidationError):
        CompletionPolicy(require_note=False)


def test_bounds_rejects_unverifiable_evidence_claims(scope: TaskScope) -> None:
    """A descriptor cannot claim verifiable evidence it cannot prove."""
    ref = EvidenceRef(artifact_id="a", version=1)
    with pytest.raises(ValidationError, match="requires a fingerprint"):
        ArtifactDescriptor(ref=ref, scope=scope, kind=ArtifactKind.JSON, evidence_verifiable=True)
    with pytest.raises(ValidationError, match="cannot carry verifiable evidence"):
        ArtifactDescriptor(
            ref=ref,
            scope=scope,
            kind=ArtifactKind.OBJECT,
            fingerprint="fp_deadbeefdeadbeef",
            evidence_verifiable=True,
        )
    ok = ArtifactDescriptor(
        ref=ref,
        scope=scope,
        kind=ArtifactKind.DATAFRAME,
        fingerprint="fp_deadbeefdeadbeef",
        fingerprint_algorithm="blake2b-8/v1",
        evidence_verifiable=True,
    )
    assert ok.evidence_verifiable is True


def test_bounds_rejects_payload_family_mismatch() -> None:
    """An event whose payload family is wrong is malformed, not guessable."""
    with pytest.raises(ReducerError, match="requires a 'task_lifecycle' payload"):
        JournalEvent(
            task_id="t-1",
            event_type=EventType.TASK_STARTED,
            payload=StepPayload(step_id="s", status=StepStatus.COMPLETED),
        )
    with pytest.raises(ReducerError, match="requires a 'tool_call' payload"):
        JournalEvent(
            task_id="t-1",
            event_type=EventType.TOOL_SUCCEEDED,
            payload=DegradedPayload(component="journal"),
        )


def test_bounds_rejection_leaves_nothing_mutated(task: TaskState) -> None:
    """A rejected command mutates nothing — validation happens before any write."""
    before = task.model_dump(mode="json")

    oversized = before | {
        "steps": [
            TaskStep(step_id=f"s{i}", title="x").model_dump(mode="json") for i in range(Limits.MAX_STEPS_PER_TASK + 1)
        ]
    }
    with pytest.raises(LimitExceeded):
        TaskState.model_validate(oversized)

    assert task.model_dump(mode="json") == before, "a rejected validation must not touch the source state"

    # Frozen models cannot be mutated at all — there is no partial-write
    # window in which a limit check could be bypassed.
    with pytest.raises(ValidationError):
        task.goal = "something else"  # type: ignore[misc]
    assert task.goal == before["goal"]


def test_bounds() -> None:
    """Required aggregate case: bounds, enums and schema versions are enforced.

    Delegates to the focused ``test_bounds_*`` functions above, which
    pytest also collects individually so a failure names the exact
    invariant.
    """
    scope = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    test_bounds_rejects_overlong_strings(scope)
    test_bounds_rejects_empty_required_text(scope)
    test_bounds_rejects_oversized_collections(scope)
    test_bounds_counts_active_entries_only(scope)
    test_bounds_event_payload_is_measured_in_utf8_bytes()
    test_bounds_multibyte_payload_counts_bytes_not_characters()
    test_bounds_rejects_schema_summary_over_4kib(scope)
    test_bounds_rejects_unknown_schema_version(scope)
    test_bounds_rejects_unknown_enum_members()
    test_bounds_rejects_extra_fields(scope)
    test_bounds_rejects_naive_timestamps(scope)
    test_bounds_rejects_bare_alias_as_evidence()
    test_bounds_rejects_self_dependency_and_duplicates()
    test_bounds_rejects_optional_completion_note()
    test_bounds_rejects_unverifiable_evidence_claims(scope)
    test_bounds_rejects_payload_family_mismatch()


# ─────────────────────────────────────────────────────────────
# Round trip
# ─────────────────────────────────────────────────────────────


def _all_payloads() -> tuple[object, ...]:
    """Return one populated instance of every payload variant."""
    ref = EvidenceRef(artifact_id="artifact-1", version=2)
    return (
        TaskLifecyclePayload(status=TaskStatus.PAUSED, goal="g", reason="inactivity"),
        PlanUpdatePayload(
            added_steps=(PlanStepSpec(step_id="s-new", title="Fetch prices"),),
            updated_steps=(PlanStepPatch(step_id="s-old", title="Clean data v2"),),
            superseded_step_ids=("s-gone",),
            added_constraints=(PlanConstraintSpec(constraint_id="c-1", text="Budget under 1000 rows"),),
            deactivated_constraint_ids=("c-0",),
            plan_complete=True,
            reason="replan",
        ),
        DecisionPayload(decision_id="d-1", text="use parquet", reason="faster", affected_step_ids=("s1",)),
        ResumeHintPayload(text="clean the data next", step_id="s-clean"),
        StepPayload(
            step_id="s-clean",
            status=StepStatus.COMPLETED,
            evidence_refs=(ref,),
            completion_source=CompletionSource.VALIDATED,
            note="validated against the snapshot",
            validator_results=(("artifact_exists", True), ("artifact_non_empty", True)),
        ),
        ToolCallPayload(
            call_id="call-1",
            tool_name="wm_store",
            attempt=2,
            executed=True,
            outcome=CallOutcome.ERROR,
            error="ValueError: bad column",
            elapsed_ms=42,
            artifact_refs=(ref,),
            counted=True,
        ),
        ArtifactPayload(
            ref=ref,
            alias="sales_clean",
            artifact_kind=ArtifactKind.DATAFRAME,
            availability=ArtifactAvailability.PERSISTED,
            fingerprint="fp_0123456789abcdef",
            fingerprint_algorithm="blake2b-8/v1",
            evidence_verifiable=True,
            byte_size=1234,
        ),
        DegradedPayload(component="journal", detail="append timed out", recovered=False),
        RetentionPayload(
            policy="terminal",
            action="archive",
            due_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            target_refs=(ref,),
            archive_uri="s3://bucket/tasks/",
        ),
    )


@pytest.mark.parametrize("payload", _all_payloads(), ids=lambda p: p.kind)
def test_roundtrip_every_payload_variant(payload: object) -> None:
    """Every payload variant round-trips through JSON with typed fields intact."""
    event_type = next(et for et, family in _families().items() if family == payload.kind)  # type: ignore[attr-defined]
    event = JournalEvent(
        task_id="t-1",
        seq=7,
        event_type=event_type,
        actor=Actor.AGENT,
        turn_id="turn-9",
        plan_revision=3,
        step_id="s-clean",
        call_id="call-1",
        parent_call_id="call-0",
        attribution=Attribution.DECLARED,
        payload=payload,  # type: ignore[arg-type]
    )
    encoded = event.model_dump_json()
    restored = JournalEvent.model_validate_json(encoded)
    assert restored == event
    assert restored.payload == payload
    assert type(restored.payload) is type(payload)


def _families() -> dict:
    """Return the event-type → payload-family map (imported lazily for clarity)."""
    from parrot.tools.working_memory.task_memory.models import PAYLOAD_FAMILY_BY_EVENT

    return PAYLOAD_FAMILY_BY_EVENT


def test_roundtrip_every_event_type_has_a_payload_family() -> None:
    """No event type is missing from the family map — a gap would crash the reducer."""
    families = _families()
    assert set(families) == set(EventType), f"unmapped event types: {set(EventType) - set(families)}"


def test_roundtrip_task_state(task: TaskState) -> None:
    """A full TaskState survives a JSON round trip unchanged."""
    task = task.model_copy(
        update={
            "decisions": (Decision(decision_id="d-1", text="use parquet", actor=Actor.AGENT),),
            "resume_hint": ResumeHint(text="clean next", step_id="s-clean", stale=True),
            "plan_complete": True,
            "revision": 5,
            "plan_revision": 2,
            "last_event_seq": 11,
        }
    )
    restored = TaskState.model_validate_json(task.model_dump_json())
    assert restored == task
    assert restored.resume_hint is not None
    assert restored.resume_hint.stale is True
    assert restored.decisions[0].actor is Actor.AGENT


def test_roundtrip_derived_lists_are_not_persisted(task: TaskState) -> None:
    """Active/ready step ids are computed, never stored as duplicate state."""
    dumped = task.model_dump()
    for derived in ("active_step_ids", "ready_step_ids", "active_constraints", "active_decisions", "can_complete"):
        assert derived not in dumped, f"{derived} must be derived, not persisted"
    assert "steps_by_id" not in dumped


def test_roundtrip_derived_readiness_rules(task: TaskState) -> None:
    """Only a *completed* dependency makes a dependent step ready."""
    assert task.ready_step_ids == ("s-load",)
    assert set(task.active_step_ids) == {"s-load", "s-clean", "s-report"}

    running = _with_status(task, "s-load", StepStatus.RUNNING)
    assert running.ready_step_ids == ()

    for blocking in (StepStatus.FAILED, StepStatus.BLOCKED, StepStatus.SUPERSEDED, StepStatus.CANCELLED):
        state = _with_status(task, "s-load", blocking)
        assert state.ready_step_ids == (), f"{blocking.value} dependency must not satisfy readiness"

    done = _with_status(task, "s-load", StepStatus.COMPLETED)
    assert done.ready_step_ids == ("s-clean",)
    assert "s-load" not in done.active_step_ids


def test_roundtrip_completion_guard(task: TaskState) -> None:
    """A task completes only with plan_complete and every required step completed."""
    assert task.can_complete is False  # plan not declared complete

    declared = task.model_copy(update={"plan_complete": True})
    assert declared.can_complete is False  # exhausted partial plan stays active

    all_done = declared
    for step_id in ("s-load", "s-clean", "s-report"):
        all_done = _with_status(all_done, step_id, StepStatus.COMPLETED)
    assert all_done.can_complete is True

    # A superseded required step does not block completion; an optional
    # incomplete one does not either.
    superseded = _with_status(all_done, "s-report", StepStatus.SUPERSEDED)
    assert superseded.can_complete is True
    optional = all_done.model_copy(
        update={
            "steps": tuple(
                s.model_copy(update={"status": StepStatus.PENDING, "required": False}) if s.step_id == "s-report" else s
                for s in all_done.steps
            )
        }
    )
    assert optional.can_complete is True


def test_roundtrip_terminal_status_helpers() -> None:
    """Terminal-status helpers agree with the specification's status lists."""
    assert {s for s in TaskStatus if s.is_terminal} == {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
    assert {s for s in StepStatus if s.is_terminal} == {
        StepStatus.COMPLETED,
        StepStatus.CANCELLED,
        StepStatus.SUPERSEDED,
    }
    assert {o for o in CallOutcome if not o.is_resolved} == {CallOutcome.UNKNOWN, CallOutcome.CANCELLED}
    assert ArtifactKind.DATAFRAME.is_supported_evidence is True
    assert ArtifactKind.OBJECT.is_supported_evidence is False


def test_roundtrip_attribution_resolution(scope: TaskScope) -> None:
    """Attribution follows D3 exactly: 0 → none, 1 → declared, 2+ → ambiguous."""
    assert TaskContext(scope=scope).attribution is Attribution.NONE
    assert TaskContext(scope=scope, declared_step_ids=("s1",)).attribution is Attribution.DECLARED
    assert TaskContext(scope=scope, declared_step_ids=("s1", "s2")).attribution is Attribution.AMBIGUOUS

    # An unmapped plan call stays task-level with plan provenance: a plan
    # node id is NOT automatically a domain step id.
    unmapped = TaskContext(scope=scope, plan_node_id="node-3", declared_step_ids=("s1",))
    assert unmapped.attribution is Attribution.PLAN
    assert unmapped.attributed_step_id is None

    mapped = TaskContext(scope=scope, plan_node_id="node-3", mapped_step_id="s-clean")
    assert mapped.attribution is Attribution.PLAN
    assert mapped.attributed_step_id == "s-clean"

    assert TaskContext(scope=scope, declared_step_ids=("s1", "s2")).attributed_step_id is None


def test_roundtrip_invocation_record_maps_outcomes(scope: TaskScope) -> None:
    """Each typed outcome maps to exactly one terminal journal event type."""
    context = TaskContext(scope=scope, task_id="t-1", declared_step_ids=("s-clean",))
    record = InvocationRecord(call_id="c1", tool_name="wm_store", context=context)
    assert record.terminal_event_type is None  # still in flight

    expected = {
        CallOutcome.SUCCESS: EventType.TOOL_SUCCEEDED,
        CallOutcome.ERROR: EventType.TOOL_FAILED,
        CallOutcome.DENIED: EventType.TOOL_FAILED,
        CallOutcome.NOT_EXECUTED: EventType.TOOL_FAILED,
        CallOutcome.CANCELLED: EventType.TOOL_CANCELLED,
        CallOutcome.UNKNOWN: EventType.TOOL_OUTCOME_UNKNOWN,
    }
    for outcome, event_type in expected.items():
        assert record.model_copy(update={"outcome": outcome}).terminal_event_type is event_type


def test_roundtrip_plan_changes_discriminated_union() -> None:
    """Every plan-change operation round-trips as its own concrete type."""
    batch = PlanChanges(
        changes=(
            AddStep(label="new", title="Fetch prices", depends_on_labels=()),
            UpdateStep(step_id="s-clean", title="Clean data v2"),
            SupersedeStep(step_id="s-old", reason="replaced"),
            AddConstraint(text="Budget under 1000 rows"),
            DeactivateConstraint(constraint_id="c-1", reason="no longer applies"),
            SetPlanComplete(plan_complete=True),
        )
    )
    restored = PlanChanges.model_validate_json(batch.model_dump_json())
    assert restored == batch
    assert [type(c).__name__ for c in restored.changes] == [
        "AddStep",
        "UpdateStep",
        "SupersedeStep",
        "AddConstraint",
        "DeactivateConstraint",
        "SetPlanComplete",
    ]
    assert PlanChanges().is_empty is True


def test_roundtrip_plan_payload_carries_definitions_not_just_ids() -> None:
    """A plan event must let a reducer REBUILD the plan, not just name it.

    The journal is the source of truth (D6). An id-only ``plan_updated``
    would make the projection the real source of truth, because replay
    from an empty state could not reconstruct a step it never saw
    defined. The derived ``*_ids`` views exist for callers that only need
    the identities.
    """
    payload = PlanUpdatePayload(
        added_steps=(
            PlanStepSpec(step_id="s-a", title="Load", required=True),
            PlanStepSpec(step_id="s-b", title="Clean", depends_on=("s-a",)),
        ),
        updated_steps=(PlanStepPatch(step_id="s-a", description="Load from parquet"),),
        superseded_step_ids=("s-old",),
        added_constraints=(PlanConstraintSpec(constraint_id="c-1", text="Read-only source"),),
        deactivated_constraint_ids=("c-0",),
    )

    # Definitions survive the round trip, so replay can rebuild them.
    restored = PlanUpdatePayload.model_validate_json(payload.model_dump_json())
    assert restored == payload
    assert restored.added_steps[1].depends_on == ("s-a",)
    assert restored.updated_steps[0].description == "Load from parquet"
    assert restored.updated_steps[0].title is None, "None means 'unchanged', not 'cleared'"

    # Derived id views.
    assert payload.added_step_ids == ("s-a", "s-b")
    assert payload.updated_step_ids == ("s-a",)
    assert payload.added_constraint_ids == ("c-1",)
    assert set(payload.touched_step_ids) == {"s-a", "s-b", "s-old"}
    assert payload.is_empty is False
    assert PlanUpdatePayload().is_empty is True
    assert PlanUpdatePayload(plan_complete=True).is_empty is False


def test_roundtrip_artifact_descriptor_carries_no_payload(scope: TaskScope) -> None:
    """A descriptor is metadata only — it has no field that could hold rows."""
    descriptor = ArtifactDescriptor(
        ref=EvidenceRef(artifact_id="a", version=1),
        scope=scope,
        alias="sales_clean",
        kind=ArtifactKind.DATAFRAME,
        availability=ArtifactAvailability.MEMORY,
        fingerprint="fp_0123456789abcdef",
        fingerprint_algorithm="blake2b-8/v1",
        evidence_verifiable=True,
        byte_size=2048,
        shape=(1000, 12),
        schema_summary={"a": "float64", "b": "object"},
        repl_binding=ReplBinding(
            worker_session_id="w-1",
            worker_generation=3,
            variable_name="sales_clean",
            ref=EvidenceRef(artifact_id="a", version=1),
        ),
    )
    dumped = descriptor.model_dump()
    assert not {"data", "df", "rows", "payload", "preview"} & set(dumped)
    assert ArtifactDescriptor.model_validate_json(descriptor.model_dump_json()) == descriptor


def test_roundtrip_typed_errors_carry_their_context() -> None:
    """Typed errors expose the fields a caller needs to react, not just a string."""
    limit = LimitExceeded("steps", 10, 11, "detail here")
    assert (limit.field, limit.limit, limit.actual) == ("steps", 10, 11)
    assert "detail here" in str(limit)

    conflict = RevisionConflict("t-1", expected=3, current=5)
    assert (conflict.task_id, conflict.expected, conflict.current) == ("t-1", 3, 5)
    assert "expected 3, current 5" in str(conflict)


def test_roundtrip() -> None:
    """Required aggregate case: every event variant round-trips losslessly.

    Delegates to the focused ``test_roundtrip_*`` functions above.
    """
    scope = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    steps = (
        TaskStep(step_id="s-load", title="Load raw data"),
        TaskStep(step_id="s-clean", title="Clean data", depends_on=("s-load",)),
        TaskStep(step_id="s-report", title="Write report", depends_on=("s-clean",)),
    )
    state = TaskState(
        task_id="t-1",
        scope=scope,
        goal="Produce the quarterly report",
        constraints=(Constraint(constraint_id="c-1", text="Never mutate the source file"),),
        steps=steps,
    )
    for payload in _all_payloads():
        test_roundtrip_every_payload_variant(payload)
    test_roundtrip_every_event_type_has_a_payload_family()
    test_roundtrip_task_state(state)
    test_roundtrip_derived_lists_are_not_persisted(state)
    test_roundtrip_derived_readiness_rules(state)
    test_roundtrip_completion_guard(state)
    test_roundtrip_attribution_resolution(scope)
    test_roundtrip_plan_changes_discriminated_union()
    test_roundtrip_plan_payload_carries_definitions_not_just_ids()


# ─────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────


def test_defaults_are_opt_in() -> None:
    """Task memory is off unless a host turns it on (AC13)."""
    config = TaskMemoryConfig()
    assert config.enabled is False
    assert config.durable is False
    assert config.best_effort_tracking is False


def test_defaults_byte_budgets() -> None:
    """Snapshot, cache and rehydration budgets match the specification."""
    config = TaskMemoryConfig()
    assert config.snapshot_max_bytes == 64 * MIB == 67_108_864
    assert config.memory_cache_max_bytes == 512 * MIB == 536_870_912
    assert config.max_rehydrate_bytes == 2_000_000
    assert config.raw_page_limit_default == 100
    assert config.raw_page_limit_max == 1_000


def test_defaults_recall_bounds() -> None:
    """Recall defaults and ceilings match the specification."""
    config = TaskMemoryConfig()
    assert config.recall_max_tokens == 2_500
    assert config.recall_max_tokens_ceiling == 16_000
    assert config.recall_recent_calls_limit == 8
    assert config.recall_recent_calls_ceiling == 100
    assert config.recall_cache_ttl_seconds == 600


def test_defaults_retention_thresholds() -> None:
    """Every row of the specification's retention table has its default."""
    config = TaskMemoryConfig()
    assert config.inactivity_pause_days == 7
    assert config.abandoned_cancel_days == 30
    assert config.terminal_retention_days == 90
    assert config.unpinned_version_ttl_hours == 24
    assert config.orphan_blob_grace_hours == 1
    assert config.lease_ttl_seconds == 30
    assert config.context_ttl_seconds == 86_400
    assert config.journal_soft_limit == 50_000
    assert config.journal_hard_limit == 100_000
    assert config.journal_reserved_events == 1_000
    assert config.max_open_tasks_per_scope == 100
    assert config.archive_uri is None  # OQ1: no archive ⇒ deletion is irreversible


def test_defaults_rehydration_ceiling_cannot_be_raised() -> None:
    """A caller may lower the raw-read budget but never raise it."""
    config = TaskMemoryConfig()
    assert config.resolve_rehydrate_bytes(None) == 2_000_000
    assert config.resolve_rehydrate_bytes(1_000) == 1_000
    assert config.resolve_rehydrate_bytes(10_000_000) == 2_000_000
    with pytest.raises(ValueError):
        config.resolve_rehydrate_bytes(-1)

    never = TaskMemoryConfig(max_rehydrate_bytes=0)
    assert never.resolve_rehydrate_bytes(None) == 0
    assert never.resolve_rehydrate_bytes(5_000) == 0, "0 means never; no request may reopen it"


def test_defaults_page_limit_clamping() -> None:
    """Tabular page sizes clamp to the configured maximum."""
    config = TaskMemoryConfig()
    assert config.resolve_page_limit(None) == 100
    assert config.resolve_page_limit(50) == 50
    assert config.resolve_page_limit(99_999) == 1_000
    with pytest.raises(ValueError):
        config.resolve_page_limit(0)


def test_defaults_journal_reserved_headroom() -> None:
    """Foreground work is refused before terminal/recovery events are."""
    config = TaskMemoryConfig()
    assert config.is_journal_exhausted(99_999) is False
    assert config.is_journal_exhausted(100_000) is True
    # Reserved events still fit above the hard limit.
    assert config.is_journal_exhausted(100_000, reserved=True) is False
    assert config.is_journal_exhausted(101_000, reserved=True) is True
    assert {e for e in EventType if e.is_reserved} == {
        EventType.TASK_COMPLETED,
        EventType.TASK_FAILED,
        EventType.TASK_CANCELLED,
        EventType.TOOL_OUTCOME_UNKNOWN,
        EventType.TRACKING_DEGRADED,
        EventType.RETENTION_SCHEDULED,
    }


def test_defaults_redaction_keys() -> None:
    """The denied key set contains the specification's names plus configured additions."""
    config = TaskMemoryConfig()
    assert {"token", "secret", "password", "authorization", "api_key"} <= config.redacted_keys

    extended = TaskMemoryConfig(extra_redacted_keys=("Session-Cookie", " bearer "))
    assert "session-cookie" in extended.redacted_keys
    assert "bearer" in extended.redacted_keys
    assert {"token", "secret"} <= extended.redacted_keys


def test_defaults_builtin_validators_registered() -> None:
    """The four built-in completion validators are configured by default."""
    assert set(TaskMemoryConfig().validator_names) == {
        "artifact_exists",
        "artifact_fingerprint_matches",
        "artifact_non_empty",
        "no_pending_tool_failures",
    }


def test_defaults_reject_inconsistent_configuration() -> None:
    """Cross-field invariants are validated, not silently repaired."""
    with pytest.raises(ValidationError):
        TaskMemoryConfig(journal_soft_limit=200_000, journal_hard_limit=100_000)
    with pytest.raises(ValidationError):
        TaskMemoryConfig(recall_max_tokens=20_000)
    with pytest.raises(ValidationError):
        TaskMemoryConfig(recall_recent_calls_limit=500)
    with pytest.raises(ValidationError):
        TaskMemoryConfig(raw_page_limit_default=5_000)
    with pytest.raises(ValidationError):
        TaskMemoryConfig(inactivity_pause_days=30, abandoned_cancel_days=7)
    with pytest.raises(ValidationError):
        TaskMemoryConfig(unknown_knob=1)  # type: ignore[call-arg]


def test_defaults_config_is_frozen() -> None:
    """Configuration is immutable once built — no live retuning behind the code's back."""
    config = TaskMemoryConfig()
    with pytest.raises(ValidationError):
        config.enabled = True  # type: ignore[misc]


def test_defaults_from_env_overrides_win() -> None:
    """Explicit overrides beat the environment, and absent variables keep defaults."""
    config = TaskMemoryConfig.from_env(enabled=True, snapshot_max_bytes=8 * MIB)
    assert config.enabled is True
    assert config.snapshot_max_bytes == 8 * MIB
    # Untouched fields still carry the specification defaults.
    assert config.max_rehydrate_bytes == 2_000_000
    assert config.terminal_retention_days == 90


def test_defaults_completion_policy() -> None:
    """A default completion policy is the weaker, note-requiring one."""
    policy = CompletionPolicy()
    assert policy.mode is CompletionMode.AGENT_ASSERTED
    assert policy.require_note is True
    assert policy.validators == ()
    assert policy.expected_outputs == ()


def test_defaults() -> None:
    """Required aggregate case: configuration defaults match the specification.

    Delegates to the focused ``test_defaults_*`` functions above.
    """
    test_defaults_are_opt_in()
    test_defaults_byte_budgets()
    test_defaults_recall_bounds()
    test_defaults_retention_thresholds()
    test_defaults_rehydration_ceiling_cannot_be_raised()
    test_defaults_page_limit_clamping()
    test_defaults_journal_reserved_headroom()
    test_defaults_redaction_keys()
    test_defaults_builtin_validators_registered()
    test_defaults_reject_inconsistent_configuration()
    test_defaults_completion_policy()


# ─────────────────────────────────────────────────────────────
# Leaf-safety
# ─────────────────────────────────────────────────────────────


def test_models_module_is_leaf_safe() -> None:
    """models.py must load standalone, pulling in no heavy dependency.

    The module is loaded **directly from its path** rather than through
    ``parrot.tools.working_memory.task_memory``: importing it by package
    path would execute the parent packages' ``__init__`` modules, which
    legitimately import the toolkit and everything under it. What must be
    leaf-safe is the module itself, so that the store, reducer, observer
    and tool layers can all share one vocabulary without an import cycle.
    """
    import subprocess
    import sys
    from pathlib import Path

    from parrot.tools.working_memory.task_memory import models as _models

    module_path = Path(_models.__file__).resolve()
    assert module_path.is_file(), f"models.py not found at {module_path}"

    code = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('_tm_models', {str(module_path)!r});"
        "mod = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(mod);"
        "banned = [n for n in ('pandas', 'numpy', 'asyncpg', 'redis', 'pyarrow', 'parrot') "
        "if n in sys.modules];"
        "print('BANNED=' + ','.join(banned))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"models.py failed to load standalone:\n{result.stderr}"
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("BANNED="))
    banned = line.removeprefix("BANNED=")
    assert banned == "", f"models.py pulled in a non-leaf dependency: {banned}"
