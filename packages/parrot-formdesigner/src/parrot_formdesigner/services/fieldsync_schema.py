"""DDL canónico para el schema ``fieldsync`` — idempotente, sin migraciones.

El schema ``fieldsync`` es el *system of record* de FEAT-302:

- ``fieldsync.projects`` — proyectos internos (contienen ``accounting_code``
  = cost center propio; UNIQUE por ``(client_id, accounting_code)``).
- ``fieldsync.workday_cost_center_mappings`` — mapeo de salida hacia Workday;
  un proyecto → un código Workday (UNIQUE por ``project_id``).
- ``fieldsync.auth_policies`` — policies ABAC/PBAC persistidas como JSONB;
  compatibles con el formato YAML del engine de nav-auth.

Diseño:
- NUNCA se lee ni escribe directamente sobre ``networkninja.projects``.
  El seed inicial (scripts/seed_fieldsync_projects.py) lee de allí solo
  para poblar ``fieldsync.projects``; después este schema es autónomo.
- DDL 100% idempotente: ``CREATE SCHEMA IF NOT EXISTS`` +
  ``CREATE TABLE IF NOT EXISTS``; segunda ejecución no falla.
- Sin framework de migraciones; columnas añadidas en futuras tasks con
  ALTER TABLE idempotente o un script de migración explícito.

Uso::

    pool = await asyncpg.create_pool(dsn=...)
    schema_mgr = FieldsyncSchemaManager(pool)
    await schema_mgr.initialize()  # crea schema + 3 tablas si no existen
"""

from __future__ import annotations

import logging

from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL constants
# ---------------------------------------------------------------------------

_CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS fieldsync;"

_CREATE_PROJECTS_SQL = """
CREATE TABLE IF NOT EXISTS fieldsync.projects (
    project_id      SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL,
    name            VARCHAR(255),
    description     TEXT,
    accounting_code VARCHAR(100) NOT NULL,
    start_timestamp TIMESTAMPTZ,
    end_timestamp   TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    org_id          INTEGER,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_projects_client_accounting UNIQUE (client_id, accounting_code)
);
"""

_CREATE_WORKDAY_COST_CENTER_MAPPINGS_SQL = """
CREATE TABLE IF NOT EXISTS fieldsync.workday_cost_center_mappings (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER NOT NULL
                   REFERENCES fieldsync.projects (project_id)
                   ON DELETE CASCADE,
    workday_code VARCHAR(100) NOT NULL,
    direction    VARCHAR(50) NOT NULL DEFAULT 'internal_to_workday',
    CONSTRAINT uq_workday_mapping_project UNIQUE (project_id)
);
"""

_CREATE_AUTH_POLICIES_SQL = """
CREATE TABLE IF NOT EXISTS fieldsync.auth_policies (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(255) UNIQUE NOT NULL,
    policy     JSONB NOT NULL,
    tenant     VARCHAR(63),
    priority   INTEGER NOT NULL DEFAULT 50,
    enforcing  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Ordered list of DDL statements executed by ``initialize()``.
_ALL_DDL: list[str] = [
    _CREATE_SCHEMA_SQL,
    _CREATE_PROJECTS_SQL,
    _CREATE_WORKDAY_COST_CENTER_MAPPINGS_SQL,
    _CREATE_AUTH_POLICIES_SQL,
]


class FieldsyncSchemaManager:
    """Apply the canonical ``fieldsync`` DDL to a Postgres database.

    All DDL statements are idempotent — executing ``initialize()`` twice on
    the same database is safe and produces no side effects.

    This class never opens a connection itself; it receives an existing
    asyncpg pool (or a compatible fake pool for unit tests).

    Args:
        pool: asyncpg connection pool (or fake with the same ``acquire()``
            async context manager interface).

    Example::

        pool = await asyncpg.create_pool(dsn=DB_DSN)
        mgr = FieldsyncSchemaManager(pool)
        await mgr.initialize()
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """Run all DDL statements in order, creating schema + 3 tables.

        Idempotent: safe to call on startup even if the objects already exist.

        Raises:
            Exception: Any asyncpg error propagates as-is (e.g. permission
                denied, connection error).
        """
        async with self._pool.acquire() as conn:
            for sql in _ALL_DDL:
                self.logger.debug("fieldsync DDL: %s", sql.strip()[:80])
                await conn.execute(sql)
        self.logger.info("fieldsync schema initialized (idempotent)")

    # ------------------------------------------------------------------
    # Introspection helpers (useful for tests)
    # ------------------------------------------------------------------

    @staticmethod
    def ddl_statements() -> list[str]:
        """Return the ordered list of DDL SQL strings (read-only copy).

        Returns:
            List of SQL strings in execution order.
        """
        return list(_ALL_DDL)
