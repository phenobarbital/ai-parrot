"""Deterministic bounded recall selection (FEAT-538, decision D5).

One recall must restore everything an agent needs to carry on after
context loss — goal, constraints, active and ready work, evidence
references, unresolved failures, truthful completion sources — inside a
token budget, from *captured* inputs only.

This module is a **pure selector**. Like the reducer, purity is the
contract rather than a preference:

- No I/O, no clock, no randomness, no tool execution, no LLM call, no
  data load. Recall never appends an event, so repeated reads cannot
  change a task's sequence or fill its journal (AC10).
- Everything it needs is passed in: the projection, a bounded event page,
  a bounded descriptor page, an **availability snapshot**, the caller's
  arguments, and the token counter plus its captured calibration.

Determinism means: identical captured state, availability snapshot,
counter identity, calibration and arguments produce **identical bytes**.
It deliberately does *not* mean that expired content stays available
forever at the same task sequence — availability can change with no task
event at all (an eviction, an expiry, a worker restart), which is exactly
why it is captured as an explicit input and folded into the result.

Selection is by **whole units**, in the specification's priority order:

1. identity, goal, active constraints, critical blockers — **required**
2. active and ready steps
3. active decisions and the resume hint
4. completed required steps and recent calls, unresolved failures first
5. relevant recent artifact descriptors

Optional units are removed, lowest priority first, until the complete
result fits. Serialized JSON strings are **never** truncated mid-value: a
half-written reference is worse than an honestly omitted one, and the
truncation account says exactly what was dropped.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

import orjson
from pydantic import BaseModel, ConfigDict, Field

from .models import (
    ArtifactAvailability,
    ArtifactDescriptor,
    CompletionSource,
    EventType,
    JournalEvent,
    StepStatus,
    TaskState,
    TaskStatus,
    ToolCallPayload,
)

__all__ = (
    "RECALL_SCHEMA_VERSION",
    "MAX_RECALL_TOKENS",
    "MIN_RECALL_TOKENS",
    "MAX_RECENT_CALLS",
    "HEURISTIC_BYTES_PER_TOKEN",
    "RecallStatus",
    "TokenCounterLike",
    "AvailabilitySnapshot",
    "RecallInputs",
    "TruncationAccount",
    "RecallResult",
    "select_recall",
    "needs_task_selection",
)

#: Version of the recall output shape. Part of the cache key: a recall
#: cached under an older shape must not be served to a newer reader.
RECALL_SCHEMA_VERSION: int = 1

#: Bounds on a caller's requested budget (spec §2 Recall).
MIN_RECALL_TOKENS: int = 1
MAX_RECALL_TOKENS: int = 16_000

#: Bound on the requested number of recent calls.
MAX_RECENT_CALLS: int = 100

#: The heuristic counter is ``bytes // 4``. When it is in use the spec
#: requires enforcing the corresponding **byte** ceiling directly, and
#: labelling the result as an estimate: it is not a guaranteed upper
#: bound on any provider's real tokenization.
HEURISTIC_BYTES_PER_TOKEN: int = 4

#: Name of the heuristic counter, as published by the compaction layer.
_HEURISTIC_NAME: str = "heuristic"


class RecallStatus(str, Enum):
    """Outcome of a recall attempt."""

    #: A complete, budget-fitting snapshot was produced.
    OK = "ok"
    #: Even the required units do not fit the requested budget.
    BUDGET_TOO_SMALL = "budget_too_small"
    #: No task is selected and more than one is open; the caller must
    #: choose. Never resolved by similarity — only by explicit selection.
    NEEDS_TASK_SELECTION = "needs_task_selection"


class TokenCounterLike(Protocol):
    """The compaction token counter's shape, restated to stay leaf-safe."""

    name: str

    def count(self, text: str) -> int:
        """Return the token count for ``text``."""
        ...


class _Model(BaseModel):
    """Shared configuration for recall models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AvailabilitySnapshot(_Model):
    """What was actually reachable at the moment recall ran.

    Captured explicitly because availability changes **without** a task
    event: an artifact is evicted, an omission expires, a worker restarts.
    Folding it into the inputs is what lets recall be deterministic for
    captured inputs while still being honest about what is gone.

    Attributes:
        artifacts: ``"artifact_id@version"`` → availability. A reference
            absent from the mapping is reported as ``missing``.
        omissions: ``om_...`` id → ``True`` (present), ``False`` (known
            gone) or ``None`` (**unknown** — a custom omission store with
            no availability probe). ``None`` is reported as unknown, never
            optimistically as present.
        worker_generation: Identity of the REPL worker generation whose
            bindings were checked. A binding from another generation is
            reported as invalid.
        generation: Monotonic marker that changes whenever availability
            changes with no task event. Part of the cache key.
    """

    artifacts: Dict[str, ArtifactAvailability] = Field(default_factory=dict)
    omissions: Dict[str, Optional[bool]] = Field(default_factory=dict)
    worker_generation: Optional[str] = None
    generation: int = Field(default=0, ge=0)

    def availability_of(self, ref: str) -> ArtifactAvailability:
        """Return the captured availability of one reference.

        Args:
            ref: Canonical ``artifact_id@version``.

        Returns:
            The captured availability, or ``MISSING`` when the reference
            was not in the snapshot. Absence is reported as missing rather
            than assumed available.
        """
        return self.artifacts.get(ref, ArtifactAvailability.MISSING)


class RecallInputs(_Model):
    """Everything recall is allowed to look at.

    Bounded by construction: the caller supplies *pages*, not a whole
    journal. Recall never scans a full journal, loads a payload, or runs
    a query of its own.

    Attributes:
        state: The reduced projection.
        as_of_seq: Sequence fence the pages were read at. Every page must
            describe the same instant.
        events: A bounded, ascending page of recent journal events.
        artifacts: A bounded page of artifact descriptors.
        availability: What was reachable when the pages were read.
        open_task_ids: Other open tasks in the scope, for the
            ``needs_task_selection`` answer.
    """

    state: TaskState
    as_of_seq: int = Field(ge=0)
    events: Tuple[JournalEvent, ...] = ()
    artifacts: Tuple[ArtifactDescriptor, ...] = ()
    availability: AvailabilitySnapshot = Field(default_factory=AvailabilitySnapshot)
    open_task_ids: Tuple[str, ...] = ()


class TruncationAccount(_Model):
    """What recall left out, counted rather than silently dropped.

    Attributes:
        steps_omitted: Active/ready steps not included.
        completed_steps_omitted: Completed required steps not included.
        decisions_omitted: Active decisions not included.
        calls_omitted: Recent calls not included.
        artifacts_omitted: Artifact descriptors not included.
        unresolved_omitted: Unresolved outcomes not included. Should stay
            ``0`` except under a genuinely tiny budget — unresolved
            failures outrank every other optional unit.
    """

    steps_omitted: int = Field(default=0, ge=0)
    completed_steps_omitted: int = Field(default=0, ge=0)
    decisions_omitted: int = Field(default=0, ge=0)
    calls_omitted: int = Field(default=0, ge=0)
    artifacts_omitted: int = Field(default=0, ge=0)
    unresolved_omitted: int = Field(default=0, ge=0)

    @property
    def any_omitted(self) -> bool:
        """Whether anything at all was left out."""
        return bool(
            self.steps_omitted
            or self.completed_steps_omitted
            or self.decisions_omitted
            or self.calls_omitted
            or self.artifacts_omitted
            or self.unresolved_omitted
        )


class RecallResult(_Model):
    """The result of one recall.

    Attributes:
        status: Whether a snapshot was produced, and if not, why.
        snapshot: The canonical snapshot payload. Empty on failure.
        payload_bytes: Canonical serialized bytes of ``snapshot``.
        estimated_tokens: Measured cost of ``payload_bytes``.
        tokens_estimated: ``True`` when the heuristic counter was used —
            the number is an estimate, not a guaranteed upper bound on a
            provider's tokenization.
        required_min_tokens: On ``budget_too_small``, the measured cost of
            the required units alone, so the caller knows what budget
            would actually work.
        truncation: What was omitted.
        cache_key_parts: The inputs a cache key must include, so a caller
            cannot accidentally cache on too little.
    """

    status: RecallStatus
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    payload_bytes: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    tokens_estimated: bool = False
    required_min_tokens: Optional[int] = Field(default=None, ge=0)
    truncation: TruncationAccount = Field(default_factory=TruncationAccount)
    cache_key_parts: Tuple[Tuple[str, str], ...] = ()

    def to_bytes(self) -> bytes:
        """Return the canonical serialization of the snapshot.

        Returns:
            Deterministic sorted-key UTF-8 JSON.
        """
        return _canonical(self.snapshot)


# ─────────────────────────────────────────────────────────────
# Canonical serialization and measurement
# ─────────────────────────────────────────────────────────────


def _canonical(value: Any) -> bytes:
    """Serialize ``value`` canonically.

    Args:
        value: A JSON-serializable structure.

    Returns:
        Sorted-key, compact UTF-8 bytes. The same structure always
        produces the same bytes, which is what makes recall comparable
        across processes.
    """
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _measure(payload: Any, counter: TokenCounterLike, calibration: float) -> Tuple[int, int]:
    """Measure a payload's serialized size and calibrated token cost.

    Args:
        payload: The structure to measure.
        counter: The token counter to use.
        calibration: The captured compaction calibration factor.

    Returns:
        A ``(byte_size, tokens)`` pair. Tokens are rounded **up** after
        calibration: under-reporting a budget is the failure that
        overflows a context window.
    """
    encoded = _canonical(payload)
    raw = counter.count(encoded.decode("utf-8"))
    tokens = int(-(-(raw * calibration) // 1)) if calibration != 1.0 else raw
    return len(encoded), tokens


def _is_heuristic(counter: TokenCounterLike) -> bool:
    """Whether ``counter`` is the heuristic estimator.

    Args:
        counter: The counter in use.

    Returns:
        ``True`` for the ``bytes // 4`` heuristic.
    """
    return getattr(counter, "name", "") == _HEURISTIC_NAME


# ─────────────────────────────────────────────────────────────
# Unit extraction
# ─────────────────────────────────────────────────────────────


def _step_unit(state: TaskState, step_id: str, availability: AvailabilitySnapshot) -> Dict[str, Any]:
    """Render one active step, with its criteria and evidence.

    Args:
        state: The projection.
        step_id: The step to render.
        availability: Captured availability, for labelling evidence.

    Returns:
        A JSON-safe mapping.
    """
    step = state.steps_by_id[step_id]
    return {
        "step_id": step.step_id,
        "title": step.title,
        "status": step.status.value,
        "required": step.required,
        "depends_on": list(step.depends_on),
        "attempts": step.attempt_count,
        "blocked_reason": step.blocked_reason,
        "completion_mode": step.completion_policy.mode.value,
        "expected_outputs": list(step.completion_policy.expected_outputs),
        "evidence": [
            {"ref": str(ref), "availability": availability.availability_of(str(ref)).value}
            for ref in step.evidence_refs
        ],
    }


def _completed_unit(state: TaskState, step_id: str) -> Dict[str, Any]:
    """Render one completed required step, labelling how it was completed.

    ``agent_asserted`` is always shown as the weaker source — a caller
    must be able to tell proven work from asserted work.

    Args:
        state: The projection.
        step_id: The step to render.

    Returns:
        A JSON-safe mapping.
    """
    step = state.steps_by_id[step_id]
    source = step.completion_source
    return {
        "step_id": step.step_id,
        "title": step.title,
        "completion_source": source.value if source else None,
        "weaker_evidence": source is CompletionSource.AGENT_ASSERTED,
        "evidence": [str(ref) for ref in step.evidence_refs],
    }


def _call_unit(event: JournalEvent, payload: ToolCallPayload) -> Dict[str, Any]:
    """Render one recent tool call.

    Args:
        event: The journal event.
        payload: Its tool-call payload.

    Returns:
        A JSON-safe mapping. Carries no arguments and no raw output —
        recall must not become a data channel.
    """
    outcome = payload.outcome
    return {
        "seq": event.seq,
        "call_id": payload.call_id,
        "tool": payload.tool_name,
        "attempt": payload.attempt,
        "executed": payload.executed,
        "outcome": outcome.value if outcome else None,
        "resolved": bool(outcome and outcome.is_resolved),
        "step_id": event.step_id,
        "attribution": event.attribution.value,
        "error": payload.error,
    }


def _artifact_unit(descriptor: ArtifactDescriptor, availability: AvailabilitySnapshot) -> Dict[str, Any]:
    """Render one artifact descriptor.

    Args:
        descriptor: The descriptor.
        availability: Captured availability.

    Returns:
        A JSON-safe mapping with no rows and no payload.
    """
    ref = str(descriptor.ref)
    binding_invalid = descriptor.binding_invalid
    binding = descriptor.repl_binding
    if binding is not None and availability.worker_generation is not None:
        # A binding from another worker generation is stale. The durable
        # artifact is still perfectly locatable — only the binding is bad.
        binding_invalid = binding_invalid or binding.worker_session_id != availability.worker_generation
    return {
        "ref": ref,
        "alias": descriptor.alias,
        "kind": descriptor.kind.value,
        "availability": availability.availability_of(ref).value,
        "verifiable": descriptor.evidence_verifiable,
        "invalidated": descriptor.invalidated,
        "binding_invalid": binding_invalid,
        "shape": list(descriptor.shape) if descriptor.shape else None,
        "bytes": descriptor.byte_size,
    }


def _unresolved_calls(events: Sequence[JournalEvent]) -> List[Tuple[JournalEvent, ToolCallPayload]]:
    """Return calls whose disposition is still unknown.

    A call becomes unresolved on a ``tool_cancelled`` or
    ``tool_outcome_unknown``, and stays unresolved until an explicit later
    attempt or a validated resolution records what happened. **A
    successful unrelated call cannot clear it** — that is the whole point,
    and the ordering below never lets an unrelated success remove one.

    Args:
        events: The bounded event page, ascending.

    Returns:
        The unresolved calls, in stable sequence order.
    """
    pending: Dict[str, Tuple[JournalEvent, ToolCallPayload]] = {}
    for event in events:
        payload = event.payload
        if not isinstance(payload, ToolCallPayload):
            continue
        call_id = payload.call_id
        if event.event_type in (EventType.TOOL_CANCELLED, EventType.TOOL_OUTCOME_UNKNOWN):
            pending[call_id] = (event, payload)
        elif event.event_type in (EventType.TOOL_SUCCEEDED, EventType.TOOL_FAILED):
            # Only THIS call's own later terminal event resolves it.
            pending.pop(call_id, None)
    return sorted(pending.values(), key=lambda item: item[0].seq)


def _recent_calls(
    events: Sequence[JournalEvent],
    limit: int,
    exclude: set,
) -> List[Tuple[JournalEvent, ToolCallPayload]]:
    """Return the most recent terminal calls, newest first.

    Args:
        events: The bounded event page, ascending.
        limit: How many to keep.
        exclude: Call ids already reported as unresolved.

    Returns:
        Up to ``limit`` calls, newest first, in stable sequence order.
    """
    terminal = [
        (event, event.payload)
        for event in events
        if isinstance(event.payload, ToolCallPayload)
        and event.event_type
        in (
            EventType.TOOL_SUCCEEDED,
            EventType.TOOL_FAILED,
            EventType.TOOL_CANCELLED,
            EventType.TOOL_OUTCOME_UNKNOWN,
        )
        and event.payload.call_id not in exclude
    ]
    terminal.sort(key=lambda item: item[0].seq, reverse=True)
    return terminal[:limit]


# ─────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────

#: Optional unit groups, in the order they are removed when the budget is
#: exhausted — lowest priority first. This is the inverse of the spec's
#: selection order, and unresolved failures are deliberately last: they
#: are the single most actionable thing a recovering agent needs.
_DROP_ORDER: Tuple[str, ...] = (
    "artifacts",
    "recent_calls",
    "completed_steps",
    "decisions",
    "resume_hint",
    "steps",
    "unresolved",
)


def _build(
    inputs: RecallInputs,
    *,
    include: Mapping[str, int],
    unresolved: Sequence[Tuple[JournalEvent, ToolCallPayload]],
    recent: Sequence[Tuple[JournalEvent, ToolCallPayload]],
    truncation: TruncationAccount,
) -> Dict[str, Any]:
    """Assemble a snapshot from the selected unit counts.

    Args:
        inputs: The captured inputs.
        include: How many of each optional group to include.
        unresolved: Unresolved calls, ascending.
        recent: Recent calls, newest first.
        truncation: The omission account to embed.

    Returns:
        The JSON-safe snapshot mapping.
    """
    state = inputs.state
    availability = inputs.availability

    active_ids = list(state.active_step_ids)
    ready = set(state.ready_step_ids)
    completed_required = [s.step_id for s in state.steps if s.required and s.status is StepStatus.COMPLETED]

    # Required units. Critical blockers are required, not optional: a
    # recovering agent that cannot see why it is stuck will simply get
    # stuck again.
    blockers = [
        {"step_id": s.step_id, "reason": s.blocked_reason} for s in state.steps if s.status is StepStatus.BLOCKED
    ]

    snapshot: Dict[str, Any] = {
        "schema_version": RECALL_SCHEMA_VERSION,
        "task_id": state.task_id,
        "goal": state.goal,
        "status": state.status.value,
        "revision": state.revision,
        "plan_revision": state.plan_revision,
        "plan_complete": state.plan_complete,
        "as_of_seq": inputs.as_of_seq,
        "availability_generation": availability.generation,
        "constraints": [c.text for c in state.active_constraints],
        "blockers": blockers,
        "can_complete": state.can_complete,
    }
    if not state.plan_complete and state.status is TaskStatus.ACTIVE:
        snapshot["plan_incomplete"] = True

    n = include.get("steps", 0)
    snapshot["steps"] = [_step_unit(state, sid, availability) for sid in active_ids[:n]]
    snapshot["ready_step_ids"] = [sid for sid in active_ids[:n] if sid in ready]

    n = include.get("unresolved", 0)
    snapshot["unresolved_outcomes"] = [_call_unit(e, p) for e, p in unresolved[:n]]

    n = include.get("decisions", 0)
    snapshot["decisions"] = [
        {"decision_id": d.decision_id, "text": d.text, "reason": d.reason} for d in state.active_decisions[:n]
    ]

    if include.get("resume_hint", 0) and state.resume_hint is not None:
        snapshot["resume_hint"] = {
            "text": state.resume_hint.text,
            "step_id": state.resume_hint.step_id,
            "stale": state.resume_hint.stale,
        }

    n = include.get("completed_steps", 0)
    snapshot["completed_steps"] = [_completed_unit(state, sid) for sid in completed_required[:n]]

    n = include.get("recent_calls", 0)
    snapshot["recent_calls"] = [_call_unit(e, p) for e, p in recent[:n]]

    n = include.get("artifacts", 0)
    snapshot["artifacts"] = [_artifact_unit(d, availability) for d in inputs.artifacts[:n]]

    snapshot["truncation"] = truncation.model_dump()
    return snapshot


def _account(
    inputs: RecallInputs,
    include: Mapping[str, int],
    totals: Mapping[str, int],
) -> TruncationAccount:
    """Compute what a given inclusion set leaves out.

    Args:
        inputs: The captured inputs.
        include: Included counts per group.
        totals: Available counts per group.

    Returns:
        The truncation account.
    """
    return TruncationAccount(
        steps_omitted=totals["steps"] - include.get("steps", 0),
        completed_steps_omitted=totals["completed_steps"] - include.get("completed_steps", 0),
        decisions_omitted=totals["decisions"] - include.get("decisions", 0),
        calls_omitted=totals["recent_calls"] - include.get("recent_calls", 0),
        artifacts_omitted=totals["artifacts"] - include.get("artifacts", 0),
        unresolved_omitted=totals["unresolved"] - include.get("unresolved", 0),
    )


def select_recall(
    inputs: RecallInputs,
    *,
    counter: TokenCounterLike,
    calibration: float = 1.0,
    max_tokens: int = 2_500,
    recent_calls_limit: int = 8,
) -> RecallResult:
    """Select a bounded, deterministic recall snapshot.

    Args:
        inputs: Everything recall is permitted to see. Bounded by the
            caller: recall never scans a whole journal.
        counter: The token counter, whose ``name`` participates in the
            cache key.
        calibration: The captured compaction calibration factor.
        max_tokens: Requested budget, clamped to
            ``[MIN_RECALL_TOKENS, MAX_RECALL_TOKENS]``.
        recent_calls_limit: Requested recent-call count, clamped to
            ``[0, MAX_RECENT_CALLS]``.

    Returns:
        A :class:`RecallResult`. ``status`` is ``budget_too_small`` when
        even the required units do not fit, carrying the measured
        ``required_min_tokens`` so the caller learns what budget works.
        ``needs_task_selection`` when no task is selected and several are
        open — never resolved by similarity.

    Raises:
        ValueError: If ``max_tokens`` or ``recent_calls_limit`` is outside
            its permitted range. A silently clamped nonsensical request
            would hide a caller bug.
    """
    if not (MIN_RECALL_TOKENS <= max_tokens <= MAX_RECALL_TOKENS):
        raise ValueError(f"max_tokens must be in [{MIN_RECALL_TOKENS}, {MAX_RECALL_TOKENS}], got {max_tokens}")
    if not (0 <= recent_calls_limit <= MAX_RECENT_CALLS):
        raise ValueError(f"recent_calls_limit must be in [0, {MAX_RECENT_CALLS}], got {recent_calls_limit}")

    estimated = _is_heuristic(counter)
    byte_ceiling = max_tokens * HEURISTIC_BYTES_PER_TOKEN if estimated else None

    cache_key_parts: Tuple[Tuple[str, str], ...] = (
        ("scope", inputs.state.scope.cache_key()),
        ("task", inputs.state.task_id),
        ("seq", str(inputs.as_of_seq)),
        ("availability_generation", str(inputs.availability.generation)),
        ("tokenizer", getattr(counter, "name", "unknown")),
        ("calibration", f"{calibration:.6f}"),
        ("max_tokens", str(max_tokens)),
        ("recent_calls_limit", str(recent_calls_limit)),
        ("recall_schema", str(RECALL_SCHEMA_VERSION)),
    )

    unresolved = _unresolved_calls(inputs.events)
    recent = _recent_calls(inputs.events, recent_calls_limit, exclude={p.call_id for _, p in unresolved})

    state = inputs.state
    totals = {
        "steps": len(state.active_step_ids),
        "unresolved": len(unresolved),
        "decisions": len(state.active_decisions),
        "resume_hint": 1 if state.resume_hint is not None else 0,
        "completed_steps": sum(1 for s in state.steps if s.required and s.status is StepStatus.COMPLETED),
        "recent_calls": len(recent),
        "artifacts": len(inputs.artifacts),
    }
    include: Dict[str, int] = dict(totals)

    def _attempt(current: Mapping[str, int]) -> Tuple[Dict[str, Any], int, int]:
        """Build and measure one candidate snapshot.

        Args:
            current: Inclusion counts to try.

        Returns:
            ``(snapshot, byte_size, tokens)``.
        """
        account = _account(inputs, current, totals)
        candidate = _build(inputs, include=current, unresolved=unresolved, recent=recent, truncation=account)
        size, tokens = _measure(candidate, counter, calibration)
        return candidate, size, tokens

    def _fits(size: int, tokens: int) -> bool:
        """Whether a measurement is within budget.

        Args:
            size: Serialized byte size.
            tokens: Calibrated token cost.

        Returns:
            ``True`` when both the token budget and, for the heuristic
            counter, the byte ceiling are satisfied.
        """
        if tokens > max_tokens:
            return False
        return not (byte_ceiling is not None and size > byte_ceiling)

    snapshot, size, tokens = _attempt(include)
    if _fits(size, tokens):
        return RecallResult(
            status=RecallStatus.OK,
            snapshot=snapshot,
            payload_bytes=size,
            estimated_tokens=tokens,
            tokens_estimated=estimated,
            truncation=_account(inputs, include, totals),
            cache_key_parts=cache_key_parts,
        )

    # Shed optional units, lowest priority first, one whole unit at a
    # time. Whole units only: a half-serialized reference is worse than an
    # honestly omitted one.
    for group in _DROP_ORDER:
        while include.get(group, 0) > 0:
            include[group] -= 1
            snapshot, size, tokens = _attempt(include)
            if _fits(size, tokens):
                return RecallResult(
                    status=RecallStatus.OK,
                    snapshot=snapshot,
                    payload_bytes=size,
                    estimated_tokens=tokens,
                    tokens_estimated=estimated,
                    truncation=_account(inputs, include, totals),
                    cache_key_parts=cache_key_parts,
                )

    # Nothing optional is left: what remains is the required floor.
    required_account = _account(inputs, include, totals)
    required = _build(inputs, include=include, unresolved=unresolved, recent=recent, truncation=required_account)
    required_size, required_tokens = _measure(required, counter, calibration)
    if byte_ceiling is not None and required_size > byte_ceiling:
        # Report the byte-implied token cost, so the caller is told a
        # budget that would actually satisfy the ceiling it tripped.
        required_tokens = max(required_tokens, -(-required_size // HEURISTIC_BYTES_PER_TOKEN))

    return RecallResult(
        status=RecallStatus.BUDGET_TOO_SMALL,
        snapshot={},
        payload_bytes=0,
        estimated_tokens=0,
        tokens_estimated=estimated,
        required_min_tokens=required_tokens,
        truncation=required_account,
        cache_key_parts=cache_key_parts,
    )


def needs_task_selection(open_task_ids: Sequence[str], selected: Optional[str]) -> bool:
    """Whether the caller must choose a task before recall can run.

    An omitted task id resolves **only** from the authoritative selected
    association. With several open tasks and no selection the answer is a
    bounded list to choose from — never a similarity guess.

    Args:
        open_task_ids: Open tasks in the scope.
        selected: The selected task id, if any.

    Returns:
        ``True`` when selection is required.
    """
    return selected is None and len(open_task_ids) > 1
