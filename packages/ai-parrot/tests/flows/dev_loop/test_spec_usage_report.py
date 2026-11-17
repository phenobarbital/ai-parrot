"""FEAT-783 AC-12 — per-spec report."""

import pytest

from parrot.flows.dev_loop.usage_report import (
    build_spec_usage_report,
    build_usage_report,
    render_usage_html,
    render_usage_markdown,
)
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.run_ledger import RunLedgerRecorder

FEAT = "FEAT-783"


def _row(**kw) -> UsageRecord:
    kw.setdefault("feat_id", FEAT)
    return UsageRecord(provider=kw.pop("provider", "anthropic"), **kw)


def _rows() -> list[UsageRecord]:
    return [
        _row(
            task_id="TASK-1",
            model="m-a",
            roster_seat="claude",
            attempt_uid="a1",
            input_tokens=100,
            output_tokens=10,
            cost_usd=0.5,
        ),
        _row(
            task_id="TASK-1",
            model="m-a",
            roster_seat="claude",
            attempt_uid="a1",
            input_tokens=50,
            output_tokens=5,
            cost_usd=0.25,
        ),
        _row(
            task_id="TASK-1",
            model="m-b",
            roster_seat="codex",
            attempt_uid="a2",
            input_tokens=10,
            output_tokens=1,
            equivalent_usd=1.0,
            provider="openai",
        ),
        _row(
            task_id="TASK-2",
            model="m-b",
            roster_seat="codex",
            attempt_uid="a3",
            input_tokens=999,
            output_tokens=999,
            usage_reported=False,
        ),
        _row(model="m-a", input_tokens=1, output_tokens=1),
    ]


def test_groups_by_task_model_seat() -> None:
    by_task = {a.seat: a for a in build_spec_usage_report(_rows(), FEAT, by="task").agents}
    assert set(by_task) == {"TASK-1", "TASK-2", "(unattributed)"}
    t1 = by_task["TASK-1"]
    assert (t1.input_tokens, t1.output_tokens, t1.rounds) == (160, 16, 2)
    assert t1.cost_usd == pytest.approx(0.75)
    assert t1.equivalent_usd == pytest.approx(1.0)
    assert t1.node_id == FEAT
    t2 = by_task["TASK-2"]
    assert t2.input_tokens is None and t2.output_tokens is None
    assert t2.cost_usd is None

    by_model = {a.seat: a for a in build_spec_usage_report(_rows(), FEAT, by="model").agents}
    assert set(by_model) == {"m-a", "m-b"}
    assert by_model["m-a"].input_tokens == 151

    report = build_spec_usage_report(_rows(), FEAT, by="seat")
    by_seat = {a.seat: a for a in report.agents}
    assert set(by_seat) == {"claude", "codex", "(unattributed)"}
    assert by_seat["codex"].rounds == 2
    assert report.run_id == FEAT
    assert report.total_input_tokens == 161
    assert report.total_cost_usd == pytest.approx(0.75)
    md = render_usage_markdown(report)
    assert "| Cost | Equivalent |" in md and "$0.7500" in md
    assert "<th>Cost</th>" in render_usage_html(report)


def test_source_and_cumulative_cost_never_summed() -> None:
    rows = [
        _row(task_id="T", cost_usd=0.1, source_cost_usd=100.0, cumulative_cost_usd=1000.0),
        _row(task_id="T", cost_usd=0.2, source_cost_usd=200.0, cumulative_cost_usd=2000.0),
    ]
    report = build_spec_usage_report(rows, FEAT)
    assert report.agents[0].cost_usd == pytest.approx(0.3)
    assert report.total_cost_usd == pytest.approx(0.3)
    assert report.total_equivalent_usd is None


def test_other_features_rows_excluded_and_bad_by_raises() -> None:
    rows = [_row(task_id="T", input_tokens=5), _row(task_id="T", input_tokens=7, feat_id="FEAT-1")]
    report = build_spec_usage_report(rows, FEAT)
    assert report.total_input_tokens == 5
    assert build_spec_usage_report([], FEAT).agents == []
    with pytest.raises(ValueError):
        build_spec_usage_report(rows, FEAT, by="node")


@pytest.mark.asyncio
async def test_run_report_render_unchanged_without_cost() -> None:
    ledger = RunLedgerRecorder(run_id="run-1")
    await ledger.record(
        UsageRecord(provider="nova", model="m", seat="qa", node_id="qa", input_tokens=3, output_tokens=2)
    )
    report = build_usage_report(ledger, run_id="run-1")
    assert report.total_cost_usd is None
    md = render_usage_markdown(report)
    assert "| Seat | Node | Backend | Model | Rounds | Tokens | Duration |\n" in md
    assert "Cost" not in md and "cost:" not in md
    html = render_usage_html(report)
    assert "Cost" not in html and "cost:" not in html
