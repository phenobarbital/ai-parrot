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
        # -- guests --------------------------------------------------------
        # People a tenant may contact with an offer. Created before reviews
        # because a review references one.
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.guests (
            guest_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         text        NOT NULL
                                          REFERENCES {schema}.tenants (tenant_id),
            email             text        NOT NULL DEFAULT '',
            phone             text        NOT NULL DEFAULT '',
            display_name      text        NOT NULL DEFAULT '',
            consent_marketing boolean     NOT NULL DEFAULT false,
            lifetime_visits   integer     NOT NULL DEFAULT 0,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now()
        )
        """,
        # Partial uniques, not plain ones: most guests have exactly one of the
        # two contact fields, and a NOT NULL DEFAULT '' would otherwise make
        # every contactless guest collide with every other.
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS guests_email_idx
            ON {schema}.guests (tenant_id, email) WHERE email <> ''
        """,
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS guests_phone_idx
            ON {schema}.guests (tenant_id, phone) WHERE phone <> ''
        """,
        # -- reviews -------------------------------------------------------
        # ``body`` rather than ``text``: the latter is a type name and reads
        # badly in a select list. ``location_ref`` is deliberately a free
        # string and not a foreign key — a review can arrive for a venue the
        # tenant has not configured yet, and refusing it would lose data the
        # platform will not resend.
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.reviews (
            review_id    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    text        NOT NULL
                                     REFERENCES {schema}.tenants (tenant_id),
            source       text        NOT NULL,
            external_id  text        NOT NULL,
            location_ref text        NOT NULL DEFAULT '',
            guest_id     uuid        REFERENCES {schema}.guests (guest_id),
            rating       integer     NOT NULL DEFAULT 0,
            body         text        NOT NULL DEFAULT '',
            language     text        NOT NULL DEFAULT 'en',
            author_name  text        NOT NULL DEFAULT '',
            status       text        NOT NULL DEFAULT 'received',
            posted_at    timestamptz NOT NULL DEFAULT now(),
            received_at  timestamptz NOT NULL DEFAULT now(),
            raw          jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            CONSTRAINT reviews_source_uniq UNIQUE (tenant_id, source, external_id)
        )
        """,
        # This constraint is the whole de-duplication story: a webhook replay
        # is an ON CONFLICT rather than a second run, a second reply and a
        # second coupon.
        f"""
        CREATE INDEX IF NOT EXISTS reviews_tenant_status_idx
            ON {schema}.reviews (tenant_id, status)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS reviews_tenant_posted_idx
            ON {schema}.reviews (tenant_id, posted_at DESC)
        """,
        # -- review replies ------------------------------------------------
        # Every drafting attempt is a row, published or not: the repair loop
        # can produce several drafts for one review, and keeping only the
        # published one erases the evidence for why it reads as it does.
        #
        # ``tenant_id`` is denormalised here on purpose. It is reachable
        # through ``review_id``, but BaseRepository refuses any statement that
        # does not name it, and a join is a poor place to put the isolation
        # predicate.
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.review_replies (
            reply_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         text        NOT NULL,
            review_id         uuid        NOT NULL
                                          REFERENCES {schema}.reviews (review_id)
                                          ON DELETE CASCADE,
            body              text        NOT NULL DEFAULT '',
            status            text        NOT NULL DEFAULT 'draft',
            external_reply_id text        NOT NULL DEFAULT '',
            attempt           integer     NOT NULL DEFAULT 1,
            reason            text        NOT NULL DEFAULT '',
            created_at        timestamptz NOT NULL DEFAULT now()
        )
        """,
        f"""
        CREATE INDEX IF NOT EXISTS review_replies_review_idx
            ON {schema}.review_replies (tenant_id, review_id, created_at DESC)
        """,
        # -- eligibility rules ---------------------------------------------
        # navrules rule rows, edited by the tenant through the rules API.
        #
        # There is deliberately no ``rule_type`` column. Only declarative
        # ConditionRules are admissible — anything else makes
        # ``RuleSet.evaluate_sync()`` raise, which would break the flow for
        # every review that tenant receives — and storing a type that can only
        # hold one value is an invitation to set it to another. The storage
        # emits the type as a constant instead, which no SQL can subvert.
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.rules (
            rule_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   text        NOT NULL
                                    REFERENCES {schema}.tenants (tenant_id),
            ruleset     text        NOT NULL DEFAULT 'coupon_eligibility',
            name        text        NOT NULL,
            priority    integer     NOT NULL DEFAULT 0,
            enabled     boolean     NOT NULL DEFAULT true,
            conditions  jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            result      jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            description text        NOT NULL DEFAULT '',
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT rules_name_uniq UNIQUE (tenant_id, ruleset, name)
        )
        """,
        # ``rule_id`` is the tie-break, and it is load-bearing: RuleSet.compile()
        # sorts by priority with a *stable* sort, so rules of equal priority
        # keep the order they arrived in. Without a deterministic second key
        # the winner between two equal-priority offers would depend on the
        # order Postgres happened to return rows in.
        f"""
        CREATE INDEX IF NOT EXISTS rules_lookup_idx
            ON {schema}.rules (tenant_id, ruleset, priority DESC, rule_id)
            WHERE enabled
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
