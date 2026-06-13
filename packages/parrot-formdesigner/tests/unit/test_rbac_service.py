"""Unit tests for TASK-016 — RBACService (fake pool, no real DB).

Covers:
- Policy model construction + round-trip serialization.
- RBACScope vocabulary values.
- _compile_scope_to_policy produces correct subjects/conditions per scope.
- RBACContext.has_permission() scope enforcement.
- assign_role() creates a policy (NEVER writes to auth.user_permissions).
- create_policy/get_policy/list_policies/delete_policy CRUD.
- resolve() builds RBACContext from policies.
- revoke_all() removes compiled policies.
- SQL constants: no writes to auth.* (only reads).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.rbac import (
    PermissionRecord,
    Policy,
    RBACContext,
    RBACScope,
    RBACService,
    _compile_scope_to_policy,
    _DELETE_POLICY_SQL,
    _INSERT_POLICY_SQL,
    _SELECT_POLICIES_BY_TENANT_SQL,
    _SELECT_POLICY_SQL,
    _SELECT_USER_GROUPS_SQL,
)


# ---------------------------------------------------------------------------
# Fake pool helpers
# ---------------------------------------------------------------------------


def _row(data: dict) -> MagicMock:
    """Fake asyncpg-style Record."""
    r = MagicMock()
    r.__getitem__ = lambda self, k: data[k]
    return r


def _make_conn(
    fetchrow_result: Any = None,
    fetch_result: list | None = None,
    execute_result: str = "INSERT 0 1",
) -> MagicMock:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetch = AsyncMock(return_value=fetch_result or [])
    conn.execute = AsyncMock(return_value=execute_result)
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


def _policy_row(
    name: str = "test_policy",
    policy_dict: dict | None = None,
    tenant: str = "acme",
    priority: int = 50,
    enforcing: bool = False,
) -> MagicMock:
    data = policy_dict or {
        "name": name,
        "effect": "allow",
        "description": "",
        "resources": ["form:*"],
        "actions": ["edit_form"],
        "subjects": {},
        "conditions": {},
        "priority": priority,
        "enforcing": enforcing,
        "tenant": tenant,
    }
    return _row(
        {
            "id": 1,
            "name": name,
            "policy": json.dumps(data),
            "tenant": tenant,
            "priority": priority,
            "enforcing": enforcing,
        }
    )


# ---------------------------------------------------------------------------
# SQL safety — no writes to auth.*
# ---------------------------------------------------------------------------


class TestSQLSafety:
    """Verify SQL constants never write to auth schema."""

    def test_insert_targets_fieldsync(self) -> None:
        assert "fieldsync.auth_policies" in _INSERT_POLICY_SQL
        assert "auth.user_permissions" not in _INSERT_POLICY_SQL

    def test_delete_targets_fieldsync(self) -> None:
        assert "fieldsync.auth_policies" in _DELETE_POLICY_SQL
        assert "auth." not in _DELETE_POLICY_SQL

    def test_select_targets_fieldsync(self) -> None:
        assert "fieldsync.auth_policies" in _SELECT_POLICY_SQL
        assert "fieldsync.auth_policies" in _SELECT_POLICIES_BY_TENANT_SQL

    def test_user_groups_is_read_only(self) -> None:
        assert "SELECT" in _SELECT_USER_GROUPS_SQL.upper()
        assert "INSERT" not in _SELECT_USER_GROUPS_SQL.upper()
        assert "UPDATE" not in _SELECT_USER_GROUPS_SQL.upper()
        assert "DELETE" not in _SELECT_USER_GROUPS_SQL.upper()


# ---------------------------------------------------------------------------
# Policy model
# ---------------------------------------------------------------------------


class TestPolicyModel:
    def test_basic_construction(self) -> None:
        pol = Policy(
            name="eng_biz_hours",
            effect="allow",
            resources=["agent:*"],
            actions=["agent:chat"],
            subjects={"groups": ["engineering"]},
            conditions={"environment": {"is_business_hours": True}},
            priority=20,
            enforcing=False,
        )
        assert pol.name == "eng_biz_hours"
        assert pol.effect == "allow"
        assert pol.priority == 20
        assert not pol.enforcing

    def test_defaults(self) -> None:
        pol = Policy(name="minimal")
        assert pol.effect == "allow"
        assert pol.priority == 50
        assert pol.enforcing is False
        assert pol.resources == []

    def test_round_trip_json(self) -> None:
        pol = Policy(
            name="test",
            effect="deny",
            resources=["form:edit"],
            actions=["edit_form"],
        )
        data = pol.model_dump(mode="json")
        pol2 = Policy(**data)
        assert pol2 == pol


# ---------------------------------------------------------------------------
# RBACScope + compile
# ---------------------------------------------------------------------------


class TestRBACScope:
    def test_scope_values(self) -> None:
        assert RBACScope.OWN.value == "own"
        assert RBACScope.TEAM.value == "team"
        assert RBACScope.CLIENT.value == "client"
        assert RBACScope.GLOBAL.value == "global"

    def test_compile_own_scope(self) -> None:
        pol = _compile_scope_to_policy(
            "user-1", program_id=7, codename="edit_form",
            scope=RBACScope.OWN, tenant="acme"
        )
        assert "user-1" in pol.subjects.get("users", [])
        assert pol.actions == ["edit_form"]
        assert pol.tenant == "acme"

    def test_compile_team_scope(self) -> None:
        pol = _compile_scope_to_policy(
            "user-1", program_id=7, codename="view_form",
            scope=RBACScope.TEAM, tenant="acme"
        )
        assert "team/7" in pol.subjects.get("groups", [])

    def test_compile_client_scope(self) -> None:
        pol = _compile_scope_to_policy(
            "user-1", program_id=7, codename="view_form",
            scope=RBACScope.CLIENT, tenant="acme"
        )
        assert pol.conditions.get("resource", {}).get("program_id") == 7

    def test_compile_global_scope(self) -> None:
        pol = _compile_scope_to_policy(
            "user-1", program_id=7, codename="admin",
            scope=RBACScope.GLOBAL, tenant="acme"
        )
        assert pol.subjects == {}
        assert pol.conditions == {}

    def test_compile_not_enforcing_by_default(self) -> None:
        pol = _compile_scope_to_policy(
            "user-1", program_id=7, codename="edit_form",
            scope=RBACScope.OWN, tenant="acme"
        )
        assert pol.enforcing is False

    def test_compile_policy_name_includes_codename_and_scope(self) -> None:
        pol = _compile_scope_to_policy(
            "user-abc", program_id=3, codename="delete_form",
            scope=RBACScope.TEAM, tenant="t1"
        )
        assert "delete_form" in pol.name
        assert "team" in pol.name
        assert "user-abc" in pol.name


# ---------------------------------------------------------------------------
# RBACContext.has_permission
# ---------------------------------------------------------------------------


class TestRBACContext:
    def _ctx(self, codename: str, scope: RBACScope) -> RBACContext:
        rec = PermissionRecord(
            user_id="u1", codename=codename, scope=scope,
            program_id=7, policy_name="p1", tenant="t1"
        )
        return RBACContext(user_id="u1", program_id=7, permissions=[rec])

    def test_has_permission_true_exact_scope(self) -> None:
        ctx = self._ctx("edit_form", RBACScope.OWN)
        assert ctx.has_permission("edit_form", scope=RBACScope.OWN)

    def test_has_permission_narrower_scope_denied(self) -> None:
        """OWN permission does NOT cover TEAM-scoped query."""
        ctx = self._ctx("edit_form", RBACScope.OWN)
        # OWN is narrower than TEAM; requesting TEAM when granted OWN → False
        assert not ctx.has_permission("edit_form", scope=RBACScope.TEAM)

    def test_has_permission_broader_scope_allowed(self) -> None:
        """GLOBAL permission covers OWN query (wider ≥ narrower)."""
        ctx = self._ctx("edit_form", RBACScope.GLOBAL)
        assert ctx.has_permission("edit_form", scope=RBACScope.OWN)
        assert ctx.has_permission("edit_form", scope=RBACScope.TEAM)
        assert ctx.has_permission("edit_form", scope=RBACScope.CLIENT)

    def test_has_permission_no_scope_always_matches(self) -> None:
        ctx = self._ctx("view_form", RBACScope.OWN)
        assert ctx.has_permission("view_form")

    def test_has_permission_wrong_codename_false(self) -> None:
        ctx = self._ctx("edit_form", RBACScope.GLOBAL)
        assert not ctx.has_permission("delete_form")

    def test_has_permission_empty_permissions(self) -> None:
        ctx = RBACContext(user_id="u1", program_id=7)
        assert not ctx.has_permission("any_perm")


# ---------------------------------------------------------------------------
# Policy CRUD via fake pool
# ---------------------------------------------------------------------------


class TestRBACServicePolicyCRUD:
    @pytest.mark.asyncio
    async def test_create_policy_inserts_row(self) -> None:
        pol = Policy(name="p1", effect="allow", tenant="t1")
        row = _policy_row("p1", tenant="t1")
        conn = _make_conn(fetchrow_result=row)
        svc = RBACService(_make_pool(conn))
        result = await svc.create_policy(pol)
        assert result.name == "p1"
        conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_policy_found(self) -> None:
        row = _policy_row("my_pol", tenant="t1")
        conn = _make_conn(fetchrow_result=row)
        svc = RBACService(_make_pool(conn))
        result = await svc.get_policy("my_pol")
        assert result is not None
        assert result.name == "my_pol"

    @pytest.mark.asyncio
    async def test_get_policy_not_found(self) -> None:
        conn = _make_conn(fetchrow_result=None)
        svc = RBACService(_make_pool(conn))
        result = await svc.get_policy("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_policies_returns_list(self) -> None:
        rows = [_policy_row("p1", tenant="t1"), _policy_row("p2", tenant="t1")]
        conn = _make_conn(fetch_result=rows)
        svc = RBACService(_make_pool(conn))
        result = await svc.list_policies(tenant="t1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_delete_policy_true_on_success(self) -> None:
        conn = _make_conn(execute_result="DELETE 1")
        svc = RBACService(_make_pool(conn))
        ok = await svc.delete_policy("pol_to_delete")
        assert ok

    @pytest.mark.asyncio
    async def test_delete_policy_false_on_not_found(self) -> None:
        conn = _make_conn(execute_result="DELETE 0")
        svc = RBACService(_make_pool(conn))
        ok = await svc.delete_policy("missing_pol")
        assert not ok


# ---------------------------------------------------------------------------
# assign_role
# ---------------------------------------------------------------------------


class TestRBACServiceAssignRole:
    @pytest.mark.asyncio
    async def test_assign_role_returns_record(self) -> None:
        pol_name = "user__u1__edit_form__own__prog7"
        row = _policy_row(pol_name, tenant="acme")
        conn = _make_conn(fetchrow_result=row)
        svc = RBACService(_make_pool(conn))
        record = await svc.assign_role(
            "u1", program_id=7, codename="edit_form",
            scope=RBACScope.OWN, tenant="acme"
        )
        assert isinstance(record, PermissionRecord)
        assert record.user_id == "u1"
        assert record.codename == "edit_form"
        assert record.scope == RBACScope.OWN
        assert record.tenant == "acme"

    @pytest.mark.asyncio
    async def test_assign_role_writes_only_to_fieldsync(self) -> None:
        row = _policy_row()
        conn = _make_conn(fetchrow_result=row)
        svc = RBACService(_make_pool(conn))
        await svc.assign_role(
            "u1", program_id=7, codename="edit_form",
            scope=RBACScope.OWN, tenant="acme"
        )
        # Verify the SQL used targets fieldsync, not auth.user_permissions
        call_sql = conn.fetchrow.call_args[0][0]
        assert "fieldsync.auth_policies" in call_sql
        assert "auth.user_permissions" not in call_sql

    @pytest.mark.asyncio
    async def test_assign_role_ref_policy_example_from_spec(self) -> None:
        """The compiled policy matches the nav-auth YAML format example (§8)."""
        pol = _compile_scope_to_policy(
            "user-eng", program_id=7, codename="agent:chat",
            scope=RBACScope.TEAM, tenant="engineering"
        )
        # Should produce a policy compatible with nav-auth YAML format
        assert pol.effect == "allow"
        assert "agent:chat" in pol.actions
        assert pol.enforcing is False  # shadow mode default


# ---------------------------------------------------------------------------
# resolve()
# ---------------------------------------------------------------------------


class TestRBACServiceResolve:
    @pytest.mark.asyncio
    async def test_resolve_builds_context(self) -> None:
        pol_name = "user__u1__edit_form__own__prog7"
        pol_data = {
            "name": pol_name, "effect": "allow",
            "resources": ["form:*"], "actions": ["edit_form"],
            "subjects": {"users": ["u1"]}, "conditions": {},
            "priority": 50, "enforcing": False, "tenant": "t1", "description": "",
        }
        rows = [_policy_row(pol_name, pol_data, "t1")]
        conn = _make_conn(fetch_result=rows)
        svc = RBACService(_make_pool(conn))
        ctx = await svc.resolve("u1", program_id=7, tenant="t1")
        assert isinstance(ctx, RBACContext)
        assert ctx.user_id == "u1"
        assert len(ctx.permissions) == 1
        assert ctx.permissions[0].codename == "edit_form"

    @pytest.mark.asyncio
    async def test_resolve_no_policies_empty_context(self) -> None:
        conn = _make_conn(fetch_result=[])
        svc = RBACService(_make_pool(conn))
        ctx = await svc.resolve("u1", program_id=7, tenant="t1")
        assert ctx.permissions == []

    @pytest.mark.asyncio
    async def test_resolve_skips_deny_policies(self) -> None:
        pol_name = "user__u1__edit_form__own__prog7"
        pol_data = {
            "name": pol_name, "effect": "deny",
            "resources": [], "actions": ["edit_form"],
            "subjects": {}, "conditions": {},
            "priority": 50, "enforcing": False, "tenant": "t1", "description": "",
        }
        rows = [_policy_row(pol_name, pol_data, "t1")]
        conn = _make_conn(fetch_result=rows)
        svc = RBACService(_make_pool(conn))
        ctx = await svc.resolve("u1", program_id=7, tenant="t1")
        # deny policies are skipped in permissions build
        assert len(ctx.permissions) == 0

    @pytest.mark.asyncio
    async def test_resolve_groups_auth_fallback(self) -> None:
        """If auth.user_groups query fails, groups = [] (graceful)."""
        pol_name = "user__u1__edit_form__own__prog7"
        pol_data = {
            "name": pol_name, "effect": "allow",
            "resources": [], "actions": ["edit_form"],
            "subjects": {}, "conditions": {},
            "priority": 50, "enforcing": False, "tenant": "t1", "description": "",
        }

        # First call: list_policies (fetch) succeeds; second call (auth groups) raises
        conn = MagicMock()

        async def _fetch(sql: str, *args: Any) -> list:
            if "fieldsync" in sql:
                return [_policy_row(pol_name, pol_data, "t1")]
            raise RuntimeError("auth DB not available")

        conn.fetch = AsyncMock(side_effect=_fetch)
        conn.fetchrow = AsyncMock(return_value=None)

        svc = RBACService(_make_pool(conn))
        ctx = await svc.resolve("u1", program_id=7, tenant="t1")
        assert ctx.groups == []


# ---------------------------------------------------------------------------
# revoke_all
# ---------------------------------------------------------------------------


class TestRBACServiceRevokeAll:
    @pytest.mark.asyncio
    async def test_revoke_all_deletes_user_policies(self) -> None:
        pol_name = "user__u1__edit_form__own__prog7"
        pol_data = {
            "name": pol_name, "effect": "allow",
            "resources": [], "actions": ["edit_form"],
            "subjects": {}, "conditions": {},
            "priority": 50, "enforcing": False, "tenant": "t1", "description": "",
        }
        rows = [_policy_row(pol_name, pol_data, "t1")]
        conn = _make_conn(fetch_result=rows, execute_result="DELETE 1")
        svc = RBACService(_make_pool(conn))
        count = await svc.revoke_all("u1", tenant="t1")
        assert count == 1

    @pytest.mark.asyncio
    async def test_revoke_all_zero_when_no_policies(self) -> None:
        conn = _make_conn(fetch_result=[], execute_result="DELETE 0")
        svc = RBACService(_make_pool(conn))
        count = await svc.revoke_all("u1", tenant="t1")
        assert count == 0
