"""RunBundle — pure exportable run summary + markdown closing report.

Implements **Module 8** (v0.2 amendment) of the FEAT-378 spec, step 3.
Everything a "run bundle" needs is already captured by the event-sourced
session state (:class:`~parrot.flows.dev_loop.session_state.SessionHost`)
and the flow's shared state — the terminal
:class:`~parrot.flows.dev_loop.session_state.Snapshot` holds per-node,
dispatch and gate state; the action log supplies the full audit trail;
``shared`` (the flow's ``ctx.shared_data``) carries the rich structured
results (``ResearchOutput``/``PlannerOutput``, ``QAReport``, deployment/
revision/feature-mode results). This module only assembles them.

This module is **pure**: no filesystem, no Redis, no network. TASK-1929
wires :func:`build_run_bundle` / :func:`render_markdown` into the runner
at run-close (writing ``{run_id}.bundle.json`` + ``{run_id}.report.md``).
"""

from __future__ import annotations

import time
from typing import Any, List, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from parrot.flows.dev_loop.nodes.base import run_label
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    GateKind,
    GateStatus,
    NodeStatus,
    RunPhase,
    Snapshot,
)


class _Frozen(BaseModel):
    """Shared base for run-bundle models (mirrors ``session_state._Frozen``:
    frozen and closed — no silent extra fields, no post-construction
    mutation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ─────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────


class NodeReport(_Frozen):
    """Per-node/agent projection for the closing report's agents table."""

    node_id: str
    status: NodeStatus = "idle"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    error: str = ""
    dispatcher: str = ""
    message_count: int = 0
    tool_use_count: int = 0
    # -- telemetry (FEAT-378 TASK-1927's DispatchState fields) --
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    total_cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    duration_ms: Optional[int] = None
    summary: dict = Field(default_factory=dict)


class GateReport(_Frozen):
    """Per-gate projection for the closing report's gate audit trail."""

    kind: GateKind
    node_id: str
    title: str = ""
    status: GateStatus = "pending"
    opened_at: Optional[float] = None
    resolved_at: Optional[float] = None
    resolved_by: str = ""
    comment: str = ""


class CriterionOutcome(_Frozen):
    """One acceptance criterion's outcome (name/passed/duration only —
    QA's full ``CriterionResult`` also carries stdout/stderr tails, which
    the closing report intentionally omits)."""

    name: str
    passed: bool
    duration_seconds: float = 0.0


class DevelopedWork(_Frozen):
    """The "what was developed" section: links, QA/review outcome, tasks."""

    jira_issue_key: str = ""
    pr_url: str = ""
    pr_number: Optional[int] = None
    feature_id: str = ""
    spec_path: str = ""
    worktree_path: str = ""
    branch: str = ""
    task_ids: List[str] = Field(
        default_factory=list,
        description=(
            "TASK-NNN ids completed by the run's dev-agent pool workers "
            "(FEAT-323 `DevelopmentOutput.worker_summaries`), when available. "
            "Empty for the single-agent path (no per-task ids are tracked)."
        ),
    )
    qa_passed: Optional[bool] = None
    lint_passed: Optional[bool] = None
    code_review_passed: Optional[bool] = None
    criteria: List[CriterionOutcome] = Field(default_factory=list)
    code_review_findings: List[str] = Field(default_factory=list)
    docs_artifact_path: str = ""


class RunTotals(_Frozen):
    """Run-wide aggregates. Telemetry fields are ``None`` when NO node
    reported them — a run with no reporting dispatchers must not render
    fake zeros."""

    duration_seconds: Optional[float] = None
    nodes_completed: int = 0
    nodes_failed: int = 0
    nodes_skipped: int = 0
    dispatch_count: int = 0
    message_count: int = 0
    tool_use_count: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_cost_usd: Optional[float] = None


class RunBundle(_Frozen):
    """The full exportable summary of one dev-loop run (any mode)."""

    run_id: str
    mode: str = "initial"
    work_kind: str = ""
    summary: str = ""
    outcome: RunPhase
    created_at: float = 0.0
    finished_at: Optional[float] = None
    totals: RunTotals
    nodes: List[NodeReport] = Field(default_factory=list)
    gates: List[GateReport] = Field(default_factory=list)
    developed: DevelopedWork = Field(default_factory=DevelopedWork)
    action_count: int = 0
    generated_at: float = Field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────


def _sum_optional_int(values: Sequence[Optional[int]]) -> Optional[int]:
    """Sum the non-``None`` values in *values*; ``None`` if none reported."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _sum_optional_float(values: Sequence[Optional[float]]) -> Optional[float]:
    """Sum the non-``None`` values in *values*; ``None`` if none reported."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _primary_output(shared: Mapping[str, Any]) -> Any:
    """Return the run's ``ResearchOutput`` or ``PlannerOutput``, whichever
    is present (feature-mode runs carry ``planner_output`` instead of
    ``research_output`` — both share the ``feat_id``/``spec_path``/
    ``worktree_path``/``branch_name`` field shape)."""
    return shared.get("planner_output") or shared.get("research_output")


def _dict_or_empty(value: Any) -> Mapping[str, Any]:
    """Return *value* if it's a mapping, else ``{}`` (defensive — the
    ``deployment_result``/``revision_result`` shared keys are plain dicts
    when present, per ``nodes/close.py``'s own ``shared.get(...) or {}``
    pattern)."""
    return value if isinstance(value, Mapping) else {}


def build_run_bundle(
    snapshot: Snapshot,
    envelopes: Sequence[ActionEnvelope],
    shared: Mapping[str, Any],
) -> RunBundle:
    """Assemble a :class:`RunBundle` from a run's terminal state.

    Pure — no filesystem, no Redis, no network. Must build a usable
    bundle even for a failed/cancelled run where most ``shared`` keys are
    absent (only ``mode`` reliably has a value).

    Args:
        snapshot: The run's terminal :class:`Snapshot` (authoritative
            node/gate/link state — the source for links like
            ``jira_issue_key``/``pr_url``, already folded via
            ``RunClosed`` at run-close).
        envelopes: The full action-envelope log (only its length is used
            today — ``action_count``).
        shared: The flow's ``ctx.shared_data`` at run-close. Every key is
            optional and read defensively (``.get``, duck-typed): a
            failed/cancelled run may only have ``mode``.

    Returns:
        The assembled :class:`RunBundle`.
    """
    state = snapshot.state

    # -- per-node reports --
    node_reports: List[NodeReport] = []
    for node_id, node in state.nodes.items():
        dispatch = node.dispatch
        duration_seconds: Optional[float] = None
        if node.started_at is not None and node.finished_at is not None:
            duration_seconds = node.finished_at - node.started_at
        node_reports.append(
            NodeReport(
                node_id=node_id,
                status=node.status,
                started_at=node.started_at,
                finished_at=node.finished_at,
                duration_seconds=duration_seconds,
                error=node.error or (dispatch.last_error if dispatch else ""),
                dispatcher=dispatch.dispatcher if dispatch else "",
                message_count=dispatch.message_count if dispatch else 0,
                tool_use_count=dispatch.tool_use_count if dispatch else 0,
                input_tokens=dispatch.input_tokens if dispatch else None,
                output_tokens=dispatch.output_tokens if dispatch else None,
                cache_creation_input_tokens=(dispatch.cache_creation_input_tokens if dispatch else None),
                cache_read_input_tokens=(dispatch.cache_read_input_tokens if dispatch else None),
                total_cost_usd=dispatch.total_cost_usd if dispatch else None,
                num_turns=dispatch.num_turns if dispatch else None,
                duration_ms=dispatch.duration_ms if dispatch else None,
                summary=dict(node.summary),
            )
        )

    # -- gate audit trail --
    gate_reports = [
        GateReport(
            kind=gate.kind,
            node_id=gate.node_id,
            title=gate.title,
            status=gate.status,
            opened_at=gate.opened_at,
            resolved_at=gate.resolved_at,
            resolved_by=gate.resolved_by,
            comment=gate.comment,
        )
        for gate in state.gates.values()
    ]

    # -- totals --
    dispatches = [n.dispatch for n in state.nodes.values() if n.dispatch is not None]
    totals = RunTotals(
        duration_seconds=(state.finished_at - state.created_at if state.finished_at is not None else None),
        nodes_completed=sum(1 for n in state.nodes.values() if n.status == "completed"),
        nodes_failed=sum(1 for n in state.nodes.values() if n.status == "failed"),
        nodes_skipped=sum(1 for n in state.nodes.values() if n.status == "skipped"),
        dispatch_count=len(dispatches),
        message_count=sum(d.message_count for d in dispatches),
        tool_use_count=sum(d.tool_use_count for d in dispatches),
        input_tokens=_sum_optional_int([d.input_tokens for d in dispatches]),
        output_tokens=_sum_optional_int([d.output_tokens for d in dispatches]),
        total_cost_usd=_sum_optional_float([d.total_cost_usd for d in dispatches]),
    )

    # -- "what was developed" --
    primary_output = _primary_output(shared)
    qa_report = shared.get("qa_report")
    deployment_result = _dict_or_empty(shared.get("deployment_result"))
    revision_result = _dict_or_empty(shared.get("revision_result"))
    development_output = shared.get("development_output")

    task_ids: List[str] = []
    worker_summaries = getattr(development_output, "worker_summaries", None) or []
    for worker in worker_summaries:
        task_ids.extend(getattr(worker, "tasks_completed", None) or [])

    criteria = [
        CriterionOutcome(name=c.name, passed=c.passed, duration_seconds=c.duration_seconds)
        for c in (getattr(qa_report, "criterion_results", None) or [])
    ]

    docs_artifact_path = ""
    if state.docs_artifacts:
        docs_artifact_path = state.docs_artifacts[-1].docs_path

    developed = DevelopedWork(
        jira_issue_key=state.jira_issue_key or getattr(primary_output, "jira_issue_key", "") or "",
        pr_url=state.pr_url or "",
        pr_number=deployment_result.get("pr_number") or revision_result.get("pr_number"),
        feature_id=run_label(primary_output, default=""),
        spec_path=getattr(primary_output, "spec_path", "") or "",
        worktree_path=getattr(primary_output, "worktree_path", "") or "",
        branch=getattr(primary_output, "branch_name", "") or "",
        task_ids=task_ids,
        qa_passed=getattr(qa_report, "passed", None),
        lint_passed=getattr(qa_report, "lint_passed", None),
        code_review_passed=getattr(qa_report, "code_review_passed", None),
        criteria=criteria,
        code_review_findings=list(getattr(qa_report, "code_review_findings", None) or []),
        docs_artifact_path=docs_artifact_path,
    )

    mode = "feature" if "planner_output" in shared else str(shared.get("mode", "initial"))

    return RunBundle(
        run_id=state.run_id,
        mode=mode,
        work_kind=state.work_kind,
        summary=state.summary,
        outcome=state.phase,
        created_at=state.created_at,
        finished_at=state.finished_at,
        totals=totals,
        nodes=node_reports,
        gates=gate_reports,
        developed=developed,
        action_count=len(envelopes),
    )


# ─────────────────────────────────────────────────────────────────────
# Renderer
# ─────────────────────────────────────────────────────────────────────


def _format_duration(seconds: Optional[float]) -> str:
    """Render a duration in ``1h 04m 12s`` style; omits zero-value units
    except when the whole duration is under a minute (``"12s"``)."""
    if seconds is None:
        return "n/a"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _format_cost(total_cost_usd: Optional[float]) -> str:
    return f"${total_cost_usd:.4f}" if total_cost_usd is not None else "n/a"


def _format_tokens(input_tokens: Optional[int], output_tokens: Optional[int]) -> str:
    if input_tokens is None and output_tokens is None:
        return "n/a"
    return f"{input_tokens or 0} in / {output_tokens or 0} out"


def render_markdown(bundle: RunBundle, usage_markdown: str = "") -> str:
    """Render *bundle* as the human-readable markdown closing report.

    Omits empty sections (e.g. no gates were opened, no code-review
    findings) and never renders ``None`` as literal text.

    Args:
        bundle: The assembled :class:`RunBundle`.
        usage_markdown: FEAT-405 Module 7 — an optional, already-rendered
            per-agent usage section (from
            :func:`~parrot.flows.dev_loop.usage_report.render_usage_markdown`),
            spliced in verbatim after the agents table. Passed as a
            pre-rendered string rather than importing
            :mod:`~parrot.flows.dev_loop.usage_report` here — that module
            imports helpers from this one, and this keeps the dependency
            one-directional. Empty string (default) omits the section
            entirely — byte-identical to pre-FEAT-405 output.

    Returns:
        The complete markdown document.
    """
    lines: List[str] = []
    d = bundle.developed

    # -- header --
    lines.append(f"# Dev-Loop Run Report — {bundle.run_id}")
    lines.append("")
    lines.append(f"- **Mode**: {bundle.mode}")
    if bundle.work_kind:
        lines.append(f"- **Work kind**: {bundle.work_kind}")
    lines.append(f"- **Outcome**: {bundle.outcome}")
    lines.append(f"- **Duration**: {_format_duration(bundle.totals.duration_seconds)}")
    if bundle.summary:
        lines.append(f"- **Summary**: {bundle.summary}")
    if d.jira_issue_key:
        lines.append(f"- **Jira**: {d.jira_issue_key}")
    if d.pr_url:
        pr_label = f"{d.pr_url}" + (f" (#{d.pr_number})" if d.pr_number else "")
        lines.append(f"- **PR**: {pr_label}")
    lines.append("")

    # -- agents table --
    if bundle.nodes:
        lines.append("## Agents")
        lines.append("")
        lines.append("| Node | Status | Duration | Dispatcher | Msgs | Tools | Tokens | Cost |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for n in bundle.nodes:
            lines.append(
                f"| {n.node_id} | {n.status} | {_format_duration(n.duration_seconds)} "
                f"| {n.dispatcher or 'n/a'} | {n.message_count} | {n.tool_use_count} "
                f"| {_format_tokens(n.input_tokens, n.output_tokens)} "
                f"| {_format_cost(n.total_cost_usd)} |"
            )
        lines.append("")

    # -- per-agent usage (FEAT-405 Module 7) --
    if usage_markdown:
        lines.append(usage_markdown.rstrip("\n"))
        lines.append("")

    # -- gate audit --
    if bundle.gates:
        lines.append("## Gate Audit")
        lines.append("")
        lines.append("| Kind | Node | Status | Resolved by | Comment |")
        lines.append("|---|---|---|---|---|")
        for g in bundle.gates:
            lines.append(f"| {g.kind} | {g.node_id} | {g.status} | {g.resolved_by or 'n/a'} " f"| {g.comment or ''} |")
        lines.append("")

    # -- what was developed --
    has_developed_content = any(
        [
            d.feature_id,
            d.spec_path,
            d.worktree_path,
            d.branch,
            d.task_ids,
            d.qa_passed is not None,
            d.lint_passed is not None,
            d.code_review_passed is not None,
            d.criteria,
            d.code_review_findings,
            d.docs_artifact_path,
        ]
    )
    if has_developed_content:
        lines.append("## What Was Developed")
        lines.append("")
        if d.feature_id:
            lines.append(f"- **Feature**: {d.feature_id}")
        if d.spec_path:
            lines.append(f"- **Spec**: {d.spec_path}")
        if d.worktree_path:
            lines.append(f"- **Worktree**: {d.worktree_path}")
        if d.branch:
            lines.append(f"- **Branch**: {d.branch}")
        if d.task_ids:
            lines.append(f"- **Tasks**: {', '.join(d.task_ids)}")
        if d.docs_artifact_path:
            lines.append(f"- **Docs artifact**: {d.docs_artifact_path}")
        if d.qa_passed is not None:
            lines.append(f"- **QA passed**: {d.qa_passed}")
        if d.lint_passed is not None:
            lines.append(f"- **Lint passed**: {d.lint_passed}")
        if d.code_review_passed is not None:
            lines.append(f"- **Code review passed**: {d.code_review_passed}")
        if d.criteria:
            lines.append("")
            lines.append("### Acceptance Criteria")
            lines.append("")
            lines.append("| Criterion | Passed | Duration |")
            lines.append("|---|---|---|")
            for c in d.criteria:
                lines.append(f"| {c.name} | {c.passed} | {_format_duration(c.duration_seconds)} |")
        if d.code_review_findings:
            lines.append("")
            lines.append("### Code Review Findings")
            lines.append("")
            for finding in d.code_review_findings:
                lines.append(f"- {finding}")
        lines.append("")

    # -- footer --
    lines.append("---")
    lines.append(f"*Generated at {bundle.generated_at}*")

    return "\n".join(lines)


__all__ = [
    "CriterionOutcome",
    "DevelopedWork",
    "GateReport",
    "NodeReport",
    "RunBundle",
    "RunTotals",
    "build_run_bundle",
    "render_markdown",
]
