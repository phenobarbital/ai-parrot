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
from typing import Any, Callable, Dict, Optional, Set

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
    _qa_failed,
    _qa_passed,
)
from parrot.flows.dev_loop.models import (
    ResearchOutput,
    RevisionBrief,
    ShellCriterion,
    WorkBrief,
)
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    ActionOrigin,
    GateKind,
    RunAdded,
    RunCancelled,
    RunClosed,
    RunCreated,
    RunRegistryState,
    RunRemoved,
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


def build_dev_loop_revision_flow(
    *,
    dispatcher: Any,
    jira_toolkit: Any,
    git_toolkit: Any,
    redis_url: str,
    codereview_dispatcher: Optional[Any] = None,
    name: str = "dev-loop-revision",
    publish_flow_events: bool = True,
) -> AgentsFlow:
    """Build the short revision-mode ``AgentsFlow`` (FEAT-250 G6).

    Mirrors ``build_dev_loop_flow``'s declarative-materialize-then-explicit
    execution: the nodes come from ``build_dev_loop_definition(revision=True)``
    via the node factories, and the graph runs in explicit-edge mode (OR-join
    on the ``failure_handler`` fan-in). Topology: ``development → qa →
    (pass) revision_handoff → close`` / ``(fail) failure_handler``.
    """
    definition = build_dev_loop_definition(revision=True)
    factories = build_dev_loop_node_factories(
        dispatcher=dispatcher,
        jira_toolkit=jira_toolkit,
        redis_url=redis_url,
        git_toolkit=git_toolkit,
        codereview_dispatcher=codereview_dispatcher,
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
        redis_url: Optional[str] = None,
        codereview_dispatcher: Optional[Any] = None,
    ) -> None:
        self.flow = flow
        self.max_concurrent_runs = int(
            max_concurrent_runs
            if max_concurrent_runs is not None
            else conf.FLOW_MAX_CONCURRENT_RUNS
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)
        self._active: Set[str] = set()
        # Deps needed to build the revision-mode flow on demand (FEAT-250 G6).
        # Optional so the legacy ``DevLoopRunner(flow)`` construction keeps
        # working; ``run_revision`` raises a clear error when they are absent.
        self._dispatcher = dispatcher
        self._jira_toolkit = jira_toolkit
        self._git_toolkit = git_toolkit
        self._redis_url = redis_url
        self._codereview_dispatcher = codereview_dispatcher
        # Lazily-built, reused revision flow (fixed topology — built once).
        self._rev_flow: Optional[AgentsFlow] = None
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
        Redis XADD is async I/O, this schedules a best-effort background
        task rather than blocking the reducer — the in-memory fold has
        already happened by the time this is called, so a slow/failing
        sink can never affect run correctness (never-break-a-run).
        """

        def _sink(envelope: ActionEnvelope) -> None:
            if not self._redis_url:
                return  # no redis configured — host still folds in-memory
            try:
                asyncio.get_running_loop().create_task(
                    self._xadd_envelope(run_id, envelope)
                )
            except RuntimeError:
                # No running loop (e.g. sync test harness) — drop silently.
                pass

        return _sink

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

        Returns:
            The sequenced :class:`ActionEnvelope` for the resolution.

        Raises:
            KeyError: ``run_id`` has no live host (unknown or already
                terminated run).
            GateNotFoundError: ``gate_id`` does not exist on this run.
            GateAlreadyResolvedError: the gate is no longer pending.
        """
        host = self._hosts.get(run_id)
        if host is None:
            raise KeyError(f"no active session host for run_id={run_id!r}")
        return host.resolve_gate(
            gate_id, resolution, resolved_by, comment, origin=origin
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
        """Run IDs currently executing (copy)."""
        return set(self._active)

    def is_active(self, run_id: str) -> bool:
        """True while *run_id* is executing."""
        return run_id in self._active

    # ── Execution ─────────────────────────────────────────────────────────

    async def run(
        self,
        brief: WorkBrief,
        *,
        run_id: Optional[str] = None,
        initial_task: str = "",
        extra_shared: Optional[Dict[str, Any]] = None,
    ) -> FlowResult:
        """Execute one dev-loop run for *brief*, respecting the run cap.

        Blocks (cooperatively) while ``max_concurrent_runs`` runs are
        already in flight.

        Args:
            brief: The validated :class:`WorkBrief` / ``BugBrief`` to process.
            run_id: Optional externally-minted run identifier; one is
                generated (``run-<hex8>``) when omitted.
            initial_task: Optional human-readable task line stored as the
                context's ``initial_task``.
            extra_shared: Extra entries merged into ``shared_data``.

        Returns:
            The aggregated :class:`FlowResult` for the run.
        """
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

        async with self._semaphore:
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
            finally:
                self._active.discard(rid)

        self.logger.info(
            "Dev-loop run %s finished status=%s", rid, result.status
        )
        self._close_host(host, result, ctx)
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
            )
        rev_flow = self._rev_flow

        # Seed a synthetic ResearchOutput so Development/QA run against the
        # existing clone without re-cloning. v1 note: the original acceptance
        # criteria are not carried on RevisionBrief, so QA re-runs a lint gate
        # by default; the reviewer feedback is surfaced in shared state and the
        # context's initial_task.
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
            acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
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

        async with self._semaphore:
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
            finally:
                self._active.discard(rid)

        self.logger.info(
            "Dev-loop revision run %s finished status=%s", rid, result.status
        )
        self._close_host(host, result, ctx)
        return result

    # ── Host terminal handling (FEAT-322) ───────────────────────────────────

    def _close_host(
        self, host: SessionHost, result: FlowResult, ctx: FlowContext,
    ) -> None:
        """Fold ``run/closed``, persist the terminal snapshot, and retire the host.

        Order (spec §3 M3): apply ``RunClosed`` -> persist the terminal
        snapshot -> schedule actions-stream retention -> fold the final
        ``RunSummaryChanged`` -> discard the host. ``RunRemoved`` is
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
        handoff_resp = result.responses.get("deployment_handoff")
        pr_url = ""
        if isinstance(handoff_resp, dict):
            pr_url = str(handoff_resp.get("pr_url", "") or "")

        host.apply(RunClosed(
            outcome=outcome, jira_issue_key=jira_issue_key, pr_url=pr_url,
        ))
        self._persist_terminal_snapshot(host)
        self._schedule_actions_retention(run_id)
        self._apply_root_action(
            RunSummaryChanged(summary=self._run_summary_from_host(host))
        )
        self._discard_host(run_id)


__all__ = ["DevLoopRunner", "build_dev_loop_revision_flow", "gate_ttl_for"]
