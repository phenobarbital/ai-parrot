"""Regression tests for the FEAT-302 code-review fixes.

- C-1/C-2/C-3 — get_node enforces tenant isolation via org_id scope.
- C-4 — list_projects/get_project require org_id; create_project handler
        uses the session org_id, never the request body.
- C-5 — _rbac_shadow_gate is wired into the form mutation handlers.
- C-6 — organization node parent_id points to the company root, not itself.
- H-1 — assign_user_role denies callers lacking manage_roles (in API tests).
- H-3 — delete_policy returns False on a "DELETE 0" status.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.org_graph import OrgGraphService
from parrot_formdesigner.services.project_service import ProjectService


# ---------------------------------------------------------------------------
# Fake asyncpg pool that records every (sql, args) call
# ---------------------------------------------------------------------------


def _make_pool(rows_by_marker: dict[str, list[dict]] | None = None) -> tuple[MagicMock, list]:
    rows_by_marker = rows_by_marker or {}
    calls: list[tuple[str, tuple]] = []

    def _row(d: dict) -> MagicMock:
        r = MagicMock()
        r.__getitem__ = lambda self, k, _d=d: _d[k]
        r.keys = lambda _d=d: list(_d.keys())
        return r

    async def _fetch(sql: str, *args: Any) -> list:
        calls.append((sql, args))
        for marker, rows in rows_by_marker.items():
            if marker in sql:
                return [_row(d) for d in rows]
        return []

    async def _fetchrow(sql: str, *args: Any) -> Any:
        calls.append((sql, args))
        for marker, rows in rows_by_marker.items():
            if marker in sql:
                return _row(rows[0]) if rows else None
        return None

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=_fetch)
    conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool, calls


# ---------------------------------------------------------------------------
# C-1/C-2/C-3 — tenant isolation in get_node
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    async def test_org_node_rejects_foreign_org(self):
        """C-1: requesting an org != session org_id raises KeyError (no leak)."""
        pool, _ = _make_pool({"auth.organizations": [{"org_id": 999, "name": "Other"}]})
        svc = OrgGraphService(pool)
        with pytest.raises(KeyError):
            await svc.get_node("organization", "999", tenant="t1", org_id=7)

    async def test_client_node_query_carries_org_id(self):
        """C-2: client lookup passes org_id as a bind parameter."""
        pool, calls = _make_pool({"auth.clients": [{"client_id": 42, "client_name": "C"}]})
        svc = OrgGraphService(pool)
        await svc.get_node("client", "42", tenant="t1", org_id=7)
        client_calls = [c for c in calls if "auth.clients" in c[0]]
        assert client_calls and 7 in client_calls[0][1]  # org_id bound

    async def test_program_node_query_carries_org_id(self):
        """C-3: program lookup passes org_id as a bind parameter."""
        pool, calls = _make_pool({"auth.programs": [{"program_id": 5, "program_name": "P"}]})
        svc = OrgGraphService(pool)
        await svc.get_node("program", "5", tenant="t1", org_id=7)
        prog_calls = [c for c in calls if "auth.programs" in c[0]]
        assert prog_calls and 7 in prog_calls[0][1]

    async def test_unknown_node_type_raises(self):
        """M-7: geography/store single-node lookup fails loudly (no stub)."""
        pool, _ = _make_pool()
        svc = OrgGraphService(pool)
        with pytest.raises(NotImplementedError):
            await svc.get_node("store", "1", tenant="t1", org_id=7)


# ---------------------------------------------------------------------------
# C-6 — org node parent_id points to the company root
# ---------------------------------------------------------------------------


class TestParentPointer:
    async def test_org_parent_is_company_root(self):
        pool, _ = _make_pool({"auth.organizations": [{"org_id": 7, "name": "Acme"}]})
        svc = OrgGraphService(pool)
        graph = await svc.get_graph(7, tenant="acme", depth=1)
        org_node = graph.root.children[0]
        assert graph.root.node_id == "company:acme"
        assert org_node.parent_id == "company:acme"   # not "7"


# ---------------------------------------------------------------------------
# C-4 — project reads require org_id
# ---------------------------------------------------------------------------


class TestProjectScoping:
    async def test_list_projects_binds_org_id(self):
        pool, calls = _make_pool({"fieldsync.projects": []})
        svc = ProjectService(pool)
        await svc.list_projects(org_id=7)
        assert calls and 7 in calls[0][1]

    async def test_get_project_binds_org_id(self):
        pool, calls = _make_pool({"fieldsync.projects": [{
            "project_id": 1, "client_id": 2, "name": "P", "accounting_code": "A",
            "org_id": 7, "start_timestamp": None, "end_timestamp": None,
            "is_active": True,
        }]})
        svc = ProjectService(pool)
        await svc.get_project(1, org_id=7)
        assert calls and calls[0][1] == (1, 7)

    def test_no_unscoped_list_sql_exists(self):
        """C-4: the cross-tenant 'select all projects' constant is gone."""
        from parrot_formdesigner.services import project_service as ps
        assert not hasattr(ps, "_SELECT_PROJECTS_ALL_SQL")


# ---------------------------------------------------------------------------
# C-5 — shadow gate wired into form mutation handlers
# ---------------------------------------------------------------------------


class TestShadowGateWired:
    def test_form_handlers_call_shadow_gate(self):
        import inspect
        from parrot_formdesigner.api import handlers as h

        for name in ("create_form", "edit_form", "update_form",
                     "patch_form", "delete_form"):
            src = inspect.getsource(getattr(h.FormAPIHandler, name))
            assert "_rbac_shadow_gate" in src, f"{name} does not call the gate"


# ---------------------------------------------------------------------------
# H-3 — delete_policy robust return
# ---------------------------------------------------------------------------


class TestDeletePolicyReturn:
    async def test_delete_zero_returns_false(self):
        from parrot_formdesigner.services.rbac import RBACService
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 0")
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        svc = RBACService(pool)
        assert await svc.delete_policy("nope") is False

    async def test_delete_one_returns_true(self):
        from parrot_formdesigner.services.rbac import RBACService
        conn = MagicMock()
        conn.execute = AsyncMock(return_value="DELETE 1")
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        svc = RBACService(pool)
        assert await svc.delete_policy("yes") is True
