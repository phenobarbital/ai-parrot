"""Tests for AuthorizationChecker — all 5 rules, OR-combine, default-deny.

Covers FEAT-158 Module 3 acceptance criteria.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.ontology.authorization import AuthorizationChecker
from parrot.knowledge.ontology.schema import AuthorizationRule, AuthorizationSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_store():
    """Mocked OntologyGraphStore."""
    gs = MagicMock()
    gs.execute_traversal = AsyncMock(return_value=[])
    return gs


@pytest.fixture
def checker(graph_store) -> AuthorizationChecker:
    """AuthorizationChecker backed by the mocked graph store."""
    return AuthorizationChecker(graph_store=graph_store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthorizationChecker:
    """Core authorization rule behaviour."""

    @pytest.mark.asyncio
    async def test_target_is_self_allows(self, checker: AuthorizationChecker) -> None:
        """target_is_self grants access when requesting user equals a resolved entity."""
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_is_self")])
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/me"},
            tenant_id="t1",
        )
        assert allowed
        assert reason is None

    @pytest.mark.asyncio
    async def test_target_is_self_denies_when_different(
        self, checker: AuthorizationChecker
    ) -> None:
        """target_is_self denies when user_id does not match any entity."""
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_is_self")])
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/other"},
            tenant_id="t1",
        )
        assert not allowed
        assert reason

    @pytest.mark.asyncio
    async def test_target_in_management_chain_depth_3(
        self, checker: AuthorizationChecker, graph_store: MagicMock
    ) -> None:
        """Management-chain traversal returns a row → allowed."""
        graph_store.execute_traversal.return_value = [{"_id": "Employee/sub3"}]
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="target_in_management_chain")]
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "Employee/mgr"},
            resolved_entities={"target": "Employee/sub3"},
            tenant_id="t1",
        )
        assert allowed

    @pytest.mark.asyncio
    async def test_target_in_management_chain_depth_11_denies(
        self, checker: AuthorizationChecker, graph_store: MagicMock
    ) -> None:
        """Traversal returns nothing (depth-10 limit) → denied."""
        graph_store.execute_traversal.return_value = []
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="target_in_management_chain")]
        )
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/mgr"},
            resolved_entities={"target": "Employee/sub11"},
            tenant_id="t1",
        )
        assert not allowed
        assert "no authorization rule matched" in (reason or "")

    @pytest.mark.asyncio
    async def test_has_role_allows(self, checker: AuthorizationChecker) -> None:
        """User with required role is granted access."""
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="has_role", role="hr_manager")]
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "u1", "roles": ["employee", "hr_manager"]},
            resolved_entities={},
            tenant_id="t1",
        )
        assert allowed

    @pytest.mark.asyncio
    async def test_has_role_denies_when_role_missing(
        self, checker: AuthorizationChecker
    ) -> None:
        """User without required role is denied."""
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="has_role", role="hr_manager")]
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "u1", "roles": ["employee"]},
            resolved_entities={},
            tenant_id="t1",
        )
        assert not allowed

    @pytest.mark.asyncio
    async def test_always_allows_unconditionally(
        self, checker: AuthorizationChecker
    ) -> None:
        """always rule passes without any resolved entities or roles."""
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="always")])
        allowed, reason = await checker.check(
            spec,
            user_context={},
            resolved_entities={},
            tenant_id="t1",
        )
        assert allowed
        assert reason is None

    @pytest.mark.asyncio
    async def test_or_combine_second_rule_passes(
        self, checker: AuthorizationChecker
    ) -> None:
        """First rule denies, second rule allows → overall allowed."""
        spec = AuthorizationSpec(
            rules=[
                AuthorizationRule(rule="has_role", role="hr_manager"),
                AuthorizationRule(rule="target_is_self"),
            ]
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "Employee/me", "roles": []},
            resolved_entities={"target": "Employee/me"},
            tenant_id="t1",
        )
        assert allowed

    @pytest.mark.asyncio
    async def test_default_deny_when_no_rules_match(
        self, checker: AuthorizationChecker
    ) -> None:
        """Default-deny behaviour: no matching rule → denied with reason."""
        spec = AuthorizationSpec(rules=[AuthorizationRule(rule="target_is_self")])
        allowed, reason = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/other"},
            tenant_id="t1",
        )
        assert not allowed
        assert reason  # not None and not empty

    @pytest.mark.asyncio
    async def test_default_deny_false_allows_unmatched(
        self, checker: AuthorizationChecker
    ) -> None:
        """default_deny=False: unmatched rules → allowed."""
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="target_is_self")],
            default_deny=False,
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "Employee/me"},
            resolved_entities={"target": "Employee/other"},
            tenant_id="t1",
        )
        assert allowed

    @pytest.mark.asyncio
    async def test_missing_user_id_denies(self, checker: AuthorizationChecker) -> None:
        """All non-always rules deny when user_id is absent."""
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="target_is_self")]
        )
        allowed, reason = await checker.check(
            spec,
            user_context={},
            resolved_entities={"target": "Employee/x"},
            tenant_id="t1",
        )
        assert not allowed
        assert "user_id" in (reason or "").lower()

    @pytest.mark.asyncio
    async def test_same_department_allows(
        self, checker: AuthorizationChecker, graph_store: MagicMock
    ) -> None:
        """same_department allows when entity's department matches user's."""
        graph_store.execute_traversal.return_value = ["Engineering"]
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="same_department")]
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "u1", "department": "Engineering"},
            resolved_entities={"target": "Employee/1"},
            tenant_id="t1",
        )
        assert allowed

    @pytest.mark.asyncio
    async def test_same_department_denies_different_dept(
        self, checker: AuthorizationChecker, graph_store: MagicMock
    ) -> None:
        """same_department denies when departments differ."""
        graph_store.execute_traversal.return_value = ["Sales"]
        spec = AuthorizationSpec(
            rules=[AuthorizationRule(rule="same_department")]
        )
        allowed, _ = await checker.check(
            spec,
            user_context={"user_id": "u1", "department": "Engineering"},
            resolved_entities={"target": "Employee/1"},
            tenant_id="t1",
        )
        assert not allowed
