"""Tests for the RLS Registry (FEAT-228 / TASK-1493)."""
from __future__ import annotations

import pytest

from parrot.auth.rls_registry import RlsRegistry, RlsPredicate, RlsRule
from parrot.auth.permission import PermissionContext, UserSession


@pytest.fixture
def registry() -> RlsRegistry:
    """Registry pre-loaded with a regional-manager predicate for sales.orders."""
    reg = RlsRegistry()
    reg.register(
        RlsRule(
            driver="pg",
            table="sales.orders",
            predicate_template="region IN (:subject.programs)",
            subject_attribute="programs",
            description="Regional managers see only their region",
        )
    )
    return reg


@pytest.fixture
def regional_pctx() -> PermissionContext:
    """PermissionContext for a regional manager with northeast + southeast programs."""
    return PermissionContext(
        session=UserSession(
            user_id="regional_mgr",
            tenant_id="corp",
            roles=frozenset({"RegionalManager"}),
            metadata={"groups": ["RegionalManager"], "programs": ["northeast", "southeast"]},
        )
    )


@pytest.fixture
def empty_pctx() -> PermissionContext:
    """PermissionContext for a user with no programs."""
    return PermissionContext(
        session=UserSession(
            user_id="nobody",
            tenant_id="corp",
            roles=frozenset(),
            metadata={"groups": [], "programs": []},
        )
    )


class TestRlsRegistry:
    """Verify RlsRegistry register / lookup / render behaviour."""

    def test_lookup_match(self, registry: RlsRegistry) -> None:
        """lookup() returns rules for matching (driver, table) pairs."""
        rules = registry.lookup("pg", {"pg:sales.orders"})
        assert len(rules) == 1
        assert rules[0].table == "sales.orders"

    def test_lookup_no_match(self, registry: RlsRegistry) -> None:
        """lookup() returns empty list when no rules match."""
        rules = registry.lookup("pg", {"pg:hr.employees"})
        assert len(rules) == 0

    def test_lookup_empty_table_set(self, registry: RlsRegistry) -> None:
        """lookup() with empty table set returns empty list."""
        rules = registry.lookup("pg", set())
        assert rules == []

    def test_lookup_multiple_tables_partial_match(self, registry: RlsRegistry) -> None:
        """lookup() returns only rules that match; unmatched tables are ignored."""
        rules = registry.lookup("pg", {"pg:sales.orders", "pg:hr.employees"})
        assert len(rules) == 1
        assert rules[0].table == "sales.orders"

    def test_render_produces_bound_params(
        self, registry: RlsRegistry, regional_pctx: PermissionContext
    ) -> None:
        """render() returns RlsPredicate with bound params, not interpolated values."""
        rules = registry.lookup("pg", {"pg:sales.orders"})
        assert rules, "Precondition: rule must be found"
        pred = registry.render(rules[0], regional_pctx)
        assert isinstance(pred, RlsPredicate)
        # Values must NOT appear in the SQL predicate string
        assert "northeast" not in pred.sql_predicate
        assert "southeast" not in pred.sql_predicate
        # Parameters should carry the values
        all_values = [v for vlist in pred.bound_params.values() for v in vlist]
        assert "northeast" in all_values
        assert "southeast" in all_values

    def test_render_empty_programs_deny_all(
        self, registry: RlsRegistry, empty_pctx: PermissionContext
    ) -> None:
        """render() with empty attribute list returns deny-all predicate."""
        rules = registry.lookup("pg", {"pg:sales.orders"})
        assert rules, "Precondition: rule must be found"
        pred = registry.render(rules[0], empty_pctx)
        assert pred.sql_predicate in ("1=0", "FALSE")

    def test_render_bound_params_are_parameterised(
        self, registry: RlsRegistry, regional_pctx: PermissionContext
    ) -> None:
        """render() SQL predicate must use :pN placeholders, not raw values."""
        rules = registry.lookup("pg", {"pg:sales.orders"})
        pred = registry.render(rules[0], regional_pctx)
        # Should contain colon-prefixed placeholders
        assert ":p" in pred.sql_predicate
        # bound_params keys must correspond to those placeholders
        for key in pred.bound_params:
            assert f":{key}" in pred.sql_predicate

    def test_register_overwrites_duplicate(self) -> None:
        """Registering a second rule for the same (driver, table) replaces the first."""
        reg = RlsRegistry()
        reg.register(
            RlsRule(
                driver="pg",
                table="t",
                predicate_template="a = :subject.groups",
                subject_attribute="groups",
            )
        )
        reg.register(
            RlsRule(
                driver="pg",
                table="t",
                predicate_template="b = :subject.programs",
                subject_attribute="programs",
            )
        )
        rules = reg.lookup("pg", {"pg:t"})
        assert len(rules) == 1
        assert rules[0].subject_attribute == "programs"
