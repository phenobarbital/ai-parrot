"""UsageReport — per-agent-seat usage view (FEAT-405 Module 7).

``run_bundle.py`` already renders a per-**node** table with token columns,
but there is no per-**agent** view: which seat spent what, on which model,
over how many rounds. This module introduces :class:`UsageReport` as the
single source of truth for ``usage.json``, the markdown section folded
into the run bundle, and the standalone HTML page (TASK-2091) — all three
views are rendered from the same model so they cannot disagree.

Pure **consumer**: rounds/tokens arrive already-final from
:class:`~parrot.flows.dev_loop.session_state.DispatchState` (populated by
the dispatch-telemetry harvest, itself fed by the per-round
``ClientRoundEvent``s TASK-2089 emits — no re-accumulation happens here,
only summing already-final per-agent numbers for the totals row).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from html import escape
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot.flows.dev_loop.run_bundle import _sum_optional_int
from parrot.flows.dev_loop.session_state import Snapshot


class _Frozen(BaseModel):
    """Shared base for usage-report models (mirrors ``run_bundle._Frozen``:
    frozen and closed — no silent extra fields, no post-construction
    mutation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentUsage(_Frozen):
    """One agent seat's usage. ``None`` (never ``0``) when unreported.

    ``seat`` is the run's ``node_id`` for that agent — the same identity
    :class:`~parrot.flows.dev_loop.run_bundle.NodeReport` already uses
    (``"development"``, ``"qa"``, ...). See :func:`build_usage_report`'s
    docstring for why this is node-granular rather than per-pool-worker
    granular (``session_state.NodeId`` is a closed ``Literal`` of the 12
    fixed flow nodes — a ``DevAgentPool`` worker's dispatch events, keyed
    by ``"development.w1"``/``"development.w2"``/..., cannot validate
    against it and never reach session state).
    """

    seat: str
    node_id: str
    backend: str = ""
    model: str = ""
    rounds: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    duration_seconds: float | None = None


class UsageReport(_Frozen):
    """Single source of truth for ``usage.json``, markdown and HTML."""

    run_id: str
    generated_at: float = Field(default_factory=time.time)
    agents: list[AgentUsage] = Field(default_factory=list)
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_rounds: int | None = None


# ─────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────


def _single_worker_summary_for_node(
    node_id: str, shared: Mapping[str, Any] | None
) -> Any | None:
    """Best-effort ``WorkerSummary`` lookup for *node_id* (``models/base.py``).

    ``DispatchState`` carries no ``model`` field, so ``WorkerSummary``
    (populated onto ``shared["development_output"].worker_summaries`` by a
    ``DevAgentPool`` wave) is the only place a worker's ``agent``/``model``
    is recorded at all. But ``WorkerSummary.worker_id`` values
    (``"development.w1"``, ``"development.w2"``, ...) are per-*worker*,
    while ``node_id`` here is per-*node* (Snapshot has no per-worker
    breakdown — see :func:`build_usage_report`). Returns a match only when
    **exactly one** worker's id starts with ``"{node_id}."`` (the common
    pool-size-1 case, where attribution is unambiguous); returns ``None``
    — never a guess — for a genuinely multi-worker pool, where no single
    worker's model can honestly represent the node's aggregate telemetry.
    """
    if not shared:
        return None
    development_output = shared.get("development_output")
    worker_summaries = getattr(development_output, "worker_summaries", None) or []
    matches = [ws for ws in worker_summaries if ws.worker_id.startswith(f"{node_id}.")]
    return matches[0] if len(matches) == 1 else None


def build_usage_report(
    snapshot: Snapshot,
    run_id: str,
    *,
    shared: Mapping[str, Any] | None = None,
) -> UsageReport:
    """Assemble a :class:`UsageReport` from a run's terminal state.

    Pure — no filesystem, no Redis, no network. One :class:`AgentUsage`
    per **node** that actually dispatched (``node.dispatch is not None``);
    a run with no reporting dispatchers still returns a valid, empty
    report.

    Node-granular, not per-pool-worker granular (spec §8 open question,
    resolved): ``session_state.NodeId`` is a closed ``Literal`` of the 12
    fixed flow nodes, and every dispatch/node-lifecycle session-state
    action is typed to it. ``DevAgentPool`` workers dispatch under
    ``node_id="development.w1"``/``"development.w2"``/... (``agent_pool.
    py``'s ``worker_id`` scheme) — those never validate against
    ``NodeId``, so the dual-publish shim
    (``dispatchers/_shared.py::_apply_to_session_host``) silently drops
    them (by design: "the shim must never break a dispatch") and they
    never reach ``Snapshot.state.nodes``. A future feature widening
    ``NodeId`` (or adding a separate per-worker session-state channel)
    could raise this to per-worker granularity without changing this
    function's shape; today, ``seat`` is honestly the same node-level
    identity :class:`~parrot.flows.dev_loop.run_bundle.NodeReport`
    already uses.

    Args:
        snapshot: The run's terminal :class:`Snapshot` (same source
            :func:`~parrot.flows.dev_loop.run_bundle.build_run_bundle`
            reads for its per-node view).
        run_id: The run id (also present on ``snapshot.state.run_id``,
            threaded explicitly so a caller can build a report for a
            differently-run_id-tagged view if ever needed).
        shared: Optional flow ``ctx.shared_data`` at run-close. When it
            carries a ``development_output`` with pool
            ``worker_summaries``, and *exactly one* worker's id belongs to
            a given node (the common pool-size-1 case), that worker's
            ``agent``/``model`` supplies the node's — ``DispatchState``
            alone has no ``model`` field. A genuinely multi-worker pool
            leaves the node's ``model`` blank (renders ``—``) rather than
            guessing which worker's model to show.

    Returns:
        The assembled :class:`UsageReport`.
    """
    agents: list[AgentUsage] = []
    for node_id, node in snapshot.state.nodes.items():
        dispatch = node.dispatch
        if dispatch is None:
            continue

        worker_summary = _single_worker_summary_for_node(node_id, shared)
        backend = (
            worker_summary.agent if worker_summary is not None else dispatch.dispatcher
        )
        model = worker_summary.model if worker_summary is not None else ""

        duration_seconds: float | None = None
        if dispatch.started_at is not None and dispatch.finished_at is not None:
            duration_seconds = dispatch.finished_at - dispatch.started_at

        agents.append(
            AgentUsage(
                seat=node_id,
                node_id=node_id,
                backend=backend,
                model=model,
                rounds=dispatch.num_turns,
                input_tokens=dispatch.input_tokens,
                output_tokens=dispatch.output_tokens,
                cache_creation_input_tokens=dispatch.cache_creation_input_tokens,
                cache_read_input_tokens=dispatch.cache_read_input_tokens,
                duration_seconds=duration_seconds,
            )
        )

    return UsageReport(
        run_id=run_id,
        agents=agents,
        total_input_tokens=_sum_optional_int([a.input_tokens for a in agents]),
        total_output_tokens=_sum_optional_int([a.output_tokens for a in agents]),
        total_rounds=_sum_optional_int([a.rounds for a in agents]),
    )


# ─────────────────────────────────────────────────────────────────────
# Renderer — markdown
# ─────────────────────────────────────────────────────────────────────


def _fmt_value(value: Any | None) -> str:
    """Render *value*, or ``—`` when unreported. Never fabricates ``0``."""
    return "—" if value is None else str(value)


def _fmt_agent_tokens(agent: AgentUsage) -> str:
    """Render one agent's token cell — ``—`` when neither is reported."""
    if agent.input_tokens is None and agent.output_tokens is None:
        return "—"
    return f"{agent.input_tokens if agent.input_tokens is not None else '—'} in / " \
           f"{agent.output_tokens if agent.output_tokens is not None else '—'} out"


def render_usage_markdown(report: UsageReport) -> str:
    """Render *report* as a markdown section (folded into the run bundle).

    Never renders ``None``/unreported values as ``0`` — they render as
    ``—`` (em dash), including in the totals row. No pricing/cost figures
    appear anywhere (spec Non-Goal).

    Args:
        report: The assembled :class:`UsageReport`.

    Returns:
        The markdown section, including its own ``## Usage`` heading.
    """
    lines: list[str] = ["## Usage", ""]

    if not report.agents:
        lines.append("_No agent usage reported for this run._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Seat | Node | Backend | Model | Rounds | Tokens | Duration |")
    lines.append("|---|---|---|---|---|---|---|")
    for agent in report.agents:
        duration = (
            f"{agent.duration_seconds:.1f}s" if agent.duration_seconds is not None else "—"
        )
        lines.append(
            f"| {agent.seat} | {agent.node_id} | {agent.backend or '—'} "
            f"| {agent.model or '—'} | {_fmt_value(agent.rounds)} "
            f"| {_fmt_agent_tokens(agent)} | {duration} |"
        )
    lines.append("")
    lines.append(
        f"**Totals** — rounds: {_fmt_value(report.total_rounds)}, "
        f"input tokens: {_fmt_value(report.total_input_tokens)}, "
        f"output tokens: {_fmt_value(report.total_output_tokens)}"
    )
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Renderer — self-contained HTML (FEAT-405 Module 7b)
# ─────────────────────────────────────────────────────────────────────


def _fmt_value_html(value: Any | None) -> str:
    """Render *value* escaped, or ``—`` when unreported. Never fabricates ``0``."""
    return "—" if value is None else escape(str(value))


def _fmt_agent_tokens_html(agent: AgentUsage) -> str:
    """Render one agent's token cell, escaped — ``—`` when neither is reported."""
    if agent.input_tokens is None and agent.output_tokens is None:
        return "—"
    input_part = escape(str(agent.input_tokens)) if agent.input_tokens is not None else "—"
    output_part = escape(str(agent.output_tokens)) if agent.output_tokens is not None else "—"
    return f"{input_part} in / {output_part} out"


def _html_row(agent: AgentUsage) -> str:
    """One ``<tr>`` for *agent* — same column set as ``render_usage_markdown``
    (Seat, Node, Backend, Model, Rounds, Tokens, Duration). Every
    interpolated value is HTML-escaped — model ids and seat names reach
    this page as data, not trusted markup.
    """
    duration = (
        f"{agent.duration_seconds:.1f}s" if agent.duration_seconds is not None else "—"
    )
    return (
        "<tr>"
        f"<td>{escape(agent.seat)}</td>"
        f"<td>{escape(agent.node_id)}</td>"
        f"<td>{escape(agent.backend) if agent.backend else '—'}</td>"
        f"<td>{escape(agent.model) if agent.model else '—'}</td>"
        f"<td>{_fmt_value_html(agent.rounds)}</td>"
        f"<td>{_fmt_agent_tokens_html(agent)}</td>"
        f"<td>{escape(duration)}</td>"
        "</tr>"
    )


def render_usage_html(report: UsageReport) -> str:
    """Render *report* as a fully self-contained HTML usage report.

    The page inlines all styling and references no external asset (no
    ``<link>``/``<script src>``, no ``@import``, no CDN) — it can be
    opened from disk or attached to a PR comment without breaking. Column
    set and the ``—``-for-unreported convention match
    :func:`render_usage_markdown` exactly, and no pricing/cost figure
    appears anywhere (spec Non-Goal).

    Args:
        report: The assembled :class:`UsageReport`.

    Returns:
        A complete ``<!doctype html>`` … ``</html>`` document.
    """
    rows = "\n".join(_html_row(agent) for agent in report.agents)
    body_table: str
    if not report.agents:
        body_table = "<p>No agent usage reported for this run.</p>"
    else:
        body_table = (
            "<table>"
            "<thead><tr>"
            "<th>Seat</th><th>Node</th><th>Backend</th><th>Model</th>"
            "<th>Rounds</th><th>Tokens</th><th>Duration</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
        )

    totals = (
        "<p><strong>Totals</strong> — "
        f"rounds: {_fmt_value_html(report.total_rounds)}, "
        f"input tokens: {_fmt_value_html(report.total_input_tokens)}, "
        f"output tokens: {_fmt_value_html(report.total_output_tokens)}</p>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dev-loop usage — {escape(report.run_id)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
th {{ background: #f0f0f0; }}
tbody tr:nth-child(even) {{ background: #fafafa; }}
</style>
</head>
<body>
<h1>Dev-loop usage — {escape(report.run_id)}</h1>
{body_table}
{totals}
</body>
</html>"""


__all__ = [
    "AgentUsage",
    "UsageReport",
    "build_usage_report",
    "render_usage_html",
    "render_usage_markdown",
]
