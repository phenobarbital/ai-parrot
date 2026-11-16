"""FEAT-713 M8 — catalog and compile cache."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from parrot.semantic.accounting.catalog import ModelCatalog
from parrot.semantic.accounting.compiler import compile_metric
from parrot.semantic.accounting.errors import ModelValidationError
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.models import ChartAccount, ChartSnapshot, MetricRequest
from parrot.semantic.cache import CompileCache


def _request(metric: str) -> MetricRequest:
    return MetricRequest.model_validate({"metric": metric, "period": {"from": "2025-02-01", "to": "2025-06-30"}})


def _copy_model(source: Path, model: str) -> Path:
    """Write a copy of *source* as ``<tenant>/<model>.yaml`` with the ``model:`` key renamed."""
    target = source.parent / f"{model}.yaml"
    text = source.read_text(encoding="utf-8").replace("model: troc_pnl\n", f"model: {model}\n", 1)
    target.write_text(text, encoding="utf-8")
    return target


def _broken_snapshot() -> ChartSnapshot:
    """A chart that leaves most sets empty — load-time validation must fail."""
    return ChartSnapshot(
        accounts=(ChartAccount(account_id="4000", nature="credit"),),
        taken_at=date(2026, 10, 1),
        source="manifest:broken",
    )


def test_compile_cache_holds_metric_queries(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    revenue = compile_metric(model, _request("revenue"), "duckdb")
    cogs = compile_metric(model, _request("cogs"), "duckdb")
    assert json.loads(revenue.cache_key)[0] == model.model_hash

    cache = CompileCache(max_entries=8)
    cache.put(revenue)
    cache.put(cogs)
    assert len(cache) == 2
    assert cache.get(revenue.cache_key) is revenue
    assert cache.get(cogs.cache_key) is cogs
    assert cache.get("missing") is None

    assert cache.invalidate_model("not-a-hash") == 0
    assert cache.invalidate_model(model.model_hash) == 2
    assert len(cache) == 0
    assert cache.get(revenue.cache_key) is None


def test_catalog_specs_without_snapshots(troc_pnl_yaml) -> None:
    catalog = ModelCatalog(troc_pnl_yaml.parent.parent)
    specs = catalog.specs()
    assert set(specs) == {("troc", "troc_pnl")}
    assert specs[("troc", "troc_pnl")].tenant == "troc"
    assert not catalog.is_loaded("troc", "troc_pnl")
    with pytest.raises(KeyError):
        catalog.get("troc", "troc_pnl")

    listed = catalog.metrics("troc")
    names = [(model, metric) for model, metric, _ in listed]
    assert names == sorted(names)
    assert names == [
        ("troc_pnl", "cogs"),
        ("troc_pnl", "ebitda"),
        ("troc_pnl", "gross_margin"),
        ("troc_pnl", "gross_margin_pct"),
        ("troc_pnl", "opex"),
        ("troc_pnl", "revenue"),
    ]
    assert {metric: d for _, metric, d in listed}["revenue"].expr == "sum(product_sales) - sum(returns)"
    assert catalog.metrics("other") == []
    assert catalog.flags("troc", "troc_pnl") is None

    # The returned mapping is a copy.
    specs.clear()
    assert ("troc", "troc_pnl") in catalog.specs()


def test_catalog_load_is_atomic(troc_pnl_yaml, chart_snapshot) -> None:
    _copy_model(troc_pnl_yaml, "troc_pnl_b")
    _copy_model(troc_pnl_yaml, "troc_pnl_c")
    catalog = ModelCatalog(troc_pnl_yaml.parent.parent)
    assert set(catalog.specs()) == {("troc", "troc_pnl"), ("troc", "troc_pnl_b"), ("troc", "troc_pnl_c")}

    # Loads only the supplied key.
    catalog.load({("troc", "troc_pnl"): chart_snapshot})
    first = catalog.get("troc", "troc_pnl")
    assert first.spec.model == "troc_pnl"
    assert not catalog.is_loaded("troc", "troc_pnl_b")

    # One invalid snapshot in the batch publishes nothing; the earlier model is preserved.
    with pytest.raises(ModelValidationError) as info:
        catalog.reload({("troc", "troc_pnl_b"): chart_snapshot, ("troc", "troc_pnl_c"): _broken_snapshot()})
    assert "troc_pnl_c.yaml" in str(info.value)
    assert info.value.problems
    assert all("troc_pnl_c.yaml" in problem.message for problem in info.value.problems)
    assert not catalog.is_loaded("troc", "troc_pnl_b")
    assert not catalog.is_loaded("troc", "troc_pnl_c")
    assert catalog.get("troc", "troc_pnl") is first

    # Unknown keys are rejected before anything is published.
    with pytest.raises(KeyError):
        catalog.load({("troc", "troc_pnl_b"): chart_snapshot, ("troc", "nope"): chart_snapshot})
    assert not catalog.is_loaded("troc", "troc_pnl_b")

    # A valid batch publishes and keeps the other loaded models.
    catalog.load({("troc", "troc_pnl_b"): chart_snapshot}, columns=None)
    assert catalog.get("troc", "troc_pnl") is first
    assert catalog.get("troc", "troc_pnl_b").spec.model == "troc_pnl_b"


def test_catalog_identity_mismatch(tmp_path, troc_pnl_yaml) -> None:
    text = troc_pnl_yaml.read_text(encoding="utf-8")
    root = tmp_path / "mismatch"
    path = root / "acme" / "troc_pnl.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")  # declares tenant: troc, path implies tenant acme
    with pytest.raises(ModelValidationError) as info:
        ModelCatalog(root)
    assert str(path) in str(info.value)
    assert "acme" in str(info.value)

    other = tmp_path / "other"
    renamed = other / "troc" / "wrong_name.yaml"
    renamed.parent.mkdir(parents=True)
    renamed.write_text(text, encoding="utf-8")  # declares model: troc_pnl, file name wrong_name
    with pytest.raises(ModelValidationError) as info:
        ModelCatalog(other)
    assert str(renamed) in str(info.value)
    assert "wrong_name" in str(info.value)
