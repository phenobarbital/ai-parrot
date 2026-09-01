"""Unit tests for ``PgUISurfaceStore`` (FEAT-492, TASK-2700).

Bypasses the real ``AsyncDB("pg")`` connection with an in-memory fake that
matches on the store's own module-level SQL constants (identity/equality),
mirroring the ``_FakeAsyncDB``/``_FakeConnCtx`` idiom used by
``test_comm_center_dispatch.py`` — no live Postgres required.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from parrot.handlers.models import ui_surfaces as m

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# In-memory fake AsyncDB
# ---------------------------------------------------------------------------


class _FakeConnCtx:
    """Bypasses the real ``AsyncDB('pg')`` connection entirely.

    ``connection()`` is itself ``async`` — matching the real ``AsyncDB``,
    which the store calls as ``async with await db.connection() as conn:``.
    """

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


def _row_from_insert_args(args) -> dict:
    return {
        "surface_id": args[0],
        "kind": args[1],
        "title": args[2],
        "envelope": args[3],
        "catalog_id": args[4],
        "agent_id": args[5],
        "user_id": args[6],
        "session_id": args[7],
        "recipe_name": args[8],
        "recipe_owner": args[9],
        "recipe_params": args[10],
        "created_at": args[11],
        "updated_at": args[12],
    }


class _FakeConn:
    """In-memory relational fake matching the store's exact SQL constants."""

    def __init__(self, state):
        self.state = state

    async def execute(self, sql, *args):
        state = self.state
        if sql == m._INSERT_SQL:
            surface_id = args[0]
            if surface_id in state.surfaces:
                raise Exception(  # noqa: TRY002 - mimic asyncpg's message heuristic
                    'duplicate key value violates unique constraint "ui_surfaces_pkey"'
                )
            state.surfaces[surface_id] = _row_from_insert_args(args)
            return
        if sql == m._UPSERT_SQL:
            surface_id = args[0]
            state.surfaces[surface_id] = _row_from_insert_args(args)
            return
        if sql == m._UPDATE_ENVELOPE_SQL:
            surface_id, envelope_json, params_json = args
            row = state.surfaces.get(surface_id)
            if row is not None:
                row["envelope"] = envelope_json
                row["recipe_params"] = params_json
                row["updated_at"] = datetime.now(UTC)
            return
        if sql == m._MINT_SHARE_SQL:
            token, surface_id, expires_at, created_at = args
            state.shares[token] = {
                "token": token,
                "surface_id": surface_id,
                "permissions": "read+refresh",
                "expires_at": expires_at,
                "revoked": False,
                "claimed_by": None,
                "claimed_at": None,
                "created_at": created_at,
            }
            return
        if sql == m._CLAIM_SHARE_SQL:
            token, user_id = args
            row = state.shares.get(token)
            if row is not None and row["claimed_by"] is None:
                row["claimed_by"] = user_id
                row["claimed_at"] = datetime.now(UTC)
            return
        if sql.strip().upper().startswith("CREATE"):
            state.ddl_calls.append(sql)
            return
        raise AssertionError(f"Unexpected execute SQL: {sql!r}")

    async def fetchrow(self, sql, *args):
        state = self.state
        if sql == m._GET_SQL:
            row = state.surfaces.get(args[0])
            return dict(row) if row else None
        if sql == m._RESOLVE_SHARE_SQL:
            row = state.shares.get(args[0])
            if row is None or row["revoked"]:
                return None
            if row["expires_at"] is not None and row["expires_at"] <= datetime.now(UTC):
                return None
            return dict(row)
        raise AssertionError(f"Unexpected fetchrow SQL: {sql!r}")

    async def fetchval(self, sql, *args):
        state = self.state
        if sql == m._DELETE_SQL:
            surface_id, user_id = args
            row = state.surfaces.get(surface_id)
            if row is not None and row["user_id"] == user_id:
                del state.surfaces[surface_id]
                return surface_id
            return None
        if sql == m._REVOKE_SHARE_SQL:
            token, surface_id = args
            row = state.shares.get(token)
            if row is not None and row["surface_id"] == surface_id:
                row["revoked"] = True
                return token
            return None
        raise AssertionError(f"Unexpected fetchval SQL: {sql!r}")

    async def fetchall(self, sql, *args):
        state = self.state
        if sql == m._LIST_SQL:
            user_id = args[0]
            rows = [r for r in state.surfaces.values() if r["user_id"] == user_id]
        elif sql == m._LIST_BY_KIND_SQL:
            user_id, kind = args
            rows = [
                r for r in state.surfaces.values() if r["user_id"] == user_id and r["kind"] == kind
            ]
        elif sql == m._LIST_SHARED_WITH_SQL:
            user_id = args[0]
            now = datetime.now(UTC)
            live_ids = {
                s["surface_id"]
                for s in state.shares.values()
                if s["claimed_by"] == user_id
                and not s["revoked"]
                and (s["expires_at"] is None or s["expires_at"] > now)
            }
            rows = [r for r in state.surfaces.values() if r["surface_id"] in live_ids]
        elif sql == m._LIST_SHARES_SQL:
            surface_id = args[0]
            rows = [r for r in state.shares.values() if r["surface_id"] == surface_id]
        else:
            raise AssertionError(f"Unexpected fetchall SQL: {sql!r}")
        rows = sorted(rows, key=lambda r: r["updated_at" if "updated_at" in r else "created_at"], reverse=True)
        return [dict(r) for r in rows]


class _FakeAsyncDB:
    def __init__(self, state):
        self.state = state

    async def connection(self):
        return _FakeConnCtx(_FakeConn(self.state))


@pytest.fixture
def fake_state():
    return SimpleNamespace(surfaces={}, shares={}, ddl_calls=[])


@pytest.fixture
def pg_store(monkeypatch, fake_state):
    store = m.PgUISurfaceStore(dsn="postgres://fake/test")
    monkeypatch.setattr(store, "_get_db", lambda: _FakeAsyncDB(fake_state))
    return store


def _sample_envelope() -> dict:
    """A minimal ``CreateSurface`` dump shape (``persist_envelope`` convention)."""
    return {
        "surfaceId": "surface-test-1",
        "components": [{"type": "Card", "id": "root"}],
        "dataModel": {"filters": {"window": "all", "plan": "All"}},
    }


def _make_record(**overrides) -> m.UISurfaceRecord:
    now = datetime.now(UTC)
    defaults = {
        "surface_id": str(uuid.uuid4()),
        "kind": m.UISurfaceKind.dashboard,
        "title": "Q3 Revenue",
        "envelope": _sample_envelope(),
        "catalog_id": None,
        "agent_id": "agent-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": {},
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return m.UISurfaceRecord(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ensure_schema_idempotent(pg_store, fake_state):
    await pg_store.ensure_schema()
    await pg_store.ensure_schema()
    assert pg_store._schema_ensured is True
    assert len(fake_state.ddl_calls) == 2 * len(m._DDL_STATEMENTS)


async def test_save_get_roundtrip_envelope_intact(pg_store):
    record = _make_record()
    surface_id = await pg_store.save(record)
    assert surface_id == record.surface_id

    fetched = await pg_store.get(record.surface_id)
    assert fetched is not None
    assert fetched.surface_id == record.surface_id
    assert fetched.title == record.title
    assert fetched.envelope == record.envelope
    assert fetched.refreshable is False


async def test_save_overwrite_flag(pg_store):
    record = _make_record()
    await pg_store.save(record)

    with pytest.raises(ValueError):
        await pg_store.save(record)

    updated = record.model_copy(update={"title": "New Title"})
    surface_id = await pg_store.save(updated, overwrite=True)
    assert surface_id == record.surface_id

    fetched = await pg_store.get(record.surface_id)
    assert fetched.title == "New Title"


async def test_list_by_owner_and_kind(pg_store):
    a = _make_record(user_id="owner-a", kind=m.UISurfaceKind.dashboard)
    b = _make_record(user_id="owner-a", kind=m.UISurfaceKind.infographic)
    c = _make_record(user_id="owner-b", kind=m.UISurfaceKind.dashboard)
    for r in (a, b, c):
        await pg_store.save(r)

    owner_a_surfaces = await pg_store.list("owner-a")
    assert {r.surface_id for r in owner_a_surfaces} == {a.surface_id, b.surface_id}

    owner_a_dashboards = await pg_store.list("owner-a", kind=m.UISurfaceKind.dashboard)
    assert [r.surface_id for r in owner_a_dashboards] == [a.surface_id]


async def test_update_envelope_in_place_bumps_updated_at(pg_store):
    record = _make_record()
    await pg_store.save(record)

    new_envelope = {**record.envelope, "dataModel": {"filters": {"window": "7d"}}}
    await pg_store.update_envelope(record.surface_id, new_envelope, {"window": "7d"})

    fetched = await pg_store.get(record.surface_id)
    assert fetched.envelope == new_envelope
    assert fetched.recipe_params == {"window": "7d"}
    assert fetched.updated_at > record.updated_at


async def test_delete_owner_only(pg_store):
    record = _make_record(user_id="owner-a")
    await pg_store.save(record)

    assert await pg_store.delete(record.surface_id, "owner-b") is False
    assert await pg_store.get(record.surface_id) is not None

    assert await pg_store.delete(record.surface_id, "owner-a") is True
    assert await pg_store.get(record.surface_id) is None


async def test_share_mint_default_no_expiry(pg_store):
    record = _make_record()
    await pg_store.save(record)

    share = await pg_store.mint_share(record.surface_id)
    assert share.expires_at is None
    assert share.revoked is False
    assert share.permissions == "read+refresh"


async def test_share_mint_ttl_defaults_90_days(pg_store):
    record = _make_record()
    await pg_store.save(record)

    share = await pg_store.mint_share(record.surface_id, use_default_ttl=True)
    assert share.expires_at is not None
    delta = share.expires_at - datetime.now(UTC)
    assert timedelta(days=89) < delta <= timedelta(days=90)


async def test_share_resolve_revoked_expired_missing_all_none(pg_store):
    record = _make_record()
    await pg_store.save(record)

    live = await pg_store.mint_share(record.surface_id)
    assert await pg_store.resolve_share(live.token) is not None

    revoked = await pg_store.mint_share(record.surface_id)
    await pg_store.revoke_share(revoked.token, record.surface_id)
    assert await pg_store.resolve_share(revoked.token) is None

    expired = await pg_store.mint_share(
        record.surface_id, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert await pg_store.resolve_share(expired.token) is None

    assert await pg_store.resolve_share("does-not-exist") is None


async def test_share_claim_idempotent_first_wins(pg_store):
    record = _make_record()
    await pg_store.save(record)
    share = await pg_store.mint_share(record.surface_id)

    await pg_store.claim_share(share.token, "first-user")
    await pg_store.claim_share(share.token, "second-user")

    shares = await pg_store.list_shares(record.surface_id)
    assert len(shares) == 1
    assert shares[0].claimed_by == "first-user"


async def test_list_shared_with_claimed_only(pg_store):
    owned = _make_record(user_id="owner-a")
    unclaimed = _make_record(user_id="owner-a")
    revoked_target = _make_record(user_id="owner-a")
    for r in (owned, unclaimed, revoked_target):
        await pg_store.save(r)

    claimed_share = await pg_store.mint_share(owned.surface_id)
    await pg_store.claim_share(claimed_share.token, "viewer-1")

    await pg_store.mint_share(unclaimed.surface_id)  # never claimed

    revoked_share = await pg_store.mint_share(revoked_target.surface_id)
    await pg_store.claim_share(revoked_share.token, "viewer-1")
    await pg_store.revoke_share(revoked_share.token, revoked_target.surface_id)

    shared = await pg_store.list_shared_with("viewer-1")
    assert [r.surface_id for r in shared] == [owned.surface_id]
