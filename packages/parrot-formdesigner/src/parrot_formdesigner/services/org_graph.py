"""OrgGraphService — árbol multi-jerarquía read-only sobre auth.* + geografía.

Lee tablas de solo-lectura:
- ``auth.organizations``, ``auth.organization_clients``, ``auth.clients``,
  ``auth.programs``, ``auth.program_clients``
- Geografía per-client: ``networkninja.markets``, ``networkninja.districts``,
  ``networkninja.regions``
- Proyectos propios: ``fieldsync.projects``

Principios de diseño (§8 spec):
- **Hard tenant isolation**: todo query filtra ``org_id`` / ``client_id``
  explícitamente; sin leakage cross-tenant.
- **SQL 100% parametrizado**: valores siempre vía ``$1``/``$2`` etc.;
  nombres de schema/tabla fijados como constantes (no interpolados desde
  input de usuario).
- **Múltiples jerarquías**: un "company" super-node agrupa todas las
  sub-jerarquías del tenant (por si un cliente tiene >1 organización).
- **Read-only**: no hay ningún INSERT/UPDATE/DELETE en este servicio.
- **Pool inyectado**: acepta pool o fake-pool para testabilidad completa.

Uso::

    svc = OrgGraphService(pool)
    graph = await svc.get_graph(org_id=7, tenant="myco")
    node  = await svc.get_node("client", "42", tenant="myco")
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Node type literal
# ---------------------------------------------------------------------------

NodeType = Literal[
    "organization",
    "company",
    "client",
    "program",
    "project",
    "market",
    "district",
    "region",
    "territory",
    "store",
]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class OrgNode(BaseModel):
    """A single node in the organizational hierarchy.

    Attributes:
        node_type: Type of the node (organization, client, program, etc.).
        node_id: String identifier unique within the ``node_type`` namespace.
        parent_id: String identifier of the parent node, or ``None`` for root.
        metadata: Arbitrary key-value metadata (name, client_id, etc.).
        children: Nested child nodes (populated up to requested ``depth``).
    """

    model_config = ConfigDict(extra="forbid")

    node_type: NodeType
    node_id: str
    parent_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    children: list["OrgNode"] = Field(default_factory=list)


class OrgGraph(BaseModel):
    """Full organizational graph for a tenant.

    Attributes:
        org_id: Numeric identifier of the organization.
        tenant: Tenant slug (program slug from navigator-auth).
        root: Root ``OrgNode`` (type ``"company"``); children are the tree.
    """

    model_config = ConfigDict(extra="forbid")

    org_id: int
    tenant: str
    root: OrgNode


# ---------------------------------------------------------------------------
# SQL constants — schema/table names are FIXED constants, never interpolated
# from user input.
# ---------------------------------------------------------------------------

_SQL_GET_ORG = """
SELECT org_id, name
FROM auth.organizations
WHERE org_id = $1
"""

_SQL_GET_CLIENTS = """
SELECT c.client_id, c.client_name
FROM auth.clients c
JOIN auth.organization_clients oc ON oc.client_id = c.client_id
WHERE oc.org_id = $1
"""

_SQL_GET_PROGRAMS_FOR_CLIENT = """
SELECT p.program_id, p.program_name
FROM auth.programs p
JOIN auth.program_clients pc ON pc.program_id = p.program_id
WHERE pc.client_id = $1
"""

_SQL_GET_PROJECTS_FOR_CLIENT = """
SELECT project_id, name, accounting_code, org_id, is_active
FROM fieldsync.projects
WHERE client_id = $1 AND org_id = $2
"""

_SQL_GET_MARKETS_FOR_CLIENT = """
SELECT market_id, market_name
FROM networkninja.markets
WHERE client_id = $1 AND orgid = $2
"""

_SQL_GET_DISTRICTS_FOR_CLIENT = """
SELECT district_id, district_name
FROM networkninja.districts
WHERE client_id = $1 AND orgid = $2
"""

_SQL_GET_REGIONS_FOR_CLIENT = """
SELECT region_id, region_name
FROM networkninja.regions
WHERE client_id = $1 AND orgid = $2
"""

# Tenant-scoped single-node lookups (hard isolation: filtered by org_id).
_SQL_GET_CLIENT_SCOPED = """
SELECT c.client_id, c.client_name
FROM auth.clients c
JOIN auth.organization_clients oc ON oc.client_id = c.client_id
WHERE c.client_id = $1 AND oc.org_id = $2
"""

_SQL_GET_PROGRAM_SCOPED = """
SELECT DISTINCT p.program_id, p.program_name
FROM auth.programs p
JOIN auth.program_clients pc ON pc.program_id = p.program_id
JOIN auth.organization_clients oc ON oc.client_id = pc.client_id
WHERE p.program_id = $1 AND oc.org_id = $2
"""

# ---------------------------------------------------------------------------
# OrgGraphService
# ---------------------------------------------------------------------------


class OrgGraphService:
    """Build in-memory org-graph trees from navigator-auth + networkninja.

    Designed for read-only access. Enforces hard tenant isolation by always
    filtering on ``org_id`` / ``client_id`` passed as parameters.

    Args:
        pool: asyncpg pool (or compatible fake). When ``None``, falls back
            to creating a pool from ``FIELDSYNC_AUTH_RO_DSN`` env var.
            In unit tests pass a fake pool explicitly.

    Example::

        svc = OrgGraphService(pool)
        graph = await svc.get_graph(7, tenant="acme")
    """

    def __init__(self, pool: Any | None = None) -> None:
        self._pool: Any | None = pool
        self.logger = logging.getLogger(__name__)

    async def _get_pool(self) -> Any:
        """Return pool, creating one from env DSN if needed.

        Returns:
            asyncpg pool or fake pool.

        Raises:
            RuntimeError: If no pool was provided and ``FIELDSYNC_AUTH_RO_DSN``
                is not set.
        """
        if self._pool is not None:
            return self._pool
        dsn = os.environ.get("FIELDSYNC_AUTH_RO_DSN")
        if not dsn:
            raise RuntimeError(
                "OrgGraphService: no pool provided and FIELDSYNC_AUTH_RO_DSN is not set"
            )
        try:
            import asyncpg  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("asyncpg is required for OrgGraphService") from exc
        self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        return self._pool

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_graph(
        self,
        org_id: int,
        *,
        tenant: str,
        depth: int = 3,
    ) -> OrgGraph:
        """Build the full org graph for ``org_id`` / ``tenant``.

        Args:
            org_id: Numeric organization identifier.
            tenant: Tenant slug (used for metadata and isolation).
            depth: How many levels deep to traverse (default 3).  Level 0 =
                company root only; 1 = + orgs; 2 = + clients/programs; 3 =
                + projects/geography.

        Returns:
            ``OrgGraph`` with a ``"company"`` root node containing all
            discovered sub-hierarchies.

        Raises:
            KeyError: If the organization is not found.
            RuntimeError: If no pool is available.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Level 1: resolve the organization
            org_row = await conn.fetchrow(_SQL_GET_ORG, org_id)
            if org_row is None:
                raise KeyError(f"Organization {org_id} not found")

            org_node = OrgNode(
                node_type="organization",
                node_id=str(org_id),
                parent_id=f"company:{tenant}",  # parent is the company root
                metadata={"name": org_row["name"] if "name" in org_row.keys() else str(org_id)},
            )

            client_nodes: list[OrgNode] = []
            if depth >= 2:
                client_rows = await conn.fetch(_SQL_GET_CLIENTS, org_id)
                for crow in client_rows:
                    client_id = crow["client_id"]
                    client_node = OrgNode(
                        node_type="client",
                        node_id=str(client_id),
                        parent_id=str(org_id),
                        metadata={
                            "client_name": crow["client_name"],
                            "client_id": client_id,
                        },
                    )

                    if depth >= 3:
                        # Programs
                        prog_rows = await conn.fetch(
                            _SQL_GET_PROGRAMS_FOR_CLIENT, client_id
                        )
                        for prow in prog_rows:
                            prog_node = OrgNode(
                                node_type="program",
                                node_id=str(prow["program_id"]),
                                parent_id=str(client_id),
                                metadata={
                                    "program_name": prow["program_name"],
                                    "program_id": prow["program_id"],
                                },
                            )
                            client_node.children.append(prog_node)

                        # Projects
                        proj_rows = await conn.fetch(
                            _SQL_GET_PROJECTS_FOR_CLIENT, client_id, org_id
                        )
                        for proj in proj_rows:
                            proj_node = OrgNode(
                                node_type="project",
                                node_id=str(proj["project_id"]),
                                parent_id=str(client_id),
                                metadata={
                                    "name": proj["name"],
                                    "accounting_code": proj["accounting_code"],
                                    "is_active": proj["is_active"],
                                },
                            )
                            client_node.children.append(proj_node)

                        # Geography: regions, districts, markets (per-client)
                        for _sql, _ntype, _id_col, _name_col in (
                            (_SQL_GET_REGIONS_FOR_CLIENT, "region", "region_id", "region_name"),
                            (_SQL_GET_DISTRICTS_FOR_CLIENT, "district", "district_id", "district_name"),
                            (_SQL_GET_MARKETS_FOR_CLIENT, "market", "market_id", "market_name"),
                        ):
                            geo_rows = await conn.fetch(_sql, client_id, org_id)
                            for g in geo_rows:
                                client_node.children.append(OrgNode(
                                    node_type=_ntype,
                                    node_id=str(g[_id_col]),
                                    parent_id=str(client_id),
                                    metadata={_name_col: g[_name_col]},
                                ))

                    client_nodes.append(client_node)

            org_node.children = client_nodes

        # Company super-root groups all organizations under this tenant
        company_root = OrgNode(
            node_type="company",
            node_id=f"company:{tenant}",
            parent_id=None,
            metadata={"tenant": tenant},
            children=[org_node],
        )

        return OrgGraph(org_id=org_id, tenant=tenant, root=company_root)

    async def get_node(
        self,
        node_type: NodeType,
        node_id: str,
        *,
        tenant: str,
        org_id: int,
    ) -> OrgNode:
        """Retrieve a single node by type and ID, enforcing tenant isolation.

        Currently supports ``"organization"``, ``"client"``, and ``"program"``
        node types. Other types return a stub node with metadata from a
        best-effort query.

        Args:
            node_type: Type of node to retrieve.
            node_id: String identifier for the node.
            tenant: Tenant slug for isolation (stored in metadata).

        Returns:
            ``OrgNode`` with ``metadata`` populated from the DB.

        Raises:
            KeyError: If the node is not found.
            RuntimeError: If no pool is available.
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            if node_type == "organization":
                # Hard isolation: a caller may only resolve its own session org.
                if int(node_id) != org_id:
                    raise KeyError(f"Organization {node_id} not found")
                row = await conn.fetchrow(_SQL_GET_ORG, int(node_id))
                if row is None:
                    raise KeyError(f"Organization {node_id} not found")
                return OrgNode(
                    node_type="organization",
                    node_id=node_id,
                    metadata={
                        "name": row["name"] if "name" in row.keys() else node_id,
                        "tenant": tenant,
                    },
                )

            if node_type == "client":
                # Hard isolation: client must belong to the caller's org.
                rows = await conn.fetch(
                    _SQL_GET_CLIENT_SCOPED, int(node_id), org_id
                )
                if not rows:
                    raise KeyError(f"Client {node_id} not found")
                row = rows[0]
                return OrgNode(
                    node_type="client",
                    node_id=node_id,
                    metadata={
                        "client_name": row["client_name"],
                        "tenant": tenant,
                    },
                )

            if node_type == "program":
                # Hard isolation: program must reach the caller's org via
                # program_clients → organization_clients.
                rows = await conn.fetch(
                    _SQL_GET_PROGRAM_SCOPED, int(node_id), org_id
                )
                if not rows:
                    raise KeyError(f"Program {node_id} not found")
                row = rows[0]
                return OrgNode(
                    node_type="program",
                    node_id=node_id,
                    metadata={
                        "program_name": row["program_name"],
                        "tenant": tenant,
                    },
                )

        # Geography / store node types are only available within get_graph();
        # a direct single-node lookup is not supported (fail loudly, no stub).
        raise NotImplementedError(
            f"get_node does not support node_type={node_type!r}; "
            "use get_graph() for geography/store nodes"
        )
