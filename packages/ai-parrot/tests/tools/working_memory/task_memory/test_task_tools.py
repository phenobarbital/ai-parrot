"""TASK-2989 — the ten LLM-facing ``wm_*`` task tools.

Three properties, one per required case:

``test_schemas``
    Exactly the ten intended tools appear when task memory is enabled and
    *none* of them when it is disabled; no internal service method leaks
    into the tool set; ``wm_store`` stays excluded either way (AC13).

``test_commands``
    Every public command actually reaches the scoped service, and its
    typed failures survive the trip: a revision conflict is reported as a
    conflict, an unvalidated completion is refused, selection validates
    the task before repointing the association (AC1, AC7, AC11).

``test_readonly``
    Recall and the two listing tools append no journal events and never
    implicitly select a task (AC10).

Deterministic throughout: the in-memory store and artifact store, a fixed
scope, no clock or network dependence.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List

import pytest

from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.context import turn_session
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.task_memory.service import TaskMemoryService
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.tools import TASK_TOOL_METHODS, TaskMemory

pytestmark = pytest.mark.asyncio

#: The ten tools spec §2 requires, as the model sees them.
EXPECTED_TASK_TOOLS = frozenset(
    {
        "wm_begin_task",
        "wm_update_plan",
        "wm_update_step",
        "wm_record_decision",
        "wm_set_resume_hint",
        "wm_recall_task",
        "wm_list_task_events",
        "wm_list_task_artifacts",
        "wm_select_task",
        "wm_update_task",
    }
)


@pytest.fixture()
def tm_enabled(tm_scope: TaskScope) -> TaskMemory:
    """Return a task-memory composition root over in-memory backends."""
    return TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), tm_scope)


@pytest.fixture()
def toolkit_on(tm_enabled: TaskMemory) -> WorkingMemoryToolkit:
    """Return a toolkit with task memory enabled."""
    return WorkingMemoryToolkit(task_memory=tm_enabled)


@pytest.fixture()
def toolkit_off() -> WorkingMemoryToolkit:
    """Return a toolkit with task memory disabled (the default)."""
    return WorkingMemoryToolkit()


def _names(toolkit: WorkingMemoryToolkit) -> set:
    """Return the tool names a toolkit publishes.

    Args:
        toolkit: The toolkit to inspect.

    Returns:
        The published tool names.
    """
    return {tool.name for tool in toolkit.get_tools()}


async def _started(toolkit: WorkingMemoryToolkit, **kwargs: Any) -> Dict[str, Any]:
    """Begin a one-step task and assert it succeeded.

    Args:
        toolkit: The enabled toolkit.
        **kwargs: Overrides for :meth:`begin_task`.

    Returns:
        The ``wm_begin_task`` response.
    """
    payload: Dict[str, Any] = {
        "goal": "reconcile the ledger",
        "steps": [{"label": "a", "title": "load rows"}],
    }
    payload.update(kwargs)
    result = await toolkit.begin_task(**payload)
    assert result["status"] == "started", result
    return result


# ─────────────────────────────────────────────────────────────
# test_schemas
# ─────────────────────────────────────────────────────────────


async def test_schemas(toolkit_on: WorkingMemoryToolkit, toolkit_off: WorkingMemoryToolkit) -> None:
    """Exactly the intended tools appear; nothing internal leaks."""
    on, off = _names(toolkit_on), _names(toolkit_off)

    # Enabled: exactly the ten of spec §2, no more and no fewer.
    assert on - off == EXPECTED_TASK_TOOLS
    assert {f"wm_{m}" for m in TASK_TOOL_METHODS} == EXPECTED_TASK_TOOLS

    # Disabled: not one of them is reachable, and the rest of the tool
    # set is untouched — a disabled deployment sees what it always saw.
    assert not (off & EXPECTED_TASK_TOOLS)
    assert off == on - EXPECTED_TASK_TOOLS

    # `wm_store` stays excluded in BOTH modes. Enabling task memory
    # rebuilds the tool cache, so this is a real opportunity to
    # accidentally un-exclude it.
    assert "wm_store" not in on
    assert "wm_store" not in off

    # No internal service method is exposed. The service is the layer the
    # tools call; publishing it would give a model an unvalidated path
    # around the input schemas.
    service_methods = {
        name
        for name, _ in inspect.getmembers(TaskMemoryService, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }
    internal_only = service_methods - {m for m in TASK_TOOL_METHODS}
    assert internal_only, "sanity: the service should have methods that are not tools"
    for name in internal_only:
        assert f"wm_{name}" not in on, f"internal service method {name} leaked as a tool"

    # The composition root itself is never a tool, and neither is any of
    # its collaborators' plumbing.
    for leaked in ("wm_service", "wm_store", "wm_reader", "wm_artifacts", "wm_select", "wm_task_id"):
        assert leaked not in on

    # Every exposed task tool carries its explicit Pydantic schema rather
    # than a signature the framework guessed.
    for tool_name in EXPECTED_TASK_TOOLS:
        tool = toolkit_on.get_tool(tool_name)
        assert tool is not None, tool_name
        assert tool.args_schema is not None, tool_name
        assert tool.args_schema.__name__.endswith("Input"), tool_name
        assert tool.description, tool_name


# ─────────────────────────────────────────────────────────────
# test_commands
# ─────────────────────────────────────────────────────────────


async def test_commands(toolkit_on: WorkingMemoryToolkit, tm_enabled: TaskMemory, tm_scope: TaskScope) -> None:
    """Every command reaches the scoped service and keeps typed failures."""
    started = await _started(toolkit_on)
    task_id = started["task_id"]
    step_id = started["steps"][0]["step_id"]

    # The command reached the service: the task is really in the store,
    # under this scope, not merely echoed back.
    snapshot = await tm_enabled.service.get_task(tm_scope, task_id)
    assert snapshot.state.goal == "reconcile the ledger"
    # ...and beginning a task selects it (spec §2).
    assert tm_enabled.task_id == task_id

    # ── plan revision, and the typed conflict ────────────────────────
    revised = await toolkit_on.update_plan(
        task_id=task_id,
        expected_revision=started["revision"],
        changes=[{"op": "add_step", "label": "b", "title": "verify totals"}],
    )
    assert revised["status"] == "updated", revised

    stale = await toolkit_on.update_plan(
        task_id=task_id,
        expected_revision=started["revision"],  # deliberately stale now
        changes=[{"op": "add_step", "label": "c", "title": "late"}],
    )
    assert stale["error"] == "revision_conflict"
    assert stale["current"] == revised["revision"]
    # The conflict carries the current state, so the model can recover
    # without a second round trip.
    assert stale["state"]

    # An unknown operation is refused as data, not raised.
    bogus = await toolkit_on.update_plan(
        task_id=task_id, expected_revision=revised["revision"], changes=[{"op": "delete_everything"}]
    )
    assert bogus["error"] == "plan_invalid"

    # ── step transition, and the declaration it publishes ────────────
    with turn_session(tm_scope) as session:
        running = await toolkit_on.update_step(
            task_id=task_id,
            step_id=step_id,
            expected_revision=revised["revision"],
            status="running",
        )
        assert running["step"]["status"] == "running", running
        # A successful running declaration is published to the turn, so
        # later dispatches in this turn attribute to the step.
        assert step_id in session.declared_step_ids

    # A bare alias is not an evidence reference.
    bare = await toolkit_on.update_step(
        task_id=task_id,
        step_id=step_id,
        expected_revision=running["revision"],
        status="completed",
        evidence_refs=["just_an_alias"],
    )
    assert bare["error"] == "bare_alias"

    # Completing against evidence that does not exist is refused, rather
    # than recorded on the strength of the call having been made.
    refused = await toolkit_on.update_step(
        task_id=task_id,
        step_id=step_id,
        expected_revision=running["revision"],
        status="completed",
        evidence_refs=["missing_artifact@1"],
    )
    assert refused["error"] in {"completion_refused", "evidence_mutated"}, refused

    # An unknown status never reaches the service at all.
    assert (
        await toolkit_on.update_step(
            task_id=task_id, step_id=step_id, expected_revision=running["revision"], status="teleported"
        )
    )["error"] == "invalid_status"

    # ── decision and resume hint ─────────────────────────────────────
    decided = await toolkit_on.record_decision(
        task_id=task_id, text="use the nightly extract", reason="the live feed lags"
    )
    assert decided["status"] == "recorded" and decided["decision_id"]

    hinted = await toolkit_on.set_resume_hint(task_id=task_id, next_action="re-run the totals", step_id=step_id)
    assert hinted["status"] == "saved"

    reloaded = await tm_enabled.service.get_task(tm_scope, task_id)
    assert reloaded.state.resume_hint is not None
    # The service parameter is `next_action`; the stored field is `text`.
    assert reloaded.state.resume_hint.text == "re-run the totals"
    assert any(d.text == "use the nightly extract" for d in reloaded.state.decisions)

    # ── selection validates before it repoints ───────────────────────
    missing = await toolkit_on.select_task(task_id="TASK-does-not-exist")
    assert missing["error"] == "task_not_found"
    # The failed selection did not clobber the live association.
    assert tm_enabled.task_id == task_id

    selected = await toolkit_on.select_task(task_id=task_id)
    assert selected["status"] == "selected" and selected["task_id"] == task_id

    # ── lifecycle, and the completion gate ───────────────────────────
    current = (await tm_enabled.service.get_task(tm_scope, task_id)).state.revision
    premature = await toolkit_on.update_task(task_id=task_id, expected_revision=current, status="completed")
    # The plan is not complete and a required step is unfinished, so the
    # reducer refuses — as a typed answer, not an exception.
    assert premature["status"] == "error", premature
    assert premature["error"] in {"refused", "invalid_transition"}

    paused = await toolkit_on.update_task(task_id=task_id, expected_revision=current, status="paused")
    assert paused["task_status"] == "paused", paused

    assert (await toolkit_on.update_task(task_id=task_id, expected_revision=paused["revision"], status="ascended"))[
        "error"
    ] == "invalid_status"

    # A cancelled task is terminal, so it stops being the default target.
    cancelled = await toolkit_on.update_task(
        task_id=task_id, expected_revision=paused["revision"], status="cancelled", reason="superseded"
    )
    assert cancelled["task_status"] == "cancelled", cancelled
    assert tm_enabled.task_id is None


async def test_commands_are_scope_bound(tm_scope: TaskScope, tm_other_scope: TaskScope) -> None:
    """A command cannot reach a task belonging to another scope."""
    store, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
    mine = WorkingMemoryToolkit(task_memory=TaskMemory(store, artifacts, tm_scope))
    theirs = WorkingMemoryToolkit(task_memory=TaskMemory(store, artifacts, tm_other_scope))

    started = await _started(mine)

    # Same store, different scope: the task is simply not there. The
    # scope comes from the toolkit's trusted wiring, never from an
    # argument the model can supply.
    for probe in (
        await theirs.select_task(task_id=started["task_id"]),
        await theirs.list_task_events(task_id=started["task_id"]),
        await theirs.record_decision(task_id=started["task_id"], text="peek"),
    ):
        assert probe["status"] == "error"
        assert probe["error"] == "task_not_found", probe


# ─────────────────────────────────────────────────────────────
# test_readonly
# ─────────────────────────────────────────────────────────────


async def _journal(tm: TaskMemory, scope: TaskScope, task_id: str) -> List[int]:
    """Return the task's event sequence numbers.

    Args:
        tm: The composition root.
        scope: Trusted scope.
        task_id: The task to read.

    Returns:
        The sequence numbers, ascending.
    """
    page = await tm.store.list_events(scope, task_id, after_seq=0, limit=200)
    return [event.seq for event in page.events]


async def test_readonly(toolkit_on: WorkingMemoryToolkit, tm_enabled: TaskMemory, tm_scope: TaskScope) -> None:
    """Recall and the listing tools neither append nor select."""
    started = await _started(toolkit_on)
    task_id = started["task_id"]

    before_seqs = await _journal(tm_enabled, tm_scope, task_id)
    before_revision = (await tm_enabled.service.get_task(tm_scope, task_id)).state.revision
    assert before_seqs, "sanity: beginning a task should have written events"

    recalled = await toolkit_on.recall_task(task_id=task_id)
    assert recalled["status"] == "recalled", recalled

    events = await toolkit_on.list_task_events(task_id=task_id)
    assert events["status"] == "ok"
    assert [e["seq"] for e in events["events"]] == before_seqs

    artifacts = await toolkit_on.list_task_artifacts(task_id=task_id)
    assert artifacts["status"] == "ok"

    # Reading twice more must still not move anything: recall in
    # particular walks the journal and the descriptors, and a read that
    # appended would make recall non-deterministic and self-inflating.
    await toolkit_on.recall_task(task_id=task_id)
    await toolkit_on.list_task_events(task_id=task_id)
    await toolkit_on.list_task_artifacts(task_id=task_id)

    assert await _journal(tm_enabled, tm_scope, task_id) == before_seqs
    assert (await tm_enabled.service.get_task(tm_scope, task_id)).state.revision == before_revision


async def test_readonly_never_selects_implicitly(tm_scope: TaskScope) -> None:
    """With several tasks open and none selected, reads ask rather than guess."""
    tm = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), tm_scope)
    toolkit = WorkingMemoryToolkit(task_memory=tm)

    first = await _started(toolkit, goal="first goal")
    second = await _started(toolkit, goal="second goal")

    # Clear the association to model the failure this feature exists for:
    # the conversation lost track of which task is in play.
    tm.select(None)
    assert tm.task_id is None

    ambiguous = await toolkit.recall_task()
    assert ambiguous["error"] == "needs_task_selection", ambiguous
    listed = {t["task_id"] for t in ambiguous["open_tasks"]}
    assert {first["task_id"], second["task_id"]} <= listed
    # Each entry carries enough to choose between them and nothing more.
    assert all({"task_id", "goal", "status", "updated_at"} == set(t) for t in ambiguous["open_tasks"])

    # Crucially, being asked to choose did NOT pick one behind our back.
    assert tm.task_id is None

    # An explicit id still works while the association is lost — and
    # reading with it does not silently adopt it as the selection.
    explicit = await toolkit.recall_task(task_id=second["task_id"])
    assert explicit["status"] == "recalled", explicit
    assert tm.task_id is None

    # Reading a task's journal and artifacts does not select it either.
    await toolkit.list_task_events(task_id=first["task_id"])
    await toolkit.list_task_artifacts(task_id=first["task_id"])
    assert tm.task_id is None

    # Only the explicit repair selects.
    chosen = await toolkit.select_task(task_id=first["task_id"])
    assert chosen["status"] == "selected"
    assert tm.task_id == first["task_id"]

    # And now an omitted id resolves from that association, not similarity.
    resumed = await toolkit.recall_task()
    assert resumed["status"] == "recalled", resumed
    assert resumed["snapshot"]["task_id"] == first["task_id"]


async def test_readonly_budget_is_reported_not_silently_truncated(
    toolkit_on: WorkingMemoryToolkit,
) -> None:
    """An impossible budget is refused with the budget that would work."""
    started = await _started(toolkit_on)

    tiny = await toolkit_on.recall_task(task_id=started["task_id"], max_tokens=1)
    assert tiny["error"] == "budget_too_small", tiny
    # The caller is told what budget would actually work, rather than
    # being handed a snapshot with the required parts quietly missing.
    assert tiny["required_min_tokens"] > 1
