"""FEAT-713 M4 — snapshots and validation."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
import yaml

from parrot.semantic.accounting.models import AccountingModelSpec, AccountSet, ChartSnapshot, ResolvedSet
from parrot.semantic.accounting.snapshot import snapshot_from_arrow, snapshot_from_manifest, snapshot_from_rows
from parrot.semantic.accounting.validation import metric_order, partition_intervals, validate

D = date(2025, 1, 1)


def _payload(troc_pnl_yaml: Path) -> dict[str, Any]:
    return yaml.safe_load(troc_pnl_yaml.read_text(encoding="utf-8"))


def _resolve(spec: AccountingModelSpec, snapshot: ChartSnapshot) -> dict[str, ResolvedSet]:
    """Minimal selector resolution for the tests (the real one is the loader's, TASK-5529)."""
    ids = [account.account_id for account in snapshot.accounts]
    tags = {account.account_id: account.tags for account in snapshot.accounts}
    resolved: dict[str, ResolvedSet] = {}
    for name, account_set in spec.sets.items():
        members = set(account_set.accounts)
        select = account_set.select
        if select is not None:
            for account in ids:
                if select.prefix is not None and account.startswith(select.prefix):
                    members.add(account)
                if select.range is not None and select.range[0] <= account <= select.range[1]:
                    members.add(account)
                if select.tag is not None and select.tag in tags[account]:
                    members.add(account)
        members -= set(account_set.except_)
        resolved[name] = ResolvedSet(
            name=name,
            accounts=tuple(sorted(members)),
            valid_from=account_set.valid_from,
            valid_to=account_set.valid_to,
        )
    return resolved


def _check(payload: dict[str, Any], snapshot: ChartSnapshot, columns: dict[str, str] | None = None):
    spec = AccountingModelSpec.model_validate(payload)
    return validate(spec, _resolve(spec, snapshot), snapshot, columns)


def _codes(problems) -> list[str]:
    return [problem.code for problem in problems]


def test_partition_intervals() -> None:
    assert partition_intervals({"a": AccountSet(accounts=("1",))}) == ((None, None),)
    assert partition_intervals({"a": AccountSet(accounts=("1",), valid_from=D)}) == ((None, D), (D, None))
    d2, d3 = date(2025, 6, 1), date(2026, 1, 1)
    sets = {
        "a": AccountSet(accounts=("1",), valid_from=D, valid_to=d3),
        "b": AccountSet(accounts=("2",), valid_from=d2, valid_to=d3),
        "c": AccountSet(accounts=("3",), valid_to=D),
    }
    assert partition_intervals(sets) == ((None, D), (D, d2), (d2, d3), (d3, None))


def test_completeness_per_interval(chart_snapshot, troc_pnl_yaml) -> None:
    payload = _payload(troc_pnl_yaml)
    assert _check(payload, chart_snapshot) == []

    del payload["sets"]["d_and_a_legacy"]
    problems = _check(payload, chart_snapshot)
    assert _codes(problems) == ["interval_gap"]
    assert problems[0].interval == (None, D)
    assert problems[0].accounts == ("6810", "6820")

    payload["excluded"] = []
    problems = _check(payload, chart_snapshot)
    unassigned = [p for p in problems if p.code == "unassigned_account"]
    assert [p.interval for p in unassigned] == [(None, D), (D, None)]
    assert all(p.accounts == ("9999",) for p in unassigned)


def test_overlap_and_allow_overlap(chart_snapshot, troc_pnl_yaml) -> None:
    payload = _payload(troc_pnl_yaml)
    payload["sets"]["all_revenue"] = {"select": {"tag": "revenue"}}
    problems = _check(payload, chart_snapshot)
    overlaps = [p for p in problems if p.code == "overlap"]
    # all_revenue vs product_sales and vs returns, in each of the two intervals
    assert len(overlaps) == 4
    assert {p.interval for p in overlaps} == {(None, D), (D, None)}
    assert ("4900",) in [p.accounts for p in overlaps]

    payload["sets"]["all_revenue"]["allow_overlap"] = ["product_sales", "returns"]
    payload["sets"]["product_sales"]["allow_overlap"] = ["all_revenue"]
    payload["sets"]["returns"]["allow_overlap"] = ["all_revenue"]
    assert _check(payload, chart_snapshot) == []

    payload["sets"]["returns"]["allow_overlap"] = []  # one-sided ⇒ still an overlap
    problems = _check(payload, chart_snapshot)
    assert _codes(problems) == ["overlap", "overlap"]
    assert all(p.accounts == ("4900",) for p in problems)


def test_cycle_and_dangling(chart_snapshot, troc_pnl_yaml) -> None:
    payload = _payload(troc_pnl_yaml)
    payload["metrics"]["a"] = {"expr": "b + 1"}
    payload["metrics"]["b"] = {"expr": "a"}
    payload["metrics"]["c"] = {"expr": "sum(nope)"}
    payload["metrics"]["d"] = {"expr": "ghost * 2"}
    payload["metrics"]["e"] = {"expr": "max(x)"}
    payload["sets"]["unused"] = {"select": {"prefix": "77"}}
    problems = _check(payload, chart_snapshot)
    codes = _codes(problems)
    assert codes.count("cycle") == 1
    assert next(p for p in problems if p.code == "cycle").accounts == ("a", "b")
    dangling = [p.message for p in problems if p.code == "dangling_ref"]
    assert len(dangling) == 3
    assert any("'nope'" in message for message in dangling)
    assert any("'ghost'" in message for message in dangling)
    assert any("position" in message for message in dangling)
    assert "selector_no_match" in codes and "empty_set" in codes
    assert problems == sorted(problems, key=lambda p: (p.code, str(p.interval), p.accounts, p.message))

    spec = AccountingModelSpec.model_validate(_payload(troc_pnl_yaml))
    order = metric_order(spec)
    assert set(order) == set(spec.metrics)
    for metric, dependency in [("gross_margin", "revenue"), ("gross_margin", "cogs"), ("ebitda", "opex")]:
        assert order.index(dependency) < order.index(metric)
    assert metric_order(AccountingModelSpec.model_validate(payload))[-2:] == ("a", "b")


def test_nature_checks(chart_snapshot, troc_pnl_yaml) -> None:
    payload = _payload(troc_pnl_yaml)
    payload["chart_of_accounts"]["nature"] = {"accounts": {"4000": "debit"}}
    codes = _codes(_check(payload, chart_snapshot))
    assert "nature_ambiguous" in codes and "nature_missing" in codes

    payload = _payload(troc_pnl_yaml)
    accounts = [a.model_copy(update={"nature": None}) if a.account_id == "4000" else a for a in chart_snapshot.accounts]
    bare = chart_snapshot.model_copy(update={"accounts": tuple(accounts)})
    problems = _check(payload, bare)
    assert _codes(problems) == ["nature_missing"]
    assert problems[0].accounts == ("4000",)


def test_float_amount_and_numeric_type(chart_snapshot, troc_pnl_yaml) -> None:
    payload = _payload(troc_pnl_yaml)
    base = {
        "account_id": "VARCHAR",
        "posting_date": "DATE",
        "entity": "VARCHAR",
        "product_line": "VARCHAR",
        "cost_center": "VARCHAR",
    }
    assert _check(payload, chart_snapshot, {**base, "amount": "DECIMAL(18,2)"}) == []
    assert _check(payload, chart_snapshot, {**base, "amount": "BIGINT"}) == []
    assert _codes(_check(payload, chart_snapshot, {**base, "amount": "DOUBLE"})) == ["float_amount"]
    assert _codes(_check(payload, chart_snapshot, {**base, "amount": "DECIMAL(38,8)"})) == ["numeric_type"]
    assert _codes(_check(payload, chart_snapshot, {**base, "amount": "DECIMAL(40,2)"})) == ["numeric_type"]
    assert _codes(_check(payload, chart_snapshot, {**base, "amount": "NUMERIC(38, 6)"})) == []
    assert _codes(_check(payload, chart_snapshot, {**base, "amount": "VARCHAR"})) == ["numeric_type"]
    missing = {k: v for k, v in base.items() if k != "cost_center"}
    assert _codes(_check(payload, chart_snapshot, missing)) == ["column_missing", "column_missing"]

    payload["chart_of_accounts"]["allow_float"] = True
    assert _check(payload, chart_snapshot, {**base, "amount": "DOUBLE PRECISION"}) == []


def test_snapshot_builders(tmp_path) -> None:
    rows = [
        {"acct": "6000", "nat": "Debit", "parent": "", "tags": "opex, admin"},
        {"acct": "4000", "nat": "CREDIT", "parent": "4", "tags": ["revenue"]},
        {"acct": "9999", "nat": None, "parent": None, "tags": None},
    ]
    taken = date(2026, 10, 1)
    keys = {"account_key": "acct", "nature_column": "nat", "parent_column": "parent", "tags_column": "tags"}
    from_rows = snapshot_from_rows(rows, source="rows", taken_at=taken, **keys)
    assert [a.account_id for a in from_rows.accounts] == ["4000", "6000", "9999"]
    assert from_rows.accounts[1].nature == "debit" and from_rows.accounts[1].tags == ("admin", "opex")
    assert from_rows.accounts[2].nature is None and from_rows.accounts[1].parent_id is None

    arrow_rows = [
        {**row, "tags": row["tags"] if isinstance(row["tags"], str) else ",".join(row["tags"] or [])} for row in rows
    ]
    from_arrow = snapshot_from_arrow(pa.Table.from_pylist(arrow_rows), source="arrow", taken_at=taken, **keys)

    manifest_rows = [
        {"account_id": "4000", "nature": "credit", "parent_id": "4", "tags": ["revenue"]},
        {"account_id": "6000", "nature": "debit", "tags": "admin,opex"},
        {"account_id": "9999"},
    ]
    yaml_path = tmp_path / "chart.yaml"
    yaml_path.write_text(yaml.safe_dump({"taken_at": "2026-10-01", "accounts": manifest_rows}), encoding="utf-8")
    from_yaml = snapshot_from_manifest(yaml_path)
    assert from_yaml.taken_at == taken and from_yaml.source == f"manifest:{yaml_path}"

    csv_path = tmp_path / "chart.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["account_id", "nature", "parent_id", "tags"])
        writer.writeheader()
        writer.writerow({"account_id": "9999", "nature": "", "parent_id": "", "tags": ""})
        writer.writerow({"account_id": "6000", "nature": "debit", "parent_id": "", "tags": "opex,admin"})
        writer.writerow({"account_id": "4000", "nature": "credit", "parent_id": "4", "tags": "revenue"})
    from_csv = snapshot_from_manifest(csv_path)

    hashes = {s.snapshot_hash for s in (from_rows, from_arrow, from_yaml, from_csv)}
    assert len(hashes) == 1

    with pytest.raises(ValueError):
        snapshot_from_rows([rows[0], rows[0]], source="rows", taken_at=taken, **keys)
    with pytest.raises(ValueError):
        snapshot_from_manifest(tmp_path / "chart.json")
