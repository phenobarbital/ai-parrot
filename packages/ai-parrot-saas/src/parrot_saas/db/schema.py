"""DDL for the SaaS schema, applied idempotently at start-up.

This repository has **no migration framework**. Its convention, stated in
``packages/parrot-formdesigner/migrations/README.md``, is that the application
code creates the schema for greenfield installs, and ``migrations/`` holds
plain, manually-run scripts only for deployments that already exist and need a
change applied. This module is the greenfield half for the SaaS plane.

All DDL lives here rather than in each repository because the tables reference
one another and creation order matters. Every statement is idempotent, so
running it on every boot is free.

Tenant isolation is a ``tenant_id`` column, not a schema per tenant: the
control plane creates tenants over HTTP, and DDL-on-signup does not survive
self-service. Physical isolation is available where it actually matters — a
``dedicated`` tenant gets its own database in its provisioned stack.
"""
from __future__ import annotations

from typing import Sequence

from asyncdb import AsyncDB
from navconfig.logging import logging

from .repository import check_identifier

logger = logging.getLogger("parrot_saas.db.schema")


def _statements(schema: str) -> Sequence[str]:
    """Return every DDL statement, in dependency order.

    Args:
        schema: Validated schema name.

    Returns:
        The statements to execute.
    """
    return (
        f"CREATE SCHEMA IF NOT EXISTS {schema}",
        # -- tenants -------------------------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.tenants (
            tenant_id  text        PRIMARY KEY,
            name       text        NOT NULL,
            mode       text        NOT NULL DEFAULT 'shared',
            status     text        NOT NULL DEFAULT 'active',
            timezone   text        NOT NULL DEFAULT 'UTC',
            locale     text        NOT NULL DEFAULT 'en',
            settings   jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        # A partial index rather than a plain one: the control plane's hot
        # query is "every active tenant", and suspended rows are dead weight
        # in it.
        f"""
        CREATE INDEX IF NOT EXISTS tenants_active_idx
            ON {schema}.tenants (tenant_id) WHERE status = 'active'
        """,
        f"""
        CREATE INDEX IF NOT EXISTS tenants_mode_idx
            ON {schema}.tenants (mode)
        """,
    )


async def ensure_schema(conn: AsyncDB, *, schema: str = "saas") -> None:
    """Create the SaaS schema and its tables if they do not exist.

    Safe to call on every start-up and from concurrent workers: every
    statement is ``IF NOT EXISTS``.

    Note the secret-store tables (``tenant_deks`` / ``tenant_secrets``) are
    **not** created here. :class:`~parrot.security.secrets.postgres.EncryptedPostgresSecretStore`
    owns them and creates them itself, because it lives in core and must work
    without this package. Both create the schema, which is why that statement
    is first and idempotent — neither has to run before the other.

    Args:
        conn: An open asyncdb connection.
        schema: Schema name to create the tables in.

    Raises:
        ValueError: If ``schema`` is not a safe identifier.
    """
    safe = check_identifier(schema, "schema")
    for statement in _statements(safe):
        await conn.execute(statement)
    logger.info("SaaS schema %r ensured", safe)


__all__ = ("ensure_schema",)
