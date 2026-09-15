"""Unit tests for the task-memory command service (FEAT-538 / TASK-2979).

Three required cases from the task's Test Specification:

- ``test_command_flow`` — begin, replan, pause/resume/cancel, decisions
  and hints produce the expected typed events and revisions.
- ``test_rejected_batch`` — a cycle, a missing dependency or a stale
  revision leaves the journal AND the projection unchanged.
- ``test_identity`` — scope is runtime-owned, and an explicit task id
  never permits crossing a scope.

The service is exercised against the real in-memory store and the real
reducer, not a mock. A mocked store would let the service claim
atomicity it never actually demonstrated.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import pytest
from parrot.interfaces.task_memory import TaskMemoryStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    Actor,
    AddConstraint,
    AddStep,
    CompletionPolicy,
    CompletionSource,
    DeactivateConstraint,
    EventType,
    EvidenceRef,
    InitialStepSpec,
    LimitExceeded,
    PlanChanges,
    PlanValidationError,
    RevisionConflict,
    SetPlanComplete,
    StepStatus,
    SupersedeStep,
    TaskScope,
    TaskStatus,
    UpdateStep,
)
from parrot.tools.working_memory.task_memory.service import TaskMemoryService, TaskNotFound
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_USER = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")
OTHER_BOT = TaskScope(chatbot_id="bot-b", user_id="user-1", session_id="sess-1")
OTHER_SESSION = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-2")


@pytest.fixture()
async def store():
    """Yield a fresh in-memory store."""
    backend = InMemoryTaskMemoryStore()
    try:
        yield backend
    finally:
        await backend.close()


@pytest.fixture()
def service(store: TaskMemoryStore) -> TaskMemoryService:
    """Yield a service over the store."""
    return TaskMemoryService(store)


def _plan() -> List[InitialStepSpec]:
    """Return a three-step initial plan addressed by labels."""
    return [
        InitialStepSpec(label="load", title="Load raw data"),
        InitialStepSpec(label="clean", title="Clean data", depends_on_labels=("load",)),
        InitialStepSpec(label="report", title="Write report", depends_on_labels=("clean",)),
    ]


async def _begin(service: TaskMemoryService, **kwargs):
    """Begin a task with the standard plan.

    Args:
        service: The service under test.
        **kwargs: Overrides for ``begin_task``.

    Returns:
        The append result.
    """
    params = {
        "goal": "Produce the quarterly report",
        "constraints": ["Never mutate the source"],
        "steps": _plan(),
    }
    params.update(kwargs)
    return await service.begin_task(SCOPE, **params)


async def _events(store: TaskMemoryStore, task_id: str, scope: TaskScope = SCOPE) -> List:
    """Return a task's whole journal.

    Args:
        store: The backend.
        task_id: The task.
        scope: The scope to read as.

    Returns:
        The events, ascending.
    """
    page = await store.list_events(scope, task_id, limit=200)
    return list(page.events)


# ─────────────────────────────────────────────────────────────
# Command flow
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_command_flow_begin_mints_ids_and_resolves_labels(
    service: TaskMemoryService, store: TaskMemoryStore
) -> None:
    """Begin resolves request-local labels to minted runtime ids."""
    result = await _begin(service)
    state = result.state

    assert state.goal == "Produce the quarterly report"
    assert state.status is TaskStatus.ACTIVE
    assert len(state.steps) == 3
    assert [s.title for s in state.steps] == ["Load raw data", "Clean data", "Write report"]

    # Labels are gone; dependencies point at real runtime ids.
    ids = [s.step_id for s in state.steps]
    assert all(sid not in {"load", "clean", "report"} for sid in ids), "labels must not leak as ids"
    assert state.steps[1].depends_on == (ids[0],)
    assert state.steps[2].depends_on == (ids[1],)
    assert state.ready_step_ids == (ids[0],)

    # Two events, committed together: no window with a half-built plan.
    events = await _events(store, state.task_id)
    assert [e.event_type for e in events] == [EventType.TASK_STARTED, EventType.PLAN_UPDATED]
    assert [e.seq for e in events] == [1, 2]


@pytest.mark.asyncio
async def test_command_flow_replan_supersedes_and_adds(service: TaskMemoryService, store: TaskMemoryStore) -> None:
    """A replan retires a step and adds a replacement in one revision."""
    result = await _begin(service)
    state = result.state
    report_id = state.steps[2].step_id

    replanned = await service.update_plan(
        SCOPE,
        state.task_id,
        expected_revision=state.revision,
        changes=PlanChanges(
            changes=(
                SupersedeStep(step_id=report_id, reason="scope changed"),
                AddStep(label="dashboard", title="Build dashboard", depends_on=(state.steps[1].step_id,)),
                AddConstraint(text="Budget under 1000 rows"),
            )
        ),
        reason="stakeholder asked for a dashboard",
    )

    new_state = replanned.state
    assert new_state.plan_revision == state.plan_revision + 1
    assert new_state.revision > state.revision
    assert new_state.steps_by_id[report_id].status is StepStatus.SUPERSEDED
    assert any(s.title == "Build dashboard" for s in new_state.steps)
    assert len(new_state.active_constraints) == 2

    payload = (await _events(store, state.task_id))[-1].payload
    assert payload.superseded_step_ids == (report_id,)
    assert len(payload.added_steps) == 1
    assert payload.reason == "stakeholder asked for a dashboard"


@pytest.mark.asyncio
async def test_command_flow_lifecycle_transitions(service: TaskMemoryService, store: TaskMemoryStore) -> None:
    """Pause, resume and cancel emit the right typed events."""
    result = await _begin(service)
    task_id = result.state.task_id

    paused = await service.update_task(
        SCOPE, task_id, expected_revision=result.state.revision, status=TaskStatus.PAUSED, reason="inactivity"
    )
    assert paused.state.status is TaskStatus.PAUSED

    resumed = await service.update_task(
        SCOPE, task_id, expected_revision=paused.state.revision, status=TaskStatus.ACTIVE
    )
    assert resumed.state.status is TaskStatus.ACTIVE
    assert resumed.state.terminal_at is None

    cancelled = await service.update_task(
        SCOPE, task_id, expected_revision=resumed.state.revision, status=TaskStatus.CANCELLED, reason="abandoned"
    )
    assert cancelled.state.status is TaskStatus.CANCELLED
    assert cancelled.state.terminal_at is not None

    kinds = [e.event_type for e in await _events(store, task_id)]
    assert kinds[-3:] == [EventType.TASK_PAUSED, EventType.TASK_RESUMED, EventType.TASK_CANCELLED]


@pytest.mark.asyncio
async def test_command_flow_terminal_task_is_immutable(service: TaskMemoryService) -> None:
    """A finished task accepts no further work."""
    result = await _begin(service)
    task_id = result.state.task_id
    cancelled = await service.update_task(
        SCOPE, task_id, expected_revision=result.state.revision, status=TaskStatus.CANCELLED
    )
    rev = cancelled.state.revision

    with pytest.raises(PlanValidationError, match="accepts no further work"):
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=rev,
            changes=PlanChanges(changes=(AddStep(title="More work"),)),
        )
    with pytest.raises(PlanValidationError, match="accepts no further work"):
        await service.record_decision(SCOPE, task_id, text="too late")
    with pytest.raises(PlanValidationError, match="accepts no further work"):
        await service.set_resume_hint(SCOPE, task_id, next_action="carry on")
    with pytest.raises(PlanValidationError, match="accepts no further work"):
        await service.update_task(SCOPE, task_id, expected_revision=rev, status=TaskStatus.ACTIVE)


@pytest.mark.asyncio
async def test_command_flow_decisions_and_hints(service: TaskMemoryService, store: TaskMemoryStore) -> None:
    """Decisions and hints are recorded with minted ids and derived staleness."""
    result = await _begin(service)
    state = result.state
    task_id = state.task_id
    clean_id = state.steps[1].step_id

    decided, decision_id = await service.record_decision(
        SCOPE, task_id, text="use parquet", reason="faster", affected_step_ids=[clean_id]
    )
    assert decision_id and decision_id not in {"use parquet"}
    assert decided.state.active_decisions[0].decision_id == decision_id
    assert decided.state.active_decisions[0].actor is Actor.AGENT

    hinted = await service.set_resume_hint(SCOPE, task_id, next_action="clean the data next", step_id=clean_id)
    hint = hinted.state.resume_hint
    assert hint is not None and hint.text == "clean the data next"
    assert hint.stale is False, "a new hint is never born stale"

    # A later event in the hint's neighbourhood makes it stale — derived
    # by the reducer, never authored by the service.
    load_id = state.steps[0].step_id
    completed = await service.update_step(
        SCOPE,
        task_id,
        load_id,
        expected_revision=hinted.state.revision,
        status=StepStatus.COMPLETED,
        note="done",
        completion_source=CompletionSource.AGENT_ASSERTED,
    )
    assert completed.state.resume_hint is not None
    assert completed.state.resume_hint.stale is True

    kinds = [e.event_type for e in await _events(store, task_id)]
    assert EventType.DECISION_RECORDED in kinds
    assert EventType.RESUME_HINT_UPDATED in kinds
    assert EventType.STEP_COMPLETED in kinds


@pytest.mark.asyncio
async def test_command_flow_completion_is_still_gated(service: TaskMemoryService) -> None:
    """The service does not let a caller complete an unfinished task."""
    result = await _begin(service)
    state = result.state
    task_id = state.task_id

    # Plan not declared complete, nothing done.
    from parrot.tools.working_memory.task_memory.models import ReducerError

    with pytest.raises(ReducerError, match="plan_incomplete"):
        await service.update_task(SCOPE, task_id, expected_revision=state.revision, status=TaskStatus.COMPLETED)

    # Declare it complete but leave required work: still refused.
    declared = await service.update_plan(
        SCOPE,
        task_id,
        expected_revision=state.revision,
        changes=PlanChanges(changes=(SetPlanComplete(plan_complete=True),)),
    )
    with pytest.raises(ReducerError, match="required steps"):
        await service.update_task(
            SCOPE, task_id, expected_revision=declared.state.revision, status=TaskStatus.COMPLETED
        )

    # Finish everything: now it completes.
    revision = declared.state.revision
    for step in declared.state.steps:
        done = await service.update_step(
            SCOPE,
            task_id,
            step.step_id,
            expected_revision=revision,
            status=StepStatus.COMPLETED,
            note="done",
            completion_source=CompletionSource.AGENT_ASSERTED,
        )
        revision = done.state.revision

    final = await service.update_task(SCOPE, task_id, expected_revision=revision, status=TaskStatus.COMPLETED)
    assert final.state.status is TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_command_flow_compact_state_is_small(service: TaskMemoryService) -> None:
    """A command acknowledgement carries a summary, not the whole task."""
    result = await _begin(service)
    summary = await service.compact_state(SCOPE, result.state.task_id)

    assert set(summary) == {
        "task_id",
        "status",
        "revision",
        "plan_revision",
        "plan_complete",
        "ready_step_ids",
        "active_step_ids",
        "plan_incomplete",
    }
    assert summary["plan_incomplete"] is True
    assert "goal" not in summary and "steps" not in summary


@pytest.mark.asyncio
async def test_command_flow_open_task_limit_is_enforced() -> None:
    """A scope cannot exceed its configured open-task ceiling."""
    backend = InMemoryTaskMemoryStore()
    svc = TaskMemoryService(backend, TaskMemoryConfig(max_open_tasks_per_scope=2))
    try:
        await svc.begin_task(SCOPE, goal="one")
        await svc.begin_task(SCOPE, goal="two")
        with pytest.raises(LimitExceeded) as excinfo:
            await svc.begin_task(SCOPE, goal="three")
        assert excinfo.value.field == "open tasks per scope"

        # A different scope is unaffected — the limit is per scope.
        await svc.begin_task(OTHER_USER, goal="theirs")
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_command_flow() -> None:
    """Required aggregate case: commands produce the expected events and revisions."""
    backend = InMemoryTaskMemoryStore()
    svc = TaskMemoryService(backend)
    try:
        await test_command_flow_begin_mints_ids_and_resolves_labels(svc, backend)
        await test_command_flow_replan_supersedes_and_adds(svc, backend)
        await test_command_flow_lifecycle_transitions(svc, backend)
        await test_command_flow_terminal_task_is_immutable(svc)
        await test_command_flow_decisions_and_hints(svc, backend)
        await test_command_flow_completion_is_still_gated(svc)
        await test_command_flow_compact_state_is_small(svc)
    finally:
        await backend.close()


# ─────────────────────────────────────────────────────────────
# Rejected batches
# ─────────────────────────────────────────────────────────────


async def _assert_unchanged(store: TaskMemoryStore, task_id: str, before) -> None:
    """Assert neither the projection nor the journal moved.

    Args:
        store: The backend.
        task_id: The task.
        before: The snapshot taken before the rejected command.
    """
    after = await store.load_snapshot(SCOPE, task_id)
    assert after is not None
    assert after.state == before.state, "a rejected command changed the projection"
    assert after.as_of_seq == before.as_of_seq, "a rejected command advanced the sequence"
    assert after.event_count == before.event_count, "a rejected command appended an event"


@pytest.mark.asyncio
async def test_rejected_batch_cycle_changes_nothing(service: TaskMemoryService, store: TaskMemoryStore) -> None:
    """A batch that would create a cycle is rejected atomically.

    The cycle exists only in the RESULT, not in any single operation —
    which is exactly why validation runs against the resulting plan.
    """
    result = await _begin(service)
    state = result.state
    task_id = state.task_id
    load_id, clean_id = state.steps[0].step_id, state.steps[1].step_id
    before = await store.load_snapshot(SCOPE, task_id)

    with pytest.raises(PlanValidationError, match="cycle"):
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=state.revision,
            changes=PlanChanges(changes=(UpdateStep(step_id=load_id, depends_on=(clean_id,)),)),
        )
    await _assert_unchanged(store, task_id, before)


@pytest.mark.asyncio
async def test_rejected_batch_missing_dependency_changes_nothing(
    service: TaskMemoryService, store: TaskMemoryStore
) -> None:
    """A dependency on a step that does not exist is rejected atomically."""
    result = await _begin(service)
    task_id = result.state.task_id
    before = await store.load_snapshot(SCOPE, task_id)

    with pytest.raises(PlanValidationError, match="unknown"):
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=result.state.revision,
            changes=PlanChanges(changes=(AddStep(title="Orphan", depends_on=("ghost",)),)),
        )
    await _assert_unchanged(store, task_id, before)

    with pytest.raises(PlanValidationError, match="unknown labels"):
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=result.state.revision,
            changes=PlanChanges(changes=(AddStep(title="Orphan", depends_on_labels=("nope",)),)),
        )
    await _assert_unchanged(store, task_id, before)


@pytest.mark.asyncio
async def test_rejected_batch_stale_revision_changes_nothing(
    service: TaskMemoryService, store: TaskMemoryStore
) -> None:
    """A stale expected revision is rejected atomically."""
    result = await _begin(service)
    task_id = result.state.task_id
    stale = result.state.revision

    moved = await service.update_plan(
        SCOPE,
        task_id,
        expected_revision=stale,
        changes=PlanChanges(changes=(AddConstraint(text="Second constraint"),)),
    )
    before = await store.load_snapshot(SCOPE, task_id)

    with pytest.raises(RevisionConflict) as excinfo:
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=stale,
            changes=PlanChanges(changes=(AddConstraint(text="Third"),)),
        )
    assert excinfo.value.current == moved.state.revision
    assert excinfo.value.expected == stale
    await _assert_unchanged(store, task_id, before)


@pytest.mark.asyncio
async def test_rejected_batch_partial_batch_never_lands(service: TaskMemoryService, store: TaskMemoryStore) -> None:
    """A valid operation before an invalid one is not applied either."""
    result = await _begin(service)
    task_id = result.state.task_id
    before = await store.load_snapshot(SCOPE, task_id)

    with pytest.raises(PlanValidationError):
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=result.state.revision,
            changes=PlanChanges(
                changes=(
                    AddConstraint(text="This one is fine"),
                    AddStep(title="But this one is not", depends_on=("ghost",)),
                )
            ),
        )
    await _assert_unchanged(store, task_id, before)
    assert len((await store.load_snapshot(SCOPE, task_id)).state.active_constraints) == 1


@pytest.mark.asyncio
async def test_rejected_batch_completed_criteria_cannot_change_in_place(
    service: TaskMemoryService, store: TaskMemoryStore
) -> None:
    """A completed step's criteria are frozen until it is reopened."""
    result = await _begin(service)
    state = result.state
    task_id, load_id = state.task_id, state.steps[0].step_id

    done = await service.update_step(
        SCOPE,
        task_id,
        load_id,
        expected_revision=state.revision,
        status=StepStatus.COMPLETED,
        note="done",
        completion_source=CompletionSource.AGENT_ASSERTED,
    )
    before = await store.load_snapshot(SCOPE, task_id)

    with pytest.raises(PlanValidationError, match="reopen it before changing"):
        await service.update_plan(
            SCOPE,
            task_id,
            expected_revision=done.state.revision,
            changes=PlanChanges(changes=(UpdateStep(step_id=load_id, completion_policy=CompletionPolicy()),)),
        )
    await _assert_unchanged(store, task_id, before)


@pytest.mark.asyncio
async def test_rejected_batch_initial_plan_defects_create_no_task(store: TaskMemoryStore) -> None:
    """A malformed initial plan leaves no task behind at all."""
    svc = TaskMemoryService(store)

    with pytest.raises(PlanValidationError, match="duplicate step labels"):
        await svc.begin_task(
            SCOPE, goal="g", steps=[InitialStepSpec(label="a", title="A"), InitialStepSpec(label="a", title="B")]
        )
    with pytest.raises(PlanValidationError, match="unknown labels"):
        await svc.begin_task(
            SCOPE, goal="g", steps=[InitialStepSpec(label="a", title="A", depends_on_labels=("ghost",))]
        )
    with pytest.raises(PlanValidationError, match="cycle"):
        await svc.begin_task(
            SCOPE,
            goal="g",
            steps=[
                InitialStepSpec(label="a", title="A", depends_on_labels=("b",)),
                InitialStepSpec(label="b", title="B", depends_on_labels=("a",)),
            ],
        )

    assert (await store.list_tasks(SCOPE)).items == (), "a rejected begin must create no task"


@pytest.mark.asyncio
async def test_rejected_batch_unknown_targets_are_refused(service: TaskMemoryService, store: TaskMemoryStore) -> None:
    """Commands naming steps that do not exist are refused, changing nothing."""
    result = await _begin(service)
    task_id = result.state.task_id
    before = await store.load_snapshot(SCOPE, task_id)

    with pytest.raises(PlanValidationError, match="unknown step"):
        await service.update_step(
            SCOPE, task_id, "ghost", expected_revision=result.state.revision, status=StepStatus.RUNNING
        )
    with pytest.raises(PlanValidationError, match="unknown steps"):
        await service.record_decision(SCOPE, task_id, text="d", affected_step_ids=["ghost"])
    with pytest.raises(PlanValidationError, match="unknown step"):
        await service.set_resume_hint(SCOPE, task_id, next_action="go", step_id="ghost")
    with pytest.raises(PlanValidationError, match="superseded by a plan change"):
        await service.update_step(
            SCOPE,
            task_id,
            result.state.steps[0].step_id,
            expected_revision=result.state.revision,
            status=StepStatus.SUPERSEDED,
        )
    await _assert_unchanged(store, task_id, before)


@pytest.mark.asyncio
async def test_rejected_batch() -> None:
    """Required aggregate case: rejected batches leave journal and projection unchanged."""
    backend = InMemoryTaskMemoryStore()
    svc = TaskMemoryService(backend)
    try:
        await test_rejected_batch_cycle_changes_nothing(svc, backend)
        await test_rejected_batch_missing_dependency_changes_nothing(svc, backend)
        await test_rejected_batch_stale_revision_changes_nothing(svc, backend)
        await test_rejected_batch_partial_batch_never_lands(svc, backend)
        await test_rejected_batch_completed_criteria_cannot_change_in_place(svc, backend)
        await test_rejected_batch_unknown_targets_are_refused(svc, backend)
    finally:
        await backend.close()


# ─────────────────────────────────────────────────────────────
# Identity and scope
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_identity_a_task_id_does_not_cross_a_scope(service: TaskMemoryService) -> None:
    """An explicit task id is a selector WITHIN a scope, never across one.

    Every component of the scope is varied independently: a different
    user, a different bot and a different session must each fail.
    """
    result = await _begin(service)
    task_id = result.state.task_id
    revision = result.state.revision

    for foreign in (OTHER_USER, OTHER_BOT, OTHER_SESSION):
        with pytest.raises(TaskNotFound):
            await service.get_task(foreign, task_id)
        with pytest.raises(TaskNotFound):
            await service.compact_state(foreign, task_id)
        with pytest.raises(TaskNotFound):
            await service.update_task(foreign, task_id, expected_revision=revision, status=TaskStatus.PAUSED)
        with pytest.raises(TaskNotFound):
            await service.update_plan(
                foreign,
                task_id,
                expected_revision=revision,
                changes=PlanChanges(changes=(AddConstraint(text="theirs"),)),
            )
        with pytest.raises(TaskNotFound):
            await service.record_decision(foreign, task_id, text="theirs")
        with pytest.raises(TaskNotFound):
            await service.set_resume_hint(foreign, task_id, next_action="theirs")
        assert (await service.list_open_tasks(foreign)).items == ()


@pytest.mark.asyncio
async def test_identity_absence_is_indistinguishable_from_forbidden(
    service: TaskMemoryService,
) -> None:
    """A foreign task and a nonexistent one fail identically.

    Distinguishing them would turn the error into an existence oracle for
    other users' task ids.
    """
    result = await _begin(service)

    with pytest.raises(TaskNotFound) as foreign:
        await service.get_task(OTHER_USER, result.state.task_id)
    with pytest.raises(TaskNotFound) as absent:
        await service.get_task(OTHER_USER, "definitely-not-a-real-task")

    assert type(foreign.value) is type(absent.value)
    # Neither message reveals whether the id exists elsewhere.
    for message in (str(foreign.value), str(absent.value)):
        assert "forbidden" not in message.lower()
        assert "another" not in message.lower()


@pytest.mark.asyncio
async def test_identity_scope_is_never_taken_from_a_command(service: TaskMemoryService) -> None:
    """No command accepts a scope from its arguments.

    Scope is the first positional parameter everywhere and is supplied by
    the runtime. A model-authored scope would be a cross-user read
    primitive, so the check is structural.
    """
    import inspect

    exempt = {"__init__"}
    for name, member in vars(TaskMemoryService).items():
        if name.startswith("_") or not callable(member) or name in exempt:
            continue
        params = [p for p in inspect.signature(member).parameters if p != "self"]
        assert params and params[0] == "scope", f"{name} does not take scope first"
        assert not any(
            p in {"chatbot_id", "user_id", "session_id"} for p in params
        ), f"{name} accepts a scope component as an argument"


@pytest.mark.asyncio
async def test_identity_runtime_ids_are_minted_not_accepted(service: TaskMemoryService) -> None:
    """Step, constraint and decision ids come from the runtime."""
    first = await _begin(service)
    second = await _begin(service)

    assert first.state.task_id != second.state.task_id
    first_ids = {s.step_id for s in first.state.steps}
    second_ids = {s.step_id for s in second.state.steps}
    assert first_ids.isdisjoint(second_ids), "two tasks must not share step identities"

    # The same labels in both plans produced different runtime ids.
    assert len(first_ids) == 3 and len(second_ids) == 3

    constraint_ids = {c.constraint_id for c in first.state.constraints}
    assert constraint_ids.isdisjoint({c.constraint_id for c in second.state.constraints})


@pytest.mark.asyncio
async def test_identity_scopes_are_isolated_end_to_end(store: TaskMemoryStore) -> None:
    """Two scopes running the same workflow never observe each other."""
    svc = TaskMemoryService(store)
    mine = await svc.begin_task(SCOPE, goal="mine", steps=[InitialStepSpec(label="a", title="A")])
    theirs = await svc.begin_task(OTHER_USER, goal="theirs", steps=[InitialStepSpec(label="a", title="A")])

    my_page = await svc.list_open_tasks(SCOPE)
    their_page = await svc.list_open_tasks(OTHER_USER)
    assert [i.task_id for i in my_page.items] == [mine.state.task_id]
    assert [i.task_id for i in their_page.items] == [theirs.state.task_id]

    # Work in one scope leaves the other untouched.
    await svc.update_task(SCOPE, mine.state.task_id, expected_revision=mine.state.revision, status=TaskStatus.PAUSED)
    still = await svc.get_task(OTHER_USER, theirs.state.task_id)
    assert still.state.status is TaskStatus.ACTIVE


@pytest.mark.asyncio
async def test_identity() -> None:
    """Required aggregate case: scope is runtime-owned and task ids cannot cross it.

    Each sub-case gets a FRESH backend. Sharing one would let tasks
    created by an earlier sub-case leak into a later one's listing
    assertions — the aggregate would then be testing accumulated state
    rather than the invariant.
    """
    for case in (
        test_identity_a_task_id_does_not_cross_a_scope,
        test_identity_absence_is_indistinguishable_from_forbidden,
        test_identity_scope_is_never_taken_from_a_command,
        test_identity_runtime_ids_are_minted_not_accepted,
    ):
        backend = InMemoryTaskMemoryStore()
        try:
            await case(TaskMemoryService(backend))
        finally:
            await backend.close()

    backend = InMemoryTaskMemoryStore()
    try:
        await test_identity_scopes_are_isolated_end_to_end(backend)
    finally:
        await backend.close()
