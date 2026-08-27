"""DevLoopRunner — orchestrator-side hosting for the dev-loop flow.

Closes spec G5's orchestrator half: the dispatcher already caps
concurrent Claude Code dispatches (``CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES``);
this runner caps concurrent *flow runs* with an ``asyncio.Semaphore``
sized by ``FLOW_MAX_CONCURRENT_RUNS``.

Responsibilities:

- mint (or accept) the ``run_id`` and seed the :class:`FlowContext`
  (``shared_data['bug_brief']`` / ``['work_brief']`` / ``['run_id']``);
- bind the run_id to the flow's :class:`FlowEventPublisher` so
  node-lifecycle events land on ``flow:{run_id}:flow``;
- track active runs (``active_runs`` / ``is_active``);
- **AHP-style host (FEAT-322)**: own one :class:`SessionHost` per run
  (registry keyed by ``run_id``, never a captured reference — one
  ``AgentsFlow`` serves concurrent runs), the root-channel run catalogue
  (:class:`RunRegistryState`), a periodic gate-expiry sweep, and the
  command methods (:meth:`resolve_gate`, :meth:`cancel_run`) the REST
  layer (TASK-1855) adapts.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Union

from navconfig.logging import logging

from parrot import conf
from parrot.bots.flows import AgentsFlow
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import FlowResult
from parrot.flows.dev_loop.definition import build_dev_loop_definition
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.flow import (
    FlowEventPublisher,
    _NullAgentRegistry,
    _feedback_accept,
    _feedback_escalate,
    _feedback_retry,
    _is_feature,
    _qa_failed,
    _qa_passed,
)
from parrot.flows.dev_loop.models import (
    FeatureBrief,
    ResearchOutput,
    RevisionBrief,
    ShellCriterion,
    WorkBrief,
)
from parrot.flows.dev_loop.run_bundle import build_run_bundle, render_markdown
from parrot.flows.dev_loop.usage_report import (
    build_usage_report,
    render_usage_html,
    render_usage_markdown,
)
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    ActionOrigin,
    GateKind,
    RunAdded,
    RunCancelled,
    RunClosed,
    RunCreated,
    RunParked,
    RunRegistryState,
    RunRemoved,
    RunResumed,
    RunSummary,
    RunSummaryChanged,
    SessionHost,
    reduce_root,
)

# ---------------------------------------------------------------------------
# Gate TTL policy (FEAT-322 §2, §8) — conf-overridable per kind, seconds.
# ---------------------------------------------------------------------------

_GATE_TTL_CONF_ATTR: Dict[GateKind, str] = {
    "deployment_approval": "DEV_LOOP_GATE_TTL_DEPLOYMENT",
    "manual_criterion": "DEV_LOOP_GATE_TTL_MANUAL",
    "revision_approval": "DEV_LOOP_GATE_TTL_REVISION",
    "plan_approval": "DEV_LOOP_GATE_TTL_PLAN",
    "review_escalation": "DEV_LOOP_GATE_TTL_REVIEW_ESCALATION",
    # FEAT-412 dev-flow: ideation Open-Questions round (fail-closed).
    "open_questions": "DEV_FLOW_GATE_TTL_QUESTIONS",
}


def gate_ttl_for(kind: GateKind) -> int:
    """Return the conf-configured TTL (seconds) for a gate ``kind``.

    Conf stays out of the transport-free ``session_state`` module — this
    helper is the single place gate-opening nodes and the runner read the
    per-kind default from. Callers may still override per-gate via
    ``SessionHost.open_gate(ttl_seconds=...)``.

    Args:
        kind: The gate kind.

    Returns:
        The TTL in seconds (``conf.DEV_LOOP_GATE_TTL_*``).
    """
    attr = _GATE_TTL_CONF_ATTR[kind]
    return int(getattr(conf, attr))


# Actions-stream expiry/retention sweep cadence (seconds).
_SWEEP_INTERVAL_SECONDS = 30

# Terminal node ids whose status dict may signal a non-success close
# (FEAT-413). These nodes never raise on failure by design — they return
# a status dict instead — so `_close_host` must scan their responses
# explicitly rather than rely on `FlowResult.status`/`AgentsFlow`'s
# completed/failed bookkeeping, which only reflects whether a node raised.
_TERMINAL_NODE_IDS = (
    "deployment_handoff", "feature_handoff", "revision_handoff", "failure_handler",
)
_FAILED_TERMINAL_STATUSES = frozenset({
    "blocked",                    # all three handoff nodes: nothing delivered
    "escalated",                  # failure_handler: QA failed, run escalated
    "escalated_without_ticket",   # failure_handler, no Jira / skip_jira
    "escalation_failed",          # failure_handler, Jira call raised
})


def build_dev_loop_revision_flow(
    *,
    dispatcher: Any,
    jira_toolkit: Any,
    git_toolkit: Any,
    redis_url: str,
    codereview_dispatcher: Optional[Any] = None,
    graph_memory: Optional[Any] = None,
    name: str = "dev-loop-revision",
    publish_flow_events: bool = True,
) -> AgentsFlow:
    """Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).

    Mirrors ``build_dev_loop_flow``'s declarative-materialize-then-explicit
    execution: the nodes come from ``build_dev_loop_definition(revision=True)``
    via the node factories, and the graph runs in explicit-edge mode (OR-join
    on the ``failure_handler`` fan-in). Topology: ``development → qa →
    (pass) revision_handoff → close`` / ``(fail) failure_handler``.

    Args:
        graph_memory: FEAT-377 TASK-1915 — optional ``DevLoopGraphMemory``
            forwarded to ``QANode``/``DevLoopCloseNode``/
            ``FailureHandlerNode`` (this graph has no ``research`` node,
            so seam 2 does not apply here). ``None`` (default) is a no-op.
    """
    definition = build_dev_loop_definition(revision=True)
    factories = build_dev_loop_node_factories(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        redis_url=redis_url,
        git_toolkit=git_toolkit,
        codereview_dispatcher=codereview_dispatcher,
        graph_memory=graph_memory,
    )
    staged = AgentsFlow.from_definition(
        definition,
        agent_registry=_NullAgentRegistry(),
        node_factories=factories,
    )
    nodes = staged._materialize_nodes()

    run_id_holder: Dict[str, str] = {}
    publisher = (
        FlowEventPublisher(redis_url, run_id_holder) if publish_flow_events else None
    )
    flow = AgentsFlow(name=name, on_node_event=publisher)
    flow._run_id_holder = run_id_holder  # type: ignore[attr-defined]
    flow._event_publisher = publisher  # type: ignore[attr-defined]
    flow._dev_loop_definition = definition  # type: ignore[attr-defined]

    for node in nodes.values():
        flow.add_node(node)

    flow.add_edge("development", "qa")
    flow.add_edge("qa", "revision_handoff", predicate=_qa_passed)
    flow.add_edge("qa", "failure_handler", predicate=_qa_failed)
    flow.add_edge("revision_handoff", "close")
    for source in ("development", "qa", "revision_handoff"):
        flow.add_edge(source, "failure_handler", condition="on_error")

    return flow


def build_dev_loop_feature_flow(
    *,
    dispatcher: Any,
    jira_toolkit: Optional[Any] = None,
    git_toolkit: Optional[Any] = None,
    wiki_toolkit: Optional[Any] = None,
    redis_url: str,
    codereview_dispatcher: Optional[Any] = None,
    development_dispatcher_builder: Optional[Any] = None,
    development_pool_max: int = 4,
    graph_memory: Optional[Any] = None,
    require_plan_approval: bool = False,
    skip_qa: bool = False,
    name: str = "dev-loop-feature",
    publish_flow_events: bool = True,
) -> AgentsFlow:
    """Build the feature-mode ``AgentsFlow`` (FEAT-378).

    Mirrors ``build_dev_loop_flow``'s declarative-materialize-then-explicit
    execution pattern (precedent: ``build_dev_loop_revision_flow`` above):
    the nodes come from ``build_dev_loop_definition(feature=True)`` via the
    node factories, and the graph runs in the engine's explicit-edge mode
    (OR-join on the ``feature_handoff``/``failure_handler`` fan-ins — see
    ``definition.py``'s ``_build_feature_definition`` docstring).

    Topology: ``intent_classifier`` -(kind=="feature")-> ``planner`` ->
    ``development`` -> ``synthesis`` -> ``qa`` -(passed)-> ``feature_handoff``
    -> ``close`` / -(failed)-> ``feedback_router`` -(escalate)->
    ``failure_handler`` / -(accept_with_notes)-> ``feature_handoff`` /
    -(retry)-> ``development`` (bounded repair loop, FEAT-377/A — the
    stop rule lives in ``FeedbackRouterNode._retry_allowed()``, not on
    this edge; see ``flow._feedback_retry``'s docstring).

    Args:
        dispatcher: Shared ``ClaudeCodeDispatcher`` for Planner/Synthesis/
            QA/FeedbackRouter.
        jira_toolkit: Optional service-account ``JiraToolkit`` — feature-mode
            Jira is link-only; ``None`` means zero Jira calls anywhere.
        git_toolkit: Optional ``GitToolkit`` (parity with the bug/revision
            flows — currently unused by the bare HTTP PR fallback).
        wiki_toolkit: Optional pre-wired ``LLMWikiToolkit`` for
            ``FeatureHandoffNode``'s docs-page ingest.
        redis_url: Redis URL for intake/flow-lifecycle events.
        codereview_dispatcher: Optional ``AbstractCodeReviewDispatcher`` for
            ``QANode`` (typically a ``JudgePanelReviewDispatcher``, TASK-1920).
        development_dispatcher_builder: Optional ``(DevAgentSpec) ->
            (dispatcher, profile)`` callable (FEAT-323) for ``DevelopmentNode``
            pool-worker materialization.
        development_pool_max: Hard cap on total pool workers (FEAT-323),
            also passed to ``PlannerNode`` for its own pool-sizing cap.
        graph_memory: FEAT-377 TASK-1914/1915 (G2) — an optional
            ``DevLoopGraphMemory`` (from ``DevLoopGraphMemory.
            from_config()``) forwarded to ``QANode``, ``DevLoopCloseNode``
            and ``FailureHandlerNode`` via ``build_dev_loop_node_factories``
            (feature-mode has no ``ResearchNode``, so seam 2 — research
            context injection — does not apply here). ``None`` (default)
            makes every graph-memory seam a strict no-op, same as
            bug/revision mode.
        require_plan_approval: FEAT-377 TASK-1916 (G5) — forwarded to
            ``DevelopmentNode`` via ``build_dev_loop_node_factories``.
            ``False`` (default) preserves current behavior exactly; set
            ``True`` to require a ``plan_approval`` HITL gate before the
            agent fleet dispatches — arguably even more apt in feature
            mode, since ``PlannerNode`` produces the very plan being
            approved.
        name: Flow name (default ``"dev-loop-feature"``).
        publish_flow_events: When True (default), attach a
            :class:`FlowEventPublisher` to the engine's ``on_node_event`` hook.

    Returns:
        A wired :class:`AgentsFlow` instance ready to ``run_flow()``.
    """
    definition = build_dev_loop_definition(feature=True)
    factories = build_dev_loop_node_factories(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        redis_url=redis_url,
        git_toolkit=git_toolkit,
        wiki_toolkit=wiki_toolkit,
        development_dispatcher_builder=development_dispatcher_builder,
        development_pool_max=development_pool_max,
        codereview_dispatcher=codereview_dispatcher,
        graph_memory=graph_memory,
        require_plan_approval=require_plan_approval,
        skip_qa=skip_qa,
    )
    staged = AgentsFlow.from_definition(
        definition,
        agent_registry=_NullAgentRegistry(),
        node_factories=factories,
    )
    nodes = staged._materialize_nodes()

    run_id_holder: Dict[str, str] = {}
    publisher = (
        FlowEventPublisher(redis_url, run_id_holder) if publish_flow_events else None
    )
    flow = AgentsFlow(name=name, on_node_event=publisher)
    flow._run_id_holder = run_id_holder  # type: ignore[attr-defined]
    flow._event_publisher = publisher  # type: ignore[attr-defined]
    flow._dev_loop_definition = definition  # type: ignore[attr-defined]

    for node in nodes.values():
        flow.add_node(node)

    flow.add_edge("intent_classifier", "planner", predicate=_is_feature)
    flow.add_edge("planner", "development")
    flow.add_edge("development", "synthesis")
    flow.add_edge("synthesis", "qa")
    flow.add_edge("qa", "feature_handoff", predicate=_qa_passed)
    flow.add_edge("qa", "feedback_router", predicate=_qa_failed)
    flow.add_edge("feedback_router", "failure_handler", predicate=_feedback_escalate)
    flow.add_edge("feedback_router", "feature_handoff", predicate=_feedback_accept)
    # FEAT-377/A: bounded repair loop back-edge. The engine's cyclic
    # re-entry support (TASK-1910) resets every node on the
    # development->synthesis->qa->feedback_router cycle and re-dispatches
    # development. Unbounded by this predicate itself — see
    # _feedback_retry's docstring.
    flow.add_edge("feedback_router", "development", predicate=_feedback_retry)
    flow.add_edge("feature_handoff", "close")
    for source in (
        "intent_classifier", "planner", "development", "synthesis",
        "qa", "feedback_router", "feature_handoff",
    ):
        flow.add_edge(source, "failure_handler", condition="on_error")

    return flow


class DevLoopRunner:
    """Hosts dev-loop flow runs behind a global concurrency cap.

    Args:
        flow: The :class:`AgentsFlow` built by ``build_dev_loop_flow``.
        max_concurrent_runs: Cap on simultaneously executing runs.
            Defaults to ``conf.FLOW_MAX_CONCURRENT_RUNS``.
    """

    def __init__(
        self,
        flow: AgentsFlow,
        *,
        max_concurrent_runs: Optional[int] = None,
        dispatcher: Optional[Any] = None,
        jira_toolkit: Optional[Any] = None,
        git_toolkit: Optional[Any] = None,
        wiki_toolkit: Optional[Any] = None,
        redis_url: Optional[str] = None,
        codereview_dispatcher: Optional[Any] = None,
        graph_memory: Optional[Any] = None,
    ) -> None:
        self.flow = flow
        self.max_concurrent_runs = int(
            max_concurrent_runs
            if max_concurrent_runs is not None
            else conf.FLOW_MAX_CONCURRENT_RUNS
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)
        self._active: Set[str] = set()
        # FEAT-377 TASK-1917 (G6): gate-park bookkeeping. `_parked` is
        # disjoint from `_active` — a run_id is in at most one of them
        # while its flow is in flight. `_pending_gate_count` tracks
        # concurrently-open gates per run so a run with several blocking
        # criteria parks once (0->1) and resumes once (1->0), not per gate.
        # `_run_completion` lets `resume_run()` (and any other caller) await
        # the SAME eventual FlowResult the original `run()` call produces.
        self._parked: Set[str] = set()
        self._pending_gate_count: Dict[str, int] = {}
        self._run_completion: Dict[str, "asyncio.Future[FlowResult]"] = {}
        # Deps needed to build the revision-mode flow on demand (FEAT-250 G6).
        # Optional so the legacy ``DevLoopRunner(flow)`` construction keeps
        # working; ``run_revision`` raises a clear error when they are absent.
        self._dispatcher = dispatcher
        self._jira_toolkit = jira_toolkit
        self._git_toolkit = git_toolkit
        self._wiki_toolkit = wiki_toolkit
        self._redis_url = redis_url
        self._codereview_dispatcher = codereview_dispatcher
        # FEAT-377 TASK-1915: optional DevLoopGraphMemory forwarded to the
        # revision flow's QA/close/failure_handler nodes. None is a no-op.
        self._graph_memory = graph_memory
        # Lazily-built, reused revision flow (fixed topology — built once).
        self._rev_flow: Optional[AgentsFlow] = None
        # Lazily-built, reused feature-mode flow (FEAT-378, fixed topology).
        self._feature_flow: Optional[AgentsFlow] = None
        self.logger = logging.getLogger("parrot.dev_loop.runner")

        # ── AHP-style host state (FEAT-322) ─────────────────────────────
        # Registry keyed by run_id — resolved per-call, NEVER captured as
        # "the current host" (one AgentsFlow serves concurrent runs).
        self._hosts: Dict[str, SessionHost] = {}
        self._registry = RunRegistryState()
        # Lazy async Redis client for the actions-stream sink. Separate from
        # FlowEventPublisher's own client — same lazy-connect, swallow-all
        # pattern (flow.py:122-128).
        self._actions_redis: Any = None
        # run_id -> epoch seconds after which flow:{run_id}:actions is
        # eligible for deletion (DEV_LOOP_ACTIONS_RETENTION_DAYS). Checked by
        # the periodic sweep alongside gate expiry.
        self._pending_retention: Dict[str, float] = {}
        self._sweep_task: Optional[asyncio.Task] = None
        # run_id -> FIFO of envelopes awaiting their XADD, plus the SINGLE
        # writer task draining it. One writer per run is what makes the
        # actions stream's order match `server_seq` — see
        # :meth:`_make_envelope_sink`. `None` on the queue is the shutdown
        # sentinel pushed by :meth:`_flush_actions_queue`.
        self._actions_queues: Dict[str, "asyncio.Queue[Any]"] = {}
        self._actions_writers: Dict[str, asyncio.Task] = {}

    # ── AHP-style host registry (FEAT-322) ──────────────────────────────────

    def get_host(self, run_id: str) -> Optional[SessionHost]:
        """Return the live :class:`SessionHost` for ``run_id``, if any.

        Returns ``None`` once the run has terminated and its host was
        discarded — callers (e.g. the ``view="state"`` multiplexer) fall
        back to folding ``flow:{run_id}:actions`` from seq 0 in that case.
        """
        return self._hosts.get(run_id)

    @property
    def registry_state(self) -> RunRegistryState:
        """The root-channel run catalogue (``parrot-root://``)."""
        return self._registry

    def _apply_root_action(self, action: Any) -> None:
        """Fold one root action into ``self._registry`` (sync, in-memory)."""
        self._registry = reduce_root(self._registry, action)

    def _run_summary_from_host(self, host: SessionHost) -> RunSummary:
        """Project a host's live state into a display-ready :class:`RunSummary`."""
        state = host.state
        pending_gates = sum(
            1 for g in state.gates.values() if g.status == "pending"
        )
        return RunSummary(
            run_id=state.run_id,
            phase=state.phase,
            work_kind=state.work_kind,
            summary=state.summary,
            jira_issue_key=state.jira_issue_key,
            pr_url=state.pr_url,
            pending_gate_count=pending_gates,
            created_at=state.created_at,
            finished_at=state.finished_at,
        )

    def _register_host(self, run_id: str) -> SessionHost:
        """Create, register and return a fresh :class:`SessionHost` for ``run_id``."""
        host = SessionHost(run_id, on_envelope=self._make_envelope_sink(run_id))
        self._hosts[run_id] = host
        self._ensure_sweep_task()
        return host

    def _discard_host(self, run_id: str) -> None:
        """Remove a terminated run's host from the registry.

        The sweep task is only cancelled when there is truly nothing left
        for it to do — no live hosts AND no runs still awaiting their
        actions-stream retention window (``_pending_retention``). Since
        ``RunRemoved`` for a finished run is now applied BY the retention
        sweep (see :meth:`_sweep_retention_once`), cancelling the task just
        because the last host was discarded would silently strand that
        run in the root catalogue forever (`RunRemoved` would never fire).
        """
        self._hosts.pop(run_id, None)
        if (
            not self._hosts
            and not self._pending_retention
            and self._sweep_task is not None
        ):
            self._sweep_task.cancel()
            self._sweep_task = None

    @staticmethod
    def _outcome_from_status(status: Any) -> str:
        """Map ``FlowResult.status`` (``FlowStatus``) to a RunClosed outcome.

        ``"completed"`` -> ``"succeeded"``; ``"partial"`` and ``"failed"``
        both map to ``"failed"`` — a partially-completed run is not a clean
        success for the session-state model's binary outcome.
        """
        value = getattr(status, "value", status)
        return "succeeded" if value == "completed" else "failed"

    # ── Envelope sink — actions-stream XADD (FEAT-322) ──────────────────────

    def _make_envelope_sink(self, run_id: str) -> Callable[[ActionEnvelope], None]:
        """Build the synchronous ``on_envelope`` callback for ``run_id``'s host.

        ``SessionHost.apply`` invokes this callback synchronously (never
        awaited) and swallows any exception it raises. Because the actual
        Redis XADD is async I/O, the envelope is handed to ``run_id``'s
        single background writer rather than blocking the reducer — the
        in-memory fold has already happened by the time this is called, so
        a slow/failing sink can never affect run correctness
        (never-break-a-run).

        ORDER MATTERS, and one writer per run is what guarantees it. This
        used to spawn an independent task per envelope; concurrent tasks on
        a pooled client each take their own connection, so arrival order at
        Redis did not have to match ``server_seq``. Any envelope that landed
        after ``run/closed`` was then lost to every console, because
        ``FlowStreamMultiplexer.state_tail`` stops on the first terminal
        action it sees — which is how a completed Handoff node stayed
        "running" with its PR link dropped. Enqueueing is synchronous and
        happens inside ``apply``'s single-writer slice, so the queue is in
        ``server_seq`` order by construction and the writer preserves it.

        FEAT-377 TASK-1917 (G6): also the park/resume trigger point — this
        is the ONE place every gate open/resolve passes through regardless
        of which node opened it, so parking applies uniformly to every
        ``GateKind`` with no per-kind special-casing.
        """

        def _sink(envelope: ActionEnvelope) -> None:
            if self._redis_url:
                self._enqueue_envelope(run_id, envelope)

            t = envelope.action.type
            if t == "gate/opened":
                self._pending_gate_count[run_id] = (
                    self._pending_gate_count.get(run_id, 0) + 1
                )
                if conf.DEV_LOOP_GATE_PARK and self._pending_gate_count[run_id] == 1:
                    self._park(run_id)
            elif t in ("gate/resolved", "gate/expired"):
                remaining = max(0, self._pending_gate_count.get(run_id, 0) - 1)
                self._pending_gate_count[run_id] = remaining
                if (
                    conf.DEV_LOOP_GATE_PARK
                    and remaining == 0
                    and run_id in self._parked
                ):
                    try:
                        asyncio.get_running_loop().create_task(
                            self._auto_resume(run_id)
                        )
                    except RuntimeError:
                        pass

        return _sink

    def _enqueue_envelope(self, run_id: str, envelope: ActionEnvelope) -> None:
        """Hand one envelope to ``run_id``'s single actions-stream writer.

        Synchronous on purpose: it runs inside ``SessionHost.apply``, so the
        queue ends up in ``server_seq`` order by construction. The writer
        task is created on first use and lives until
        :meth:`_flush_actions_queue` retires it, so there is no
        empty-queue/exit race that could strand a late envelope.

        Args:
            run_id: The run whose actions stream the envelope belongs to.
            envelope: The sequenced envelope to publish.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. sync test harness) — drop silently, same
            # contract as the per-envelope task this replaced.
            return
        queue = self._actions_queues.get(run_id)
        if queue is None:
            queue = asyncio.Queue()
            self._actions_queues[run_id] = queue
        queue.put_nowait(envelope)
        writer = self._actions_writers.get(run_id)
        if writer is None or writer.done():
            self._actions_writers[run_id] = loop.create_task(
                self._drain_actions_queue(run_id, queue)
            )

    async def _drain_actions_queue(
        self, run_id: str, queue: "asyncio.Queue[Any]"
    ) -> None:
        """XADD ``run_id``'s envelopes one at a time, in ``server_seq`` order.

        Awaiting each XADD before pulling the next entry is the whole point:
        it serialises the writes onto one connection's command order. Returns
        on the ``None`` sentinel from :meth:`_flush_actions_queue`.

        Args:
            run_id: The run being published.
            queue: That run's envelope FIFO.
        """
        while True:
            envelope = await queue.get()
            if envelope is None:
                return
            await self._xadd_envelope(run_id, envelope)

    async def _flush_actions_queue(
        self, run_id: str, timeout: float = 5.0
    ) -> None:
        """Publish ``run_id``'s remaining envelopes, then retire its writer.

        Called from :meth:`_close_host` so a finished run's stream is
        complete — ``run/closed`` is enqueued before the sentinel, so it is
        genuinely the last entry and a console tailing the stream can stop on
        it without truncating anything.

        Args:
            run_id: The run to flush.
            timeout: Upper bound in seconds. A wedged Redis leaves the writer
                to be garbage-collected rather than holding up the caller —
                the actions stream is a best-effort mirror of state already
                folded in memory.
        """
        queue = self._actions_queues.pop(run_id, None)
        writer = self._actions_writers.pop(run_id, None)
        if queue is not None:
            queue.put_nowait(None)
        if writer is None or writer.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(writer), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.logger.debug(
                "dev-loop actions-stream flush for run %s did not finish in "
                "%.1fs — remaining envelopes dropped", run_id, timeout,
            )
        except Exception:  # noqa: BLE001 - actions publish must never break a run
            self.logger.debug(
                "dev-loop actions-stream flush failed for run %s",
                run_id, exc_info=True,
            )

    def _retire_actions_writer(self, run_id: str) -> None:
        """Drop ``run_id``'s actions-stream writer without waiting for it.

        For an ABANDONED run only. ``_close_host`` — and the awaited flush
        inside it — never runs when ``run_flow`` raises or is cancelled, so
        the writer would otherwise stay parked on ``queue.get()`` for the
        life of the process. Synchronous and non-awaiting on purpose: it is
        called from an ``except BaseException`` branch, where awaiting during
        cancellation could re-raise before the caller re-raises ``exc``.

        Anything still queued is discarded. Such a run never produced a
        ``run/closed``, so its stream is incomplete regardless and consoles
        fall back to their socket-close handling.

        Args:
            run_id: The abandoned run whose writer should be retired.
        """
        self._actions_queues.pop(run_id, None)
        writer = self._actions_writers.pop(run_id, None)
        if writer is not None and not writer.done():
            writer.cancel()

    async def _ensure_actions_redis(self) -> Any:
        """Return a cached async Redis client for the actions stream."""
        if self._actions_redis is None:
            import redis.asyncio as aioredis  # noqa: PLC0415 - lazy

            self._actions_redis = aioredis.from_url(
                self._redis_url, decode_responses=True
            )
        return self._actions_redis

    async def _xadd_envelope(self, run_id: str, envelope: ActionEnvelope) -> None:
        """XADD one sequenced envelope to ``flow:{run_id}:actions``.

        Every failure is swallowed and logged at DEBUG — the actions
        stream is an operational, best-effort mirror of state already
        folded in-memory (spec §2 "Retention").
        """
        try:
            redis_client = await self._ensure_actions_redis()
            await redis_client.xadd(
                f"flow:{run_id}:actions",
                {"envelope": envelope.model_dump_json()},
                maxlen=100_000,
                approximate=True,
            )
        except Exception:  # noqa: BLE001 - actions publish must never break a run
            self.logger.debug(
                "dev-loop actions XADD failed for run %s", run_id, exc_info=True
            )

    # ── Terminal snapshot + retention (FEAT-322) ────────────────────────────

    def _persist_terminal_snapshot(self, host: SessionHost) -> None:
        """Persist the terminal :class:`Snapshot` as a run artifact.

        Location is an implementation choice (spec §7): a JSON file under
        ``conf.OUTPUT_DIR/dev_loop_runs/{run_id}.snapshot.json``, reusing
        the existing output-directory convention rather than inventing a
        new one. Failures are logged and swallowed — never break the run.
        """
        try:
            snapshot = host.snapshot()
            out_dir = Path(conf.OUTPUT_DIR) / "dev_loop_runs"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{host.state.run_id}.snapshot.json"
            path.write_text(snapshot.model_dump_json(indent=2))
            self.logger.info(
                "Persisted terminal snapshot for run %s at %s",
                host.state.run_id, path,
            )
        except Exception:  # noqa: BLE001 - artifact persistence must not break a run
            self.logger.warning(
                "Failed to persist terminal snapshot for run %s",
                host.state.run_id, exc_info=True,
            )

    def _persist_run_bundle(
        self, host: SessionHost, ctx: Optional[FlowContext],
    ) -> None:
        """Persist the run bundle + markdown closing report (FEAT-378 TASK-1929).

        Mirrors :meth:`_persist_terminal_snapshot`: files under
        ``conf.OUTPUT_DIR/dev_loop_runs/`` — ``{run_id}.bundle.json`` and
        ``{run_id}.report.md``, plus ``{run_id}.usage.json`` /
        ``{run_id}.usage.html`` (FEAT-405 Module 7, folded into
        ``report.md`` too). Independent of the terminal-snapshot
        export (one failing must not skip the other); failures are
        logged and swallowed — bundle export must NEVER break or delay
        run teardown.

        Args:
            host: The run's terminal :class:`SessionHost`.
            ctx: The flow's :class:`FlowContext` (or a plain dict, or
                ``None``) — read defensively for ``shared_data``, same
                duck-typing as ``DevLoopNode.shared_state``.
        """
        try:
            if isinstance(ctx, FlowContext):
                shared: Dict[str, Any] = ctx.shared_data
            elif isinstance(ctx, dict):
                shared = ctx
            else:
                shared = {}
            bundle = build_run_bundle(host.snapshot(), host.replay_since(0), shared)
            out_dir = Path(conf.OUTPUT_DIR) / "dev_loop_runs"
            out_dir.mkdir(parents=True, exist_ok=True)
            bundle_path = out_dir / f"{host.state.run_id}.bundle.json"
            report_path = out_dir / f"{host.state.run_id}.report.md"
            usage_path = out_dir / f"{host.state.run_id}.usage.json"
            usage_html_path = out_dir / f"{host.state.run_id}.usage.html"
            bundle_path.write_text(bundle.model_dump_json(indent=2))
            # FEAT-405 Module 7: per-agent usage — same snapshot/shared the
            # bundle above reads. Independent of the bundle write above (a
            # failure here must not skip report.md, hence its own
            # try/except rather than sharing the outer one's early exit).
            usage_markdown = ""
            try:
                usage_report = build_usage_report(
                    host.snapshot(), host.state.run_id, shared=shared
                )
                usage_path.write_text(usage_report.model_dump_json(indent=2))
                usage_html_path.write_text(render_usage_html(usage_report))
                usage_markdown = render_usage_markdown(usage_report)
            except Exception:  # noqa: BLE001 - usage export must not break bundle export
                self.logger.warning(
                    "Failed to persist usage report for run %s",
                    host.state.run_id, exc_info=True,
                )
            report_path.write_text(render_markdown(bundle, usage_markdown))
            self.logger.info(
                "Persisted run bundle for run %s at %s and %s",
                host.state.run_id, bundle_path, report_path,
            )
        except Exception:  # noqa: BLE001 - artifact persistence must not break a run
            self.logger.warning(
                "Failed to persist run bundle for run %s",
                host.state.run_id, exc_info=True,
            )

    def _schedule_actions_retention(self, run_id: str) -> None:
        """Record the delete-after time for ``flow:{run_id}:actions``.

        The periodic sweep (:meth:`_sweep_once`) deletes the stream once
        ``DEV_LOOP_ACTIONS_RETENTION_DAYS`` has elapsed since the run
        terminated — checked alongside gate expiry rather than via a
        separate long-lived per-run task (which would not survive a
        process restart and would leak if never awaited).
        """
        retention_seconds = float(conf.DEV_LOOP_ACTIONS_RETENTION_DAYS) * 86400.0
        self._pending_retention[run_id] = time.time() + retention_seconds
        self.logger.info(
            "Scheduled flow:%s:actions for deletion in %.0fd",
            run_id, conf.DEV_LOOP_ACTIONS_RETENTION_DAYS,
        )

    async def _sweep_retention_once(self) -> None:
        """Delete due actions streams AND remove their runs from the root catalogue.

        ``RunRemoved`` is applied HERE, alongside the actions-stream
        deletion, per spec §3 M3 ("RunRemoved after retention") — NOT
        immediately at run-close (:meth:`_close_host`), so a just-finished
        run stays visible in ``registry_state`` with its final
        ``RunSummary`` for the full ``DEV_LOOP_ACTIONS_RETENTION_DAYS``
        window, matching how the actions stream itself is retained.

        Runs without a redis-backed actions stream (``self._redis_url`` is
        ``None``) still get ``RunRemoved`` applied once their window
        elapses — there's simply no stream to delete first.
        """
        now = time.time()
        due = [rid for rid, at in self._pending_retention.items() if now >= at]
        for rid in due:
            if self._redis_url:
                try:
                    redis_client = await self._ensure_actions_redis()
                    await redis_client.delete(f"flow:{rid}:actions")
                except Exception:  # noqa: BLE001 - retention sweep must not raise
                    self.logger.debug(
                        "actions-stream retention delete failed for run %s",
                        rid, exc_info=True,
                    )
            self._pending_retention.pop(rid, None)
            self._apply_root_action(RunRemoved(run_id=rid))
            self.logger.info(
                "Run %s retention window elapsed — removed from root catalogue",
                rid,
            )

    # ── Expiry sweep loop (FEAT-322) ─────────────────────────────────────────

    def _ensure_sweep_task(self) -> None:
        """Start the periodic gate-expiry/retention sweep if not running."""
        if self._sweep_task is None or self._sweep_task.done():
            try:
                self._sweep_task = asyncio.get_running_loop().create_task(
                    self._sweep_loop()
                )
            except RuntimeError:
                # No running loop (e.g. constructed outside async context) —
                # the sweep starts lazily on the next call from async code.
                self._sweep_task = None

    async def _sweep_loop(self) -> None:
        """Periodic loop: expire due gates on every live host + retention."""
        try:
            while True:
                await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
                await self._sweep_once()
        except asyncio.CancelledError:
            raise

    async def _sweep_once(self) -> None:
        """Run one gate-expiry + retention sweep pass (testable in isolation)."""
        for host in list(self._hosts.values()):
            try:
                host.expire_due_gates()
            except Exception:  # noqa: BLE001 - sweep must never raise
                self.logger.debug(
                    "gate-expiry sweep failed for run %s",
                    host.state.run_id, exc_info=True,
                )
        await self._sweep_retention_once()

    # ── HITL command surface (FEAT-322) ──────────────────────────────────────

    async def resolve_gate(
        self,
        run_id: str,
        gate_id: str,
        resolution: str,
        resolved_by: str,
        comment: str = "",
        origin: Optional[ActionOrigin] = None,
        answers: Optional[Dict[str, str]] = None,
    ) -> ActionEnvelope:
        """Resolve a pending gate on ``run_id``'s host.

        Args:
            run_id: The target run.
            gate_id: The gate to resolve.
            resolution: ``"approved"`` or ``"rejected"``.
            resolved_by: Identity of the resolving client/user.
            comment: Optional free-text audit comment.
            origin: Optional multi-client attribution (FEAT-322 TASK-1855 —
                the REST command layer passes the calling client here).
            answers: FEAT-412 — structured ``question -> answer`` mapping for
                an ``open_questions`` gate (dev-flow ideation rounds).
                Required when approving such a gate; ignored otherwise.

        Returns:
            The sequenced :class:`ActionEnvelope` for the resolution.

        Raises:
            KeyError: ``run_id`` has no live host (unknown or already
                terminated run).
            GateNotFoundError: ``gate_id`` does not exist on this run.
            GateAlreadyResolvedError: the gate is no longer pending.
            ValueError: An ``open_questions`` gate is approved with no answers.
        """
        host = self._hosts.get(run_id)
        if host is None:
            raise KeyError(f"no active session host for run_id={run_id!r}")
        return host.resolve_gate(
            gate_id, resolution, resolved_by, comment, origin=origin,
            answers=answers,
        )

    async def cancel_run(self, run_id: str, requested_by: str) -> ActionEnvelope:
        """Request cancellation of ``run_id`` (terminal-sticky).

        Args:
            run_id: The target run.
            requested_by: Identity of the requesting client/user.

        Returns:
            The sequenced :class:`ActionEnvelope` for ``run/cancelled``.

        Raises:
            KeyError: ``run_id`` has no live host.
        """
        host = self._hosts.get(run_id)
        if host is None:
            raise KeyError(f"no active session host for run_id={run_id!r}")
        return host.apply(RunCancelled(requested_by=requested_by))

    # ── Introspection ─────────────────────────────────────────────────────

    @property
    def active_runs(self) -> Set[str]:
        """Run IDs currently HOLDING a concurrency slot (copy).

        Excludes parked runs (FEAT-377 TASK-1917) — a parked run's flow is
        still in flight (blocked on a gate) but has released its slot, so
        it does not count against ``FLOW_MAX_CONCURRENT_RUNS``. See
        :attr:`parked_runs` for the other half.
        """
        return set(self._active)

    def is_active(self, run_id: str) -> bool:
        """True while *run_id* is holding a concurrency slot."""
        return run_id in self._active

    @property
    def parked_runs(self) -> Set[str]:
        """Run IDs whose flow is in flight but has released its slot
        (FEAT-377 TASK-1917 — awaiting a gate with ``DEV_LOOP_GATE_PARK``
        enabled). Copy."""
        return set(self._parked)

    def is_parked(self, run_id: str) -> bool:
        """True while *run_id* is parked (awaiting a gate, slot released)."""
        return run_id in self._parked

    # ── Gate park / resume (FEAT-377 TASK-1917 — G6) ────────────────────────

    def _park(self, run_id: str) -> None:
        """Release ``run_id``'s concurrency slot immediately (synchronous).

        Called from the envelope sink on the first gate a run opens
        (``_pending_gate_count`` 0->1). ``asyncio.Semaphore.release()`` has
        no per-task ownership, so releasing here — from a different
        logical call stack than the ``acquire()`` in :meth:`run` — is
        safe; the exactly-once invariant is enforced by the ``run_id in
        self._active`` guard (a run can only be parked from the active
        state) together with the sink's own 0->1 transition guard.

        Args:
            run_id: The run whose slot is being released.
        """
        if run_id not in self._active:
            return  # already parked, or not a slot-holding run — no-op
        self._active.discard(run_id)
        self._parked.add(run_id)
        self._apply_root_action(RunParked(run_id=run_id))
        self._semaphore.release()
        self.logger.info(
            "Dev-loop run %s parked (gate opened); slot released (%d/%d active).",
            run_id, len(self._active), self.max_concurrent_runs,
        )

    async def _auto_resume(self, run_id: str) -> None:
        """Fire-and-forget wrapper: resume ``run_id`` when its last
        pending gate resolves, without requiring a caller to await it.

        Errors are logged, never raised — the resolving gate's own
        resolution has already succeeded by this point; a failure here
        must not look like the gate resolution itself failed.
        """
        try:
            await self.resume_run(run_id)
        except Exception as exc:  # noqa: BLE001 - never break gate resolution
            self.logger.warning(
                "Auto-resume failed for parked run %s: %s", run_id, exc
            )

    async def resume_run(self, run_id: str) -> FlowResult:
        """Re-acquire a slot for a parked run and await its eventual result.

        Safe to call whether or not ``run_id`` is currently parked (a
        no-op re-acquire step is skipped when it is not — e.g. called
        twice, or called after the run already resumed on its own) — the
        run's flow continues on its own once the gate resolves (via
        ``SessionHost.wait_gate``'s internal ``asyncio.Event``,
        independent of slot bookkeeping); this method's job is purely to
        restore the concurrency-slot invariant and hand back the run's
        eventual :class:`FlowResult` to whoever calls it (the automatic
        gate-resolution hook does not consume it; a REST caller might).

        Args:
            run_id: The run to resume.

        Returns:
            The same :class:`FlowResult` the original :meth:`run` call
            for ``run_id`` will eventually return.

        Raises:
            KeyError: No in-progress run is tracked for ``run_id`` (never
                started, or already finished and cleaned up).
        """
        fut = self._run_completion.get(run_id)
        if fut is None:
            raise KeyError(f"No in-progress dev-loop run found for {run_id!r}.")
        if run_id in self._parked and not fut.done():
            await self._semaphore.acquire()
            # Re-check after the await: the run may have finished WHILE we
            # were waiting for a free slot (a fast/mocked flow can finish
            # before this coroutine gets scheduled at all — see the
            # sink's `create_task(self._auto_resume(...))`). Release
            # immediately rather than leaking an acquired-but-unused slot.
            if fut.done():
                self._semaphore.release()
            else:
                self._parked.discard(run_id)
                self._active.add(run_id)
                self._apply_root_action(RunResumed(run_id=run_id))
                self.logger.info(
                    "Dev-loop run %s resumed; slot re-acquired (%d/%d active).",
                    run_id, len(self._active), self.max_concurrent_runs,
                )
        return await fut

    # ── Execution ─────────────────────────────────────────────────────────

    async def run(
        self,
        brief: Union[WorkBrief, FeatureBrief],
        *,
        run_id: Optional[str] = None,
        initial_task: str = "",
        extra_shared: Optional[Dict[str, Any]] = None,
    ) -> FlowResult:
        """Execute one dev-loop run for *brief*, respecting the run cap.

        Blocks (cooperatively) while ``max_concurrent_runs`` runs are
        already in flight.

        FEAT-378: ``brief`` accepts the ``Brief`` discriminated union
        (``WorkBrief | FeatureBrief``, TASK-1918). A :class:`FeatureBrief`
        is routed to :meth:`_run_feature` (the feature-mode topology,
        lazily built/reused like ``run_revision``'s ``_rev_flow``); the
        ``WorkBrief`` path below is otherwise byte-identical to before.

        Args:
            brief: The validated :class:`WorkBrief` / ``BugBrief`` /
                :class:`FeatureBrief` to process.
            run_id: Optional externally-minted run identifier; one is
                generated (``run-<hex8>``) when omitted.
            initial_task: Optional human-readable task line stored as the
                context's ``initial_task``.
            extra_shared: Extra entries merged into ``shared_data``.

        Returns:
            The aggregated :class:`FlowResult` for the run.
        """
        if isinstance(brief, FeatureBrief):
            return await self._run_feature(
                brief,
                run_id=run_id,
                initial_task=initial_task,
                extra_shared=extra_shared,
            )

        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"

        # AHP-style host: create + register before the flow runs, seed it
        # into shared state so nodes resolve it per-run (never a captured
        # reference — QANode/DeploymentHandoffNode read
        # ``shared["session_host"]``, they never import the runner).
        host = self._register_host(rid)
        host.apply(RunCreated(
            run_id=rid, revision=False, work_kind=brief.kind,
            summary=brief.summary,
        ))
        self._apply_root_action(RunAdded(summary=self._run_summary_from_host(host)))

        shared: Dict[str, Any] = {
            "bug_brief": brief,    # legacy key — nodes read this
            "work_brief": brief,   # forward-compat name
            "run_id": rid,
            "session_host": host,
        }
        if extra_shared:
            shared.update(extra_shared)

        ctx = FlowContext(
            initial_task=initial_task or brief.summary,
            shared_data=shared,
        )

        # FEAT-377 TASK-1917 (G6): a manual acquire/release (not `async
        # with self._semaphore`) is required because a park can release
        # the slot WHILE `run_flow()` below is still in flight (the
        # release happens synchronously from the envelope sink, invoked
        # from deep inside whichever node opens a gate) — a context
        # manager spanning the call cannot express "release, then maybe
        # someone else re-acquires before I get back control".
        loop = asyncio.get_running_loop()
        completion: "asyncio.Future[FlowResult]" = loop.create_future()
        self._run_completion[rid] = completion
        await self._semaphore.acquire()
        self._active.add(rid)
        # Point the flow's event publisher at this run's stream.
        holder = getattr(self.flow, "_run_id_holder", None)
        if isinstance(holder, dict):
            holder["run_id"] = rid
        self.logger.info(
            "Starting dev-loop run %s (%d/%d active)",
            rid, len(self._active), self.max_concurrent_runs,
        )
        try:
            result = await self.flow.run_flow(ctx)
        except BaseException as exc:
            # Propagate to any `resume_run()` awaiter too — a future that
            # never resolves would hang them forever. Popped from the
            # registry (not left for `finally`) so it happens BEFORE the
            # exception continues propagating out of this method.
            if not completion.done():
                completion.set_exception(exc)
            self._run_completion.pop(rid, None)
            self._retire_actions_writer(rid)
            raise
        finally:
            # Exactly-once release: only if this run is STILL holding its
            # slot (i.e. it was never parked, or it was parked and already
            # resumed by the time `run_flow()` returned/raised). A run
            # that finishes WHILE still parked releases nothing here —
            # `_park` already released its slot, and `resume_run`'s own
            # `fut.done()` re-check prevents a late resume from acquiring
            # a slot for a run that no longer needs one.
            if rid in self._active:
                self._active.discard(rid)
                self._semaphore.release()
            else:
                self._parked.discard(rid)
            self._pending_gate_count.pop(rid, None)

        self.logger.info(
            "Dev-loop run %s finished status=%s", rid, result.status
        )
        await self._close_host(host, result, ctx)
        if not completion.done():
            completion.set_result(result)
        self._run_completion.pop(rid, None)
        return result

    def _feature_codereview_dispatcher(self) -> Any:
        """Resolve the code-review dispatcher for the feature-mode flow.

        Code-review finding (post-TASK-1925): this runner has a single
        ``self._codereview_dispatcher`` field shared by ``run()``/
        ``run_revision()`` (bug/revision QA) and ``_run_feature()``
        (feature-mode QA) — an explicit caller-supplied dispatcher applies
        to both, unchanged. But when the caller left it unset (``None``,
        today's default), feature-mode QA silently fell through to
        ``QANode``'s own bare fallback (a single
        ``ClaudeCodeReviewDispatcher``) instead of the N-judge panel spec
        §2/§4 (Module 4, TASK-1920) describes as feature-mode's default
        review gate. Only feature-mode gets this default upgrade — bug/
        revision behavior is unchanged (still ``None`` -> QANode's own
        fallback) — because only feature-mode's QA is documented to
        default to the judge panel.

        Returns:
            ``self._codereview_dispatcher`` when explicitly configured,
            otherwise a freshly-built ``JudgePanelReviewDispatcher`` (its
            own constructor resolves ``DEV_LOOP_JUDGE_PANEL`` / falls back
            to ``default_judge_panel()``).
        """
        if self._codereview_dispatcher is not None:
            return self._codereview_dispatcher
        from parrot.flows.dev_loop.code_review import JudgePanelReviewDispatcher

        return JudgePanelReviewDispatcher(redis_url=self._redis_url)

    async def _run_feature(
        self,
        brief: FeatureBrief,
        *,
        run_id: Optional[str] = None,
        initial_task: str = "",
        extra_shared: Optional[Dict[str, Any]] = None,
    ) -> FlowResult:
        """Execute one feature-mode dev-loop run for *brief* (FEAT-378).

        Builds (and reuses, like ``run_revision``'s ``_rev_flow``) the
        feature-mode flow, seeds ``shared["feature_brief"]``, and runs it.
        Mirrors :meth:`run`'s AHP-host lifecycle exactly — the only
        differences are the flow topology and the seeded brief key.

        Args:
            brief: The validated :class:`FeatureBrief`.
            run_id: Optional externally-minted id (``run-<hex8>`` otherwise).
            initial_task: Optional human-readable task line.
            extra_shared: Extra entries merged into ``shared_data``.

        Returns:
            The aggregated :class:`FlowResult` for the run.

        Raises:
            RuntimeError: If the runner was constructed without the deps
                needed to build the feature flow (dispatcher + redis_url).
        """
        if not all((self._dispatcher, self._redis_url)):
            raise RuntimeError(
                "feature-mode run requires the runner to be constructed "
                "with dispatcher and redis_url."
            )

        rid = run_id or f"run-{uuid.uuid4().hex[:8]}"

        host = self._register_host(rid)
        # NOTE: RunCreated.work_kind is a closed Literal["bug","enhancement",
        # "new_feature"] deliberately NOT extended with "feature" (TASK-1918)
        # — FeatureBrief carries its own `kind` field instead. "bug" here is
        # a structural placeholder only (never read on this path — no
        # ResearchNode / Jira-issuetype selection happens in feature-mode).
        host.apply(RunCreated(
            run_id=rid, revision=False, work_kind="bug",
            summary=f"Feature: {brief.document_path}",
        ))
        self._apply_root_action(RunAdded(summary=self._run_summary_from_host(host)))

        # Build the feature flow once (fixed topology) and reuse it — fresh
        # node FSMs are materialized per run by the scheduler, like ``run``.
        if self._feature_flow is None:
            self._feature_flow = build_dev_loop_feature_flow(
                dispatcher=self._dispatcher,
                jira_toolkit=self._jira_toolkit,
                git_toolkit=self._git_toolkit,
                wiki_toolkit=self._wiki_toolkit,
                redis_url=self._redis_url,
                codereview_dispatcher=self._feature_codereview_dispatcher(),
                # FEAT-377 TASK-1914/1915: mirrors run_revision's lazy
                # ``_rev_flow`` build — forwards the same instance-level
                # graph_memory so this fallback default flow isn't a
                # strict subset of the pre-seeded one server.py builds.
                # require_plan_approval has no stored instance attribute
                # (like the revision flow, this thin default path doesn't
                # expose it) — callers who want it pre-seed self._feature_flow
                # themselves (see examples/dev_loop/server.py).
                graph_memory=self._graph_memory,
            )
        feature_flow = self._feature_flow

        shared: Dict[str, Any] = {
            "feature_brief": brief,
            "run_id": rid,
            "session_host": host,
        }
        if extra_shared:
            shared.update(extra_shared)

        ctx = FlowContext(
            initial_task=initial_task or f"Feature: {brief.document_path}",
            shared_data=shared,
        )

        # FEAT-377 TASK-1917 (G6) / code-review finding (post-TASK-1925): same
        # manual acquire/park-aware structure as `run()`/`run_revision()` — a
        # feature run's QA can open gates too (`review_escalation` via the
        # judge panel, `manual_criterion`), so a plain `async with
        # self._semaphore` is unsafe: `_park()` can release the slot WHILE
        # `run_flow()` is still in flight (from deep inside whichever node
        # opens a gate), which a context manager cannot express — and without
        # registering `_run_completion[rid]`, `resume_run()` would have
        # nothing to await for a parked feature run.
        loop = asyncio.get_running_loop()
        completion: "asyncio.Future[FlowResult]" = loop.create_future()
        self._run_completion[rid] = completion
        await self._semaphore.acquire()
        self._active.add(rid)
        holder = getattr(feature_flow, "_run_id_holder", None)
        if isinstance(holder, dict):
            holder["run_id"] = rid
        self.logger.info(
            "Starting dev-loop FEATURE run %s (%d/%d active)",
            rid, len(self._active), self.max_concurrent_runs,
        )
        try:
            result = await feature_flow.run_flow(ctx)
        except BaseException as exc:
            if not completion.done():
                completion.set_exception(exc)
            self._run_completion.pop(rid, None)
            self._retire_actions_writer(rid)
            raise
        finally:
            if rid in self._active:
                self._active.discard(rid)
                self._semaphore.release()
            else:
                self._parked.discard(rid)
            self._pending_gate_count.pop(rid, None)

        self.logger.info(
            "Dev-loop feature run %s finished status=%s", rid, result.status
        )
        await self._close_host(host, result, ctx)
        if not completion.done():
            completion.set_result(result)
        self._run_completion.pop(rid, None)
        return result

    async def run_revision(
        self,
        brief: RevisionBrief,
        *,
        run_id: Optional[str] = None,
    ) -> FlowResult:
        """Execute a revision-mode run for *brief* (FEAT-250 G6).

        Builds the short revision flow (``development → qa → revision_handoff →
        close`` / fail → ``failure_handler``), seeds the shared state to reuse
        the existing clone + branch (no Intent/BugIntake/Research/clone), and
        runs it. ``RevisionHandoffNode`` pushes to the existing branch and
        comments the same PR — it never opens a new PR.

        Args:
            brief: The :class:`RevisionBrief` describing the existing clone,
                branch, PR and reviewer feedback.
            run_id: Optional externally-minted id (``rev-<hex8>`` otherwise).

        Returns:
            The aggregated :class:`FlowResult` for the revision run.

        Raises:
            RuntimeError: If the runner was constructed without the deps needed
                to build the revision flow.
        """
        if not all(
            (self._dispatcher, self._jira_toolkit, self._git_toolkit, self._redis_url)
        ):
            raise RuntimeError(
                "run_revision requires the runner to be constructed with "
                "dispatcher, jira_toolkit, git_toolkit and redis_url."
            )

        rid = run_id or f"rev-{uuid.uuid4().hex[:8]}"

        # AHP-style host — same lifecycle as ``run()`` (revision=True).
        host = self._register_host(rid)
        host.apply(RunCreated(
            run_id=rid, revision=True,
            work_kind="bug",
            summary=f"Revision for {brief.jira_issue_key or brief.branch}",
        ))
        self._apply_root_action(RunAdded(summary=self._run_summary_from_host(host)))

        # Build the revision flow once (fixed topology) and reuse it — fresh
        # node FSMs are materialized per run by the scheduler, like ``run``.
        if self._rev_flow is None:
            self._rev_flow = build_dev_loop_revision_flow(
                dispatcher=self._dispatcher,
                jira_toolkit=self._jira_toolkit,
                git_toolkit=self._git_toolkit,
                redis_url=self._redis_url,
                codereview_dispatcher=self._codereview_dispatcher,
                graph_memory=self._graph_memory,
            )
        rev_flow = self._rev_flow

        # Seed a synthetic ResearchOutput so Development/QA run against the
        # existing clone without re-cloning. FEAT-377 TASK-1908: when the
        # original feature's acceptance criteria are carried on
        # `RevisionBrief.acceptance_criteria`, QA re-verifies them alongside
        # the lint gate; when absent (`None`/empty — no caller populates this
        # yet, graph memory write-back in TASK-1915 is the intended future
        # source), QA re-runs a lint-only gate exactly as before. The
        # reviewer feedback is surfaced in shared state and the context's
        # initial_task either way.
        research = ResearchOutput(
            jira_issue_key=brief.jira_issue_key,
            spec_path="",
            feat_id="",
            branch_name=brief.branch,
            worktree_path=brief.repo_path,
            repo_path=brief.repo_path,
        )
        work = WorkBrief(
            kind="bug",
            summary=f"Revision for {brief.jira_issue_key or brief.branch}",
            description=brief.feedback,
            affected_component="(revision)",
            # NOTE: the revision graph skips BugIntakeNode, so this command is
            # NOT run through ACCEPTANCE_CRITERION_ALLOWLIST. It is injected by
            # the runner (trusted internal input, run via exec — no shell), so
            # the allowlist bypass is intentional and safe.
            acceptance_criteria=[
                *(brief.acceptance_criteria or []),
                ShellCriterion(name="lint", command="ruff check ."),
            ],
            escalation_assignee="",
            reporter="",
        )
        shared: Dict[str, Any] = {
            "run_id": rid,
            "mode": "revision",
            "research_output": research,
            "bug_brief": work,
            "work_brief": work,
            "repo_path": brief.repo_path,
            "branch": brief.branch,
            "pr_number": brief.pr_number,
            "repository": brief.repository,
            "jira_issue_key": brief.jira_issue_key,
            "feedback": brief.feedback,
            "head_sha": brief.head_sha,
            "session_host": host,
        }
        ctx = FlowContext(
            initial_task=brief.feedback or "revision", shared_data=shared
        )

        # FEAT-377 TASK-1917 (G6): same manual acquire/park-aware structure
        # as `run()` — a revision run's QA can open `manual_criterion`
        # gates too, so parking must apply here identically.
        loop = asyncio.get_running_loop()
        completion: "asyncio.Future[FlowResult]" = loop.create_future()
        self._run_completion[rid] = completion
        await self._semaphore.acquire()
        self._active.add(rid)
        holder = getattr(rev_flow, "_run_id_holder", None)
        if isinstance(holder, dict):
            holder["run_id"] = rid
        self.logger.info(
            "Starting dev-loop REVISION run %s (PR #%s, branch %s)",
            rid, brief.pr_number, brief.branch,
        )
        try:
            result = await rev_flow.run_flow(ctx)
        except BaseException as exc:
            if not completion.done():
                completion.set_exception(exc)
            self._run_completion.pop(rid, None)
            self._retire_actions_writer(rid)
            raise
        finally:
            if rid in self._active:
                self._active.discard(rid)
                self._semaphore.release()
            else:
                self._parked.discard(rid)
            self._pending_gate_count.pop(rid, None)

        self.logger.info(
            "Dev-loop revision run %s finished status=%s", rid, result.status
        )
        await self._close_host(host, result, ctx)
        if not completion.done():
            completion.set_result(result)
        self._run_completion.pop(rid, None)
        return result

    # ── Host terminal handling (FEAT-322) ───────────────────────────────────

    async def _close_host(
        self, host: SessionHost, result: FlowResult, ctx: FlowContext,
    ) -> None:
        """Fold ``run/closed``, persist the terminal snapshot + run bundle,
        and retire the host.

        Order (spec §3 M3, extended by the v0.2 run-bundle amendment):
        apply ``RunClosed`` -> persist the terminal snapshot -> persist
        the run bundle (FEAT-378 TASK-1929) -> schedule actions-stream
        retention -> fold the final ``RunSummaryChanged`` -> discard the
        host. ``RunRemoved`` is
        deliberately NOT applied here — per spec §3 M3 ("RunRemoved AFTER
        retention"), the finished run stays visible in the root catalogue
        (``registry_state``) with its final summary until
        ``_sweep_retention_once`` deletes the actions stream
        (``DEV_LOOP_ACTIONS_RETENTION_DAYS``, default 7d), at which point
        both happen together (code-review finding: an earlier version
        removed the run from the catalogue immediately at close, which
        silently diverged from the spec's stated intent — an operator
        dashboard watching ``parrot-root://`` would never see a run that
        just finished).

        The host itself IS still discarded immediately (not kept until
        retention): the ``view="state"`` multiplexer falls back to
        replaying ``flow:{run_id}:actions`` for a finished run (spec §3 M6)
        — only the ROOT-CHANNEL catalogue entry outlives the host.
        """
        run_id = host.state.run_id
        outcome = self._outcome_from_status(result.status)
        jira_issue_key = str(ctx.shared_data.get("jira_issue_key", "") or "")
        # FEAT-378: feature-mode's handoff node id is "feature_handoff"
        # rather than "deployment_handoff" — check both so this projection
        # generalizes across topologies without a mode flag.
        handoff_resp = result.responses.get("deployment_handoff") or result.responses.get(
            "feature_handoff"
        )
        pr_url = ""
        if isinstance(handoff_resp, dict):
            pr_url = str(handoff_resp.get("pr_url", "") or "")

        # FEAT-413: none of the terminal nodes raise on failure — they
        # return a status dict instead — so a blocked handoff or an
        # escalated failure_handler still lands in FlowResult.status ==
        # "completed" (AgentsFlow only tracks whether a node raised).
        # Scan the explicit terminal-node allowlist directly against
        # result.responses (NOT handoff_resp, which is None when the
        # handoff node was skipped, e.g. the failure_handler case) and
        # force outcome="failed" when any of them reported a failure
        # status.
        for _nid in _TERMINAL_NODE_IDS:
            _resp = result.responses.get(_nid)
            if isinstance(_resp, dict) and _resp.get("status") in _FAILED_TERMINAL_STATUSES:
                self.logger.warning(
                    "Run %s: terminal node %s reported status=%s — recording "
                    "outcome=failed (FlowResult.status=%s)",
                    run_id, _nid, _resp.get("status"), result.status,
                )
                outcome = "failed"
                break

        host.apply(RunClosed(
            outcome=outcome, jira_issue_key=jira_issue_key, pr_url=pr_url,
        ))
        self._persist_terminal_snapshot(host)
        self._persist_run_bundle(host, ctx)
        self._schedule_actions_retention(run_id)
        self._apply_root_action(
            RunSummaryChanged(summary=self._run_summary_from_host(host))
        )
        # Every `host.apply` for this run has happened, so `run/closed` is the
        # last thing in the queue. Draining here is what lets a console stop
        # tailing on it without truncating a still-in-flight node event.
        await self._flush_actions_queue(run_id)
        self._discard_host(run_id)


__all__ = [
    "DevLoopRunner",
    "build_dev_loop_revision_flow",
    "build_dev_loop_feature_flow",
    "gate_ttl_for",
]
