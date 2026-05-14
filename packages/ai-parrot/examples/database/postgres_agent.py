"""Postgres DatabaseAgent example — FEAT-164 homologation demo.

Demonstrates the refactored DatabaseAgent shape:
- Single PostgresToolkit + configure/cleanup lifecycle.
- QueryResponse structured output (explanation, query, data).
- Three query flavours: schema exploration, NL→SQL, raw SQL validation.
- Retry loop in action: deliberately incorrect column name exercises TASK-1129.

Run::

    python -m examples.database.postgres_agent

Credentials are read from the ``querysource`` default database config or from
the ``DATABASE_URL`` environment variable as a fallback.  When neither is
available the script exits 0 with a friendly message.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("examples.postgres_agent")


# ---------------------------------------------------------------------------
# DSN helper — deferred to avoid import-time failure when querysource is not
# configured (querysource.conf raises RuntimeError at module level if the
# default PostgreSQL settings are absent).
# ---------------------------------------------------------------------------

def _get_dsn() -> Optional[str]:
    """Return the database DSN from querysource config or DATABASE_URL env var."""
    try:
        from querysource.conf import async_database_url  # type: ignore[import-untyped]
        return async_database_url("default")
    except Exception:
        return os.environ.get("DATABASE_URL")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_response(label: str, output: object) -> None:
    """Print a labelled QueryResponse section."""
    from parrot.bots.database import QueryResponse  # local import — no side effects

    print(f"\n=== {label} ===")
    if not isinstance(output, QueryResponse):
        print("(no structured output)")
        return
    print(f"Explanation : {output.explanation}")
    print(f"Query       : {output.query}")
    if output.data is not None:
        print(f"Rows        : {output.data.row_count}  columns: {output.data.columns}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Run the DatabaseAgent demo."""
    dsn = _get_dsn()
    if not dsn:
        print(
            "No database URL configured.  "
            "Set DATABASE_URL or configure querysource default settings."
        )
        return

    from parrot.bots.database import DatabaseAgent, PostgresToolkit
    from parrot.bots.database.models import UserRole
    from parrot.bots.database.retries import QueryRetryConfig

    toolkit = PostgresToolkit(
        dsn=dsn,
        allowed_schemas=["public"],
        primary_schema="public",
        read_only=True,
    )
    agent = DatabaseAgent(
        name="postgres-demo",
        toolkits=[toolkit],
        default_user_role=UserRole.DATA_ANALYST,
        retry_config=QueryRetryConfig(max_retries=2),
    )

    try:
        await agent.configure()
    except Exception as exc:
        logger.warning("Could not configure agent (Postgres unreachable?): %s", exc)
        return

    try:
        # 1. Schema exploration
        msg = await agent.ask("List the tables in the public schema.")
        _print_response("schema exploration", msg.output)

        # 2. NL → SQL
        msg = await agent.ask("How many rows are in the users table?")
        _print_response("nl->sql", msg.output)

        # 3. Raw SQL validation
        msg = await agent.ask("Validate this query: SELECT 1 FROM dual")
        _print_response("raw sql validation", msg.output)

        # 4. Retry demo — deliberate column typo exercises the retry loop
        try:
            msg = await agent.ask(
                "Get the usrname column (typo) from auth.users table"
            )
            _print_response("retry demo", msg.output)
        except Exception as exc:
            logger.warning("Retry demo raised (expected if no auth schema): %s", exc)

    except Exception as exc:
        logger.warning("Agent ask() failed: %s", exc)
    finally:
        await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
