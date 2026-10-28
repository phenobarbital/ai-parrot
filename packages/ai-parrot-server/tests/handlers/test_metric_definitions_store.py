"""Unit + gated live tests for PgMetricDefinitionStore (FEAT-756, TASK-4848)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from parrot.conf import default_dsn
from parrot.handlers.models import metric_definitions as m
from parrot.handlers.scope import RequestScope
from parrot.metrics import MetricDefinition

pytestmark = pytest.mark.asyncio
DSN = default_dsn


class _FakeConnCtx:
    """Async context manager returning the fake connection."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _FakeConn:
    """In-memory rows keyed by (tenant, metric_id); records every (sql, args)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.rows: dict[tuple, dict] = {}

    async def execute(self, sql: str, *args: Any) -> tuple:
        self.calls.append((sql, args))
        return (None, None)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append((sql, args))
        if sql in (m._INSERT_TENANT_SQL, m._INSERT_GLOBAL_SQL, m._UPSERT_TENANT_SQL, m._UPSERT_GLOBAL_SQL) or sql in (
            m._UPSERT_TENANT_VERSIONED_SQL,
            m._UPSERT_GLOBAL_VERSIONED_SQL,
        ):
            key = (args[1], args[0])
            if sql in (m._UPSERT_TENANT_VERSIONED_SQL, m._UPSERT_GLOBAL_VERSIONED_SQL):
                stored = self.rows.get(key)
                if stored is not None and stored["version"] != args[12]:
                    return None
                args = args[:12]
            if key in self.rows and sql in (m._INSERT_TENANT_SQL, m._INSERT_GLOBAL_SQL):
                return None
            cols = [c.strip() for c in m._COLUMNS.split(",")]
            self.rows[key] = dict(zip(cols, args, strict=True))
            return args[0]
        if sql == m._DELETE_TENANT_SQL:
            return args[0] if self.rows.pop((args[1], args[0]), None) else None
        if sql == m._DELETE_GLOBAL_SQL:
            return args[0] if self.rows.pop((None, args[0]), None) else None
        raise AssertionError(sql)

    async def fetch_one(self, sql: str, *args: Any) -> Any:
        self.calls.append((sql, args))
        tenant = None if sql == m._GET_GLOBAL_SQL else args[1]
        return self.rows.get((tenant, args[0]))

    async def fetch_all(self, sql: str, *args: Any) -> list:
        self.calls.append((sql, args))
        rows = list(self.rows.values())
        if sql == m._LIST_VISIBLE_SQL:
            return [r for r in rows if (r["tenant"] is None and r["visibility"] == "public") or r["tenant"] == args[0]]
        if sql == m._LIST_VISIBLE_GLOBAL_SQL:
            return [r for r in rows if r["tenant"] is None and r["visibility"] == "public"]
        if sql == m._LIST_TENANT_SQL:
            return [r for r in rows if r["tenant"] == args[0]]
        if sql == m._LIST_GLOBAL_SQL:
            return [r for r in rows if r["tenant"] is None]
        raise AssertionError(sql)


class _FakeAsyncDB:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def connection(self) -> _FakeConnCtx:
        return _FakeConnCtx(self._conn)


def _store(conn: _FakeConn) -> m.PgMetricDefinitionStore:
    store = m.PgMetricDefinitionStore(dsn="postgres://fake")
    store._get_db = lambda: _FakeAsyncDB(conn)  # type: ignore[method-assign]
    return store


def _definition(**overrides: Any) -> MetricDefinition:
    data: dict[str, Any] = {
        "id": "sales_total",
        "name": "Sales total",
        "tenant": "acme",
        "time": {"binding": {"date_column": "order_date"}},
        "default_shape": {"component": "KPICard", "value_column": "total"},
        "source": {"kind": "query_slug", "slug": "sales_by_day", "fields": ["total"]},
    }
    data.update(overrides)
    return MetricDefinition.model_validate(data)


def _scope(**kw: Any) -> RequestScope:
    base: dict[str, Any] = {"user_id": "u1", "tenant": "acme", "groups": frozenset()}
    base.update(kw)
    return RequestScope(**base)


async def test_pg_store_sql_shapes() -> None:
    """DDL list run once; native-dict jsonb params; upsert vs insert-or-skip; duplicate -> ValueError."""
    conn = _FakeConn()
    store = _store(conn)
    definition = _definition()
    assert await store.save(definition) == "sales_total"
    assert await store.save(_definition(id="other")) == "other"
    ddl = [sql for sql, _ in conn.calls if sql in m._DDL_STATEMENTS]
    assert ddl == m._DDL_STATEMENTS
    insert_args = next(args for sql, args in conn.calls if sql == m._INSERT_TENANT_SQL)
    assert isinstance(insert_args[8], dict) and insert_args[8]["id"] == "sales_total"
    assert isinstance(insert_args[5], list)
    with pytest.raises(ValueError):
        await store.save(definition)
    await store.save(_definition(name="Renamed"), overwrite=True)
    assert any(sql == m._UPSERT_TENANT_SQL for sql, _ in conn.calls)
    got = await store.get("sales_total", tenant="acme")
    assert got is not None and got.name == "Renamed"
    assert await store.get("sales_total", tenant=None) is None
    await store.save(_definition(tenant=None, visibility="public"))
    assert any(sql == m._INSERT_GLOBAL_SQL for sql, _ in conn.calls)
    assert [d.id for d in await store.list(tenant=None)] == ["sales_total"]
    assert await store.delete("sales_total", tenant=None) is True
    assert await store.delete("sales_total", tenant=None) is False


async def test_save_with_expected_version_is_compare_and_set() -> None:
    """overwrite + expected_version uses the versioned upsert; a stale version raises MetricVersionConflict."""
    conn = _FakeConn()
    store = _store(conn)
    await store.save(_definition(version=1))
    assert await store.save(_definition(version=2), overwrite=True, expected_version=1) == "sales_total"
    sql, args = conn.calls[-1]
    assert sql == m._UPSERT_TENANT_VERSIONED_SQL and args[-1] == 1
    with pytest.raises(m.MetricVersionConflict):
        await store.save(_definition(version=2), overwrite=True, expected_version=1)
    assert conn.rows[("acme", "sales_total")]["version"] == 2


async def test_list_visible_predicate_per_scope() -> None:
    """global public visible to all; tenant rows via owner / scope_grants; other tenant never."""
    conn = _FakeConn()
    store = _store(conn)
    await store.save(_definition(id="g_public", tenant=None, visibility="public"))
    await store.save(_definition(id="g_private", tenant=None, visibility="private"))
    await store.save(_definition(id="t_tenant", visibility="tenant"))
    await store.save(_definition(id="t_private_own", visibility="private", owner="u1"))
    await store.save(_definition(id="t_private_other", visibility="private", owner="u2"))
    await store.save(_definition(id="x_tenant", tenant="other", visibility="tenant"))

    ids = {d.id for d in await store.list_visible(_scope())}
    assert ids == {"g_public", "t_tenant", "t_private_own"}
    ids = {d.id for d in await store.list_visible(_scope(is_superuser=True))}
    assert ids == {"g_public", "t_tenant", "t_private_own", "t_private_other"}
    ids = {d.id for d in await store.list_visible(_scope(tenant=None))}
    assert ids == {"g_public"}


@pytest.mark.skipif(not DSN, reason="parrot.conf.default_dsn is not configured")
async def test_live_roundtrip() -> None:
    """ensure_schema, save, get, list_visible, delete against real Postgres; clean up own rows only."""
    store = m.PgMetricDefinitionStore(dsn=DSN)
    await store.ensure_schema()
    metric_id = f"t4848_{uuid.uuid4().hex[:8]}"
    tenant = f"t4848{uuid.uuid4().hex[:6]}"
    try:
        await store.save(_definition(id=metric_id, tenant=tenant))
        got = await store.get(metric_id, tenant=tenant)
        assert got is not None and got.id == metric_id
        visible = await store.list_visible(_scope(tenant=tenant))
        assert metric_id in {d.id for d in visible}
        # compare-and-set upsert: the right version wins, a stale one is refused
        await store.save(_definition(id=metric_id, tenant=tenant, version=2), overwrite=True, expected_version=1)
        with pytest.raises(m.MetricVersionConflict):
            await store.save(_definition(id=metric_id, tenant=tenant, version=2), overwrite=True, expected_version=1)
        updated = await store.get(metric_id, tenant=tenant)
        assert updated is not None and updated.version == 2
    finally:
        await store.delete(metric_id, tenant=tenant)
    assert await store.get(metric_id, tenant=tenant) is None
