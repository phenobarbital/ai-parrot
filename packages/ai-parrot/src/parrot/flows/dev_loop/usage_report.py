"""UsageReport — per-agent-seat usage view (FEAT-405 Module 7, rebuilt on
the FEAT-479 per-run ledger).

``run_bundle.py`` already renders a per-**node** table with token columns,
but there is no per-**agent** view: which seat spent what, on which model,
over how many rounds/cycles. This module introduces :class:`UsageReport` as
the single source of truth for ``usage.json``, the markdown section folded
into the run bundle, and the standalone HTML page (TASK-2091) — all three
views are rendered from the same model so they cannot disagree.

FEAT-479 Module 7a: the builder now reads from a
:class:`~parrot.observability.recorders.run_ledger.RunLedgerRecorder`
instead of session-state's ``Snapshot``. The ledger is append-only (retry
cycles accumulate rather than overwrite — Finding 2) and keys seats by a
free string (pool-worker seats like ``"development.w1"`` are first-class —
Finding 3), so the previous single-worker-model heuristic
(``_single_worker_summary_for_node``) is obsolete: the model now arrives as
real per-cycle data, never a guess.

Pure **consumer**: no filesystem, no Redis, no network — only summing
already-final per-seat numbers already accumulated by the ledger.
"""

from __future__ import annotations

import time
from html import escape
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot.flows.dev_loop.run_bundle import _sum_optional_float, _sum_optional_int
from parrot.observability.recorders.run_ledger import RunLedgerRecorder, SeatUsage


class _Frozen(BaseModel):
    """Shared base for usage-report models (mirrors ``run_bundle._Frozen``:
    frozen and closed — no silent extra fields, no post-construction
    mutation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CycleUsage(_Frozen):
    """One retained ledger record for a seat — one dispatch/LLM-call cycle.

    ``cycle`` is the ledger's 1-based attempt index within ``(run_id,
    seat)`` (``RunLedgerRecorder.next_cycle``); appends never overwrite, so
    every retry round for a seat is retained here (Finding 2).
    """

    cycle: int
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    status: str = "completed"
    error_type: str = ""


class AgentUsage(_Frozen):
    """One agent seat's usage, rolled up across its cycles.

    ``seat`` is the run's accounting seat — a node id (``"qa"``) or a
    pool-worker id (``"development.w1"``); ``node_id`` is the roll-up
    owner (``"development.w1"`` rolls up to ``"development"``). Unlike
    the pre-FEAT-479 session-state-sourced report, pool-worker seats are
    first-class rows here, each with its own real model (Finding 3).
    ``None`` (never ``0``) when a field is unreported across every cycle.
    """

    seat: str
    node_id: str
    backend: str = ""
    model: str = ""
    rounds: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    cycles: list[CycleUsage] = Field(default_factory=list)
    failures: int = 0


class UsageReport(_Frozen):
    """Single source of truth for ``usage.json``, markdown and HTML."""

    run_id: str
    generated_at: float = Field(default_factory=time.time)
    agents: list[AgentUsage] = Field(default_factory=list)
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_rounds: int | None = None
    # FEAT-479 §8 Q1: a resumed run whose in-memory ledger was lost
    # (cross-process resume) labels itself partial rather than silently
    # presenting a short total as complete.
    partial: bool = False
    partial_reason: str = ""


# ─────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────


def _ordered_seats(seats: list[SeatUsage]) -> list[SeatUsage]:
    """Stable seat order: parent node first, then its workers.

    Groups seats by ``node_id`` in first-appearance order (so the
    renderer's node grouping matches actual dispatch order across runs),
    and within a group puts the bare node (``seat == node_id``) before its
    pool workers, sorted by seat name (``"development.w1"`` before
    ``"development.w2"``).
    """
    node_order: dict[str, int] = {}
    for su in seats:
        node_order.setdefault(su.node_id, len(node_order))

    def _key(su: SeatUsage) -> tuple[int, bool, str]:
        is_worker = su.seat != su.node_id
        return (node_order[su.node_id], is_worker, su.seat)

    return sorted(seats, key=_key)


def build_usage_report(ledger: RunLedgerRecorder, run_id: str) -> UsageReport:
    """Assemble a :class:`UsageReport` from a run's usage ledger.

    Pure — no filesystem, no Redis, no network. One :class:`AgentUsage` per
    seat the ledger retained a record for; a run with an empty ledger
    (nothing dispatched, or nothing reported usage) still returns a valid,
    empty report rather than raising.

    Node → cycle → worker granular (FEAT-479, superseding the FEAT-405
    node-granular-only shape): pool-worker seats
    (``"development.w1"``/``"development.w2"``/...) are retained as their
    own rows, each carrying its own real model — the ledger's ``seat`` is a
    free string (spec Module 2), not the closed ``session_state.NodeId``
    ``Literal`` that silently dropped them before. Every retained cycle for
    a seat is exposed via ``AgentUsage.cycles`` (retry rounds accumulate,
    never overwrite — Finding 2's fix).

    Sums (``AgentUsage.input_tokens``/``.output_tokens``/``UsageReport.
    total_*``) come straight from ``RunLedgerRecorder.by_seat()``, which
    already skips ``usage_reported=False`` cycles rather than coercing —
    an all-unreported seat totals ``None``, never a fabricated ``0``.

    Args:
        ledger: The run's :class:`RunLedgerRecorder`. Callers detecting a
            missing ledger (e.g. a cross-process resume that lost the
            in-memory ledger, spec §8 Q1) should pass a fresh, empty
            ledger with ``mark_partial(...)`` already called, rather than
            omitting the argument — this function has no "missing ledger"
            branch of its own; ``ledger.partial``/``.partial_reason`` are
            read straight through onto the report.
        run_id: The run id (also present on ``ledger.run_id``, threaded
            explicitly so a caller can build a report for a
            differently-run_id-tagged view if ever needed).

    Returns:
        The assembled :class:`UsageReport`.
    """
    agents: list[AgentUsage] = []
    for seat_usage in _ordered_seats(ledger.by_seat()):
        cycles = [
            CycleUsage(
                cycle=record.cycle or 0,
                model=record.model,
                input_tokens=record.input_tokens if record.usage_reported else None,
                output_tokens=record.output_tokens if record.usage_reported else None,
                duration_seconds=(
                    record.duration_ms / 1000.0 if record.duration_ms else None
                ),
                status=record.status,
                error_type=record.error_type or "",
            )
            for record in seat_usage.cycles
        ]
        agents.append(
            AgentUsage(
                seat=seat_usage.seat,
                node_id=seat_usage.node_id,
                backend=seat_usage.provider,
                model=seat_usage.model,
                rounds=seat_usage.rounds,
                input_tokens=seat_usage.input_tokens,
                output_tokens=seat_usage.output_tokens,
                duration_seconds=_sum_optional_float(
                    [c.duration_seconds for c in cycles]
                ),
                cycles=cycles,
                failures=seat_usage.failures,
            )
        )

    return UsageReport(
        run_id=run_id,
        agents=agents,
        total_input_tokens=_sum_optional_int([a.input_tokens for a in agents]),
        total_output_tokens=_sum_optional_int([a.output_tokens for a in agents]),
        total_rounds=_sum_optional_int([a.rounds for a in agents]),
        partial=ledger.partial,
        partial_reason=ledger.partial_reason,
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
    appear anywhere (spec Non-Goal). A ``partial`` report (§8 Q1) carries a
    visible marker so a short total is never presented as complete.

    Args:
        report: The assembled :class:`UsageReport`.

    Returns:
        The markdown section, including its own ``## Usage`` heading.
    """
    lines: list[str] = ["## Usage", ""]
    if report.partial:
        reason = report.partial_reason or "reason unknown"
        lines.append(f"⚠️ **Partial usage report** — {reason}")
        lines.append("")

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
    appears anywhere (spec Non-Goal). A ``partial`` report (§8 Q1) carries
    a visible marker.

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
    partial_banner = ""
    if report.partial:
        reason = escape(report.partial_reason or "reason unknown")
        partial_banner = (
            f'<p style="color:#b45309"><strong>⚠️ Partial usage report</strong> '
            f"— {reason}</p>"
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
{partial_banner}
{body_table}
{totals}
</body>
</html>"""


__all__ = [
    "AgentUsage",
    "CycleUsage",
    "UsageReport",
    "build_usage_report",
    "render_usage_html",
    "render_usage_markdown",
]
