"""Create the navigator-auth schema and a demo user for the passkey example.

Idempotent. Run once after ``docker compose up -d``::

    python examples/passkey/setup_demo_db.py

The user is ``demo`` / ``demo-password`` (override with ``DEMO_USER`` /
``DEMO_PASSWORD``). Passkey tables are created by ``PasskeyAuth`` itself on
server startup.
"""

from __future__ import annotations

import asyncio
import os

import asyncpg

from env_defaults import apply_defaults

apply_defaults()

from navigator_auth.handlers.users.passwd import set_basic_password  # noqa: E402

DSN = "postgres://{u}:{p}@{h}:{port}/{db}".format(
    u=os.environ["DBUSER"], p=os.environ["DBPWD"], h=os.environ["DBHOST"],
    port=os.environ["DBPORT"], db=os.environ["DBNAME"],
)

DDL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
    user_id       bigserial PRIMARY KEY,
    userid        uuid NOT NULL DEFAULT uuid_generate_v4(),
    username      varchar NOT NULL UNIQUE,
    first_name    varchar,
    last_name     varchar,
    display_name  varchar,
    email         varchar,
    alt_email     varchar,
    password      varchar(128),
    last_login    timestamptz,
    user_role     integer NOT NULL DEFAULT 1,
    is_superuser  boolean NOT NULL DEFAULT false,
    is_staff      boolean DEFAULT true,
    title         varchar,
    avatar        text,
    is_active     boolean NOT NULL DEFAULT true,
    is_new        boolean NOT NULL DEFAULT true,
    timezone      varchar DEFAULT 'UTC',
    attributes    jsonb,
    created_at    timestamptz DEFAULT CURRENT_TIMESTAMP,
    updated_at    timestamptz DEFAULT CURRENT_TIMESTAMP,
    created_by    varchar
);
"""


async def main() -> None:
    """Create the schema and upsert the demo user."""
    username = os.environ.get("DEMO_USER", "demo")
    password = os.environ.get("DEMO_PASSWORD", "demo-password")
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(DDL)
        await conn.execute(
            """
            INSERT INTO auth.users (username, first_name, last_name, display_name, email, password, is_superuser)
            VALUES ($1, 'Demo', 'User', 'Demo User', $2, $3, true)
            ON CONFLICT (username) DO UPDATE SET password = EXCLUDED.password
            """,
            username, f"{username}@example.com", set_basic_password(password),
        )
    finally:
        await conn.close()
    print(f"Ready: user '{username}' in {os.environ['DBHOST']}:{os.environ['DBPORT']}/{os.environ['DBNAME']}")


if __name__ == "__main__":
    asyncio.run(main())
