"""``DevLoopToolkit`` — the dev loop as tools an agent can call.

The dev loop (``parrot.flows.dev_loop``) could only be started three ways:
``DevLoopRunner.run(brief)`` in code, the two HTTP consoles under
``examples/dev_loop/``, or the webhook. None of those is reachable from a
conversation, so an agent asked to fix a bug could describe the pipeline but
never start it.

This toolkit closes that: ``start_dev_loop`` builds the brief and launches a
run, ``dev_loop_status`` reports where it got to, and ``dev_loop_approve``
resolves a HITL gate. Every public async method here becomes a tool
automatically (``AbstractToolkit``), named ``devloop_<method>``.

Two seams keep it useful without knowing anything about the caller's world:

* ``brief_enricher`` — fills in what a one-line report cannot say
  (``affected_component``, the right repo, acceptance criteria). A caller
  with a codebase index plugs it in here; without one the toolkit still
  works, it just needs a fuller brief.
* ``flow_builder`` — the approval gates are baked in at flow-construction
  time, not per run, so a flow is built (and cached) per approval mode.

Runs are launched in the background and the tool returns a ``run_id``
immediately. A dev-loop run takes minutes: returning its result would block
the caller — and, for an agentd daemon, its socket — for the whole run.

Autonomy is decided *after* seeing the plan, not before. A run starts with
every gate enabled, so the first thing that happens is the plan coming back
for approval; approving it with ``then="autonomous"`` hands the rest of the
run over, and ``then="ask"`` keeps the later gates. This is deliberate: the
gates are compiled into the flow at construction time, so a run cannot gain
a gate later — it can only be relieved of one. Starting locked down and
loosening on request is therefore the only order that lets the choice come
after the plan.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol

from parrot.flows.dev_loop.models import WorkBrief
from parrot.flows.dev_loop.runner import DevLoopRunner
from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger(__name__)

#: How much of the run a human still gates.
#:
#: ``"plan"``       — approve the plan, then the run finishes on its own.
#: ``"every_step"`` — also approve before the PR is handed off.
#: ``"none"``       — fully autonomous, no gates.
ApprovalMode = Literal["plan", "every_step", "none"]

#: Gate flags per approval mode, as ``build_dev_loop_flow`` expects them.
#: The flow offers exactly two gates today (plan and deployment), so
#: ``"every_step"`` means "both", not "one per node".
_MODE_GATES: Dict[str, Dict[str, bool]] = {
    "none": {"require_plan_approval": False, "require_deployment_approval": False},
    "plan": {"require_plan_approval": True, "require_deployment_approval": False},
    "every_step": {
        "require_plan_approval": True,
        "require_deployment_approval": True,
    },
}


class BriefEnricher(Protocol):
    """Fills in a brief that a one-line bug report cannot fully specify.

    Implementations resolve things like "the api returns 500 on /xyz" into
    the repo and component that actually own the endpoint.
    """

    async def enrich(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Return ``draft`` with missing fields filled in.

        Args:
            draft: Partial ``WorkBrief`` kwargs.

        Returns:
            The same mapping, enriched. Implementations must not raise for
            "could not resolve" — leave the field alone and let validation
            report it.
        """
        ...


class DevLoopToolkit(AbstractToolkit):
    """Start and supervise dev-loop runs from an agent conversation.

    Tool names (with ``tool_prefix="devloop"``):
      - ``devloop_start_dev_loop``  — start a run from a bug/enhancement report
      - ``devloop_dev_loop_status`` — phase, nodes, pending gates of a run
      - ``devloop_dev_loop_runs``   — the runs this toolkit has started
      - ``devloop_dev_loop_approve``— resolve a pending HITL gate
      - ``devloop_dev_loop_cancel`` — request cancellation of a run

    Example::

        toolkit = DevLoopToolkit(
            flow_kwargs={"git_toolkit": git, "repos": repos},
            brief_enricher=my_enricher,
        )
        agent.register_tools(toolkit.get_tools())
    """

    #: Namespace prefix applied to every auto-generated tool name.
    tool_prefix: Optional[str] = "devloop"

    #: Starting a run writes code and opens a PR — worth a confirmation when
    #: the host wires HITL for tools.
    confirming_tools: frozenset = frozenset({"start_dev_loop"})

    def __init__(
        self,
        *,
        flow_builder: Optional[Callable[..., Any]] = None,
        flow_kwargs: Optional[Dict[str, Any]] = None,
        runner_kwargs: Optional[Dict[str, Any]] = None,
        brief_enricher: Optional[BriefEnricher] = None,
        default_reporter: str = "agent",
        default_assignee: str = "unassigned",
        default_approval_mode: ApprovalMode = "every_step",
        gate_poll_seconds: float = 5.0,
        **kwargs: Any,
    ) -> None:
        """Initialise the toolkit.

        Args:
            flow_builder: Callable building a dev-loop flow. Defaults to
                :func:`parrot.flows.dev_loop.flow.build_dev_loop_flow`,
                imported lazily so constructing the toolkit stays cheap.
            flow_kwargs: Forwarded to ``flow_builder`` (toolkits,
                dispatchers, repos, ...). The gate flags are set per
                approval mode and must not be passed here.
            runner_kwargs: Forwarded to :class:`DevLoopRunner`.
            brief_enricher: Optional :class:`BriefEnricher`.
            default_reporter: ``WorkBrief.reporter`` when the caller gives
                none — an agent-started run still needs an author.
            default_assignee: ``WorkBrief.escalation_assignee`` default.
            default_approval_mode: Approval mode when the caller gives none.
                Defaults to ``"every_step"`` so a run starts locked down and
                the autonomy decision can be made after the plan is seen
                (see the module docstring).
            gate_poll_seconds: How often the watcher checks for gates to
                auto-approve on a run set to autonomous.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._flow_builder = flow_builder
        self._flow_kwargs = dict(flow_kwargs or {})
        self._runner_kwargs = dict(runner_kwargs or {})
        self._enricher = brief_enricher
        self._default_reporter = default_reporter
        self._default_assignee = default_assignee
        self._default_mode: ApprovalMode = default_approval_mode
        #: One runner per approval mode — the gates are compiled into the flow.
        self._runners: Dict[str, DevLoopRunner] = {}
        #: run_id -> bookkeeping for the runs this toolkit started.
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._watchers: Dict[str, asyncio.Task] = {}
        self._gate_poll_seconds = gate_poll_seconds
        overlap = set(self._flow_kwargs) & {
            "require_plan_approval",
            "require_deployment_approval",
        }
        if overlap:
            raise ValueError(
                "flow_kwargs must not set the gate flags "
                f"({', '.join(sorted(overlap))}) — they are derived from "
                "approval_mode per run."
            )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    async def start_dev_loop(
        self,
        summary: str,
        description: str = "",
        kind: str = "bug",
        repo: Optional[str] = None,
        error_text: Optional[str] = None,
        acceptance_commands: Optional[List[str]] = None,
        approval_mode: Optional[str] = None,
        reporter: Optional[str] = None,
        existing_issue_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a dev-loop run for a bug or enhancement, and return its id.

        Runs research, development, QA and PR hand-off. This returns as soon
        as the run is accepted — a run takes minutes, so poll
        ``dev_loop_status`` instead of waiting on this call.

        Approval: with ``approval_mode="plan"`` (the default) the run pauses
        for a human to approve the plan and then finishes on its own; with
        ``"every_step"`` it also pauses before the PR hand-off; with
        ``"none"`` it never pauses. Report the mode back to the user — it
        decides how autonomous the run is.

        Args:
            summary: One-line statement of the problem ("500 on /api/v1/xyz").
            description: Everything else known: steps, expected vs actual.
            kind: ``bug``, ``enhancement`` or ``new_feature``.
            repo: Repository that owns the code. Inferred when omitted and
                an enricher is configured.
            error_text: Pasted stack trace / error body. Attached as an
                ``inline`` log source, which is what the intake and research
                nodes read.
            acceptance_commands: Shell commands QA runs to decide the work
                is done — a criterion is executed, not read, so this takes
                commands (``pytest tests/test_xyz.py``) rather than prose.
                The command head is allow-listed at intake.
            approval_mode: ``plan`` | ``every_step`` | ``none``.
            reporter: Who is asking. Defaults to the configured reporter.
            existing_issue_key: Attach to this Jira issue instead of
                creating one.

        Returns:
            ``{"run_id", "status", "approval_mode", "gates", "brief"}``.

        Raises:
            ValueError: ``kind``/``approval_mode`` invalid, or the brief is
                still incomplete after enrichment.
        """
        mode = self._resolve_mode(approval_mode)
        draft: Dict[str, Any] = {
            "kind": kind,
            "summary": summary,
            "description": description or summary,
            "reporter": reporter or self._default_reporter,
            "escalation_assignee": self._default_assignee,
        }
        if repo:
            draft["affected_component"] = repo
        if existing_issue_key:
            draft["existing_issue_key"] = existing_issue_key
        if error_text:
            draft["log_sources"] = [
                {"kind": "inline", "locator": error_text}
            ]
        if acceptance_commands:
            draft["acceptance_criteria"] = [
                {
                    "kind": "shell",
                    "name": f"acceptance-{index}",
                    "command": command,
                }
                for index, command in enumerate(acceptance_commands, start=1)
            ]

        if self._enricher is not None:
            try:
                draft = await self._enricher.enrich(draft)
            except Exception as exc:  # noqa: BLE001 — enrichment is advisory
                logger.warning(
                    "Brief enrichment failed (%s); continuing with the raw "
                    "report", exc,
                )

        brief = self._validate(draft)
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        runner = self._runner_for(mode)

        self._runs[run_id] = {
            "run_id": run_id,
            "approval_mode": mode,
            "summary": brief.summary,
            "kind": brief.kind,
            "status": "running",
            "result": None,
            "error": None,
            # Set by dev_loop_approve(then="autonomous"): from then on the
            # watcher resolves this run's gates instead of waiting for a human.
            "autonomous": False,
            "auto_approved": [],
            # The runner that started this run. Held here rather than looked
            # up by mode: a run belongs to the runner that launched it, and
            # the mode is only how that runner was chosen.
            "runner": runner,
        }
        task = asyncio.create_task(self._execute(runner, brief, run_id))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t, rid=run_id: self._tasks.pop(rid, None))

        return {
            "run_id": run_id,
            "status": "running",
            "approval_mode": mode,
            "gates": [
                name.replace("require_", "").replace("_approval", "")
                for name, on in _MODE_GATES[mode].items()
                if on
            ],
            "brief": {
                "kind": brief.kind,
                "summary": brief.summary,
                "affected_component": brief.affected_component,
                "log_sources": len(brief.log_sources),
                "acceptance_criteria": len(brief.acceptance_criteria),
            },
        }

    async def dev_loop_status(self, run_id: str) -> Dict[str, Any]:
        """Report where a dev-loop run got to, and what it is waiting for.

        Use the ``run_id`` that ``start_dev_loop`` returned. Pending gates
        are what a human has to act on: pass one to ``dev_loop_approve``.

        Args:
            run_id: The run to inspect.

        Returns:
            ``{"run_id", "status", "phase", "nodes", "pending_gates",
            "error"}``.

        Raises:
            KeyError: This toolkit never started ``run_id``.
        """
        record = self._require_run(run_id)
        out: Dict[str, Any] = {
            "run_id": run_id,
            "status": record["status"],
            "approval_mode": record["approval_mode"],
            "autonomous": record.get("autonomous", False),
            "auto_approved": list(record.get("auto_approved", [])),
            "summary": record["summary"],
            "error": record["error"],
            "phase": None,
            "nodes": {},
            "pending_gates": [],
        }
        runner = record.get("runner")
        host = runner.get_host(run_id) if runner is not None else None
        if host is not None:
            state = host.state
            out["phase"] = getattr(state, "phase", None)
            out["pending_gates"] = [
                {
                    "gate_id": gate_id,
                    "kind": getattr(gate, "kind", None),
                    "prompt": getattr(gate, "prompt", None),
                }
                for gate_id, gate in getattr(state, "gates", {}).items()
                if getattr(gate, "status", None) == "pending"
            ]
        result = record.get("result")
        if result is not None:
            out["nodes"] = {
                node: str(response)[:400]
                for node, response in getattr(result, "responses", {}).items()
            }
        return out

    async def dev_loop_runs(self) -> Dict[str, Any]:
        """List the dev-loop runs this agent has started.

        Returns:
            ``{"runs": [{"run_id", "status", "kind", "summary",
            "approval_mode"}]}``, newest last.
        """
        return {
            "runs": [
                {
                    key: record[key]
                    for key in (
                        "run_id", "status", "kind", "summary", "approval_mode",
                    )
                }
                for record in self._runs.values()
            ]
        }

    async def dev_loop_approve(
        self,
        run_id: str,
        gate_id: str,
        resolution: str = "approved",
        then: str = "ask",
        comment: str = "",
        resolved_by: str = "",
    ) -> Dict[str, Any]:
        """Resolve a pending approval gate so a paused run can continue.

        Get ``gate_id`` from ``dev_loop_status``, which also returns the plan
        the gate is asking about. ``resolution="rejected"`` aborts instead of
        continuing.

        ``then`` is how much of the rest of the run still needs a human, and
        is the decision to put to the user once they have read the plan:
        ``"ask"`` keeps stopping at every later gate, ``"autonomous"`` lets
        the run finish on its own — including opening the PR. Ask before
        choosing ``"autonomous"``; do not assume it.

        Args:
            run_id: The paused run.
            gate_id: The gate to resolve.
            resolution: ``approved`` or ``rejected``.
            then: ``ask`` (default) or ``autonomous``.
            comment: Free-text audit comment.
            resolved_by: Who approved. Defaults to the configured reporter.

        Returns:
            ``{"run_id", "gate_id", "resolution", "then", "sequence"}``.

        Raises:
            KeyError: Unknown run, or the run has no live host.
            ValueError: ``resolution`` or ``then`` is not a valid value.
        """
        if resolution not in ("approved", "rejected"):
            raise ValueError(
                f"resolution must be 'approved' or 'rejected', got {resolution!r}"
            )
        if then not in ("ask", "autonomous"):
            raise ValueError(
                f"then must be 'ask' or 'autonomous', got {then!r}"
            )
        record = self._require_run(run_id)
        runner = record.get("runner")
        if runner is None:  # pragma: no cover - set when the run is created
            raise KeyError(f"no runner for run_id={run_id!r}")
        envelope = await runner.resolve_gate(
            run_id,
            gate_id,
            resolution,
            resolved_by or self._default_reporter,
            comment=comment,
        )
        if resolution == "approved" and then == "autonomous":
            record["autonomous"] = True
            self._ensure_watcher(run_id)
            logger.info(
                "dev-loop run %s continues autonomously; later gates will be "
                "auto-approved", run_id,
            )
        return {
            "run_id": run_id,
            "gate_id": gate_id,
            "resolution": resolution,
            "then": then,
            "sequence": getattr(envelope, "sequence", None),
        }

    async def dev_loop_cancel(
        self, run_id: str, requested_by: str = ""
    ) -> Dict[str, Any]:
        """Request cancellation of a running dev-loop run.

        Args:
            run_id: The run to cancel.
            requested_by: Who asked. Defaults to the configured reporter.

        Returns:
            ``{"run_id", "cancelled"}``.

        Raises:
            KeyError: Unknown run, or the run has no live host.
        """
        record = self._require_run(run_id)
        runner = record.get("runner")
        if runner is None:  # pragma: no cover - set when the run is created
            raise KeyError(f"no runner for run_id={run_id!r}")
        await runner.cancel_run(run_id, requested_by or self._default_reporter)
        record["status"] = "cancelled"
        return {"run_id": run_id, "cancelled": True}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_mode(self, approval_mode: Optional[str]) -> str:
        """Validate an approval mode, falling back to the configured default."""
        mode = approval_mode or self._default_mode
        if mode not in _MODE_GATES:
            raise ValueError(
                f"approval_mode must be one of {sorted(_MODE_GATES)}, "
                f"got {mode!r}"
            )
        return mode

    def _validate(self, draft: Dict[str, Any]) -> WorkBrief:
        """Validate the draft, or say what is missing and who fills it.

        ``affected_component`` and ``acceptance_criteria`` are required and
        have no defaults, so a one-line report never validates on its own.
        Pydantic's raw error is poor guidance for a caller (and worse for a
        model deciding what to do next), so it is translated into the
        question that actually needs answering.

        Args:
            draft: Partial ``WorkBrief`` kwargs.

        Returns:
            The validated brief.

        Raises:
            ValueError: The brief is incomplete, naming each missing field
                and how to supply it.
        """
        from pydantic import ValidationError

        try:
            return WorkBrief.model_validate(draft)
        except ValidationError as exc:
            hints = {
                "affected_component": (
                    "which repository/service owns the code — pass `repo`"
                ),
                "acceptance_criteria": (
                    "how to verify the fix — pass `acceptance_commands`, e.g. "
                    "['pytest tests/test_xyz.py']"
                ),
            }
            missing = [
                str(err["loc"][0])
                for err in exc.errors()
                if err.get("type") == "missing" and err.get("loc")
            ]
            if not missing:
                raise
            detail = "; ".join(
                f"{field} ({hints.get(field, 'required')})" for field in missing
            )
            enricher = (
                "" if self._enricher is not None else
                " No brief enricher is configured, so nothing can infer these."
            )
            raise ValueError(
                f"The report is not specific enough to start a run. Missing: "
                f"{detail}.{enricher}"
            ) from exc

    def _require_run(self, run_id: str) -> Dict[str, Any]:
        """Look up a run this toolkit started, or fail with the known ids."""
        record = self._runs.get(run_id)
        if record is None:
            known = ", ".join(self._runs) or "none"
            raise KeyError(f"unknown run_id={run_id!r} (known: {known})")
        return record

    def _ensure_watcher(self, run_id: str) -> None:
        """Start the task that auto-approves this run's remaining gates.

        Polls rather than subscribing to the event stream: the gate set is
        small, the run already takes minutes, and a poll needs no Redis and
        no ordering guarantees. Idempotent — a second call is a no-op while
        the first watcher is alive.

        Args:
            run_id: The run to watch.
        """
        existing = self._watchers.get(run_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._watch_gates(run_id))
        self._watchers[run_id] = task
        task.add_done_callback(lambda _t, rid=run_id: self._watchers.pop(rid, None))

    async def _watch_gates(self, run_id: str) -> None:
        """Approve gates on an autonomous run until it finishes.

        Stops as soon as the run leaves ``running``, so a finished or
        cancelled run does not leave a task polling forever.

        Args:
            run_id: The run to watch.
        """
        record = self._runs.get(run_id)
        if record is None:  # pragma: no cover - watcher starts after the record
            return
        runner = record.get("runner")
        while record.get("autonomous") and record.get("status") == "running":
            await asyncio.sleep(self._gate_poll_seconds)
            host = runner.get_host(run_id) if runner is not None else None
            if host is None:
                continue
            pending = [
                gate_id
                for gate_id, gate in getattr(host.state, "gates", {}).items()
                if getattr(gate, "status", None) == "pending"
            ]
            for gate_id in pending:
                try:
                    await runner.resolve_gate(
                        run_id,
                        gate_id,
                        "approved",
                        self._default_reporter,
                        comment="auto-approved: run set to autonomous",
                    )
                except Exception as exc:  # noqa: BLE001 — see below
                    # A gate that expired or was resolved by a human in the
                    # meantime is not our problem; anything else would only
                    # be surfaced as an unretrieved task exception.
                    logger.info(
                        "could not auto-approve gate %s on %s: %s",
                        gate_id, run_id, exc,
                    )
                    continue
                record["auto_approved"].append(gate_id)
                logger.info("auto-approved gate %s on run %s", gate_id, run_id)

    def _runner_for(self, mode: str) -> DevLoopRunner:
        """Return (building once) the runner whose flow carries ``mode``'s gates.

        The gate flags are compiled into the flow by ``build_dev_loop_flow``,
        so a mode change needs a different flow — hence one runner per mode
        rather than one per run.
        """
        runner = self._runners.get(mode)
        if runner is not None:
            return runner
        builder = self._flow_builder
        if builder is None:
            from parrot.flows.dev_loop.flow import build_dev_loop_flow

            builder = build_dev_loop_flow
        flow = builder(**self._flow_kwargs, **_MODE_GATES[mode])
        runner = DevLoopRunner(flow, **self._runner_kwargs)
        self._runners[mode] = runner
        return runner

    async def _execute(
        self, runner: DevLoopRunner, brief: WorkBrief, run_id: str
    ) -> None:
        """Run the flow to completion, recording the outcome on the record.

        Failures are recorded, never raised: nothing awaits this task, so an
        escaping exception would only surface as "Task exception was never
        retrieved" long after the fact.
        """
        record = self._runs[run_id]
        try:
            result = await runner.run(brief, run_id=run_id)
            record["result"] = result
            record["status"] = getattr(result, "status", "finished")
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.exception("dev-loop run %s failed", run_id)
            record["status"] = "failed"
            record["error"] = str(exc)
