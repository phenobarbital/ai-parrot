"""Evidence-bound completion validation (FEAT-538 / TASK-2980).

Three required cases from the task's Test Specification:

- ``test_completion_modes`` — ``validated`` policies require every named
  validator; ``agent_asserted`` requires accessible evidence plus the
  required note, and is always labelled as the weaker source.
- ``test_mutation_race`` — a mutation or a revision change during
  validation causes a retry or a rejection, never a stale completion.
- ``test_overwrites`` — an old immutable version stays valid after an
  overwrite; a same-version live mutation invalidates and blocks.

The overwrite/mutation distinction is the point of this module, so it is
tested from both directions: an overwrite must NOT invalidate, and a
mutation must. Testing only one direction would let the opposite bug
through — spuriously invalidating sound work is as wrong as accepting
evidence that changed.
"""

from __future__ import annotations

import pandas as pd
import pytest
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    CompletionMode,
    CompletionPolicy,
    CompletionSource,
    EvidenceRef,
    InitialStepSpec,
    RevisionConflict,
    StepStatus,
    TaskScope,
    UnknownValidatorError,
)
from parrot.tools.working_memory.task_memory.service import TaskMemoryService
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.validators import (
    VALIDATOR_NAMES,
    CompletionValidationError,
    EvidenceMutated,
    resolve_evidence,
    validate_completion,
)

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


@pytest.fixture()
async def stores():
    """Yield a ``(task store, artifact store)`` pair."""
    tasks = InMemoryTaskMemoryStore()
    artifacts = InMemoryArtifactStore()
    try:
        yield tasks, artifacts
    finally:
        await tasks.close()
        await artifacts.close()


def frame(rows: int = 3) -> pd.DataFrame:
    """Return a small, Arrow-representable frame.

    Args:
        rows: Row count.

    Returns:
        A numeric/string DataFrame.
    """
    return pd.DataFrame({"n": range(rows), "s": [f"r{i}" for i in range(rows)]})


async def _task(service: TaskMemoryService, policy: CompletionPolicy):
    """Begin a one-step task carrying ``policy``.

    Args:
        service: The service.
        policy: The step's completion policy.

    Returns:
        A ``(result, step_id)`` pair.
    """
    result = await service.begin_task(
        SCOPE,
        goal="Produce the report",
        steps=[InitialStepSpec(label="a", title="Clean data", completion_policy=policy)],
    )
    return result, result.state.steps[0].step_id


# ─────────────────────────────────────────────────────────────
# Completion modes
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completion_modes_validated_requires_every_validator(stores) -> None:
    """A validated policy passes only when every named validator passes."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(
        mode=CompletionMode.VALIDATED,
        validators=("artifact_exists", "artifact_fingerprint_matches", "artifact_non_empty"),
        expected_outputs=("clean_sales",),
    )
    result, step_id = await _task(service, policy)
    task_id = result.state.task_id

    descriptor = await artifacts.put(SCOPE, "clean_sales", frame(), task_id=task_id)
    assert descriptor.evidence_verifiable is True

    completed = await service.complete_step(
        SCOPE, task_id, step_id, expected_revision=result.state.revision, note="validated against snapshot"
    )
    step = completed.state.steps_by_id[step_id]
    assert step.status is StepStatus.COMPLETED
    assert step.completion_source is CompletionSource.VALIDATED
    assert descriptor.ref in step.evidence_refs, "the exact version must be bound"


@pytest.mark.asyncio
async def test_completion_modes_validated_fails_on_empty_and_unverifiable(stores) -> None:
    """An empty frame fails non_empty; a nested-object frame fails fingerprint_matches."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)

    empty_policy = CompletionPolicy(
        mode=CompletionMode.VALIDATED, validators=("artifact_non_empty",), expected_outputs=("out",)
    )
    result, step_id = await _task(service, empty_policy)
    await artifacts.put(SCOPE, "out", pd.DataFrame({"n": []}), task_id=result.state.task_id)
    with pytest.raises(CompletionValidationError, match="artifact_non_empty"):
        await service.complete_step(
            SCOPE, result.state.task_id, step_id, expected_revision=result.state.revision, note="n"
        )

    # A nested-object frame is UNVERIFIABLE (pandas repr-hashes it), so it
    # can never satisfy a fingerprint validator even though a fingerprint
    # might be computable.
    fp_policy = CompletionPolicy(
        mode=CompletionMode.VALIDATED,
        validators=("artifact_fingerprint_matches",),
        expected_outputs=("nested",),
    )
    result2, step2 = await _task(service, fp_policy)
    nested = pd.DataFrame({"v": [1.0], "obj": pd.Series([{"a": 1}], dtype="object")})
    descriptor = await artifacts.put(SCOPE, "nested", nested, task_id=result2.state.task_id)
    assert descriptor.evidence_verifiable is False
    with pytest.raises(CompletionValidationError, match="artifact_fingerprint_matches"):
        await service.complete_step(
            SCOPE, result2.state.task_id, step2, expected_revision=result2.state.revision, note="n"
        )


@pytest.mark.asyncio
async def test_completion_modes_asserted_requires_evidence_and_note(stores) -> None:
    """Asserted completion needs accessible evidence AND the note, and is labelled weaker."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.AGENT_ASSERTED)
    result, step_id = await _task(service, policy)
    task_id = result.state.task_id

    # No evidence at all -> refused.
    with pytest.raises(CompletionValidationError, match="accessible evidence"):
        await service.complete_step(SCOPE, task_id, step_id, expected_revision=result.state.revision, note="trust me")

    descriptor = await artifacts.put(SCOPE, "notes", {"summary": "done"}, task_id=task_id)

    # No note -> refused, even with evidence.
    with pytest.raises(CompletionValidationError, match="note is required"):
        await service.complete_step(
            SCOPE,
            task_id,
            step_id,
            expected_revision=result.state.revision,
            evidence_refs=[descriptor.ref],
        )

    completed = await service.complete_step(
        SCOPE,
        task_id,
        step_id,
        expected_revision=result.state.revision,
        evidence_refs=[descriptor.ref],
        note="I checked it by hand",
    )
    step = completed.state.steps_by_id[step_id]
    assert step.completion_source is CompletionSource.AGENT_ASSERTED, "must be the WEAKER label"
    assert step.completion_note == "I checked it by hand"


@pytest.mark.asyncio
async def test_completion_modes_unknown_validator_is_never_a_vacuous_pass(stores) -> None:
    """An unregistered validator raises rather than silently passing.

    Treating an unknown name as "nothing to check" would downgrade a
    `validated` completion to an unchecked one without anybody noticing.
    """
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.VALIDATED, validators=("no_such_validator",))
    result, step_id = await _task(service, policy)

    with pytest.raises(UnknownValidatorError, match="never a vacuous pass"):
        await service.complete_step(
            SCOPE, result.state.task_id, step_id, expected_revision=result.state.revision, note="n"
        )


@pytest.mark.asyncio
async def test_completion_modes_missing_expected_output_is_refused(stores) -> None:
    """An expected output that was never produced refuses the completion."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(
        mode=CompletionMode.VALIDATED, validators=("artifact_exists",), expected_outputs=("never_made",)
    )
    result, step_id = await _task(service, policy)
    with pytest.raises(CompletionValidationError, match="has not been produced"):
        await service.complete_step(
            SCOPE, result.state.task_id, step_id, expected_revision=result.state.revision, note="n"
        )


@pytest.mark.asyncio
async def test_completion_modes_refusal_leaves_the_step_untouched(stores) -> None:
    """A refused completion changes nothing about the step."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.AGENT_ASSERTED)
    result, step_id = await _task(service, policy)
    before = await tasks.load_snapshot(SCOPE, result.state.task_id)

    with pytest.raises(CompletionValidationError):
        await service.complete_step(
            SCOPE, result.state.task_id, step_id, expected_revision=result.state.revision, note="x"
        )

    after = await tasks.load_snapshot(SCOPE, result.state.task_id)
    assert after.state == before.state
    assert after.event_count == before.event_count


@pytest.mark.asyncio
async def test_completion_modes_requires_an_artifact_store(stores) -> None:
    """Without an artifact store the service REFUSES rather than skipping validation."""
    tasks, _ = stores
    service = TaskMemoryService(tasks)  # no artifacts
    result, step_id = await _task(service, CompletionPolicy())

    with pytest.raises(CompletionValidationError, match="requires an artifact store"):
        await service.complete_step(
            SCOPE, result.state.task_id, step_id, expected_revision=result.state.revision, note="n"
        )


@pytest.mark.asyncio
async def test_completion_modes_registry_matches_the_configured_names() -> None:
    """The code registry and the configuration's default list agree."""
    from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig

    assert set(VALIDATOR_NAMES) == set(TaskMemoryConfig().validator_names)


@pytest.mark.asyncio
async def test_completion_modes() -> None:
    """Required aggregate case: validated and asserted rules, with explicit labels."""
    for case in (
        test_completion_modes_validated_requires_every_validator,
        test_completion_modes_validated_fails_on_empty_and_unverifiable,
        test_completion_modes_asserted_requires_evidence_and_note,
        test_completion_modes_unknown_validator_is_never_a_vacuous_pass,
        test_completion_modes_missing_expected_output_is_refused,
        test_completion_modes_refusal_leaves_the_step_untouched,
        test_completion_modes_requires_an_artifact_store,
    ):
        tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
        try:
            await case((tasks, artifacts))
        finally:
            await tasks.close()
            await artifacts.close()


# ─────────────────────────────────────────────────────────────
# Overwrite vs mutation
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overwrites_old_version_survives_an_overwrite(stores) -> None:
    """An overwrite creates a NEW version; the old one stays valid evidence.

    This is the direction that must NOT invalidate. Getting it wrong
    would spuriously reopen sound completed work every time an alias was
    written again.
    """
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.VALIDATED, validators=("artifact_exists",))
    result, step_id = await _task(service, policy)
    task_id = result.state.task_id

    v1 = await artifacts.put(SCOPE, "sales", frame(3), task_id=task_id)
    completed = await service.complete_step(
        SCOPE,
        task_id,
        step_id,
        expected_revision=result.state.revision,
        evidence_refs=[v1.ref],
        note="bound to v1",
    )
    assert completed.state.steps_by_id[step_id].evidence_refs == (v1.ref,)

    # Overwrite the alias. A NEW version appears; v1 is untouched.
    v2 = await artifacts.put(SCOPE, "sales", frame(9), task_id=task_id)
    assert v2.ref.artifact_id == v1.ref.artifact_id
    assert v2.ref.version == v1.ref.version + 1

    still = await artifacts.get_version(SCOPE, v1.ref, task_id=task_id)
    assert still is not None and not still.invalidated
    assert still.fingerprint == v1.fingerprint, "an overwrite must not touch the old version"

    # And the completed step is still bound to v1 and still complete.
    state = (await tasks.load_snapshot(SCOPE, task_id)).state
    assert state.steps_by_id[step_id].status is StepStatus.COMPLETED
    assert state.steps_by_id[step_id].evidence_refs == (v1.ref,)


@pytest.mark.asyncio
async def test_overwrites_same_version_mutation_blocks_completion(stores) -> None:
    """Content changing behind a BOUND version blocks the completion.

    Two distinct situations, asserted separately because they are not the
    same thing and must not report the same error:

    * evidence that is **already** invalidated when validation begins is
      simply invalid evidence — ``artifact_exists`` refuses it;
    * evidence invalidated **during** the validation window is a
      *mutation* — it raises :class:`EvidenceMutated`, which additionally
      means anything already completed against it must be reopened.
    """
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.VALIDATED, validators=("artifact_exists",))

    # (a) Already invalid before we start.
    result, step_id = await _task(service, policy)
    task_id = result.state.task_id
    v1 = await artifacts.put(SCOPE, "sales", frame(3), task_id=task_id)
    await artifacts.invalidate(SCOPE, v1.ref, reason="mutated before we looked")

    with pytest.raises(CompletionValidationError, match="artifact_exists"):
        await service.complete_step(
            SCOPE,
            task_id,
            step_id,
            expected_revision=result.state.revision,
            evidence_refs=[v1.ref],
            note="should not stand",
        )
    state = (await tasks.load_snapshot(SCOPE, task_id)).state
    assert state.steps_by_id[step_id].status is not StepStatus.COMPLETED

    # (b) Invalidated inside the window -> a mutation.
    result2, step2 = await _task(service, policy)
    task2 = result2.state.task_id
    v2 = await artifacts.put(SCOPE, "sales", frame(3), task_id=task2)

    original = artifacts.get_version
    seen = {"n": 0}

    async def _mutating(scope, ref, *, task_id=None):
        seen["n"] += 1
        if seen["n"] == 3:  # after validation passed, before the commit check
            await artifacts.invalidate(scope, ref, reason="mutated under us")
        return await original(scope, ref, task_id=task_id)

    artifacts.get_version = _mutating  # type: ignore[assignment]
    try:
        with pytest.raises(EvidenceMutated) as excinfo:
            await service.complete_step(
                SCOPE,
                task2,
                step2,
                expected_revision=result2.state.revision,
                evidence_refs=[v2.ref],
                note="should not stand",
            )
    finally:
        artifacts.get_version = original  # type: ignore[assignment]

    assert excinfo.value.ref == v2.ref
    assert "not an overwrite" in str(excinfo.value)
    state2 = (await tasks.load_snapshot(SCOPE, task2)).state
    assert state2.steps_by_id[step2].status is not StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_overwrites_resolution_pins_once(stores) -> None:
    """An alias is resolved once and pinned to the version it named then."""
    tasks, artifacts = stores
    _, _ = await _task(TaskMemoryService(tasks, artifacts=artifacts), CompletionPolicy())

    v1 = await artifacts.put(SCOPE, "sales", frame(3), task_id="t")
    bindings = await resolve_evidence(artifacts, SCOPE, task_id="t", aliases=["sales"])
    assert [b.ref for b in bindings] == [v1.ref]

    # An overwrite AFTER resolution does not retroactively change what
    # was pinned. Resolving twice would open exactly that window.
    v2 = await artifacts.put(SCOPE, "sales", frame(9), task_id="t")
    assert bindings[0].ref == v1.ref != v2.ref


@pytest.mark.asyncio
async def test_overwrites_evidence_must_resolve_in_scope(stores) -> None:
    """Evidence from another scope does not resolve."""
    _, artifacts = stores
    other = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")
    theirs = await artifacts.put(other, "sales", frame(), task_id="t")

    with pytest.raises(CompletionValidationError, match="does not resolve in this scope"):
        await resolve_evidence(artifacts, SCOPE, task_id="t", refs=[theirs.ref])


@pytest.mark.asyncio
async def test_overwrites() -> None:
    """Required aggregate case: overwrite preserves; same-version mutation blocks."""
    for case in (
        test_overwrites_old_version_survives_an_overwrite,
        test_overwrites_same_version_mutation_blocks_completion,
        test_overwrites_resolution_pins_once,
        test_overwrites_evidence_must_resolve_in_scope,
    ):
        tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
        try:
            await case((tasks, artifacts))
        finally:
            await tasks.close()
            await artifacts.close()


# ─────────────────────────────────────────────────────────────
# Races
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mutation_race_revision_move_retries_then_conflicts(stores) -> None:
    """A task moving during validation causes a retry, then an honest conflict."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.VALIDATED, validators=("artifact_exists",))
    result, step_id = await _task(service, policy)
    task_id = result.state.task_id
    descriptor = await artifacts.put(SCOPE, "sales", frame(), task_id=task_id)

    # Move the task on EVERY validation pass, so no attempt can commit.
    calls = {"n": 0}
    real_validate = service._require

    async def _moving(scope, tid):
        snapshot = await real_validate(scope, tid)
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            await service.set_resume_hint(scope, tid, next_action=f"nudge {calls['n']}")
        return snapshot

    service._require = _moving  # type: ignore[assignment]
    try:
        with pytest.raises(RevisionConflict):
            await service.complete_step(
                SCOPE,
                task_id,
                step_id,
                expected_revision=result.state.revision,
                evidence_refs=[descriptor.ref],
                note="racing",
            )
    finally:
        service._require = real_validate  # type: ignore[assignment]

    assert calls["n"] >= 2, "the retry path must actually have been exercised"

    state = (await tasks.load_snapshot(SCOPE, task_id)).state
    assert state.steps_by_id[step_id].status is not StepStatus.COMPLETED, "never a stale completion"


@pytest.mark.asyncio
async def test_mutation_race_stale_expected_revision_is_rejected(stores) -> None:
    """A caller's stale revision is refused before any validation work."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    result, step_id = await _task(service, CompletionPolicy())
    task_id = result.state.task_id
    descriptor = await artifacts.put(SCOPE, "sales", frame(), task_id=task_id)

    stale = result.state.revision
    await service.set_resume_hint(SCOPE, task_id, next_action="moved on")

    with pytest.raises(RevisionConflict):
        await service.complete_step(
            SCOPE,
            task_id,
            step_id,
            expected_revision=stale,
            evidence_refs=[descriptor.ref],
            note="stale",
        )


@pytest.mark.asyncio
async def test_mutation_race_mutation_between_validate_and_commit(stores) -> None:
    """Evidence mutating after validation but before commit blocks the completion."""
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    policy = CompletionPolicy(mode=CompletionMode.VALIDATED, validators=("artifact_exists",))
    result, step_id = await _task(service, policy)
    task_id = result.state.task_id
    descriptor = await artifacts.put(SCOPE, "sales", frame(), task_id=task_id)

    # Mutate exactly once, after validation has read the descriptor.
    original = artifacts.get_version
    seen = {"n": 0}

    async def _mutating(scope, ref, *, task_id=None):
        seen["n"] += 1
        if seen["n"] == 3:  # after validation passed, before the commit check
            await artifacts.invalidate(scope, ref, reason="raced")
        return await original(scope, ref, task_id=task_id)

    artifacts.get_version = _mutating  # type: ignore[assignment]
    try:
        with pytest.raises(EvidenceMutated):
            await service.complete_step(
                SCOPE,
                task_id,
                step_id,
                expected_revision=result.state.revision,
                evidence_refs=[descriptor.ref],
                note="racing",
            )
    finally:
        artifacts.get_version = original  # type: ignore[assignment]

    state = (await tasks.load_snapshot(SCOPE, task_id)).state
    assert state.steps_by_id[step_id].status is not StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_mutation_race_validation_runs_outside_the_store_lock(stores) -> None:
    """Validation does not hold the task store's lock.

    Validators may do real work; holding a lock across them would
    serialize the whole task on the slowest check. Proven by having a
    validator perform another read on the SAME task — which would
    deadlock if the lock were held.
    """
    tasks, artifacts = stores
    service = TaskMemoryService(tasks, artifacts=artifacts)
    from parrot.tools.working_memory.task_memory import validators as validators_module

    result, step_id = await _task(
        service, CompletionPolicy(mode=CompletionMode.VALIDATED, validators=("artifact_exists",))
    )
    task_id = result.state.task_id
    descriptor = await artifacts.put(SCOPE, "sales", frame(), task_id=task_id)

    reentered = {"ok": False}
    original = validators_module.VALIDATORS["artifact_exists"]

    async def _reentrant(ctx):
        # A read of the same task from inside a validator.
        await tasks.load_snapshot(SCOPE, task_id)
        reentered["ok"] = True
        return await original(ctx)

    validators_module.VALIDATORS["artifact_exists"] = _reentrant
    try:
        completed = await service.complete_step(
            SCOPE,
            task_id,
            step_id,
            expected_revision=result.state.revision,
            evidence_refs=[descriptor.ref],
            note="ok",
        )
    finally:
        validators_module.VALIDATORS["artifact_exists"] = original

    assert reentered["ok"], "the re-entrant validator never ran"
    assert completed.state.steps_by_id[step_id].status is StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_mutation_race() -> None:
    """Required aggregate case: races cause retry or rejection, never stale completion."""
    for case in (
        test_mutation_race_revision_move_retries_then_conflicts,
        test_mutation_race_stale_expected_revision_is_rejected,
        test_mutation_race_mutation_between_validate_and_commit,
        test_mutation_race_validation_runs_outside_the_store_lock,
    ):
        tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
        try:
            await case((tasks, artifacts))
        finally:
            await tasks.close()
            await artifacts.close()
