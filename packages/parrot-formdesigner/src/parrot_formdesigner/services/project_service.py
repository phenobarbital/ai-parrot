"""ProjectService — CRUD sobre ``fieldsync.projects`` + mapping Workday.

Implementa el *system of record* de proyectos internos (FEAT-302 Module 2):
- ``create_project`` / ``get_project`` / ``list_projects``
- ``map_to_workday`` (upsert en ``fieldsync.workday_cost_center_mappings``)

Reglas de negocio confirmadas (§8 spec):
- ``accounting_code`` es el **cost center interno**; NUNCA se importa desde
  Workday (Workday es destino de salida, no fuente).
- UNIQUE ``(client_id, accounting_code)`` — duplicate → ``DuplicateAccountingCodeError``.
- ``map_to_workday`` hace UPSERT por ``project_id`` (un proyecto tiene como
  máximo un Workday mapping).
- NUNCA se escribe en ``networkninja.projects``.

Diseño:
- Pool inyectado en constructor → testable sin DB real.
- SQL 100% parametrizado ($1, $2…); nombres de tabla fijados en constantes.
- Pydantic v2 para modelos de datos.

Uso::

    svc = ProjectService(pool)
    proj = await svc.create_project(
        accounting_code="ACC-001",
        name="Q1 Campaign",
        client_id=42,
        org_id=7,
        tenant="acme",
    )
    mapping = await svc.map_to_workday(proj.project_id, "WD-99001", tenant="acme")
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DuplicateAccountingCodeError(Exception):
    """Raised when ``(client_id, accounting_code)`` already exists.

    Attributes:
        client_id: Client the conflict belongs to.
        accounting_code: The duplicate code.
    """

    def __init__(self, client_id: int, accounting_code: str) -> None:
        self.client_id = client_id
        self.accounting_code = accounting_code
        super().__init__(
            f"accounting_code {accounting_code!r} already exists for client {client_id}"
        )


class ProjectNotFoundError(Exception):
    """Raised when a project lookup returns no row.

    Attributes:
        project_id: The missing project identifier.
    """

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id
        super().__init__(f"Project {project_id} not found")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Project(BaseModel):
    """A project stored in ``fieldsync.projects``.

    Attributes:
        project_id: Auto-incremented serial PK.
        name: Human-readable project name.
        accounting_code: Internal cost center code (source of truth).
        client_id: Client this project belongs to.
        org_id: Organization identifier.
        start_timestamp: Optional project start date.
        end_timestamp: Optional project end date.
        is_active: Whether the project is currently active.
        tenant: Tenant slug (metadata, not stored in the table directly).
    """

    model_config = ConfigDict(extra="forbid")

    project_id: int
    name: str | None
    accounting_code: str
    client_id: int
    org_id: int | None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    is_active: bool = True
    tenant: str | None = None


class WorkdayCostCenterMapping(BaseModel):
    """Mapping from an internal project to a Workday cost center code.

    Attributes:
        project_id: FK to ``fieldsync.projects``.
        workday_code: Workday cost center identifier (output side only).
        direction: Flow direction; default is ``"internal_to_workday"``.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: int
    workday_code: str
    direction: str = "internal_to_workday"


# ---------------------------------------------------------------------------
# SQL constants (table names FIXED in constants — not from user input)
# ---------------------------------------------------------------------------

_INSERT_PROJECT_SQL = """
INSERT INTO fieldsync.projects
    (client_id, name, accounting_code, org_id)
VALUES ($1, $2, $3, $4)
RETURNING project_id, client_id, name, accounting_code, org_id,
          start_timestamp, end_timestamp, is_active
"""

_SELECT_PROJECT_SQL = """
SELECT project_id, client_id, name, accounting_code, org_id,
       start_timestamp, end_timestamp, is_active
FROM fieldsync.projects
WHERE project_id = $1 AND org_id = $2
"""

_SELECT_PROJECTS_BY_CLIENT_SQL = """
SELECT project_id, client_id, name, accounting_code, org_id,
       start_timestamp, end_timestamp, is_active
FROM fieldsync.projects
WHERE client_id = $1 AND org_id = $2
ORDER BY project_id
"""

_SELECT_PROJECTS_BY_ORG_SQL = """
SELECT project_id, client_id, name, accounting_code, org_id,
       start_timestamp, end_timestamp, is_active
FROM fieldsync.projects
WHERE org_id = $1
ORDER BY project_id
"""

_UPSERT_WORKDAY_MAPPING_SQL = """
INSERT INTO fieldsync.workday_cost_center_mappings
    (project_id, workday_code, direction)
VALUES ($1, $2, $3)
ON CONFLICT (project_id) DO UPDATE
    SET workday_code = EXCLUDED.workday_code,
        direction    = EXCLUDED.direction
RETURNING project_id, workday_code, direction
"""

_SELECT_WORKDAY_MAPPING_SQL = """
SELECT project_id, workday_code, direction
FROM fieldsync.workday_cost_center_mappings
WHERE project_id = $1
"""

# asyncpg error code for UNIQUE constraint violation
_UNIQUE_VIOLATION_CODE = "23505"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProjectService:
    """CRUD service for ``fieldsync.projects`` and Workday mappings.

    Args:
        pool: asyncpg pool (or fake pool for tests).

    Example::

        svc = ProjectService(pool)
        proj = await svc.create_project(
            accounting_code="ACC-001",
            name="My Project",
            client_id=42,
            org_id=7,
            tenant="acme",
        )
        await svc.map_to_workday(proj.project_id, "WD-12345", tenant="acme")
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Project CRUD
    # ------------------------------------------------------------------

    async def create_project(
        self,
        *,
        accounting_code: str,
        name: str | None = None,
        client_id: int,
        org_id: int | None = None,
        tenant: str | None = None,
    ) -> Project:
        """Create a new project in ``fieldsync.projects``.

        Args:
            accounting_code: Internal cost center code (UNIQUE per client).
            name: Human-readable project name.
            client_id: Client this project belongs to.
            org_id: Organization identifier.
            tenant: Tenant slug (stored in the returned model metadata only).

        Returns:
            The newly created ``Project`` with its DB-assigned ``project_id``.

        Raises:
            DuplicateAccountingCodeError: If ``(client_id, accounting_code)``
                already exists.
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    _INSERT_PROJECT_SQL,
                    client_id,
                    name,
                    accounting_code,
                    org_id,
                )
            except Exception as exc:
                # Detect asyncpg UniqueViolationError by message or code
                exc_str = str(exc)
                if (
                    "unique" in exc_str.lower()
                    or _UNIQUE_VIOLATION_CODE in exc_str
                    or "uq_projects_client_accounting" in exc_str
                    or "UniqueViolation" in type(exc).__name__
                ):
                    raise DuplicateAccountingCodeError(client_id, accounting_code) from exc
                raise

        return Project(
            project_id=row["project_id"],
            client_id=row["client_id"],
            name=row["name"],
            accounting_code=row["accounting_code"],
            org_id=row["org_id"],
            start_timestamp=row["start_timestamp"],
            end_timestamp=row["end_timestamp"],
            is_active=row["is_active"],
            tenant=tenant,
        )

    async def get_project(
        self, project_id: int, *, org_id: int, tenant: str | None = None
    ) -> Project:
        """Retrieve a project by its primary key, scoped to ``org_id``.

        Args:
            project_id: Primary key of the project.
            org_id: Organization the caller is scoped to (hard isolation).
            tenant: Optional tenant slug (stored in returned model).

        Returns:
            ``Project`` model populated from the DB row.

        Raises:
            ProjectNotFoundError: If no project with ``project_id`` exists
                within ``org_id``.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_PROJECT_SQL, project_id, org_id)
        if row is None:
            raise ProjectNotFoundError(project_id)
        return Project(
            project_id=row["project_id"],
            client_id=row["client_id"],
            name=row["name"],
            accounting_code=row["accounting_code"],
            org_id=row["org_id"],
            start_timestamp=row["start_timestamp"],
            end_timestamp=row["end_timestamp"],
            is_active=row["is_active"],
            tenant=tenant,
        )

    async def list_projects(
        self,
        *,
        org_id: int,
        client_id: int | None = None,
        tenant: str | None = None,
    ) -> list[Project]:
        """List projects within ``org_id`` (hard isolation), optionally by client.

        Args:
            org_id: Organization the caller is scoped to (REQUIRED — every
                query is filtered by it; there is no cross-tenant list path).
            client_id: Optionally narrow to a single client within the org.
            tenant: Tenant slug stored in returned models.

        Returns:
            List of ``Project`` instances (empty list if none match).
        """
        async with self._pool.acquire() as conn:
            if client_id is not None:
                rows = await conn.fetch(
                    _SELECT_PROJECTS_BY_CLIENT_SQL, client_id, org_id
                )
            else:
                rows = await conn.fetch(_SELECT_PROJECTS_BY_ORG_SQL, org_id)

        return [
            Project(
                project_id=row["project_id"],
                client_id=row["client_id"],
                name=row["name"],
                accounting_code=row["accounting_code"],
                org_id=row["org_id"],
                start_timestamp=row["start_timestamp"],
                end_timestamp=row["end_timestamp"],
                is_active=row["is_active"],
                tenant=tenant,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Workday mapping
    # ------------------------------------------------------------------

    async def map_to_workday(
        self,
        project_id: int,
        workday_code: str,
        *,
        tenant: str | None = None,
        direction: str = "internal_to_workday",
    ) -> WorkdayCostCenterMapping:
        """Create or update a Workday cost center mapping for a project.

        Uses UPSERT — if a mapping already exists for ``project_id``, its
        ``workday_code`` is updated in place.

        Args:
            project_id: FK to ``fieldsync.projects``.
            workday_code: Workday cost center identifier.
            tenant: Tenant slug (not stored in the mapping table; used for logs).
            direction: Flow direction (default ``"internal_to_workday"``).

        Returns:
            ``WorkdayCostCenterMapping`` reflecting the persisted row.

        Raises:
            Exception: Any DB error (e.g. FK violation if project_id unknown).
        """
        self.logger.info(
            "map_to_workday: project_id=%s workday_code=%s tenant=%s",
            project_id,
            workday_code,
            tenant,
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                _UPSERT_WORKDAY_MAPPING_SQL,
                project_id,
                workday_code,
                direction,
            )
        return WorkdayCostCenterMapping(
            project_id=row["project_id"],
            workday_code=row["workday_code"],
            direction=row["direction"],
        )
