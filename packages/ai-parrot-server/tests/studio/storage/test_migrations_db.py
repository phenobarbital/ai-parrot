"""FEAT-621 M1 — real-Postgres migration tests (AC1, AC2, AC3)."""
import asyncio
import os


from parrot.handlers.studio.storage.migrate import (
    STUDIO_SCHEMA_REQUIRED,
    apply_studio_migrations,
    list_migrations,
    main,
    read_ledger,
)
from parrot.handlers.studio.storage.repositories import _exec, studio_transaction

_DROP = (
    "DROP TABLE IF EXISTS navigator.ai_agent_assets, navigator.ai_agent_tooling, navigator.ai_agent_drafts, "
    "navigator.ai_agents, navigator.ai_skills_catalog, navigator.studio_drafts, "
    "navigator.ai_studio_migrations CASCADE"
)


async def _run(pool, sql, *args):
    """Execute raw SQL outside any transaction; return the error text, or None on success.

    asyncdb 2.16.2's ``execute`` swallows unique/FK/not-null violations (``return`` inside ``finally``) and hands
    back the previous statement's result, so DML goes through a data-modifying CTE on ``fetch_one``, which
    raises ``ProviderError`` on any violation.
    """
    if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
        sql = f"WITH r AS ({sql} RETURNING 1) SELECT count(*) AS n FROM r"
        async with pool.acquire() as conn:
            try:
                await conn.fetch_one(sql, *args)
            except Exception as exc:
                return repr(exc)
        return None
    async with pool.acquire() as conn:
        try:
            result = await conn.execute(sql, *args)
        except Exception as exc:
            return repr(exc)
    return result[1] if isinstance(result, list) and result[1] else None


async def _one(pool, sql, *args):
    async with pool.acquire() as conn:
        return await conn.fetch_one(sql, *args)


async def _all(pool, sql, *args):
    async with pool.acquire() as conn:
        return list(await conn.fetch_all(sql, *args) or [])


async def _empty(pool) -> None:
    assert await _run(pool, _DROP) is None


def _manifest() -> dict:
    return {m.version: m.checksum for m in list_migrations()}


async def _ledger(pool) -> dict:
    async with pool.acquire() as conn:
        return (await read_ledger(conn)).applied


def _cli(*argv: str) -> int:
    return main(["--dsn", os.environ["TEST_STUDIO_PG_DSN"], *argv])


async def test_migrations_apply_twice(studio_pool) -> None:
    pool = studio_pool
    await _empty(pool)
    assert await apply_studio_migrations(pool) == [1, 2, 3, 4, 5]
    assert await apply_studio_migrations(pool) == []
    assert await _ledger(pool) == _manifest()
    assert await asyncio.to_thread(_cli, "--verify") == 0


async def test_migrations_apply_on_feat467_database(studio_pool) -> None:
    pool = studio_pool
    await _empty(pool)
    uuid_default = "gen_random_uuid()"
    if await _run(pool, 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"') is None:
        uuid_default = "uuid_generate_v4()"
    for ddl in (
        "CREATE SCHEMA IF NOT EXISTS navigator",
        f"""CREATE TABLE navigator.ai_skills_catalog (
            skill_id UUID PRIMARY KEY DEFAULT {uuid_default}, name VARCHAR NOT NULL UNIQUE,
            description TEXT NOT NULL, category VARCHAR NOT NULL DEFAULT 'general', owner VARCHAR NOT NULL,
            triggers JSONB DEFAULT '[]'::JSONB, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR NOT NULL DEFAULT 'active', search_index_stale BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())""",
        f"""CREATE TABLE navigator.studio_drafts (
            draft_id UUID PRIMARY KEY DEFAULT {uuid_default}, name VARCHAR NOT NULL UNIQUE,
            file_path VARCHAR NOT NULL, status VARCHAR NOT NULL DEFAULT 'draft',
            validation_report JSONB DEFAULT '{{}}'::JSONB, base_class VARCHAR, owner_user_id VARCHAR NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            activated_at TIMESTAMP WITH TIME ZONE)""",
        "INSERT INTO navigator.ai_skills_catalog (name, description, owner, body) VALUES ('s1','d','u','b')",
        "INSERT INTO navigator.studio_drafts (name, file_path, owner_user_id) VALUES ('d1','/x.py','u')",
    ):
        assert await _run(pool, ddl) is None, ddl
    assert await apply_studio_migrations(pool) == [1, 2, 3, 4, 5]
    assert await apply_studio_migrations(pool) == []
    assert await asyncio.to_thread(_cli, "--verify") == 0
    row = await _one(pool, "SELECT tenant, visibility FROM navigator.ai_skills_catalog WHERE name = 's1'")
    assert row["tenant"] is None and row["visibility"] == "private"
    assert (await _one(pool, "SELECT count(*) AS n FROM navigator.studio_drafts"))["n"] == 1
    ins = "INSERT INTO navigator.ai_skills_catalog (tenant, name, description, owner, body) VALUES ($1,$2,'d','u','b')"
    assert await _run(pool, ins, "acme", "s1") is None
    assert await _run(pool, ins, "beta", "s1") is None          # per-partition uniqueness
    assert await _run(pool, ins, "acme", "s1") is not None      # duplicate in the partition
    assert await _run(pool, ins, None, "s1") is not None        # duplicate in the non-tenant partition


async def test_host_created_unique_index_on_name_warns(studio_pool) -> None:
    pool = studio_pool
    await _empty(pool)
    assert await _run(pool, "CREATE SCHEMA IF NOT EXISTS navigator") is None
    assert await _run(
        pool,
        "CREATE TABLE navigator.ai_skills_catalog (skill_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "name varchar NOT NULL, description text NOT NULL, category varchar NOT NULL DEFAULT 'general', "
        "owner varchar NOT NULL, triggers jsonb, body text NOT NULL, version integer NOT NULL DEFAULT 1, "
        "status varchar NOT NULL DEFAULT 'active', search_index_stale boolean NOT NULL DEFAULT false, "
        "created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())",
    ) is None
    assert await _run(pool, "CREATE UNIQUE INDEX host_skill_name_uq ON navigator.ai_skills_catalog (name)") is None
    await apply_studio_migrations(pool)
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    assert state.skills_name_unique_index and state.warnings()
    assert state.complete_for(STUDIO_SCHEMA_REQUIRED, _manifest())      # a warning, not a problem


async def test_migrations_detect_altered_and_missing(studio_pool) -> None:
    pool = studio_pool
    manifest = _manifest()
    await _empty(pool)
    await apply_studio_migrations(pool)
    async with pool.acquire() as conn:
        assert (await read_ledger(conn)).complete_for(STUDIO_SCHEMA_REQUIRED, manifest)

    assert await _run(pool, "UPDATE navigator.ai_studio_migrations SET checksum = $1 WHERE version = 2", "0" * 64) is None
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    assert state.problems(STUDIO_SCHEMA_REQUIRED, manifest) == ["drift 2"]
    assert not state.complete_for(STUDIO_SCHEMA_REQUIRED, manifest)
    assert await asyncio.to_thread(_cli, "--verify") == 1
    assert await _run(pool, "UPDATE navigator.ai_studio_migrations SET checksum = $1 WHERE version = 2", manifest[2]) is None

    assert await _run(pool, "DELETE FROM navigator.ai_studio_migrations WHERE version = 3") is None
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    assert state.problems(STUDIO_SCHEMA_REQUIRED, manifest) == ["missing 3"]      # a gap, not "max(version)"
    assert await asyncio.to_thread(_cli, "--verify") == 1
    assert await apply_studio_migrations(pool) == [3]                              # re-applies only the gap

    assert await _run(
        pool, "INSERT INTO navigator.ai_studio_migrations (version, name, checksum) VALUES (99, 'x', $1)", "a" * 64
    ) is None
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    assert state.problems(STUDIO_SCHEMA_REQUIRED, manifest) == ["unknown 99"]
    assert await asyncio.to_thread(_cli, "--verify") == 1
    assert await _run(pool, "DELETE FROM navigator.ai_studio_migrations WHERE version = 99") is None


async def _raw_per_file_runner(pool) -> None:
    """The FieldSync path: every packaged file's raw bytes (body + trailer) in one transaction."""
    for mig in list_migrations():
        async with studio_transaction(pool) as conn:
            await _exec(conn, (mig.body + mig.trailer).decode("utf-8"))


async def test_migrations_concurrent_runners(studio_pool) -> None:
    pool = studio_pool
    manifest = _manifest()
    for _ in range(10):
        await _empty(pool)
        first, second = await asyncio.gather(apply_studio_migrations(pool), apply_studio_migrations(pool))
        assert sorted(first + second) == [1, 2, 3, 4, 5]          # each version recorded by exactly one runner
        assert await _ledger(pool) == manifest
    for _ in range(5):
        await _empty(pool)
        await asyncio.gather(apply_studio_migrations(pool), _raw_per_file_runner(pool))
        assert await _ledger(pool) == manifest
        assert (await _one(pool, "SELECT count(*) AS n FROM navigator.ai_studio_migrations"))["n"] == 5


async def test_host_runner_records_same_checksums(studio_pool) -> None:
    pool = studio_pool
    await _empty(pool)
    await _raw_per_file_runner(pool)
    await _raw_per_file_runner(pool)                                # idempotent
    assert await _ledger(pool) == _manifest()
    async with pool.acquire() as conn:
        assert (await read_ledger(conn)).complete_for(STUDIO_SCHEMA_REQUIRED, _manifest())
    assert await apply_studio_migrations(pool) == []


async def test_probe_is_read_only(studio_pool) -> None:
    pool = studio_pool
    await _empty(pool)
    before = await _all(pool, "SELECT relname FROM pg_class ORDER BY relname")
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    assert state.present is False and state.applied == {} and state.server_version_num >= 140000
    assert await _all(pool, "SELECT relname FROM pg_class ORDER BY relname") == before
    assert (await _one(pool, "SELECT to_regclass('navigator.ai_studio_migrations') AS r"))["r"] is None
    assert await asyncio.to_thread(_cli, "--dry-run") == 0
    assert (await _one(pool, "SELECT to_regclass('navigator.ai_studio_migrations') AS r"))["r"] is None


async def test_constraints_raw_sql(studio_pool) -> None:
    pool = studio_pool
    await _truncate(pool)
    cat = "INSERT INTO navigator.ai_skills_catalog (tenant, visibility, name, description, owner, body) VALUES ($1,$2,'n','d','o','b')"
    assert await _run(pool, cat, "acme", "public") is not None
    assert await _run(pool, cat, None, "tenant") is not None
    assert await _run(pool, cat, "Bad Tenant", "private") is not None
    drf = "INSERT INTO navigator.ai_agent_drafts (tenant, visibility, owner, name, definition) VALUES ($1,$2,'o','n','{}'::jsonb)"
    assert await _run(pool, drf, "-x", "private") is not None
    assert await _run(pool, drf, None, "groups") is not None
    agent = "INSERT INTO navigator.ai_agents (tenant, owner, name, definition) VALUES (NULL,'o',$1,'{}'::jsonb)"
    assert await _run(pool, agent, "a:b") is not None
    assert await _run(pool, agent, "ok") is None
    aid = (await _one(pool, "SELECT agent_id FROM navigator.ai_agents WHERE name = 'ok'"))["agent_id"]
    asset = (
        "INSERT INTO navigator.ai_agent_assets (agent_id, kind, name, content, size, sha256) "
        "VALUES ($1,'kb','x.md','c',$2,$3)"
    )
    assert await _run(pool, asset, aid, -1, "a" * 64) is not None
    tool = (
        "INSERT INTO navigator.ai_agent_tooling (agent_id, kind, slug, config) VALUES ($1,'toolkit','jira',$2::text::jsonb)"
    )
    assert await _run(pool, tool, aid, "[]") is not None
    assert await _run(pool, tool, aid, "{}") is None


async def _truncate(pool) -> None:
    from .conftest import _truncate_studio_tables

    await _truncate_studio_tables(pool)


async def test_delete_cascades_with_touch_trigger(studio_pool) -> None:
    pool = studio_pool
    await _truncate(pool)
    assert await _run(pool, "INSERT INTO navigator.ai_agents (owner, name, definition) VALUES ('o','casc','{}'::jsonb)") is None
    aid = (await _one(pool, "SELECT agent_id FROM navigator.ai_agents WHERE name = 'casc'"))["agent_id"]
    assert await _run(
        pool,
        "INSERT INTO navigator.ai_agent_assets (agent_id, kind, name, content, size, sha256) VALUES ($1,'kb','a.md','c',1,$2)",
        aid, "b" * 64,
    ) is None
    assert await _run(pool, "INSERT INTO navigator.ai_agent_tooling (agent_id, kind, slug) VALUES ($1,'mcp','m')", aid) is None
    assert await _run(pool, "DELETE FROM navigator.ai_agents WHERE agent_id = $1", aid) is None
    for table in ("ai_agents", "ai_agent_assets", "ai_agent_tooling"):
        assert (await _one(pool, f"SELECT count(*) AS n FROM navigator.{table}"))["n"] == 0


async def test_version_bumps_on_child_write(studio_pool) -> None:
    pool = studio_pool
    await _truncate(pool)
    assert await _run(pool, "INSERT INTO navigator.ai_agents (owner, name, definition) VALUES ('o','ver','{}'::jsonb)") is None
    aid = (await _one(pool, "SELECT agent_id FROM navigator.ai_agents WHERE name = 'ver'"))["agent_id"]

    async def version() -> int:
        return (await _one(pool, "SELECT version FROM navigator.ai_agents WHERE agent_id = $1", aid))["version"]

    assert await version() == 1
    assert await _run(pool, "UPDATE navigator.ai_agents SET description_unused = 1") is not None   # sanity: bad SQL errors
    assert await _run(pool, "UPDATE navigator.ai_agents SET status = 'disabled' WHERE agent_id = $1", aid) is None
    assert await version() == 2                                      # a psql-style UPDATE bumps it
    assert await _run(
        pool,
        "INSERT INTO navigator.ai_agent_assets (agent_id, kind, name, content, size, sha256) VALUES ($1,'kb','a.md','c',1,$2)",
        aid, "c" * 64,
    ) is None
    assert await version() == 3                                      # child write touches the parent
    assert await _run(pool, "INSERT INTO navigator.ai_agent_tooling (agent_id, kind, slug) VALUES ($1,'mcp','m')", aid) is None
    assert await version() == 4
    assert await _run(pool, "DELETE FROM navigator.ai_agent_assets WHERE agent_id = $1", aid) is None
    assert await version() == 5
