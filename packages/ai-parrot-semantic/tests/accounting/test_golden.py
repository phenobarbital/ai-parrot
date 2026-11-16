"""FEAT-713 M5 — golden SQL and plans. REGENERATE_GOLDENS=1 rewrites the files."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from parrot.semantic.accounting.compiler import compile_assertion, compile_metric, plan_assertion, plan_metric
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.models import AccountingModel, AssertionRequest, MetricPlan, MetricRequest

GOLDEN = Path(__file__).parent / "golden"
REGENERATE = os.environ.get("REGENERATE_GOLDENS") == "1"
CASES = {
    "revenue_by_entity_month": {
        "kind": "metric",
        "metric": "revenue",
        "grain": "month",
        "dimensions": ["entity"],
        "period": {"from": "2025-01-01", "to": "2025-06-30"},
    },
    "gross_margin_pct_month": {
        "kind": "metric",
        "metric": "gross_margin_pct",
        "grain": "month",
        "period": {"from": "2025-01-01", "to": "2025-06-30"},
    },
    "ebitda_ytd_month": {
        "kind": "metric",
        "metric": "ebitda",
        "grain": "month",
        "period": {"from": "2025-03-15", "to": "2025-06-30", "cumulative": "ytd"},
    },
    "assertion_0": {
        "kind": "assertion",
        "assertion_index": 0,
        "period": {"from": "2025-01-01", "to": "2025-03-31"},
    },
}


def _request(case: str) -> MetricRequest | AssertionRequest:
    data = CASES[case]
    if data["kind"] == "assertion":
        return AssertionRequest.model_validate(data)
    return MetricRequest.model_validate(data)


def _plan(model: AccountingModel, case: str) -> MetricPlan:
    request = _request(case)
    if isinstance(request, AssertionRequest):
        return plan_assertion(model, request)
    return plan_metric(model, request)


def _sql(model: AccountingModel, case: str, dialect: str) -> str:
    request = _request(case)
    if isinstance(request, AssertionRequest):
        return compile_assertion(model, request, dialect).sql
    return compile_metric(model, request, dialect).sql


def _compare(path: Path, actual: str) -> None:
    if REGENERATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"missing golden file {path}; run with REGENERATE_GOLDENS=1 and review it"
    assert path.read_text(encoding="utf-8") == actual, f"{path.name} differs from its golden file"


def test_plan_golden(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    for case in CASES:
        plan = _plan(model, case)
        text = json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        _compare(GOLDEN / "plans" / f"{case}.json", text)
        assert MetricPlan.model_validate_json((GOLDEN / "plans" / f"{case}.json").read_text(encoding="utf-8")) == plan


@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "bigquery"])
def test_compile_golden(dialect: str, troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    for case in CASES:
        _compare(GOLDEN / dialect / f"{case}.sql", _sql(model, case, dialect) + "\n")
