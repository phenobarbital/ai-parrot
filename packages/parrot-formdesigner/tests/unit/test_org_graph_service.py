"""Unit tests for TASK-014 — OrgGraphService (fake pool, no real DB).

Verifies:
- OrgNode / OrgGraph model construction.
- get_graph() builds tree with correct nesting and depth.
- Hard tenant isolation: nodes carry tenant in metadata.
- Multi-hierarchy: two organizations under the same company root.
- get_node() returns correct node for org / client / program.
- KeyError raised when org not found.
- RuntimeError raised when no pool and no env var.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_formdesigner.services.org_graph import OrgGraph, OrgGraphService, OrgNode


# ---------------------------------------------------------------------------
# Fake pool helpers
# ---------------------------------------------------------------------------


def _make_conn(fetchrow_results: dict | None = None, fetch_results: dict | None = None) -> MagicMock:
    """Build a fake asyncpg-style connection.

    Args:
        fetchrow_results: Mapping of SQL → row dict (or None for not found).
        fetch_results: Mapping of SQL → list of row dicts.
    """
    conn = MagicMock()
    fetchrow_results = fetchrow_results or {}
    fetch_results = fetch_results or {}

    async def _fetchrow(sql: str, *args: Any) -> MagicMock | None:
        # Match on sql prefix
        for key, val in fetchrow_results.items():
            if key in sql:
                if val is None:
                    return None
                row = MagicMock()
                row.__getitem__ = lambda self, k: val[k]
                row.keys = lambda: list(val.keys())
                return row
        return None

    async def _fetch(sql: str, *args: Any) -> list[MagicMock]:
        for key, val in fetch_results.items():
            if key in sql:
                rows = []
                for item in val:
                    row = MagicMock()
                    row.__getitem__ = lambda self, k, _item=item: _item[k]
                    rows.append(row)
                return rows
        return []

    conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    conn.fetch = AsyncMock(side_effect=_fetch)
    return conn


def _make_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestOrgNodeModel:
    def test_basic_construction(self) -> None:
        node = OrgNode(node_type="organization", node_id="7")
        assert node.node_id == "7"
        assert node.children == []
        assert node.metadata == {}

    def test_company_node(self) -> None:
        node = OrgNode(
            node_type="company",
            node_id="company:acme",
            metadata={"tenant": "acme"},
        )
        assert node.parent_id is None
        assert node.node_type == "company"

    def test_nested_children(self) -> None:
        child = OrgNode(node_type="client", node_id="42", parent_id="7")
        parent = OrgNode(node_type="organization", node_id="7", children=[child])
        assert len(parent.children) == 1
        assert parent.children[0].node_id == "42"


class TestOrgGraphModel:
    def test_basic_construction(self) -> None:
        root = OrgNode(node_type="company", node_id="company:t1")
        graph = OrgGraph(org_id=7, tenant="t1", root=root)
        assert graph.org_id == 7
        assert graph.tenant == "t1"
        assert graph.root.node_type == "company"


# ---------------------------------------------------------------------------
# get_graph() tests
# ---------------------------------------------------------------------------


class TestOrgGraphServiceGetGraph:
    """Tests using fake pool — no real DB required."""

    def _svc(self, conn: MagicMock) -> OrgGraphService:
        pool = _make_pool(conn)
        return OrgGraphService(pool)

    @pytest.mark.asyncio
    async def test_get_graph_returns_company_root(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Acme Corp"}},
            fetch_results={
                "auth.clients": [],
            },
        )
        svc = self._svc(conn)
        graph = await svc.get_graph(7, tenant="acme", depth=2)
        assert graph.org_id == 7
        assert graph.tenant == "acme"
        assert graph.root.node_type == "company"
        assert graph.root.node_id == "company:acme"

    @pytest.mark.asyncio
    async def test_get_graph_org_node_in_children(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Acme Corp"}},
            fetch_results={"auth.clients": []},
        )
        svc = self._svc(conn)
        graph = await svc.get_graph(7, tenant="acme", depth=2)
        assert len(graph.root.children) == 1
        org_node = graph.root.children[0]
        assert org_node.node_type == "organization"
        assert org_node.node_id == "7"

    @pytest.mark.asyncio
    async def test_get_graph_depth_1_no_clients(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Org"}},
            fetch_results={},
        )
        svc = self._svc(conn)
        graph = await svc.get_graph(7, tenant="t1", depth=1)
        org_node = graph.root.children[0]
        assert org_node.children == []

    @pytest.mark.asyncio
    async def test_get_graph_depth_2_includes_clients(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Org"}},
            fetch_results={
                "auth.clients": [
                    {"client_id": 42, "client_name": "ClientA"},
                    {"client_id": 43, "client_name": "ClientB"},
                ],
            },
        )
        svc = self._svc(conn)
        graph = await svc.get_graph(7, tenant="t1", depth=2)
        org_node = graph.root.children[0]
        assert len(org_node.children) == 2
        assert org_node.children[0].node_type == "client"
        assert org_node.children[0].node_id == "42"

    @pytest.mark.asyncio
    async def test_get_graph_depth_3_includes_programs_and_projects(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Org"}},
            fetch_results={
                "auth.clients": [{"client_id": 10, "client_name": "C1"}],
                "auth.programs": [{"program_id": 1, "program_name": "P1"}],
                "fieldsync.projects": [
                    {
                        "project_id": 99,
                        "name": "Proj1",
                        "accounting_code": "ACC001",
                        "is_active": True,
                    }
                ],
                "networkninja.markets": [],
            },
        )
        svc = self._svc(conn)
        graph = await svc.get_graph(7, tenant="t1", depth=3)
        client_node = graph.root.children[0].children[0]
        types = {n.node_type for n in client_node.children}
        assert "program" in types
        assert "project" in types

    @pytest.mark.asyncio
    async def test_get_graph_org_not_found_raises(self) -> None:
        conn = _make_conn(fetchrow_results={"auth.organizations": None})
        svc = self._svc(conn)
        with pytest.raises(KeyError, match="Organization 99 not found"):
            await svc.get_graph(99, tenant="t1")

    @pytest.mark.asyncio
    async def test_tenant_in_company_root_metadata(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Org"}},
            fetch_results={"auth.clients": []},
        )
        svc = self._svc(conn)
        graph = await svc.get_graph(7, tenant="isolated_tenant")
        assert graph.root.metadata["tenant"] == "isolated_tenant"

    @pytest.mark.asyncio
    async def test_multi_hierarchy_two_orgs_share_company_root(self) -> None:
        """Two separate get_graph() calls for two orgs → same tenant, separate graphs."""
        conn1 = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Org A"}},
            fetch_results={"auth.clients": []},
        )
        conn2 = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "Org B"}},
            fetch_results={"auth.clients": []},
        )
        svc1 = OrgGraphService(_make_pool(conn1))
        svc2 = OrgGraphService(_make_pool(conn2))
        g1 = await svc1.get_graph(1, tenant="bigco")
        g2 = await svc2.get_graph(2, tenant="bigco")
        # Both roots are company:bigco
        assert g1.root.node_id == "company:bigco"
        assert g2.root.node_id == "company:bigco"
        # Each graph has its own organization child
        assert g1.root.children[0].node_id == "1"
        assert g2.root.children[0].node_id == "2"


# ---------------------------------------------------------------------------
# get_node() tests
# ---------------------------------------------------------------------------


class TestOrgGraphServiceGetNode:
    @pytest.mark.asyncio
    async def test_get_org_node(self) -> None:
        conn = _make_conn(
            fetchrow_results={"auth.organizations": {"name": "MyOrg"}},
        )
        svc = OrgGraphService(_make_pool(conn))
        node = await svc.get_node("organization", "7", tenant="t1", org_id=7)
        assert node.node_type == "organization"
        assert node.node_id == "7"
        assert node.metadata["name"] == "MyOrg"

    @pytest.mark.asyncio
    async def test_get_org_node_not_found(self) -> None:
        conn = _make_conn(fetchrow_results={"auth.organizations": None})
        svc = OrgGraphService(_make_pool(conn))
        with pytest.raises(KeyError, match="Organization 99 not found"):
            await svc.get_node("organization", "99", tenant="t1", org_id=7)

    @pytest.mark.asyncio
    async def test_get_client_node(self) -> None:
        conn = _make_conn(
            fetch_results={
                "auth.clients": [{"client_id": 42, "client_name": "ClientX"}]
            }
        )
        svc = OrgGraphService(_make_pool(conn))
        node = await svc.get_node("client", "42", tenant="t1", org_id=7)
        assert node.node_type == "client"
        assert node.metadata["client_name"] == "ClientX"

    @pytest.mark.asyncio
    async def test_get_client_not_found(self) -> None:
        conn = _make_conn(fetch_results={"auth.clients": []})
        svc = OrgGraphService(_make_pool(conn))
        with pytest.raises(KeyError, match="Client 99 not found"):
            await svc.get_node("client", "99", tenant="t1", org_id=7)

    @pytest.mark.asyncio
    async def test_get_program_node(self) -> None:
        conn = _make_conn(
            fetch_results={
                "auth.programs": [{"program_id": 5, "program_name": "ProgramX"}]
            }
        )
        svc = OrgGraphService(_make_pool(conn))
        node = await svc.get_node("program", "5", tenant="t1", org_id=7)
        assert node.node_type == "program"
        assert node.metadata["program_name"] == "ProgramX"


# ---------------------------------------------------------------------------
# No-pool / env fallback tests
# ---------------------------------------------------------------------------


class TestOrgGraphServiceNoPool:
    @pytest.mark.asyncio
    async def test_no_pool_no_env_raises(self) -> None:
        svc = OrgGraphService(pool=None)
        with patch.dict("os.environ", {}, clear=False):
            # Ensure env var is absent
            import os
            os.environ.pop("FIELDSYNC_AUTH_RO_DSN", None)
            with pytest.raises(RuntimeError, match="FIELDSYNC_AUTH_RO_DSN"):
                await svc.get_graph(1, tenant="t1")
