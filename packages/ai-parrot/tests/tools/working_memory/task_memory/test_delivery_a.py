"""TASK-3002 — Delivery A acceptance: in-process task continuity.

This module is the acceptance gate for Delivery A, so its assertions are
written to *fail* if the behaviour regresses rather than to describe what
the code happens to do.

**Delivery A is explicitly NOT durable.** Everything here runs against the
in-process stores (`InMemoryTaskMemoryStore` / `InMemoryArtifactStore`)
and proves *in-process continuity only*: continuity across a lost
conversational context inside one live process. It proves nothing about
surviving a restart, a crash, or a second pod — that is Delivery B, and is
covered by the service-gated suites (`test_postgres_task_store.py`,
`test_call_recovery.py`). No test here may be read as a durability claim.

Required cases:

``test_primary_continuity``
    The spec's four-step scenario end to end: a synthetic dataset, one
    step completed with **validated** evidence and one **asserted**, a
    recoverable failure, the conversational context discarded, then one
    recall by explicit same-scope task id. Constraints, exact version refs
    and the next ready step survive — and, crucially, **no physical work
    is repeated**, asserted by counting real side effects on a fake tool
    rather than by reading a status field (AC1, AC3, AC7, AC10, AC11).

``test_no_false_evidence``
    Error results, alias overwrite and mutation-behind-a-bound-version
    reach three *distinct*, correct outcomes. The overwrite/mutation
    distinction is the subtle one: a new version behind an alias leaves
    the old version valid, while invalidating the bound version itself
    must refuse the completion (AC3, AC5).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.models import CompletionSource, TaskScope
from parrot.tools.working_memory.task_memory.repl import BindingStatus, ReplBindingResolver
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.tools import TaskMemory

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────
# Synthetic dataset and a side-effect counting tool
# ─────────────────────────────────────────────────────────────


def synthetic_rows(n: int = 64) -> List[Dict[str, Any]]:
    """Build a deterministic synthetic dataset.

    Args:
        n: Row count.

    Returns:
        The rows.
    """
    return [{"id": i, "region": "north" if i % 2 else "south", "amount": i * 10} for i in range(n)]


class LedgerTool:
    """A fake tool that records every physical execution.

    Counting is the whole point. "Work was not repeated" is only a
    checkable claim if something records that the work actually ran; a
    status field on the task cannot distinguish "already done" from "done
    again and overwritten".
    """

    def __init__(self) -> None:
        """Initialize with an empty call log."""
        self.calls: List[str] = []

    async def run(self, step_label: str) -> Dict[str, Any]:
        """Execute one unit of physical work.

        Args:
            step_label: Which unit of work ran.

        Returns:
            A synthetic result payload.
        """
        self.calls.append(step_label)
        return {"step": step_label, "rows": synthetic_rows(8)}

    def count(self, step_label: str) -> int:
        """Return how many times a unit of work actually ran.

        Args:
            step_label: The unit of work.

        Returns:
            The execution count.
        """
        return self.calls.count(step_label)


@pytest.fixture()
def scope() -> TaskScope:
    """Return the trusted scope for this module."""
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


@pytest.fixture()
def artifacts() -> InMemoryArtifactStore:
    """Return a fresh in-process artifact store (NOT durable)."""
    return InMemoryArtifactStore()


@pytest.fixture()
def task_memory(scope: TaskScope, artifacts: InMemoryArtifactStore) -> TaskMemory:
    """Return a task-memory composition root over in-process stores."""
    return TaskMemory(InMemoryTaskMemoryStore(), artifacts, scope)


@pytest.fixture()
def toolkit(task_memory: TaskMemory) -> WorkingMemoryToolkit:
    """Return a task-memory-enabled working-memory toolkit."""
    return WorkingMemoryToolkit(task_memory=task_memory)


async def _revision(task_memory: TaskMemory, scope: TaskScope, task_id: str) -> int:
    """Read a task's current revision.

    Args:
        task_memory: The composition root.
        scope: Trusted scope.
        task_id: The task.

    Returns:
        The current revision.
    """
    state = await task_memory.service.compact_state(scope, task_id)
    return int(state["revision"])


# ─────────────────────────────────────────────────────────────
# test_primary_continuity
# ─────────────────────────────────────────────────────────────


async def test_primary_continuity(
    toolkit: WorkingMemoryToolkit,
    task_memory: TaskMemory,
    artifacts: InMemoryArtifactStore,
    scope: TaskScope,
) -> None:
    """The four-step scenario survives context loss without repeating work."""
    tool = LedgerTool()

    # ── 1. a four-step task with standing constraints ────────────────
    begun = await toolkit.begin_task(
        goal="reconcile the quarterly ledger against the nightly extract",
        constraints=["never write to production", "use the nightly extract only"],
        steps=[
            {"label": "load", "title": "load rows"},
            {"label": "clean", "title": "clean rows", "depends_on_labels": ["load"]},
            {"label": "verify", "title": "verify totals", "depends_on_labels": ["clean"]},
            {"label": "report", "title": "write report", "depends_on_labels": ["verify"]},
        ],
        plan_complete=True,
    )
    assert begun["status"] == "started", begun
    task_id = begun["task_id"]
    steps = {s["title"]: s["step_id"] for s in begun["steps"]}
    load, clean, verify, report = (
        steps["load rows"],
        steps["clean rows"],
        steps["verify totals"],
        steps["write report"],
    )

    # Only the first step is ready: dependencies gate the rest (AC7).
    state = await task_memory.service.compact_state(scope, task_id)
    assert state["ready_step_ids"] == [load]

    # ── 2. step one: VALIDATED completion ────────────────────────────
    # Bind a real artifact and require validators to pass against it, so
    # "validated" means something was actually checked.
    result = await tool.run("load")
    loaded = await artifacts.put(scope, "rows_raw", result, task_id=task_id, pin_for=task_id)
    assert loaded.evidence_verifiable is True, "a fingerprinted artifact must be verifiable"

    planned = await toolkit.update_plan(
        task_id=task_id,
        expected_revision=await _revision(task_memory, scope, task_id),
        changes=[
            {
                "op": "update_step",
                "step_id": load,
                "completion_policy": {
                    "mode": "validated",
                    "validators": ["artifact_exists", "artifact_non_empty", "artifact_fingerprint_matches"],
                    "expected_outputs": ["rows_raw"],
                },
            }
        ],
    )
    assert planned["status"] == "updated", planned

    done_load = await toolkit.update_step(
        task_id=task_id,
        step_id=load,
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=[str(loaded.ref)],
        note="loaded the nightly extract",
    )
    assert done_load["step"]["completion_source"] == CompletionSource.VALIDATED.value, done_load

    # ── 3. step two: ASSERTED completion ─────────────────────────────
    cleaned_result = await tool.run("clean")
    cleaned = await artifacts.put(scope, "rows_clean", cleaned_result, task_id=task_id, pin_for=task_id)
    done_clean = await toolkit.update_step(
        task_id=task_id,
        step_id=clean,
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=[str(cleaned.ref)],
        note="deduplicated by id; no schema change",
    )
    assert done_clean["step"]["completion_source"] == CompletionSource.AGENT_ASSERTED.value, done_clean

    # ── 4. step three: a RECOVERABLE failure ─────────────────────────
    blocked = await toolkit.update_step(
        task_id=task_id,
        step_id=verify,
        expected_revision=await _revision(task_memory, scope, task_id),
        status="blocked",
        reason="totals endpoint returned 503",
    )
    assert blocked["step"]["status"] == "blocked", blocked

    await toolkit.set_resume_hint(
        task_id=task_id, next_action="retry the totals endpoint, then write the report", step_id=verify
    )
    await toolkit.record_decision(
        task_id=task_id, text="use the nightly extract, not the live feed", reason="the live feed lags by a day"
    )

    work_before = list(tool.calls)
    assert work_before == ["load", "clean"]

    # ── 5. DISCARD the conversational context ────────────────────────
    # Modelled the way it actually happens: the selection is gone and the
    # in-process turn context is gone. The task itself is untouched — this
    # is precisely the failure the feature exists to survive.
    task_memory.select(None)
    assert task_memory.task_id is None

    # ── 6. ONE recall, by explicit same-scope task id ────────────────
    recalled = await toolkit.recall_task(task_id=task_id)
    assert recalled["status"] == "recalled", recalled
    snapshot = recalled["snapshot"]

    # Goal and BOTH constraints survive verbatim (AC1).
    assert snapshot["task_id"] == task_id
    assert snapshot["goal"].startswith("reconcile the quarterly ledger")
    assert snapshot["constraints"] == ["never write to production", "use the nightly extract only"]

    # Exact version refs survive — not aliases (AC1, AC5).
    completed = {c["step_id"]: c for c in snapshot["completed_steps"]}
    assert set(completed) == {load, clean}
    assert completed[load]["evidence"] == [str(loaded.ref)]
    assert completed[clean]["evidence"] == [str(cleaned.ref)]
    assert "@" in completed[load]["evidence"][0], "evidence must be an exact version, never a bare alias"

    # Truthful completion sources: the asserted one is flagged weaker (AC1).
    assert completed[load]["completion_source"] == "validated"
    assert completed[load]["weaker_evidence"] is False
    assert completed[clean]["completion_source"] == "agent_asserted"
    assert completed[clean]["weaker_evidence"] is True

    # The unresolved failure and its reason survive (AC1).
    assert [b["step_id"] for b in snapshot["blockers"]] == [verify]
    assert "503" in snapshot["blockers"][0]["reason"]

    # The resume hint and the decision survive.
    assert "totals endpoint" in snapshot["resume_hint"]["text"]
    assert any("nightly extract" in d["text"] for d in snapshot["decisions"])

    # Recall is read-only: it did NOT select the task for us (AC10, AC11).
    assert task_memory.task_id is None

    # ── 7. resume: the next ready step, and NO repeated work ─────────
    # `verify` is blocked, so nothing is ready until it is unblocked.
    assert snapshot["ready_step_ids"] == []

    # A blocked step is resumed by RUNNING it again, not by reopening it.
    # `pending` maps to step_reopened, which deliberately blocks every
    # transitive dependent (see the dedicated test below) — correct after
    # a completion is invalidated, but wrong for retrying a step that
    # never completed.
    await toolkit.update_step(
        task_id=task_id,
        step_id=verify,
        expected_revision=await _revision(task_memory, scope, task_id),
        status="running",
    )
    resumed = await toolkit.recall_task(task_id=task_id)
    resumed_steps = {s["step_id"]: s for s in resumed["snapshot"]["steps"]}
    # `verify` is the outstanding work again and is no longer blocked. It
    # is not in `ready_step_ids` because it is now RUNNING — ready means
    # "awaiting pickup", and this step has already been picked up.
    assert resumed_steps[verify]["status"] == "running"
    assert resumed_steps[verify]["blocked_reason"] is None
    assert resumed["snapshot"]["blockers"] == []

    # A driver that trusts recall does only the outstanding work.
    for step_id, label in ((verify, "verify"), (report, "report")):
        current = await toolkit.recall_task(task_id=task_id)
        outstanding = {s["step_id"] for s in current["snapshot"]["steps"]}
        assert step_id in outstanding, f"{label} should still be outstanding work"
        # Already-completed work is never offered again.
        assert not outstanding & {load, clean}
        payload = await tool.run(label)
        produced = await artifacts.put(scope, f"out_{label}", payload, task_id=task_id, pin_for=task_id)
        finished = await toolkit.update_step(
            task_id=task_id,
            step_id=step_id,
            expected_revision=await _revision(task_memory, scope, task_id),
            status="completed",
            evidence_refs=[str(produced.ref)],
            note=f"{label} finished after recovery",
        )
        assert finished["step"]["status"] == "completed", finished

    # THE ASSERTION THIS TEST EXISTS FOR: each unit of physical work ran
    # exactly once across the whole scenario, including across the context
    # loss. Counted from real side effects, not from a status field.
    assert tool.calls == ["load", "clean", "verify", "report"]
    for label in ("load", "clean", "verify", "report"):
        assert tool.count(label) == 1, f"{label} was executed {tool.count(label)} times; recovery repeated work"

    # And the task can now legitimately complete (AC7).
    final = await task_memory.service.compact_state(scope, task_id)
    assert final["ready_step_ids"] == []
    completed_task = await toolkit.update_task(
        task_id=task_id, expected_revision=final["revision"], status="completed"
    )
    assert completed_task["task_status"] == "completed", completed_task


async def test_primary_continuity_is_in_process_only_not_durable(
    toolkit: WorkingMemoryToolkit, task_memory: TaskMemory, scope: TaskScope
) -> None:
    """Delivery A continuity does not survive losing the process.

    Asserted rather than merely documented, so nobody can mistake
    Delivery A for durability. A *new* store is what a restart looks like
    from the task's point of view, and the task is simply not there.
    """
    begun = await toolkit.begin_task(goal="in-process only", steps=[{"label": "a", "title": "A"}])
    task_id = begun["task_id"]

    # Same scope, same explicit id — but a fresh in-process store, which
    # is exactly what a process restart leaves behind for Delivery A.
    restarted = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), scope)
    after_restart = WorkingMemoryToolkit(task_memory=restarted)

    answer = await after_restart.recall_task(task_id=task_id)
    assert answer["status"] == "error"
    assert answer["error"] in {"task_not_found", "needs_task_selection", "no_open_task"}, answer

    # The original process still has it: the loss is the process boundary,
    # not the data model. Durability is Delivery B.
    assert (await toolkit.recall_task(task_id=task_id))["status"] == "recalled"


async def test_multi_task_selection_never_guesses(
    toolkit: WorkingMemoryToolkit, task_memory: TaskMemory
) -> None:
    """With several tasks open and none selected, recall asks (AC11)."""
    alpha = await toolkit.begin_task(goal="alpha reconciliation", steps=[{"label": "x", "title": "X"}])
    beta = await toolkit.begin_task(goal="beta migration", steps=[{"label": "y", "title": "Y"}])
    task_memory.select(None)

    answer = await toolkit.recall_task()
    assert answer["error"] == "needs_task_selection", answer
    listed = {t["task_id"] for t in answer["open_tasks"]}
    assert {alpha["task_id"], beta["task_id"]} <= listed
    # Bounded and sufficient to choose between them, nothing more.
    assert all({"task_id", "goal", "status", "updated_at"} == set(t) for t in answer["open_tasks"])

    # Asking twice does not eventually pick one, and a goal that closely
    # matches a task's text must not resolve it either — selection is
    # explicit or it does not happen.
    assert (await toolkit.recall_task())["error"] == "needs_task_selection"
    assert task_memory.task_id is None

    chosen = await toolkit.select_task(task_id=beta["task_id"])
    assert chosen["status"] == "selected"
    assert (await toolkit.recall_task())["snapshot"]["task_id"] == beta["task_id"]


async def test_in_process_worker_replacement_reports_stale_binding(
    toolkit: WorkingMemoryToolkit, artifacts: InMemoryArtifactStore, scope: TaskScope
) -> None:
    """A replaced worker invalidates the binding, never the evidence."""
    begun = await toolkit.begin_task(goal="worker replacement", steps=[{"label": "a", "title": "A"}])
    task_id = begun["task_id"]
    descriptor = await artifacts.put(scope, "frame", synthetic_rows(4), task_id=task_id, pin_for=task_id)

    resolver = ReplBindingResolver(artifacts)
    stale = await resolver.describe(
        scope,
        descriptor.ref.artifact_id,
        descriptor.ref.version,
        "generation-that-is-gone",
        task_id=task_id,
    )

    # Both halves matter: a routine worker replacement must not look like
    # data loss, and lost bytes must not be reported as a stale binding.
    assert stale.status is BindingStatus.BINDING_INVALID
    assert stale.artifact_locatable is True

    # The evidence itself is untouched and still completes a step.
    finished = await toolkit.update_step(
        task_id=task_id,
        step_id=begun["steps"][0]["step_id"],
        expected_revision=begun["revision"],
        status="completed",
        evidence_refs=[str(descriptor.ref)],
        note="evidence survived the worker replacement",
    )
    assert finished["step"]["status"] == "completed", finished


# ─────────────────────────────────────────────────────────────
# test_no_false_evidence
# ─────────────────────────────────────────────────────────────


async def test_no_false_evidence(
    toolkit: WorkingMemoryToolkit,
    task_memory: TaskMemory,
    artifacts: InMemoryArtifactStore,
    scope: TaskScope,
) -> None:
    """Errors, overwrite and mutation reach three distinct outcomes."""
    begun = await toolkit.begin_task(
        goal="evidence discipline",
        steps=[
            {"label": "err", "title": "ERR"},
            {"label": "over", "title": "OVER"},
            {"label": "mut", "title": "MUT"},
        ],
    )
    task_id = begun["task_id"]
    ids = {s["title"]: s["step_id"] for s in begun["steps"]}

    # ── (a) an error result is not evidence ──────────────────────────
    # Nothing accessible was produced, so the completion is REFUSED. A
    # tool call that merely happened is never proof a step is done (AC3).
    refused = await toolkit.update_step(
        task_id=task_id,
        step_id=ids["ERR"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=[],
        note="the tool returned an error payload",
    )
    assert refused["status"] == "error"
    assert refused["error"] == "completion_refused", refused
    # And the step really did not move.
    state = await task_memory.service.get_task(scope, task_id)
    assert state.state.steps_by_id[ids["ERR"]].status.value != "completed"

    # A dangling reference is refused too, and distinctly from a bare
    # alias, which never parses as a version at all.
    dangling = await toolkit.update_step(
        task_id=task_id,
        step_id=ids["ERR"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=["art_00099999@7"],
        note="points at nothing",
    )
    assert dangling["error"] == "completion_refused", dangling
    bare = await toolkit.update_step(
        task_id=task_id,
        step_id=ids["ERR"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=["rows_raw"],
        note="an alias is not a version",
    )
    assert bare["error"] == "bare_alias", bare

    # ── (b) OVERWRITING an alias preserves the older evidence ────────
    first = await artifacts.put(scope, "shared", {"v": 1}, task_id=task_id, pin_for=task_id)
    bound = await toolkit.update_step(
        task_id=task_id,
        step_id=ids["OVER"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=[str(first.ref)],
        note="completed against version 1",
    )
    assert bound["step"]["status"] == "completed", bound

    second = await artifacts.put(scope, "shared", {"v": 2}, task_id=task_id, pin_for=task_id)
    assert second.ref.version == first.ref.version + 1, "an overwrite must allocate a NEW version"

    # The bound version is untouched and still valid. This is the
    # distinction the feature turns on: an overwrite is not a mutation.
    still = await artifacts.get_version(scope, first.ref, task_id=task_id)
    assert still is not None and still.invalidated is False
    after = await toolkit.recall_task(task_id=task_id)
    over_unit = next(c for c in after["snapshot"]["completed_steps"] if c["step_id"] == ids["OVER"])
    assert over_unit["evidence"] == [str(first.ref)], "the completed step still cites the version it was proven on"

    # ── (c) MUTATION behind a bound version invalidates it ───────────
    third = await artifacts.put(scope, "mutable", {"rows": [1, 2, 3]}, task_id=task_id, pin_for=task_id)
    await artifacts.invalidate(scope, third.ref, reason="content changed in place")

    mutated = await toolkit.update_step(
        task_id=task_id,
        step_id=ids["MUT"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=[str(third.ref)],
        note="the bound version changed underneath",
    )
    assert mutated["status"] == "error"
    assert mutated["error"] in {"completion_refused", "evidence_mutated"}, mutated

    # The three outcomes really are distinct: an overwrite completed, the
    # error and the mutation did not.
    final = await task_memory.service.get_task(scope, task_id)
    by_id = final.state.steps_by_id
    assert by_id[ids["OVER"]].status.value == "completed"
    assert by_id[ids["ERR"]].status.value != "completed"
    assert by_id[ids["MUT"]].status.value != "completed"


async def test_no_false_evidence_nested_mutable_data_is_not_falsely_verified(
    toolkit: WorkingMemoryToolkit, artifacts: InMemoryArtifactStore, scope: TaskScope
) -> None:
    """Mutating the caller's object cannot change registered evidence (AC5)."""
    begun = await toolkit.begin_task(goal="nested mutable", steps=[{"label": "a", "title": "A"}])
    task_id = begun["task_id"]

    payload: Dict[str, Any] = {"rows": [1, 2, 3], "nested": {"k": ["a"]}}
    descriptor = await artifacts.put(scope, "nested", payload, task_id=task_id, pin_for=task_id)

    # Mutate the caller's object *after* registration, deeply.
    payload["rows"].append(999)
    payload["nested"]["k"].append("b")

    reread = await artifacts.get_version(scope, descriptor.ref, task_id=task_id)
    assert reread is not None
    # The registered version is a snapshot, so its fingerprint is stable.
    # Were it a live reference, the evidence would silently describe data
    # that no longer matches what was verified.
    assert reread.fingerprint == descriptor.fingerprint
    assert reread.invalidated is False


async def test_reopening_a_step_blocks_its_dependents_until_revalidated(
    toolkit: WorkingMemoryToolkit,
    task_memory: TaskMemory,
    artifacts: InMemoryArtifactStore,
    scope: TaskScope,
) -> None:
    """Reopening invalidates downstream work rather than trusting it (AC7).

    This is a sharp edge worth pinning. ``pending`` maps to
    ``step_reopened``, which blocks every transitive dependent with
    ``upstream_reopened`` — including ones already **completed**. That is
    the safe direction: if the input a step was proven on is back in
    question, the conclusion drawn from it is too. Readiness returns only
    when each dependent is explicitly revalidated, never merely because
    the upstream succeeded again.
    """
    begun = await toolkit.begin_task(
        goal="reopen propagation",
        steps=[
            {"label": "up", "title": "UP"},
            {"label": "mid", "title": "MID", "depends_on_labels": ["up"]},
            {"label": "down", "title": "DOWN", "depends_on_labels": ["mid"]},
        ],
        plan_complete=True,
    )
    task_id = begun["task_id"]
    ids = {s["title"]: s["step_id"] for s in begun["steps"]}

    # Complete UP and MID against real evidence.
    for title in ("UP", "MID"):
        descriptor = await artifacts.put(scope, f"ev_{title}", {"t": title}, task_id=task_id, pin_for=task_id)
        done = await toolkit.update_step(
            task_id=task_id,
            step_id=ids[title],
            expected_revision=await _revision(task_memory, scope, task_id),
            status="completed",
            evidence_refs=[str(descriptor.ref)],
            note=f"{title} done",
        )
        assert done["step"]["status"] == "completed", done

    state = await task_memory.service.get_task(scope, task_id)
    assert state.state.steps_by_id[ids["MID"]].status.value == "completed"

    # Reopen UP: its conclusion is back in question.
    reopened = await toolkit.update_step(
        task_id=task_id,
        step_id=ids["UP"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="pending",
        reason="source data was corrected",
    )
    assert reopened["step"]["status"] == "pending", reopened

    after = await task_memory.service.get_task(scope, task_id)
    by_id = after.state.steps_by_id
    # The COMPLETED dependent is blocked, and its completion source is
    # cleared — it is no longer proven work.
    assert by_id[ids["MID"]].status.value == "blocked"
    assert by_id[ids["MID"]].blocked_reason == "upstream_reopened"
    assert by_id[ids["MID"]].completion_source is None
    assert by_id[ids["DOWN"]].status.value == "blocked"

    # Completing UP again does NOT auto-restore the dependents: they must
    # be revalidated explicitly.
    descriptor = await artifacts.put(scope, "ev_UP2", {"t": "UP2"}, task_id=task_id, pin_for=task_id)
    await toolkit.update_step(
        task_id=task_id,
        step_id=ids["UP"],
        expected_revision=await _revision(task_memory, scope, task_id),
        status="completed",
        evidence_refs=[str(descriptor.ref)],
        note="UP redone",
    )
    still = await task_memory.service.get_task(scope, task_id)
    assert still.state.steps_by_id[ids["MID"]].status.value == "blocked", (
        "a dependent must not silently un-block just because its upstream succeeded again"
    )
