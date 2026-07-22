"""DevLoop session-state model — AHP-style channels, actions & pure reducers.

Authoritative core for ``sdd/specs/agent-host-protocol-session-state.spec.md``
(FEAT-322). Protocol-agnostic: this module deliberately does NOT import
JSON-RPC, aiohttp or Redis. It defines the invariant layers that survive
whatever wire protocol wins (AHP, A2A, or in-house):

1. **State**   — ``DevLoopSessionState`` (per run) and ``RunRegistryState``
                 (root channel): immutable, authoritative, snapshot-able.
2. **Actions** — closed discriminated unions; the *only* mechanism of
                 mutation (``DevLoopAction`` for the session channel,
                 ``RootAction`` for the root channel).
3. **Reducers**— pure ``(state, action) -> state``; run identically host-side
                 and client-side (a future Svelte port mirrors this file 1:1).

Mapping from the current ad-hoc events:

    FlowEventPublisher            DispatchEvent.kind          Action here
    ─────────────────────         ─────────────────────       ─────────────────────
    flow.node_started         →   —                           NodeStarted
    flow.node_completed       →   —                           NodeCompleted
    flow.node_failed          →   —                           NodeFailed
    flow.node_skipped         →   —                           NodeSkipped
    —                             dispatch.queued             DispatchQueued
    —                             dispatch.started            DispatchStarted
    —                             dispatch.message             DispatchDelta
    —                             dispatch.tool_use           DispatchToolUse
    —                             dispatch.tool_result        DispatchToolResult
    —                             dispatch.output_invalid     DispatchOutputInvalid
    —                             dispatch.failed             DispatchFailed
    —                             dispatch.completed          DispatchCompleted
    (new — HITL)                                              GateOpened / GateResolved
    (new — lifecycle)                                         RunCreated / RunCancelled / RunClosed

Host-side sequencing contract (AHP-compatible; the host itself —
``SessionHost`` — and the migration shims land in a second pass, TASK-1849):

* Every accepted action is wrapped in an ``ActionEnvelope`` with a per-channel
  monotonically increasing ``server_seq`` (AHP ``serverSeq``) plus optional
  multi-client ``origin`` attribution (``ActionOrigin``) and a
  ``rejection_reason`` slot.
* ``subscribe(channel)`` → ``Snapshot(state, from_seq)`` + subsequent envelopes.
* Reconnect: client sends ``last_seen_server_seq``; host replays envelopes
  ``> last_seen`` from the retained log (Redis Stream keeps being the log —
  it just stops being the *state*).

HITL arbitration contract (the mutex analogy):

* ``GateResolved`` is only valid while the gate is ``pending``. The host
  validates *before* sequencing: the first client to resolve wins; later
  attempts are rejected with ``GateAlreadyResolvedError`` and never become
  actions. Reducers therefore never see a conflicting resolve — reducers
  stay total and non-raising.

Root channel (``parrot-root://``): a lightweight run catalogue —
``RunRegistryState`` tracks one ``RunSummary`` per run_id, mutated by
``RunAdded`` / ``RunSummaryChanged`` / ``RunRemoved`` through ``reduce_root``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import (
    Annotated,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
)

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────────────
# Channel URIs — neutral scheme. Mirrors AHP's channel *model* without
# claiming wire compatibility; the parrot-* -> ahp-* (or A2A task-id)
# mapping is owned exclusively by the future wire adapter.
# ─────────────────────────────────────────────────────────────────────

ROOT_CHANNEL = "parrot-root://"


def session_channel(run_id: str) -> str:
    """Return the channel URI for a dev-loop run (AHP session channel).

    Args:
        run_id: The run identifier (e.g. ``run-<hex8>`` or ``rev-<hex8>``).

    Returns:
        The ``parrot-session:/<run_id>`` channel URI.
    """
    return f"parrot-session:/{run_id}"


def terminal_channel(run_id: str, node_id: str) -> str:
    """Return the channel URI for a dispatch pty/stream (AHP terminal channel).

    Args:
        run_id: The run identifier.
        node_id: The node hosting the dispatch (e.g. ``"development"``).

    Returns:
        The ``parrot-terminal:/<run_id>/<node_id>`` channel URI.
    """
    return f"parrot-terminal:/{run_id}/{node_id}"


def changeset_channel(run_id: str) -> str:
    """Return the channel URI for the run's diff/PR view (AHP changeset channel).

    Args:
        run_id: The run identifier.

    Returns:
        The ``parrot-changeset:/<run_id>`` channel URI.
    """
    return f"parrot-changeset:/{run_id}"


# ─────────────────────────────────────────────────────────────────────
# Frozen base — house style: closed, deterministic contracts
# ─────────────────────────────────────────────────────────────────────


class _Frozen(BaseModel):
    """Shared base for all session-state models: frozen and closed."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ─────────────────────────────────────────────────────────────────────
# State fragments (session channel)
# ─────────────────────────────────────────────────────────────────────

NodeId = Literal[
    "intent_classifier",
    "bug_intake",
    "research",
    "development",
    "qa",
    "deployment_handoff",
    "revision_handoff",
    "failure_handler",
    "close",
]

NodeStatus = Literal["idle", "running", "completed", "failed", "skipped"]

DispatchStatus = Literal[
    "queued", "running", "completed", "failed", "output_invalid"
]

RunPhase = Literal[
    "created",       # RunCreated accepted, flow not yet scheduled
    "running",       # at least one node running / more nodes pending
    "awaiting_gate", # blocked on a pending ApprovalGate (HITL)
    "succeeded",     # close reached via deployment/revision handoff
    "failed",        # failure_handler terminal
    "cancelled",     # RunCancelled accepted
]

GateKind = Literal[
    "manual_criterion",     # QA ManualCriterion instructions
    "deployment_approval",  # gate before Jira → "Ready to Deploy"
    "revision_approval",    # gate before pushing a revision to the PR
    "plan_approval",        # optional: approve ResearchOutput plan
]

GateStatus = Literal["pending", "approved", "rejected", "expired"]


class DispatchState(_Frozen):
    """Reduced view of one dispatcher execution inside a node.

    Heavy payloads (full SDK messages, tool outputs) do NOT live here —
    AHP's lazy-loading rule: large content is stored by reference and
    fetched separately. The terminal channel carries the raw stream; the
    session state only keeps display-ready counters and the last error.
    """

    status: DispatchStatus
    dispatcher: str = ""            # "claude-code", "codex", ...
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    message_count: int = 0
    tool_use_count: int = 0
    last_error: str = ""
    terminal: str = ""              # terminal channel URI (content by reference)


class NodeState(_Frozen):
    """Per-node projection of the flow graph."""

    node_id: NodeId
    status: NodeStatus = "idle"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: str = ""
    dispatch: Optional[DispatchState] = None
    # Small, display-ready result summary (e.g. QAReport.passed, PR URL).
    # Full Pydantic results stay in FlowContext; state holds the projection.
    summary: Dict[str, str] = Field(default_factory=dict)


class ApprovalGate(_Frozen):
    """A HITL gate: the run blocks until exactly one client resolves it.

    Deterministic contract: ``resolved_by``/``status`` are set at most once
    (host-validated). ``expires_at`` enables auto-expiry policies (e.g.
    escalate to ``escalation_assignee`` after N hours).
    """

    gate_id: str
    kind: GateKind
    node_id: NodeId                 # node that opened the gate
    status: GateStatus = "pending"
    on_expiry: Literal["fail", "approve"] = "fail"
    # "fail"    → fail-closed: expiry sweep emits GateExpired (→ escalation).
    #             Mandatory for gates guarding irreversible/external effects
    #             (deployment_approval, blocking manual_criterion,
    #             revision_approval): silence ≠ consent.
    # "approve" → fail-open: expiry sweep emits GateResolved by
    #             "system:ttl-auto-approve" (advisory gates: plan_approval).
    title: str = ""
    instructions: str = ""          # e.g. ManualCriterion.instructions
    payload_ref: str = ""           # changeset/terminal URI with evidence
    opened_at: float = 0.0
    expires_at: Optional[float] = None
    resolved_by: str = ""           # client/user identity — audit trail
    resolved_at: Optional[float] = None
    comment: str = ""


class DevLoopSessionState(_Frozen):
    """Authoritative, immutable state tree for one dev-loop run.

    This is what ``subscribe(session_channel(run_id))`` snapshots. All
    fields are cheap to serialise; everything heavy is by-reference.
    """

    run_id: str
    channel: str
    revision: bool = False          # initial graph vs revision graph
    phase: RunPhase = "created"
    created_at: float = 0.0
    finished_at: Optional[float] = None
    # Intake projection (from WorkBrief — not the full model).
    work_kind: Literal["bug", "enhancement", "new_feature", ""] = ""
    summary: str = ""
    jira_issue_key: str = ""
    pr_url: str = ""
    nodes: Dict[str, NodeState] = Field(default_factory=dict)
    gates: Dict[str, ApprovalGate] = Field(default_factory=dict)
    cancel_requested_by: str = ""
    error: str = ""


# ─────────────────────────────────────────────────────────────────────
# Actions (session channel) — the closed discriminated union
# ─────────────────────────────────────────────────────────────────────


class _ActionBase(_Frozen):
    """Shared base for session-channel actions: carries a timestamp."""

    ts: float = Field(default_factory=time.time)


# -- run lifecycle ----------------------------------------------------


class RunCreated(_ActionBase):
    type: Literal["run/created"] = "run/created"
    run_id: str
    revision: bool = False
    work_kind: Literal["bug", "enhancement", "new_feature"] = "bug"
    summary: str = ""


class RunCancelled(_ActionBase):
    type: Literal["run/cancelled"] = "run/cancelled"
    requested_by: str


class RunClosed(_ActionBase):
    type: Literal["run/closed"] = "run/closed"
    outcome: Literal["succeeded", "failed"]
    jira_issue_key: str = ""
    pr_url: str = ""


# -- flow node lifecycle (maps FlowEventPublisher) --------------------


class NodeStarted(_ActionBase):
    type: Literal["node/started"] = "node/started"
    node_id: NodeId


class NodeCompleted(_ActionBase):
    type: Literal["node/completed"] = "node/completed"
    node_id: NodeId
    summary: Dict[str, str] = Field(default_factory=dict)


class NodeFailed(_ActionBase):
    type: Literal["node/failed"] = "node/failed"
    node_id: NodeId
    error: str = ""


class NodeSkipped(_ActionBase):
    type: Literal["node/skipped"] = "node/skipped"
    node_id: NodeId


# -- dispatch lifecycle (maps DispatchEvent) --------------------------


class _DispatchAction(_ActionBase):
    node_id: NodeId


class DispatchQueued(_DispatchAction):
    type: Literal["dispatch/queued"] = "dispatch/queued"
    dispatcher: str = ""


class DispatchStarted(_DispatchAction):
    type: Literal["dispatch/started"] = "dispatch/started"
    terminal: str = ""              # terminal channel URI


class DispatchDelta(_DispatchAction):
    """One SDK message arrived. Content lives on the terminal channel;
    the session state only bumps the counter (lazy loading)."""

    type: Literal["dispatch/delta"] = "dispatch/delta"


class DispatchToolUse(_DispatchAction):
    type: Literal["dispatch/tool_use"] = "dispatch/tool_use"
    tool_name: str = ""


class DispatchToolResult(_DispatchAction):
    type: Literal["dispatch/tool_result"] = "dispatch/tool_result"


class DispatchOutputInvalid(_DispatchAction):
    type: Literal["dispatch/output_invalid"] = "dispatch/output_invalid"
    error: str = ""


class DispatchFailed(_DispatchAction):
    type: Literal["dispatch/failed"] = "dispatch/failed"
    error: str = ""


class DispatchCompleted(_DispatchAction):
    type: Literal["dispatch/completed"] = "dispatch/completed"


# -- HITL gates (new capability) --------------------------------------


class GateOpened(_ActionBase):
    type: Literal["gate/opened"] = "gate/opened"
    gate: ApprovalGate              # status MUST be "pending"


class GateResolved(_ActionBase):
    """Host-arbitrated: sequenced only if the gate is still pending."""

    type: Literal["gate/resolved"] = "gate/resolved"
    gate_id: str
    resolution: Literal["approved", "rejected"]
    resolved_by: str
    comment: str = ""


class GateExpired(_ActionBase):
    type: Literal["gate/expired"] = "gate/expired"
    gate_id: str


# -- projections from node results ------------------------------------


class JiraLinked(_ActionBase):
    type: Literal["run/jiraLinked"] = "run/jiraLinked"
    issue_key: str


class PullRequestLinked(_ActionBase):
    type: Literal["run/prLinked"] = "run/prLinked"
    pr_url: str
    changeset: str = ""             # changeset channel URI


DevLoopAction = Annotated[
    Union[
        RunCreated, RunCancelled, RunClosed,
        NodeStarted, NodeCompleted, NodeFailed, NodeSkipped,
        DispatchQueued, DispatchStarted, DispatchDelta,
        DispatchToolUse, DispatchToolResult,
        DispatchOutputInvalid, DispatchFailed, DispatchCompleted,
        GateOpened, GateResolved, GateExpired,
        JiraLinked, PullRequestLinked,
    ],
    Field(discriminator="type"),
]


# ─────────────────────────────────────────────────────────────────────
# Envelope & snapshot (AHP-aligned; extends the design sketch with
# multi-client attribution — spec §2)
# ─────────────────────────────────────────────────────────────────────


class ActionOrigin(_Frozen):
    """Multi-client attribution for an accepted action (AHP common type)."""

    client_id: str
    client_seq: int


class ActionEnvelope(_Frozen):
    """Wire-agnostic envelope — mirrors AHP's ActionEnvelope."""

    channel: str
    server_seq: int
    action: DevLoopAction
    origin: Optional[ActionOrigin] = None
    rejection_reason: str = ""


class Snapshot(_Frozen):
    """``subscribe()`` result — state + the seq it corresponds to."""

    channel: str
    state: DevLoopSessionState
    from_seq: int


# ─────────────────────────────────────────────────────────────────────
# Root channel (``parrot-root://``) — run catalogue (spec §2, proposal U2)
# ─────────────────────────────────────────────────────────────────────


class RunSummary(_Frozen):
    """Small, display-ready projection of a run for the root catalogue."""

    run_id: str
    phase: RunPhase
    work_kind: str = ""
    summary: str = ""
    jira_issue_key: str = ""
    pr_url: str = ""
    pending_gate_count: int = 0
    created_at: float = 0.0
    finished_at: Optional[float] = None


class RunRegistryState(_Frozen):
    """Authoritative state tree for the root channel (run catalogue)."""

    channel: str = ROOT_CHANNEL
    runs: Dict[str, RunSummary] = Field(default_factory=dict)


class _RootActionBase(_Frozen):
    """Shared base for root-channel actions: carries a timestamp."""

    ts: float = Field(default_factory=time.time)


class RunAdded(_RootActionBase):
    type: Literal["root/runAdded"] = "root/runAdded"
    summary: RunSummary


class RunSummaryChanged(_RootActionBase):
    type: Literal["root/runSummaryChanged"] = "root/runSummaryChanged"
    summary: RunSummary


class RunRemoved(_RootActionBase):
    type: Literal["root/runRemoved"] = "root/runRemoved"
    run_id: str


RootAction = Annotated[
    Union[RunAdded, RunSummaryChanged, RunRemoved],
    Field(discriminator="type"),
]


# ─────────────────────────────────────────────────────────────────────
# Exceptions — HITL gate arbitration (raised by SessionHost, TASK-1849)
# ─────────────────────────────────────────────────────────────────────


class GateNotFoundError(KeyError):
    """Raised when a command targets a ``gate_id`` that does not exist."""


class GateAlreadyResolvedError(RuntimeError):
    """Second (and later) resolve attempts on a gate — first one won.

    Carries the resolver identity/status in the exception message so
    callers can surface a 409-style conflict with resolver attribution.
    """


# ─────────────────────────────────────────────────────────────────────
# Reducers — pure, total, non-raising
# ─────────────────────────────────────────────────────────────────────

_TERMINAL_PHASES: frozenset = frozenset({"succeeded", "failed", "cancelled"})


def _with_node(
    state: DevLoopSessionState, node_id: str, **changes
) -> DevLoopSessionState:
    """Return ``state`` with ``node_id``'s :class:`NodeState` updated.

    Creates the node projection on first touch (default ``idle`` state)
    so events can arrive in any order without raising.
    """
    node = state.nodes.get(node_id, NodeState(node_id=node_id))  # type: ignore[arg-type]
    nodes = {**state.nodes, node_id: node.model_copy(update=changes)}
    return state.model_copy(update={"nodes": nodes})


def _with_dispatch(
    state: DevLoopSessionState, node_id: str, **changes
) -> DevLoopSessionState:
    """Return ``state`` with ``node_id``'s :class:`DispatchState` updated."""
    node = state.nodes.get(node_id, NodeState(node_id=node_id))  # type: ignore[arg-type]
    dispatch = node.dispatch or DispatchState(status="queued")
    node = node.model_copy(update={"dispatch": dispatch.model_copy(update=changes)})
    return state.model_copy(update={"nodes": {**state.nodes, node_id: node}})


def _recompute_phase(state: DevLoopSessionState) -> DevLoopSessionState:
    """Derive ``phase`` after gate transitions. Terminal phases are sticky."""
    if state.phase in _TERMINAL_PHASES:
        return state
    pending = any(g.status == "pending" for g in state.gates.values())
    phase: RunPhase = "awaiting_gate" if pending else "running"
    return state.model_copy(update={"phase": phase})


def reduce(  # noqa: C901 — a flat, exhaustive match is the point
    state: DevLoopSessionState, action: DevLoopAction
) -> DevLoopSessionState:
    """Pure reducer: ``(state, action) -> new_state``.

    Total over the action union; unknown/late actions against terminal
    states degrade to no-ops rather than raising (host validation is the
    layer that rejects — the reducer only folds).

    Args:
        state: The current session state.
        action: The action to fold.

    Returns:
        The new session state. ``fold(log) == state`` is the invariant
        this function must uphold under any action sequence.
    """
    t = action.type

    # -- run lifecycle
    if t == "run/created":
        # Terminal-sticky (FEAT-322 TASK-1850): a late/duplicate run/created
        # replayed against an already-terminal state must not resurrect the
        # phase — mirrors the guard already on run/cancelled below.
        if state.phase in _TERMINAL_PHASES:
            return state
        return state.model_copy(update={
            "phase": "running",
            "created_at": action.ts,
            "revision": action.revision,
            "work_kind": action.work_kind,
            "summary": action.summary,
        })
    if t == "run/cancelled":
        if state.phase in _TERMINAL_PHASES:
            return state
        return state.model_copy(update={
            "phase": "cancelled",
            "cancel_requested_by": action.requested_by,
            "finished_at": action.ts,
        })
    if t == "run/closed":
        # Terminal-sticky (FEAT-322 TASK-1850): a late/duplicate run/closed
        # against an already-terminal state must not flip the phase again
        # (e.g. failed -> succeeded) — same guard as run/created/cancelled.
        if state.phase in _TERMINAL_PHASES:
            return state
        return state.model_copy(update={
            "phase": action.outcome,
            "finished_at": action.ts,
            "jira_issue_key": action.jira_issue_key or state.jira_issue_key,
            "pr_url": action.pr_url or state.pr_url,
        })

    # -- node lifecycle
    if t == "node/started":
        return _with_node(state, action.node_id,
                          status="running", started_at=action.ts, error="")
    if t == "node/completed":
        return _with_node(state, action.node_id,
                          status="completed", finished_at=action.ts,
                          summary=action.summary)
    if t == "node/failed":
        new = _with_node(state, action.node_id,
                         status="failed", finished_at=action.ts,
                         error=action.error)
        return new.model_copy(update={"error": action.error})
    if t == "node/skipped":
        return _with_node(state, action.node_id, status="skipped")

    # -- dispatch lifecycle
    if t == "dispatch/queued":
        return _with_dispatch(state, action.node_id,
                              status="queued", dispatcher=action.dispatcher)
    if t == "dispatch/started":
        return _with_dispatch(state, action.node_id,
                              status="running", started_at=action.ts,
                              terminal=action.terminal)
    if t == "dispatch/delta":
        node = state.nodes.get(action.node_id)
        count = node.dispatch.message_count if node and node.dispatch else 0
        return _with_dispatch(state, action.node_id, message_count=count + 1)
    if t == "dispatch/tool_use":
        node = state.nodes.get(action.node_id)
        count = node.dispatch.tool_use_count if node and node.dispatch else 0
        return _with_dispatch(state, action.node_id, tool_use_count=count + 1)
    if t == "dispatch/tool_result":
        return state  # counters only on tool_use; result content is by-ref
    if t == "dispatch/output_invalid":
        return _with_dispatch(state, action.node_id,
                              status="output_invalid", last_error=action.error)
    if t == "dispatch/failed":
        return _with_dispatch(state, action.node_id,
                              status="failed", finished_at=action.ts,
                              last_error=action.error)
    if t == "dispatch/completed":
        return _with_dispatch(state, action.node_id,
                              status="completed", finished_at=action.ts)

    # -- gates (HITL)
    if t == "gate/opened":
        gates = {**state.gates, action.gate.gate_id: action.gate}
        return _recompute_phase(state.model_copy(update={"gates": gates}))
    if t == "gate/resolved":
        gate = state.gates.get(action.gate_id)
        if gate is None or gate.status != "pending":
            return state  # host should have rejected; reducer stays total
        gate = gate.model_copy(update={
            "status": action.resolution,
            "resolved_by": action.resolved_by,
            "resolved_at": action.ts,
            "comment": action.comment,
        })
        gates = {**state.gates, gate.gate_id: gate}
        return _recompute_phase(state.model_copy(update={"gates": gates}))
    if t == "gate/expired":
        gate = state.gates.get(action.gate_id)
        if gate is None or gate.status != "pending":
            return state
        gates = {**state.gates,
                 gate.gate_id: gate.model_copy(update={"status": "expired"})}
        return _recompute_phase(state.model_copy(update={"gates": gates}))

    # -- projections
    if t == "run/jiraLinked":
        return state.model_copy(update={"jira_issue_key": action.issue_key})
    if t == "run/prLinked":
        return state.model_copy(update={"pr_url": action.pr_url})

    return state  # forward-compat: unknown action → no-op


def reduce_root(state: RunRegistryState, action: RootAction) -> RunRegistryState:
    """Pure reducer for the root channel (run catalogue).

    Total and non-raising, mirroring :func:`reduce`: an unknown/late
    ``root/runRemoved`` for a run_id not in ``state.runs`` is a no-op.

    Args:
        state: The current run-registry state.
        action: The root action to fold.

    Returns:
        The new run-registry state.
    """
    t = action.type

    if t == "root/runAdded" or t == "root/runSummaryChanged":
        runs = {**state.runs, action.summary.run_id: action.summary}
        return state.model_copy(update={"runs": runs})
    if t == "root/runRemoved":
        if action.run_id not in state.runs:
            return state  # unknown run removal = no-op
        runs = {k: v for k, v in state.runs.items() if k != action.run_id}
        return state.model_copy(update={"runs": runs})

    return state  # forward-compat: unknown action → no-op


# ─────────────────────────────────────────────────────────────────────
# Host-side sequencing + gate arbitration (the AHP "mutex")
# ─────────────────────────────────────────────────────────────────────


class SessionHost:
    """Minimal authoritative host for one session channel.

    Responsibilities (per AHP): hold the state tree, validate commands,
    sequence accepted actions with ``server_seq``, retain the envelope log
    for replay, and let gate-opening nodes ``await`` a gate's resolution.
    Transport (WS/REST) and persistence (Redis XADD of the envelope) plug
    in via ``on_envelope`` — this class stays pure-ish and NEVER imports
    redis/aiohttp itself.

    NOT thread-safe by design: one host per run, driven from the runner's
    event loop (single-writer). Multi-client writes arrive as commands and
    are serialised here — that's the whole point.
    """

    def __init__(
        self,
        run_id: str,
        *,
        on_envelope: Optional[Callable[[ActionEnvelope], None]] = None,
    ) -> None:
        """Initialize a fresh host for ``run_id``.

        Args:
            run_id: The run this host is authoritative for.
            on_envelope: Optional sink invoked with every accepted
                :class:`ActionEnvelope` (e.g. XADD to
                ``flow:{run_id}:actions``). Exceptions raised by the sink
                are swallowed — the new-path publish must never break a
                run.
        """
        self._state = DevLoopSessionState(
            run_id=run_id, channel=session_channel(run_id)
        )
        self._seq = 0
        self._log: List[ActionEnvelope] = []
        self._on_envelope = on_envelope
        self._gate_events: Dict[str, asyncio.Event] = {}

    # -- read side ----------------------------------------------------

    @property
    def state(self) -> DevLoopSessionState:
        """The current, authoritative session state."""
        return self._state

    def snapshot(self) -> Snapshot:
        """Return a :class:`Snapshot` of the current state and seq."""
        return Snapshot(channel=self._state.channel,
                        state=self._state, from_seq=self._seq)

    def replay_since(self, last_seen_server_seq: int) -> List[ActionEnvelope]:
        """Return all envelopes with ``server_seq > last_seen_server_seq``."""
        return [e for e in self._log if e.server_seq > last_seen_server_seq]

    # -- write side ---------------------------------------------------

    def apply(
        self,
        action: DevLoopAction,
        origin: Optional[ActionOrigin] = None,
    ) -> ActionEnvelope:
        """Sequence + fold one action. Trusted-producer path (the flow).

        Args:
            action: The action to sequence and fold.
            origin: Optional multi-client attribution for this action.

        Returns:
            The sequenced :class:`ActionEnvelope`.
        """
        self._seq += 1
        envelope = ActionEnvelope(
            channel=self._state.channel, server_seq=self._seq, action=action,
            origin=origin,
        )
        self._state = reduce(self._state, action)
        self._log.append(envelope)
        self._signal_gate_waiters(action)
        if self._on_envelope is not None:
            try:
                self._on_envelope(envelope)
            except Exception:  # noqa: BLE001 — never break a run
                pass
        return envelope

    def _signal_gate_waiters(self, action: DevLoopAction) -> None:
        """Wake any ``wait_gate`` coroutine when a gate reaches a final state."""
        if action.type in ("gate/resolved", "gate/expired"):
            event = self._gate_events.get(action.gate_id)
            if event is not None:
                event.set()

    def resolve_gate(
        self,
        gate_id: str,
        resolution: Literal["approved", "rejected"],
        resolved_by: str,
        comment: str = "",
    ) -> ActionEnvelope:
        """Client command path — validated BEFORE sequencing.

        First writer wins; later attempts raise and never become actions.
        This is the arbitration AHP describes for tool-call confirmation,
        applied to deployment/QA gates.

        Args:
            gate_id: The gate to resolve.
            resolution: ``"approved"`` or ``"rejected"``.
            resolved_by: Identity of the resolving client/user.
            comment: Optional free-text audit comment.

        Returns:
            The sequenced :class:`ActionEnvelope` for the resolution.

        Raises:
            GateNotFoundError: ``gate_id`` does not exist.
            GateAlreadyResolvedError: the gate is no longer ``"pending"``.
        """
        gate = self._state.gates.get(gate_id)
        if gate is None:
            raise GateNotFoundError(gate_id)
        if gate.status != "pending":
            raise GateAlreadyResolvedError(
                f"gate {gate_id} already {gate.status} "
                f"by {gate.resolved_by or 'system'}"
            )
        return self.apply(GateResolved(
            gate_id=gate_id, resolution=resolution,
            resolved_by=resolved_by, comment=comment,
        ))

    def open_gate(
        self,
        *,
        kind: GateKind,
        node_id: NodeId,
        title: str,
        instructions: str = "",
        payload_ref: str = "",
        ttl_seconds: Optional[int] = None,
        on_expiry: Literal["fail", "approve"] = "fail",
    ) -> Tuple[str, ActionEnvelope]:
        """Open a new gate (convenience for QA/DeploymentHandoff nodes).

        Args:
            kind: The gate kind (``manual_criterion``, ``deployment_approval``,
                ``revision_approval``, ``plan_approval``).
            node_id: The node opening the gate.
            title: Short human-readable title.
            instructions: Longer instructions/context for the approver.
            payload_ref: Changeset/terminal URI carrying supporting evidence.
            ttl_seconds: Optional per-gate TTL override.
            on_expiry: ``"fail"`` (fail-closed) or ``"approve"`` (fail-open).

        Returns:
            A ``(gate_id, envelope)`` tuple.
        """
        now = time.time()
        gate = ApprovalGate(
            gate_id=uuid.uuid4().hex,
            kind=kind, node_id=node_id, title=title,
            instructions=instructions, payload_ref=payload_ref,
            opened_at=now,
            expires_at=(now + ttl_seconds) if ttl_seconds else None,
            on_expiry=on_expiry,
        )
        return gate.gate_id, self.apply(GateOpened(gate=gate))

    def expire_due_gates(self, now: Optional[float] = None
                         ) -> List[ActionEnvelope]:
        """Expiry sweep — call periodically from the runner's loop.

        For each pending gate past its ``expires_at``, applies the gate's
        ``on_expiry`` policy: ``"fail"`` → ``GateExpired`` (fail-closed;
        the flow routes to failure/escalation); ``"approve"`` →
        ``GateResolved`` by ``system:ttl-auto-approve`` (fail-open; audited
        in-state exactly like a human resolution). Reducer stays untouched.

        Args:
            now: Optional override for the current time (testing).

        Returns:
            The list of envelopes emitted by this sweep pass.
        """
        now = time.time() if now is None else now
        out: List[ActionEnvelope] = []
        for gate in list(self._state.gates.values()):
            if gate.status != "pending" or gate.expires_at is None:
                continue
            if now < gate.expires_at:
                continue
            if gate.on_expiry == "approve":
                out.append(self.apply(GateResolved(
                    gate_id=gate.gate_id, resolution="approved",
                    resolved_by="system:ttl-auto-approve",
                    comment="TTL expired; fail-open policy.",
                )))
            else:
                out.append(self.apply(GateExpired(gate_id=gate.gate_id)))
        return out

    async def wait_gate(self, gate_id: str) -> ApprovalGate:
        """Await a gate's resolution (approved/rejected/expired).

        Works regardless of ordering: if the gate is already resolved when
        called, returns immediately; otherwise awaits the internal
        ``asyncio.Event`` set by :meth:`apply` when a matching
        ``gate/resolved``/``gate/expired`` action folds.

        Args:
            gate_id: The gate to wait on.

        Returns:
            The final :class:`ApprovalGate` (status != ``"pending"``).

        Raises:
            GateNotFoundError: ``gate_id`` does not exist in state.
        """
        gate = self._state.gates.get(gate_id)
        if gate is None:
            raise GateNotFoundError(gate_id)
        if gate.status != "pending":
            return gate
        event = self._gate_events.setdefault(gate_id, asyncio.Event())
        await event.wait()
        self._gate_events.pop(gate_id, None)
        return self._state.gates[gate_id]


# ─────────────────────────────────────────────────────────────────────
# Adapters from the current ad-hoc events (migration shims, Fase 1)
# ─────────────────────────────────────────────────────────────────────

_FLOW_EVENT_MAP: Dict[str, str] = {
    "node_started": "node/started",
    "node_completed": "node/completed",
    "node_failed": "node/failed",
    "node_skipped": "node/skipped",
}

_DISPATCH_KIND_MAP: Dict[str, type] = {
    "dispatch.queued": DispatchQueued,
    "dispatch.started": DispatchStarted,
    "dispatch.message": DispatchDelta,
    "dispatch.tool_use": DispatchToolUse,
    "dispatch.tool_result": DispatchToolResult,
    "dispatch.output_invalid": DispatchOutputInvalid,
    "dispatch.failed": DispatchFailed,
    "dispatch.completed": DispatchCompleted,
}


def action_from_flow_event(event: str, node_id: str, ts: float,
                           error: str = "") -> Optional[DevLoopAction]:
    """Map a ``FlowEventPublisher`` event to a :data:`DevLoopAction`.

    Args:
        event: The flow event name (e.g. ``"node_started"``, unprefixed —
            callers strip the ``"flow."`` prefix before calling this shim).
        node_id: The node the event concerns.
        ts: Event timestamp (POSIX seconds).
        error: Optional error string (only used for ``node_failed``).

    Returns:
        The mapped action, or ``None`` if ``event`` is not recognised
        (forward-compat: unknown events are ignored, never raise).
    """
    mapped = _FLOW_EVENT_MAP.get(event)
    if mapped is None:
        return None
    if mapped == "node/started":
        return NodeStarted(node_id=node_id, ts=ts)  # type: ignore[arg-type]
    if mapped == "node/completed":
        return NodeCompleted(node_id=node_id, ts=ts)  # type: ignore[arg-type]
    if mapped == "node/failed":
        return NodeFailed(node_id=node_id, ts=ts, error=error[:500])  # type: ignore[arg-type]
    return NodeSkipped(node_id=node_id, ts=ts)  # type: ignore[arg-type]


def action_from_dispatch_event(kind: str, node_id: str, ts: float,
                               payload: Optional[dict] = None
                               ) -> Optional[DevLoopAction]:
    """Map a ``DispatchEvent.kind`` to a :data:`DevLoopAction`.

    Args:
        kind: The dispatch event kind (e.g. ``"dispatch.queued"``).
        node_id: The node hosting the dispatch.
        ts: Event timestamp (POSIX seconds).
        payload: Optional raw payload dict; only display-ready fields are
            extracted (lazy-loading rule — heavy content stays by-reference).

    Returns:
        The mapped action, or ``None`` if ``kind`` is not recognised.
    """
    cls = _DISPATCH_KIND_MAP.get(kind)
    if cls is None:
        return None
    payload = payload or {}
    kwargs: dict = {"node_id": node_id, "ts": ts}
    if cls in (DispatchOutputInvalid, DispatchFailed):
        kwargs["error"] = str(payload.get("error", ""))[:500]
    if cls is DispatchToolUse:
        kwargs["tool_name"] = str(payload.get("tool_name", ""))
    if cls is DispatchQueued:
        kwargs["dispatcher"] = str(payload.get("dispatcher", ""))
    return cls(**kwargs)  # type: ignore[return-value]


__all__ = [
    "ActionEnvelope",
    "ActionOrigin",
    "ApprovalGate",
    "DevLoopAction",
    "DevLoopSessionState",
    "DispatchCompleted",
    "DispatchDelta",
    "DispatchFailed",
    "DispatchOutputInvalid",
    "DispatchQueued",
    "DispatchStarted",
    "DispatchState",
    "DispatchStatus",
    "DispatchToolResult",
    "DispatchToolUse",
    "GateAlreadyResolvedError",
    "GateExpired",
    "GateKind",
    "GateNotFoundError",
    "GateOpened",
    "GateResolved",
    "GateStatus",
    "JiraLinked",
    "NodeCompleted",
    "NodeFailed",
    "NodeId",
    "NodeSkipped",
    "NodeStarted",
    "NodeState",
    "NodeStatus",
    "PullRequestLinked",
    "ROOT_CHANNEL",
    "RootAction",
    "RunAdded",
    "RunCancelled",
    "RunCreated",
    "RunClosed",
    "RunPhase",
    "RunRegistryState",
    "RunRemoved",
    "RunSummary",
    "RunSummaryChanged",
    "SessionHost",
    "Snapshot",
    "action_from_dispatch_event",
    "action_from_flow_event",
    "changeset_channel",
    "reduce",
    "reduce_root",
    "session_channel",
    "terminal_channel",
]
