"""FEAT-713 M4 — loader."""

from __future__ import annotations

import copy

import pytest
import yaml

from parrot.semantic.accounting.errors import ModelValidationError
from parrot.semantic.accounting.loader import detect_drift, load_model
from parrot.semantic.accounting.models import AccountingModel, ChartAccount, ChartSnapshot


def _snapshot_with(base: ChartSnapshot, *extra: ChartAccount) -> ChartSnapshot:
    return ChartSnapshot(accounts=(*base.accounts, *extra), taken_at=base.taken_at, source=base.source)


def test_fixture_model_loads_cleanly(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    assert model.model_hash
    for resolved in model.sets.values():
        assert list(resolved.accounts) == sorted(resolved.accounts)
    assert model.sets["returns"].accounts == ("4900",)
    assert "5900" not in model.sets["cost_of_sales"].accounts
    assert model.sets["operating_expenses"].accounts[0] == "6000"
    assert len(model.sets["product_sales"].accounts) == 10


def test_all_problems_reported(troc_pnl_yaml, chart_snapshot) -> None:
    data = yaml.safe_load(troc_pnl_yaml.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["sets"]["returns"] = {"accounts": ["4900", "4000"]}  # overlap with product_sales
    data["sets"]["ghost"] = {"select": {"prefix": "ZZ"}}  # selector_no_match + empty_set
    data["excluded"] = []  # 9999 becomes unassigned
    data["metrics"]["bad"] = {"expr": "sum(nope)"}  # dangling_ref
    data["metrics"]["loop_a"] = {"expr": "loop_b"}
    data["metrics"]["loop_b"] = {"expr": "loop_a"}  # cycle
    with pytest.raises(ModelValidationError) as info:
        load_model(data, chart_snapshot)
    codes = {problem.code for problem in info.value.problems}
    assert {"overlap", "selector_no_match", "unassigned_account", "dangling_ref", "cycle"} <= codes
    assert len(info.value.problems) >= 5


def test_model_hash_changes_with_snapshot(troc_pnl_yaml, chart_snapshot) -> None:
    first = load_model(troc_pnl_yaml, chart_snapshot)
    assert load_model(troc_pnl_yaml, chart_snapshot).model_hash == first.model_hash
    extra = _snapshot_with(chart_snapshot, ChartAccount(account_id="4095", nature="credit"))
    assert load_model(troc_pnl_yaml, extra).model_hash != first.model_hash
    changed = ChartSnapshot(
        accounts=tuple(
            a.model_copy(update={"nature": "credit"}) if a.account_id == "6000" else a for a in chart_snapshot.accounts
        ),
        taken_at=chart_snapshot.taken_at,
        source=chart_snapshot.source,
    )
    assert load_model(troc_pnl_yaml, changed).model_hash != first.model_hash


def test_resolved_natures_round_trip(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    selected = {a for s in model.sets.values() for a in s.accounts}
    assert {account for account, _ in model.natures} == selected
    assert dict(model.natures)["4900"] == "debit"
    assert AccountingModel.model_validate_json(model.model_dump_json()) == model

    data = yaml.safe_load(troc_pnl_yaml.read_text(encoding="utf-8"))
    data["chart_of_accounts"]["nature"] = {"accounts": {"4000": "debit"}}
    with pytest.raises(ModelValidationError) as info:
        load_model(data, chart_snapshot)
    assert "nature_ambiguous" in {p.code for p in info.value.problems}


def test_detect_drift(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    assert detect_drift(model, chart_snapshot) == ()
    fresh = _snapshot_with(chart_snapshot, ChartAccount(account_id="7xxx", nature="debit"))
    assert detect_drift(model, fresh) == ("7xxx",)
