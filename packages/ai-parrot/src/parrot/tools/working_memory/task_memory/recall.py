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

import hashlib
import logging
import re
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

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
    "build_cache_key_parts",
    "cache_digest",
    "RECALL_EVENT_WINDOW",
    "RECALL_ARTIFACT_LIMIT",
    "NEEDS_SELECTION_PAGE",
    "RecallCache",
    "InMemoryRecallCache",
    "RedisRecallCache",
    "RecallReader",
    "collect_omission_ids",
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


def build_cache_key_parts(
    *,
    scope_key: str,
    task_id: str,
    as_of_seq: int,
    availability_generation: int,
    tokenizer: str,
    calibration: float,
    max_tokens: int,
    recent_calls_limit: int,
) -> Tuple[Tuple[str, str], ...]:
    """Return every input a recall cache key must cover.

    Extracted so the *reader* can compute the key **before** running a
    selection — a cache that could only be keyed after doing the work it
    is meant to avoid would be useless — while keeping exactly one
    definition of what the key contains. A part omitted here is a part a
    stale entry could be served across.

    ``availability_generation`` is the subtle one: it moves when an
    artifact is evicted, an omission expires or a worker restarts, none
    of which appends a task event. Without it, "deterministic" would
    decay into "expired content stays available forever at the same task
    sequence".

    Args:
        scope_key: Collision-safe encoding of the trusted scope.
        task_id: The task recalled.
        as_of_seq: Journal fence the pages were read at.
        availability_generation: Availability marker at read time.
        tokenizer: Token counter identity.
        calibration: Captured compaction calibration.
        max_tokens: Requested budget.
        recent_calls_limit: Requested recent-call count.

    Returns:
        Ordered ``(name, value)`` pairs.
    """
    return (
        ("scope", scope_key),
        ("task", task_id),
        ("seq", str(as_of_seq)),
        ("availability_generation", str(availability_generation)),
        ("tokenizer", tokenizer),
        ("calibration", f"{calibration:.6f}"),
        ("max_tokens", str(max_tokens)),
        ("recent_calls_limit", str(recent_calls_limit)),
        ("recall_schema", str(RECALL_SCHEMA_VERSION)),
    )


def cache_digest(parts: Sequence[Tuple[str, str]]) -> str:
    """Digest cache-key parts into one opaque, collision-safe token.

    Args:
        parts: The parts from :func:`build_cache_key_parts`.

    Returns:
        A hex digest. Derived from the canonical serialization of the
        parts, so two different part sets cannot collide by concatenation
        (the failure a naive ``":".join`` invites when a value contains
        the separator).
    """
    material = _canonical([list(pair) for pair in parts])
    return hashlib.blake2b(material, digest_size=16).hexdigest()


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

    cache_key_parts = build_cache_key_parts(
        scope_key=inputs.state.scope.cache_key(),
        task_id=inputs.state.task_id,
        as_of_seq=inputs.as_of_seq,
        availability_generation=inputs.availability.generation,
        tokenizer=getattr(counter, "name", "unknown"),
        calibration=calibration,
        max_tokens=max_tokens,
        recent_calls_limit=recent_calls_limit,
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


# ─────────────────────────────────────────────────────────────
# Bounded reads, caching and availability probes
# ─────────────────────────────────────────────────────────────

#: How many recent journal events one recall may read. Bounded so a long
#: journal costs the same as a short one: recall reads the TAIL, never a
#: full scan (AC10).
RECALL_EVENT_WINDOW: int = 120

#: How many artifact descriptors one recall may read.
RECALL_ARTIFACT_LIMIT: int = 50

#: Bound on the task list returned with ``needs_task_selection``.
NEEDS_SELECTION_PAGE: int = 20

#: Matches the omission ids the compaction layer mints. The single ``om_``
#: prefix is deliberate — the existing store already includes it, and
#: adding a second would break every recorded reference.
_OMISSION_ID_RE = re.compile(r"\bom_[0-9a-f]{16}\b")


class RecallCache(Protocol):
    """A TTL cache for serialized recall results."""

    async def get(self, key: str) -> Optional[bytes]:
        """Return the cached payload for ``key``, or ``None``."""
        ...

    async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
        """Store ``payload`` under ``key`` for ``ttl_seconds``."""
        ...


class InMemoryRecallCache:
    """Process-local recall cache with a monotonic-clock TTL.

    The clock is injectable so expiry can be tested without sleeping —
    a test that slept would be slow and, worse, flaky under load.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        """Initialize an empty cache.

        Args:
            clock: Monotonic time source, in seconds. **Required, not
                defaulted.** This module is held to a purity guard that
                forbids importing a clock anywhere in it — precisely so
                that hidden time dependencies cannot creep into recall —
                so the time source is supplied by the caller instead.
                Production wiring passes ``time.monotonic``; tests pass a
                controllable fake, which is also how TTL expiry is tested
                without sleeping.
        """
        self._clock = clock
        self._entries: Dict[str, Tuple[float, bytes]] = {}

    async def get(self, key: str) -> Optional[bytes]:
        """Return a live entry, dropping it when its TTL has passed.

        Args:
            key: The cache key.

        Returns:
            The payload, or ``None`` when absent or expired.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if self._clock() >= expires_at:
            self._entries.pop(key, None)
            return None
        return payload

    async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
        """Store a payload with a TTL.

        Args:
            key: The cache key.
            payload: Serialized recall result.
            ttl_seconds: Lifetime. ``0`` or less stores nothing.
        """
        if ttl_seconds <= 0:
            return
        self._entries[key] = (self._clock() + ttl_seconds, payload)

    def clear(self) -> None:
        """Drop every entry."""
        self._entries.clear()


class RedisRecallCache:
    """Recall cache over an existing async Redis client.

    Never opens its own connection: it borrows the one the conversation
    memory already owns, exactly as :class:`RedisOmissionStore` does.
    """

    def __init__(self, redis_client: Any) -> None:
        """Initialize the cache.

        Args:
            redis_client: An already-constructed async Redis client.
        """
        self._redis = redis_client

    async def get(self, key: str) -> Optional[bytes]:
        """Return the cached payload, or ``None``.

        Args:
            key: The cache key.

        Returns:
            The payload as bytes, or ``None``.
        """
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)

    async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
        """Store a payload with a Redis TTL.

        Args:
            key: The cache key.
            payload: Serialized recall result.
            ttl_seconds: Lifetime in seconds. ``0`` or less stores
                nothing, rather than storing something that never
                expires.
        """
        if ttl_seconds <= 0:
            return
        await self._redis.set(key, payload, ex=ttl_seconds)


def collect_omission_ids(events: Sequence[JournalEvent]) -> Tuple[str, ...]:
    """Return the omission ids referenced by a bounded page of events.

    Scans the serialized payloads rather than reaching for a specific
    field, because omission references can appear anywhere redaction put
    one. The scan is bounded twice over: the event page is bounded, and
    each payload is capped at 8 KiB.

    Args:
        events: The bounded event page.

    Returns:
        The distinct ids, in first-seen order so the result is stable.
    """
    seen: Dict[str, None] = {}
    for event in events:
        text = _canonical(event.payload.model_dump(mode="json")).decode("utf-8")
        for match in _OMISSION_ID_RE.findall(text):
            seen.setdefault(match, None)
    return tuple(seen)


class RecallReader:
    """Builds bounded recall inputs, caches results, and never loads payloads.

    This is the I/O half of recall; :func:`select_recall` remains a pure
    function and does the choosing. The split matters: everything that
    could make recall expensive or non-deterministic lives here, where it
    is bounded and observable, and the selector cannot reach past what it
    is handed.

    Three properties this class exists to guarantee (AC10):

    - **One fence.** The projection, the event page and the descriptor
      page are all read at a single ``as_of_seq``, so they describe one
      instant rather than three nearby ones.
    - **No payload reads.** It calls ``list``/``load_snapshot``/
      ``list_events`` and the omission *probe*. It never calls
      ``load_payload``, never calls ``OmissionStore.get``, and never asks
      a descriptor to summarize itself.
    - **Bounded everything.** Page sizes are constants, not caller input.

    Args:
        store: The task-memory store.
        artifacts: The artifact store, read for descriptors only.
        config: Capacity and TTL configuration.
        cache: Optional recall cache.
        association: Optional association store, used to resolve an
            omitted task id and to build the cache key.
        omission_store: Optional omission store to probe.
        counter: Token counter; defaults to the compaction default.
    """

    def __init__(
        self,
        store: Any,
        artifacts: Any,
        *,
        config: Optional[Any] = None,
        cache: Optional[RecallCache] = None,
        association: Optional[Any] = None,
        omission_store: Optional[Any] = None,
        counter: Optional[TokenCounterLike] = None,
    ) -> None:
        """Initialize the reader (see class docstring)."""
        from .config import TaskMemoryConfig

        self._store = store
        self._artifacts = artifacts
        self._config = config or TaskMemoryConfig()
        self._cache = cache
        self._association = association
        self._omissions = omission_store
        self._counter = counter
        self.logger = logging.getLogger(__name__)

    def _resolve_counter(self) -> TokenCounterLike:
        """Return the token counter to measure with.

        Returns:
            The injected counter, or the compaction layer's default.
        """
        if self._counter is not None:
            return self._counter
        from parrot.memory.compaction.tokens import get_default_counter

        self._counter = get_default_counter()
        return self._counter

    @staticmethod
    def omission_key(scope: Any) -> str:
        """Compose the omission-store scoping key for a task scope.

        Mirrors ``ConversationMemory.omission_key`` exactly — that method
        documents the composition as ``"{chatbot_id}:{user_id}:{session_id}"``,
        so this is a restatement rather than a guess.

        Args:
            scope: The trusted scope.

        Returns:
            The omission-store session key.
        """
        return f"{scope.chatbot_id or '_default'}:{scope.user_id}:{scope.session_id}"

    async def _probe_omissions(self, scope: Any, events: Sequence[JournalEvent]) -> Dict[str, Optional[bool]]:
        """Probe every omission id the event page references.

        Args:
            scope: The trusted scope.
            events: The bounded event page.

        Returns:
            A mapping of id to three-valued availability. Every id maps to
            ``None`` when no store is configured — unknown, never
            optimistically present.
        """
        ids = collect_omission_ids(events)
        if not ids:
            return {}
        if self._omissions is None:
            return {cid: None for cid in ids}
        try:
            return await self._omissions.probe_many(self.omission_key(scope), ids)
        except Exception as exc:  # noqa: BLE001 — a probe failure is "unknown", not fatal
            self.logger.warning("omission availability probe failed (%s); reporting unknown", exc)
            return {cid: None for cid in ids}

    async def _read_fence(self, scope: Any, task_id: str) -> Optional[Tuple[Any, Any]]:
        """Read the two things a cache key needs, and nothing more.

        A cache entry cannot be trusted without knowing the fence it was
        taken at, so these two reads happen on every recall — including a
        hit. They are deliberately the *cheap* ones: the projection and a
        bounded descriptor page. The expensive work a hit actually avoids
        is the journal page, the omission probes and the whole selection
        loop.

        Args:
            scope: The trusted scope.
            task_id: The task to read.

        Returns:
            A ``(snapshot, artifact_page)`` pair, or ``None`` when the
            task does not exist in this scope.
        """
        snapshot = await self._store.load_snapshot(scope, task_id)
        if snapshot is None:
            return None
        artifact_page = await self._artifacts.list(
            scope, task_id=task_id, limit=RECALL_ARTIFACT_LIMIT, as_of_seq=snapshot.as_of_seq
        )
        return snapshot, artifact_page

    async def _complete_inputs(
        self,
        scope: Any,
        task_id: str,
        snapshot: Any,
        artifact_page: Any,
        *,
        worker_generation: Optional[str],
    ) -> RecallInputs:
        """Finish building inputs — reached on a cache miss only.

        Args:
            scope: The trusted scope.
            task_id: The task to read.
            snapshot: The projection already read for the fence.
            artifact_page: The descriptor page already read for the fence.
            worker_generation: Live REPL worker generation.

        Returns:
            The complete recall inputs.
        """
        as_of = snapshot.as_of_seq
        # Read the TAIL of the journal, fenced at the same sequence the
        # projection reflects. A full scan would make recall's cost grow
        # with the task's age.
        after = max(0, as_of - RECALL_EVENT_WINDOW)
        event_page = await self._store.list_events(
            scope, task_id, after_seq=after, limit=RECALL_EVENT_WINDOW, as_of_seq=as_of
        )
        availability = AvailabilitySnapshot(
            artifacts={str(d.ref): d.availability for d in artifact_page.items},
            omissions=await self._probe_omissions(scope, event_page.events),
            worker_generation=worker_generation,
            generation=artifact_page.availability_generation,
        )
        return RecallInputs(
            state=snapshot.state,
            as_of_seq=as_of,
            events=tuple(event_page.events),
            artifacts=tuple(artifact_page.items),
            availability=availability,
        )

    async def build_inputs(
        self,
        scope: Any,
        task_id: str,
        *,
        worker_generation: Optional[str] = None,
    ) -> Optional[RecallInputs]:
        """Read one consistent, bounded set of recall inputs.

        Every page is fenced at the projection's ``as_of_seq``, so the
        projection, the journal page and the descriptor page describe one
        instant rather than three nearby ones.

        Args:
            scope: The trusted scope.
            task_id: The task to read.
            worker_generation: Identity of the live REPL worker
                generation, so stale bindings can be labelled.

        Returns:
            The inputs, or ``None`` when the task does not exist in this
            scope.
        """
        fence = await self._read_fence(scope, task_id)
        if fence is None:
            return None
        snapshot, artifact_page = fence
        return await self._complete_inputs(scope, task_id, snapshot, artifact_page, worker_generation=worker_generation)

    async def recall(
        self,
        scope: Any,
        task_id: Optional[str] = None,
        *,
        max_tokens: Optional[int] = None,
        recent_calls_limit: Optional[int] = None,
        calibration: float = 1.0,
        worker_generation: Optional[str] = None,
        use_cache: bool = True,
    ) -> RecallResult:
        """Produce one bounded recall, serving a cached result when valid.

        Args:
            scope: The trusted scope.
            task_id: The task to recall. When ``None``, resolved from the
                authoritative selected association — never by similarity.
            max_tokens: Budget; defaults to the configured value.
            recent_calls_limit: Recent-call count; defaults to configured.
            calibration: Captured compaction calibration.
            worker_generation: Live REPL worker generation.
            use_cache: Whether to consult and populate the cache.

        Returns:
            The recall result. ``needs_task_selection`` carries a bounded
            list of open tasks to choose from.
        """
        budget = self._config.recall_max_tokens if max_tokens is None else max_tokens
        calls = self._config.recall_recent_calls_limit if recent_calls_limit is None else recent_calls_limit

        resolved = await self._resolve_task(scope, task_id)
        if resolved is None:
            return await self._needs_selection(scope)

        fence = await self._read_fence(scope, resolved)
        if fence is None:
            return await self._needs_selection(scope)
        snapshot, artifact_page = fence

        counter = self._resolve_counter()
        parts = build_cache_key_parts(
            scope_key=scope.cache_key(),
            task_id=snapshot.state.task_id,
            as_of_seq=snapshot.as_of_seq,
            availability_generation=artifact_page.availability_generation,
            tokenizer=getattr(counter, "name", "unknown"),
            calibration=calibration,
            max_tokens=budget,
            recent_calls_limit=calls,
        )
        key = self._cache_key(scope, parts)

        # Checked BEFORE the journal page and the omission probes, so a
        # hit actually avoids work rather than merely avoiding the final
        # serialization. The fence reads above cannot be skipped: an entry
        # cannot be known fresh without them.
        if use_cache and self._cache is not None:
            cached = await self._cache_get(key)
            if cached is not None:
                return cached

        inputs = await self._complete_inputs(
            scope, resolved, snapshot, artifact_page, worker_generation=worker_generation
        )
        result = select_recall(
            inputs,
            counter=counter,
            calibration=calibration,
            max_tokens=budget,
            recent_calls_limit=calls,
        )
        if use_cache and self._cache is not None:
            await self._cache_set(key, result)
        return result

    def _cache_key(self, scope: Any, parts: Sequence[Tuple[str, str]]) -> str:
        """Build the cache key for one recall shape.

        Uses the association store's key family when one is available, so
        recall entries live under the same scoped, TTL'd namespace as the
        other hot keys rather than in a parallel scheme.

        Args:
            scope: The trusted scope.
            parts: The cache-key parts.

        Returns:
            The key.
        """
        digest = cache_digest(parts)
        if self._association is not None:
            return self._association.recall_key(scope, digest)
        return f"_task_recall:{scope.cache_key()}:{digest}"

    async def _cache_get(self, key: str) -> Optional[RecallResult]:
        """Read a cached result, tolerating a cache outage.

        A cache failure must never change task truth, so it degrades to a
        miss rather than propagating.

        Args:
            key: The cache key.

        Returns:
            The cached result, or ``None``.
        """
        try:
            raw = await self._cache.get(key)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 — cache outage degrades to a miss
            self.logger.warning("recall cache read failed (%s); recomputing", exc)
            return None
        if raw is None:
            return None
        try:
            return RecallResult.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 — a corrupt entry is a miss
            self.logger.warning("discarding unreadable recall cache entry (%s)", exc)
            return None

    async def _cache_set(self, key: str, result: RecallResult) -> None:
        """Store a result, tolerating a cache outage.

        Args:
            key: The cache key.
            result: The result to cache.
        """
        try:
            await self._cache.set(  # type: ignore[union-attr]
                key, result.model_dump_json().encode("utf-8"), self._config.recall_cache_ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 — cache outage must not fail a recall
            self.logger.warning("recall cache write failed (%s); continuing uncached", exc)

    async def _resolve_task(self, scope: Any, task_id: Optional[str]) -> Optional[str]:
        """Resolve which task to recall.

        Args:
            scope: The trusted scope.
            task_id: Explicit task id, when the caller supplied one.

        Returns:
            The task id, or ``None`` when the caller must choose.
        """
        if task_id is not None:
            return task_id
        if self._association is None:
            return None
        selection = await self._association.resolve(scope)
        return getattr(selection, "task_id", None)

    async def _needs_selection(self, scope: Any) -> RecallResult:
        """Return the bounded "choose a task" answer.

        Args:
            scope: The trusted scope.

        Returns:
            A ``needs_task_selection`` result carrying a bounded page of
            open tasks. Never a similarity guess.
        """
        page = await self._store.list_tasks(scope, limit=NEEDS_SELECTION_PAGE)
        snapshot = {
            "schema_version": RECALL_SCHEMA_VERSION,
            "status": RecallStatus.NEEDS_TASK_SELECTION.value,
            "open_tasks": [
                {
                    "task_id": item.task_id,
                    "goal": item.goal_preview,
                    "status": item.status.value,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in page.items
            ],
        }
        encoded = _canonical(snapshot)
        return RecallResult(
            status=RecallStatus.NEEDS_TASK_SELECTION,
            snapshot=snapshot,
            payload_bytes=len(encoded),
            estimated_tokens=0,
            truncation=TruncationAccount(),
        )
