"""Unit tests for the deterministic recall selector (FEAT-538 / TASK-2987).

Three required cases from the task's Test Specification:

- ``test_determinism`` — identical captured inputs yield exactly
  identical bytes, counters included.
- ``test_budget`` — envelope and truncation overhead are counted; a
  required-only overflow returns the measured minimum; the Unicode
  heuristic obeys its byte ceiling.
- ``test_priority`` — unresolved outcomes precede optional recent
  successes and artifacts, and the truncation counts match what was
  actually omitted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import orjson
import pytest
from parrot.memory.compaction.tokens import HeuristicCounter
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    ArtifactDescriptor,
    ArtifactKind,
    Attribution,
    CallOutcome,
    CompletionPolicy,
    CompletionSource,
    Constraint,
    Decision,
    EventType,
    EvidenceRef,
    JournalEvent,
    ReplBinding,
    ResumeHint,
    StepStatus,
    TaskScope,
    TaskState,
    TaskStatus,
    TaskStep,
    ToolCallPayload,
)
from parrot.tools.working_memory.task_memory.recall import (
    HEURISTIC_BYTES_PER_TOKEN,
    MAX_RECALL_TOKENS,
    MAX_RECENT_CALLS,
    AvailabilitySnapshot,
    RecallInputs,
    RecallStatus,
    needs_task_selection,
    select_recall,
)

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Counter:
    """A deterministic counter with a controllable name and ratio."""

    def __init__(self, name: str = "test", per_char: int = 1) -> None:
        """Initialize the counter.

        Args:
            name: Tokenizer identity, which participates in the cache key.
            per_char: Tokens charged per character.
        """
        self.name = name
        self._per_char = per_char

    def count(self, text: str) -> int:
        """Return the token count for ``text``.

        Args:
            text: The text to count.

        Returns:
            ``len(text) * per_char``.
        """
        return len(text) * self._per_char


def _tool_event(
    seq: int,
    *,
    call_id: str,
    event_type: EventType,
    outcome: Optional[CallOutcome],
    step_id: Optional[str] = None,
    tool: str = "wm_store",
    error: Optional[str] = None,
) -> JournalEvent:
    """Build a deterministic tool-call event.

    Args:
        seq: Journal sequence.
        call_id: Physical attempt identity.
        event_type: Which tool event.
        outcome: Typed outcome.
        step_id: Step correlation.
        tool: Tool name.
        error: Condensed error text.

    Returns:
        The event.
    """
    return JournalEvent(
        event_id=f"e{seq}",
        task_id="t-1",
        seq=seq,
        occurred_at=T0 + timedelta(seconds=seq),
        event_type=event_type,
        step_id=step_id,
        attribution=Attribution.DECLARED if step_id else Attribution.NONE,
        payload=ToolCallPayload(call_id=call_id, tool_name=tool, outcome=outcome, error=error, counted=True),
    )


def _state(**overrides) -> TaskState:
    """Build a three-step task projection.

    Args:
        **overrides: Fields to replace.

    Returns:
        The projection.
    """
    steps = (
        TaskStep(
            step_id="s-load",
            title="Load raw data",
            status=StepStatus.COMPLETED,
            completion_source=CompletionSource.VALIDATED,
            evidence_refs=(EvidenceRef(artifact_id="art-1", version=1),),
        ),
        TaskStep(step_id="s-clean", title="Clean data", depends_on=("s-load",)),
        TaskStep(step_id="s-report", title="Write report", depends_on=("s-clean",)),
    )
    base = {
        "task_id": "t-1",
        "scope": SCOPE,
        "goal": "Produce the quarterly report",
        "constraints": (Constraint(constraint_id="c-1", text="Never mutate the source"),),
        "steps": steps,
        "decisions": (Decision(decision_id="d-1", text="use parquet", reason="faster"),),
        "resume_hint": ResumeHint(text="clean the data next", step_id="s-clean"),
        "revision": 7,
        "plan_revision": 2,
        "last_event_seq": 12,
    }
    base.update(overrides)
    return TaskState(**base)


def _inputs(**overrides) -> RecallInputs:
    """Build recall inputs over the standard projection.

    Args:
        **overrides: Fields to replace.

    Returns:
        The inputs.
    """
    base = {"state": _state(), "as_of_seq": 12}
    base.update(overrides)
    return RecallInputs(**base)


# ─────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────


def test_determinism_identical_inputs_yield_identical_bytes() -> None:
    """Two runs over the same captured inputs are byte-identical."""
    inputs = _inputs()
    counter = HeuristicCounter()

    first = select_recall(inputs, counter=counter, calibration=1.0, max_tokens=2_500)
    second = select_recall(inputs, counter=counter, calibration=1.0, max_tokens=2_500)

    assert first.to_bytes() == second.to_bytes()
    assert (first.payload_bytes, first.estimated_tokens) == (second.payload_bytes, second.estimated_tokens)
    assert first.truncation == second.truncation
    assert first.cache_key_parts == second.cache_key_parts


def test_determinism_serialization_is_canonical() -> None:
    """Output keys are sorted, so two equal structures cannot differ in bytes."""
    result = select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=2_500)
    encoded = result.to_bytes()
    assert encoded == orjson.dumps(result.snapshot, option=orjson.OPT_SORT_KEYS)
    assert encoded == orjson.dumps(orjson.loads(encoded), option=orjson.OPT_SORT_KEYS)


def test_determinism_cache_key_covers_everything_that_changes_output() -> None:
    """Anything that changes the bytes must also change the cache key.

    A cache key that omitted one of these would serve a stale recall after
    the underlying thing moved — most dangerously the availability
    generation, which changes with **no task event at all**.
    """
    base = _inputs()
    counter = HeuristicCounter()
    reference = select_recall(base, counter=counter, calibration=1.0, max_tokens=2_500)
    key = dict(reference.cache_key_parts)

    for part in (
        "scope",
        "task",
        "seq",
        "availability_generation",
        "tokenizer",
        "calibration",
        "max_tokens",
        "recent_calls_limit",
        "recall_schema",
    ):
        assert part in key, f"cache key omits {part!r}"

    # Availability changing with no task event must move the key.
    moved = select_recall(
        _inputs(availability=AvailabilitySnapshot(generation=9)),
        counter=counter,
        calibration=1.0,
        max_tokens=2_500,
    )
    assert dict(moved.cache_key_parts)["availability_generation"] != key["availability_generation"]
    assert moved.to_bytes() != reference.to_bytes(), "the generation is echoed into the snapshot"

    # A different tokenizer identity must move the key.
    other = select_recall(base, counter=_Counter(name="tiktoken-x"), calibration=1.0, max_tokens=2_500)
    assert dict(other.cache_key_parts)["tokenizer"] != key["tokenizer"]

    # And so must a different calibration.
    calibrated = select_recall(base, counter=counter, calibration=1.5, max_tokens=2_500)
    assert dict(calibrated.cache_key_parts)["calibration"] != key["calibration"]


def test_determinism_recall_is_pure() -> None:
    """The selector reads no clock, mints no ids and performs no I/O.

    Checked by parsing the module, not by monkeypatching: a patch on a
    default factory captured at class-definition time would not be reached
    and the test would pass while proving nothing.
    """
    import ast
    import importlib
    from pathlib import Path

    module = importlib.import_module("parrot.tools.working_memory.task_memory.recall")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    forbidden_calls = {"utc_now", "new_id", "uuid4", "now", "today", "random", "open", "sleep"}
    called = {
        (node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not (called & forbidden_calls), f"recall.py calls {sorted(called & forbidden_calls)}"

    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert not imported & {"random", "uuid", "time", "os", "pathlib", "asyncio", "redis", "asyncpg"}


def test_determinism_recall_never_appends() -> None:
    """Repeated recalls leave the captured inputs completely untouched."""
    inputs = _inputs(
        events=(_tool_event(1, call_id="c1", event_type=EventType.TOOL_SUCCEEDED, outcome=CallOutcome.SUCCESS),)
    )
    before = inputs.model_dump_json()
    for _ in range(5):
        select_recall(inputs, counter=HeuristicCounter(), max_tokens=2_500)
    assert inputs.model_dump_json() == before


def test_determinism() -> None:
    """Required aggregate case: identical captured inputs yield identical bytes."""
    test_determinism_identical_inputs_yield_identical_bytes()
    test_determinism_serialization_is_canonical()
    test_determinism_cache_key_covers_everything_that_changes_output()
    test_determinism_recall_is_pure()
    test_determinism_recall_never_appends()


# ─────────────────────────────────────────────────────────────
# Budget
# ─────────────────────────────────────────────────────────────


def test_budget_counts_envelope_and_truncation_overhead() -> None:
    """The measured cost is the cost of the WHOLE payload, truncation block included."""
    result = select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=2_500)
    assert result.status is RecallStatus.OK

    # The reported byte size is the size of exactly what would be sent —
    # envelope, truncation account and all.
    assert result.payload_bytes == len(result.to_bytes())
    assert "truncation" in result.snapshot
    assert result.estimated_tokens == HeuristicCounter().count(result.to_bytes().decode("utf-8"))


def test_budget_required_only_overflow_returns_measured_minimum() -> None:
    """When even the required units do not fit, the caller is told what would."""
    result = select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=1)

    assert result.status is RecallStatus.BUDGET_TOO_SMALL
    assert result.snapshot == {}, "a failed recall returns no partial payload"
    assert result.payload_bytes == 0
    assert result.required_min_tokens is not None and result.required_min_tokens > 1

    # And that reported minimum is honest: asking for it succeeds.
    retry = select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=result.required_min_tokens)
    assert retry.status is RecallStatus.OK, "the reported minimum must actually be sufficient"


def test_budget_unicode_obeys_the_byte_ceiling() -> None:
    """With the heuristic counter, the 4-bytes-per-token ceiling is enforced.

    Multibyte text is where a character-based check would silently
    overflow: the heuristic is ``bytes // 4``, so the ceiling must be
    measured in bytes.
    """
    # Every character is 3 UTF-8 bytes.
    heavy = _state(goal="✓" * 600, constraints=(Constraint(constraint_id="c-1", text="✓" * 400),))
    inputs = _inputs(state=heavy)

    budget = 400
    result = select_recall(inputs, counter=HeuristicCounter(), max_tokens=budget)

    if result.status is RecallStatus.OK:
        assert result.payload_bytes <= budget * HEURISTIC_BYTES_PER_TOKEN
        assert result.estimated_tokens <= budget
    else:
        assert result.status is RecallStatus.BUDGET_TOO_SMALL
        assert result.required_min_tokens is not None
        assert result.required_min_tokens > budget

    assert result.tokens_estimated is True, "the heuristic result must be labelled an estimate"


def test_budget_tokens_estimated_flag_tracks_the_counter() -> None:
    """Only the heuristic counter produces an estimated result."""
    assert select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=2_500).tokens_estimated is True
    assert (
        select_recall(_inputs(), counter=_Counter(name="o200k_base"), max_tokens=MAX_RECALL_TOKENS).tokens_estimated
        is False
    )


def test_budget_calibration_is_applied_and_rounded_up() -> None:
    """Calibration scales the estimate, rounding up rather than down.

    Under-reporting is the failure that overflows a context window, so the
    rounding direction is not arbitrary.
    """
    inputs = _inputs()
    plain = select_recall(inputs, counter=_Counter(), calibration=1.0, max_tokens=MAX_RECALL_TOKENS)
    scaled = select_recall(inputs, counter=_Counter(), calibration=2.0, max_tokens=MAX_RECALL_TOKENS)
    assert scaled.estimated_tokens >= plain.estimated_tokens * 2 - 1


def test_budget_rejects_out_of_range_requests() -> None:
    """Nonsensical bounds are rejected, not silently clamped.

    Silently clamping would hide a caller bug behind a plausible answer.
    """
    for bad in (0, -1, MAX_RECALL_TOKENS + 1):
        with pytest.raises(ValueError, match="max_tokens"):
            select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=bad)

    for bad in (-1, MAX_RECENT_CALLS + 1):
        with pytest.raises(ValueError, match="recent_calls_limit"):
            select_recall(_inputs(), counter=HeuristicCounter(), max_tokens=2_500, recent_calls_limit=bad)


def test_budget_never_truncates_a_serialized_value() -> None:
    """Units are dropped whole; no string is cut mid-value.

    A half-written evidence reference is worse than an omitted one — it
    looks resolvable and is not.
    """
    events = tuple(
        _tool_event(i, call_id=f"c{i}", event_type=EventType.TOOL_SUCCEEDED, outcome=CallOutcome.SUCCESS)
        for i in range(1, 30)
    )
    artifacts = tuple(
        ArtifactDescriptor(
            ref=EvidenceRef(artifact_id=f"art-{i}", version=1),
            scope=SCOPE,
            alias=f"alias-{i}",
            kind=ArtifactKind.DATAFRAME,
        )
        for i in range(20)
    )
    inputs = _inputs(events=events, artifacts=artifacts)

    result = select_recall(inputs, counter=HeuristicCounter(), max_tokens=400, recent_calls_limit=20)
    assert result.status is RecallStatus.OK

    # Every unit that survived is complete and parses.
    decoded = orjson.loads(result.to_bytes())
    for artifact in decoded["artifacts"]:
        assert set(artifact) >= {"ref", "alias", "kind", "availability"}
        assert artifact["ref"].count("@") == 1, "a reference was cut in half"
    for call in decoded["recent_calls"]:
        assert set(call) >= {"seq", "call_id", "tool", "outcome"}


def test_budget() -> None:
    """Required aggregate case: overhead counted, minimum measured, ceiling obeyed."""
    test_budget_counts_envelope_and_truncation_overhead()
    test_budget_required_only_overflow_returns_measured_minimum()
    test_budget_unicode_obeys_the_byte_ceiling()
    test_budget_tokens_estimated_flag_tracks_the_counter()
    test_budget_rejects_out_of_range_requests()
    test_budget_never_truncates_a_serialized_value()


# ─────────────────────────────────────────────────────────────
# Priority
# ─────────────────────────────────────────────────────────────


def _mixed_events() -> Tuple[JournalEvent, ...]:
    """Return a page with one unresolved call among several successes."""
    return (
        _tool_event(1, call_id="c1", event_type=EventType.TOOL_SUCCEEDED, outcome=CallOutcome.SUCCESS),
        _tool_event(
            2, call_id="c2", event_type=EventType.TOOL_OUTCOME_UNKNOWN, outcome=CallOutcome.UNKNOWN, tool="charge_card"
        ),
        _tool_event(3, call_id="c3", event_type=EventType.TOOL_SUCCEEDED, outcome=CallOutcome.SUCCESS),
        _tool_event(4, call_id="c4", event_type=EventType.TOOL_SUCCEEDED, outcome=CallOutcome.SUCCESS),
    )


def test_priority_unresolved_survive_when_optional_units_are_dropped() -> None:
    """Unresolved outcomes outrank recent successes and artifacts."""
    artifacts = tuple(
        ArtifactDescriptor(ref=EvidenceRef(artifact_id=f"art-{i}", version=1), scope=SCOPE, alias=f"a{i}")
        for i in range(10)
    )
    inputs = _inputs(events=_mixed_events(), artifacts=artifacts)

    # A budget tight enough to force shedding, but not fatal.
    result = select_recall(inputs, counter=HeuristicCounter(), max_tokens=260, recent_calls_limit=10)
    assert result.status is RecallStatus.OK

    unresolved = result.snapshot["unresolved_outcomes"]
    assert [c["call_id"] for c in unresolved] == ["c2"], "the unknown outcome must survive"
    assert unresolved[0]["resolved"] is False
    assert unresolved[0]["tool"] == "charge_card"

    # Artifacts and recent successes were shed first.
    assert len(result.snapshot["artifacts"]) < len(artifacts)
    assert result.truncation.artifacts_omitted > 0
    assert result.truncation.unresolved_omitted == 0


def test_priority_an_unrelated_success_cannot_clear_an_unresolved_call() -> None:
    """Only the same call's own terminal event resolves it.

    A later unrelated success clearing an unknown outcome would be the
    system quietly deciding an uncertain external effect had succeeded.
    """
    inputs = _inputs(events=_mixed_events())
    result = select_recall(inputs, counter=HeuristicCounter(), max_tokens=2_500, recent_calls_limit=10)

    assert [c["call_id"] for c in result.snapshot["unresolved_outcomes"]] == ["c2"]

    # The same call reaching a terminal outcome DOES resolve it.
    resolved = inputs.events + (
        _tool_event(5, call_id="c2", event_type=EventType.TOOL_FAILED, outcome=CallOutcome.ERROR, tool="charge_card"),
    )
    after = select_recall(_inputs(events=resolved), counter=HeuristicCounter(), max_tokens=2_500, recent_calls_limit=10)
    assert after.snapshot["unresolved_outcomes"] == []


def test_priority_truncation_counts_match_the_omissions() -> None:
    """The account is arithmetic, not decoration."""
    artifacts = tuple(
        ArtifactDescriptor(ref=EvidenceRef(artifact_id=f"art-{i}", version=1), scope=SCOPE) for i in range(12)
    )
    inputs = _inputs(events=_mixed_events(), artifacts=artifacts)
    result = select_recall(inputs, counter=HeuristicCounter(), max_tokens=300, recent_calls_limit=10)
    assert result.status is RecallStatus.OK

    snapshot = result.snapshot
    account = result.truncation
    state = inputs.state

    assert len(snapshot["artifacts"]) + account.artifacts_omitted == len(artifacts)
    assert len(snapshot["steps"]) + account.steps_omitted == len(state.active_step_ids)
    assert len(snapshot["decisions"]) + account.decisions_omitted == len(state.active_decisions)
    assert len(snapshot["unresolved_outcomes"]) + account.unresolved_omitted == 1
    completed_required = sum(1 for s in state.steps if s.required and s.status is StepStatus.COMPLETED)
    assert len(snapshot["completed_steps"]) + account.completed_steps_omitted == completed_required
    assert account.any_omitted is True


def test_priority_required_units_always_survive() -> None:
    """Identity, goal, constraints and blockers are never shed."""
    blocked = _state(
        steps=(TaskStep(step_id="s-a", title="A", status=StepStatus.BLOCKED, blocked_reason="upstream_reopened"),)
    )
    artifacts = tuple(
        ArtifactDescriptor(ref=EvidenceRef(artifact_id=f"art-{i}", version=1), scope=SCOPE) for i in range(30)
    )
    result = select_recall(_inputs(state=blocked, artifacts=artifacts), counter=HeuristicCounter(), max_tokens=200)
    assert result.status is RecallStatus.OK

    snapshot = result.snapshot
    assert snapshot["task_id"] == "t-1"
    assert snapshot["goal"] == "Produce the quarterly report"
    assert snapshot["constraints"] == ["Never mutate the source"]
    assert snapshot["blockers"] == [{"step_id": "s-a", "reason": "upstream_reopened"}]


def test_priority_completion_source_is_labelled_honestly() -> None:
    """Recall always shows asserted completion as the weaker source."""
    asserted = _state(
        steps=(
            TaskStep(
                step_id="s-a", title="A", status=StepStatus.COMPLETED, completion_source=CompletionSource.AGENT_ASSERTED
            ),
            TaskStep(
                step_id="s-b", title="B", status=StepStatus.COMPLETED, completion_source=CompletionSource.VALIDATED
            ),
        )
    )
    result = select_recall(_inputs(state=asserted), counter=HeuristicCounter(), max_tokens=2_500)
    by_id = {s["step_id"]: s for s in result.snapshot["completed_steps"]}
    assert by_id["s-a"]["weaker_evidence"] is True
    assert by_id["s-a"]["completion_source"] == "agent_asserted"
    assert by_id["s-b"]["weaker_evidence"] is False


def test_priority_stale_hint_and_missing_evidence_are_labelled() -> None:
    """A stale hint and unavailable evidence are reported honestly."""
    state = _state(resume_hint=ResumeHint(text="clean next", step_id="s-clean", stale=True))
    availability = AvailabilitySnapshot(artifacts={"art-1@1": ArtifactAvailability.EXPIRED}, generation=3)
    result = select_recall(
        _inputs(state=state, availability=availability), counter=HeuristicCounter(), max_tokens=2_500
    )
    assert result.snapshot["resume_hint"]["stale"] is True

    completed = {s["step_id"]: s for s in result.snapshot["completed_steps"]}
    assert "art-1@1" in completed["s-load"]["evidence"]


def test_priority_unknown_availability_is_not_reported_as_present() -> None:
    """A reference absent from the snapshot reads as missing, never available."""
    availability = AvailabilitySnapshot(artifacts={}, generation=1)
    descriptor = ArtifactDescriptor(ref=EvidenceRef(artifact_id="art-9", version=2), scope=SCOPE, alias="ghost")
    result = select_recall(
        _inputs(artifacts=(descriptor,), availability=availability),
        counter=HeuristicCounter(),
        max_tokens=2_500,
    )
    assert result.snapshot["artifacts"][0]["availability"] == ArtifactAvailability.MISSING.value


def test_priority_stale_worker_binding_is_flagged() -> None:
    """A binding from another worker generation is invalid; the artifact is not."""
    descriptor = ArtifactDescriptor(
        ref=EvidenceRef(artifact_id="art-1", version=1),
        scope=SCOPE,
        alias="sales",
        repl_binding=ReplBinding(
            worker_session_id="gen-OLD",
            variable_name="sales",
            ref=EvidenceRef(artifact_id="art-1", version=1),
        ),
    )
    availability = AvailabilitySnapshot(
        artifacts={"art-1@1": ArtifactAvailability.PERSISTED},
        worker_generation="gen-NEW",
        generation=2,
    )
    result = select_recall(
        _inputs(artifacts=(descriptor,), availability=availability),
        counter=HeuristicCounter(),
        max_tokens=2_500,
    )
    entry = result.snapshot["artifacts"][0]
    assert entry["binding_invalid"] is True
    assert (
        entry["availability"] == ArtifactAvailability.PERSISTED.value
    ), "a stale binding does not mean the durable payload disappeared"


def test_priority_recall_carries_no_payload_or_arguments() -> None:
    """Recall is not a data channel: no rows, no raw output, no arguments."""
    events = (_tool_event(1, call_id="c1", event_type=EventType.TOOL_SUCCEEDED, outcome=CallOutcome.SUCCESS),)
    result = select_recall(_inputs(events=events), counter=HeuristicCounter(), max_tokens=2_500, recent_calls_limit=5)
    for call in result.snapshot["recent_calls"]:
        assert not {"input", "arguments", "output", "result", "payload"} & set(call)


def test_priority_needs_task_selection_is_never_a_guess() -> None:
    """With several open tasks and no selection, the caller must choose."""
    assert needs_task_selection(["t-1", "t-2"], None) is True
    assert needs_task_selection(["t-1"], None) is False
    assert needs_task_selection(["t-1", "t-2"], "t-1") is False
    assert needs_task_selection([], None) is False


def test_priority() -> None:
    """Required aggregate case: unresolved outrank optional units; counts match."""
    test_priority_unresolved_survive_when_optional_units_are_dropped()
    test_priority_an_unrelated_success_cannot_clear_an_unresolved_call()
    test_priority_truncation_counts_match_the_omissions()
    test_priority_required_units_always_survive()
    test_priority_completion_source_is_labelled_honestly()
    test_priority_stale_hint_and_missing_evidence_are_labelled()
    test_priority_unknown_availability_is_not_reported_as_present()
    test_priority_stale_worker_binding_is_flagged()
    test_priority_recall_carries_no_payload_or_arguments()
    test_priority_needs_task_selection_is_never_a_guess()
