"""Regression: policy-file RLS rules never override foreign rules; reload tracks ownership (issue:e3ff9bfb4a83)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parrot.auth import RlsRegistry, RlsRule
from parrot.semantic import SemanticLayerToolkit
from parrot.semantic.errors import SemanticPolicyError

from ._models import models_dir  # noqa: F401

_POLICY = (
    "governed: false\n"
    "roles: {analyst: {metrics: '*', dimensions: '*', usage: '*'}}\n"
    "rls:\n"
    "  - {driver: duckdb, table: sales.orders, predicate_template: \"%s IN (:subject.programs)\","
    " subject_attribute: programs}\n"
)


def _write(models_dir: Path, column: str) -> None:
    """Write the orders policy with one RLS rule on ``column``."""
    (models_dir / "orders.policy.yaml").write_text(_POLICY % column, encoding="utf-8")


def _host_rule() -> RlsRule:
    """Build a host-registered rule for the same key as the policy file."""
    return RlsRule(
        driver="duckdb",
        table="sales.orders",
        predicate_template="tenant_id IN (:subject.tenants)",
        subject_attribute="tenants",
    )


def test_policy_rule_refuses_to_override_host_rule(models_dir: Path) -> None:
    """A host rule for the same (driver, table) is never silently replaced."""
    _write(models_dir, "region")
    registry = RlsRegistry()
    registry.register(_host_rule())
    with pytest.raises(SemanticPolicyError) as error:
        SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", rls_registry=registry)
    assert error.value.code == "rls_conflict"
    assert registry.lookup("duckdb", {"sales.orders"}) == [_host_rule()]


def test_identical_foreign_rule_is_accepted_but_not_claimed(models_dir: Path) -> None:
    """An identical pre-registered rule is not a conflict and is not owned by the toolkit."""
    _write(models_dir, "region")
    registry = RlsRegistry()
    toolkit_a = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", rls_registry=registry)
    toolkit_b = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", rls_registry=registry)
    assert ("duckdb", "sales.orders") in toolkit_a._owned_rls
    assert toolkit_b._owned_rls == {}


def test_reload_replaces_owned_rule_and_rejects_new_conflict(models_dir: Path) -> None:
    """Reload may update an owned rule; a conflicting reload keeps the previous snapshot."""
    _write(models_dir, "region")
    registry = RlsRegistry()
    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", rls_registry=registry)
    _write(models_dir, "tenant_id")
    toolkit.reload()
    assert registry.lookup("duckdb", {"sales.orders"})[0].predicate_template.startswith("tenant_id")

    registry._rules[("duckdb", "dim.customers")] = _host_rule().model_copy(update={"table": "dim.customers"})
    previous = toolkit._models
    (models_dir / "customers.policy.yaml").write_text(
        "governed: false\nrls:\n  - {driver: duckdb, table: dim.customers,"
        " predicate_template: \"id IN (:subject.ids)\", subject_attribute: ids}\n",
        encoding="utf-8",
    )
    with pytest.raises(SemanticPolicyError) as error:
        toolkit.reload()
    assert error.value.code == "rls_conflict"
    assert toolkit._models is previous


def test_reload_warns_on_removed_rule_without_unregister_api(
    models_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """RlsRegistry has no unregister API: a removed rule is reported, kept (fail-safe) and still owned."""
    _write(models_dir, "region")
    registry = RlsRegistry()
    toolkit = SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", rls_registry=registry)
    (models_dir / "orders.policy.yaml").write_text("governed: false\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        toolkit.reload()
    assert "no unregister API" in caplog.text
    assert ("duckdb", "sales.orders") in toolkit._owned_rls
