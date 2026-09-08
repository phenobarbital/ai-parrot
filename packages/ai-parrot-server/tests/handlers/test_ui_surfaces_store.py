"""Unit tests for ``PgUISurfaceStore`` (FEAT-492, TASK-2700).

Bypasses the real ``AsyncDB("pg")`` connection with an in-memory fake that
matches on the store's own module-level SQL constants (identity/equality),
mirroring the ``_FakeAsyncDB``/``_FakeConnCtx`` idiom used by
``test_comm_center_dispatch.py`` — no live Postgres required.
"""

from __future__ import annotations

import json
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
        "tenant": args[11],
        "visibility": args[12],
        "allowed_groups": args[13],
        "created_at": args[14],
        "updated_at": args[15],
    }


def _old_row(surface_id: str, **overrides) -> dict:
    """A row shaped like it was written BEFORE FEAT-535 — no visibility columns."""
    now = datetime.now(UTC)
    row = {
        "surface_id": surface_id,
        "kind": m.UISurfaceKind.dashboard.value,
        "title": "Pre-feature surface",
        "envelope": json.dumps({}),
        "catalog_id": None,
        "agent_id": "agent-1",
        "user_id": "owner-1",
        "session_id": None,
        "recipe_name": None,
        "recipe_owner": None,
        "recipe_params": json.dumps({}),
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def _row_allowed_groups(row: dict) -> list[str]:
    """Decode a fake row's ``allowed_groups`` (JSON string, list, or missing)."""
    raw = row.get("allowed_groups")
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    return json.loads(raw)


def _row_visible(row: dict, *, user_id, tenant, groups, is_superuser) -> bool:
    """Mirrors ``_LIST_VISIBLE_SQL``'s WHERE clause for the in-memory fake."""
    if row["user_id"] == user_id:
        return True
    row_tenant = row.get("tenant")
    if tenant is None or row_tenant is None or row_tenant != tenant:
        return False
    visibility = row.get("visibility") or m.SurfaceVisibility.private.value
    if visibility == m.SurfaceVisibility.tenant.value:
        return True
    if is_superuser:
        return True
    if visibility == m.SurfaceVisibility.groups.value:
        return bool(set(_row_allowed_groups(row)) & set(groups))
    return False


class _FakeConn:
    """In-memory relational fake matching the store's exact SQL constants.

    Mirrors the driver methods the store actually calls (``execute`` for DDL
    only; ``fetchval`` for every write with a ``RETURNING`` clause;
    ``fetch_one``/``fetch_all`` for reads) — the asyncdb quirks documented in
    ``handlers/models/ui_surfaces.py`` (compatibility fix, 2026-09-05).
    """

    def __init__(self, state):
        self.state = state

    async def execute(self, sql, *args):
        state = self.state
        if sql.strip().upper().startswith(("CREATE", "ALTER")):
            state.ddl_calls.append(sql)
            return None
        raise AssertionError(f"Unexpected execute SQL: {sql!r}")

    async def fetch_one(self, sql, *args):
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
        raise AssertionError(f"Unexpected fetch_one SQL: {sql!r}")

    async def fetchval(self, sql, *args):
        state = self.state
        if sql == m._INSERT_OR_SKIP_SQL:
            surface_id = args[0]
            if surface_id in state.surfaces:
                # ON CONFLICT (surface_id) DO NOTHING — real Postgres yields no
                # RETURNING row (None), it does not raise.
                return None
            state.surfaces[surface_id] = _row_from_insert_args(args)
            return surface_id
        if sql == m._UPSERT_SQL:
            surface_id = args[0]
            state.surfaces[surface_id] = _row_from_insert_args(args)
            return surface_id
        if sql == m._UPDATE_ENVELOPE_SQL:
            surface_id, envelope_json, params_json = args
            row = state.surfaces.get(surface_id)
            if row is not None:
                row["envelope"] = envelope_json
                row["recipe_params"] = params_json
                row["updated_at"] = datetime.now(UTC)
            return surface_id
        if sql == m._UPDATE_VISIBILITY_SQL:
            surface_id, user_id, visibility, allowed_groups_json = args
            row = state.surfaces.get(surface_id)
            if row is not None and row["user_id"] == user_id:
                row["visibility"] = visibility
                row["allowed_groups"] = allowed_groups_json
                row["updated_at"] = datetime.now(UTC)
                return surface_id
            return None
        if sql == m._DELETE_SQL:
            surface_id, user_id = args
            row = state.surfaces.get(surface_id)
            if row is not None and row["user_id"] == user_id:
                del state.surfaces[surface_id]
                return surface_id
            return None
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
            return token
        if sql == m._CLAIM_SHARE_SQL:
            token, user_id = args
            row = state.shares.get(token)
            if row is not None and row["claimed_by"] is None:
                row["claimed_by"] = user_id
                row["claimed_at"] = datetime.now(UTC)
            return token
        if sql == m._REVOKE_SHARE_SQL:
            token, surface_id = args
            row = state.shares.get(token)
            if row is not None and row["surface_id"] == surface_id:
                row["revoked"] = True
                return token
            return None
        raise AssertionError(f"Unexpected fetchval SQL: {sql!r}")

    async def fetch_all(self, sql, *args):
        state = self.state
        if sql == m._LIST_SQL:
            user_id = args[0]
            rows = [r for r in state.surfaces.values() if r["user_id"] == user_id]
        elif sql == m._LIST_BY_KIND_SQL:
            user_id, kind = args
            rows = [r for r in state.surfaces.values() if r["user_id"] == user_id and r["kind"] == kind]
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
        elif sql == m._LIST_VISIBLE_SQL:
            user_id, tenant, groups, is_superuser = args
            rows = [
                r
                for r in state.surfaces.values()
                if _row_visible(r, user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)
            ]
        elif sql == m._LIST_VISIBLE_BY_KIND_SQL:
            user_id, tenant, groups, is_superuser, kind = args
            rows = [
                r
                for r in state.surfaces.values()
                if _row_visible(r, user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)
                and r["kind"] == kind
            ]
        else:
            raise AssertionError(f"Unexpected fetch_all SQL: {sql!r}")
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

    expired = await pg_store.mint_share(record.surface_id, expires_at=datetime.now(UTC) - timedelta(seconds=1))
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


# ---------------------------------------------------------------------------
# FEAT-535: tenant/group visibility
# ---------------------------------------------------------------------------


def _scope(user_id=None, tenant=None, groups=(), is_superuser=False):
    """Duck-typed ``SurfaceScope`` stand-in — this module never imports the
    handler-package type (spec §3 Module 1); ``list_visible`` only reads
    ``user_id``/``tenant``/``groups``/``is_superuser`` attributes."""
    return SimpleNamespace(user_id=user_id, tenant=tenant, groups=groups, is_superuser=is_superuser)


async def test_old_row_without_new_columns_loads_as_private(pg_store, fake_state):
    rid = str(uuid.uuid4())
    # Keyed by the parsed UUID, matching how `save()`/`get()` key the fake
    # (the store's binary uuid codec always parses the id first — see
    # `_as_uuid`/`_require_uuid`).
    fake_state.surfaces[uuid.UUID(rid)] = _old_row(rid)

    rec = await pg_store.get(rid)

    assert rec is not None
    assert rec.visibility is m.SurfaceVisibility.private
    assert rec.tenant is None
    assert rec.allowed_groups == []


async def test_list_visible_matrix(pg_store):
    owned = _make_record(user_id="owner-a", tenant=None, visibility=m.SurfaceVisibility.private)
    tenant_visible_same = _make_record(user_id="owner-b", tenant="epson", visibility=m.SurfaceVisibility.tenant)
    tenant_visible_other = _make_record(user_id="owner-c", tenant="other-tenant", visibility=m.SurfaceVisibility.tenant)
    groups_hit = _make_record(
        user_id="owner-d",
        tenant="epson",
        visibility=m.SurfaceVisibility.groups,
        allowed_groups=["epson_fieldsync_manager"],
    )
    groups_miss = _make_record(
        user_id="owner-e",
        tenant="epson",
        visibility=m.SurfaceVisibility.groups,
        allowed_groups=["some_other_group"],
    )
    private_same_tenant = _make_record(user_id="owner-f", tenant="epson", visibility=m.SurfaceVisibility.private)
    row_without_tenant = _make_record(user_id="owner-g", tenant=None, visibility=m.SurfaceVisibility.tenant)
    for r in (
        owned,
        tenant_visible_same,
        tenant_visible_other,
        groups_hit,
        groups_miss,
        private_same_tenant,
        row_without_tenant,
    ):
        await pg_store.save(r)

    # Plain caller: owns `owned`, tenant="epson", one matching group.
    caller_scope = _scope(user_id="owner-a", tenant="epson", groups=["epson_fieldsync_manager"])
    visible = await pg_store.list_visible(caller_scope)
    visible_ids = {r.surface_id for r in visible}
    assert owned.surface_id in visible_ids  # owns it
    assert tenant_visible_same.surface_id in visible_ids  # tenant match, visibility=tenant
    assert tenant_visible_other.surface_id not in visible_ids  # other tenant
    assert groups_hit.surface_id in visible_ids  # tenant match, group intersects
    assert groups_miss.surface_id not in visible_ids  # tenant match, group does NOT intersect
    assert private_same_tenant.surface_id not in visible_ids  # private, not owner
    assert row_without_tenant.surface_id not in visible_ids  # row has no tenant

    # Superuser in "epson" sees every "epson" row, including private ones,
    # but nothing from "other-tenant".
    superuser_scope = _scope(user_id="superuser-1", tenant="epson", groups=[], is_superuser=True)
    superuser_visible = {r.surface_id for r in await pg_store.list_visible(superuser_scope)}
    assert tenant_visible_same.surface_id in superuser_visible
    assert groups_hit.surface_id in superuser_visible
    assert groups_miss.surface_id in superuser_visible
    assert private_same_tenant.surface_id in superuser_visible
    assert tenant_visible_other.surface_id not in superuser_visible
    assert row_without_tenant.surface_id not in superuser_visible

    # Caller with no tenant (e.g. multi-program session) sees only what it owns.
    no_tenant_scope = _scope(user_id="owner-a", tenant=None, groups=["epson_fieldsync_manager"])
    no_tenant_visible = {r.surface_id for r in await pg_store.list_visible(no_tenant_scope)}
    assert no_tenant_visible == {owned.surface_id}


async def test_update_visibility_owner_only(pg_store):
    record = _make_record(user_id="owner-a", tenant="epson", visibility=m.SurfaceVisibility.private)
    await pg_store.save(record)

    non_owner_result = await pg_store.update_visibility(record.surface_id, "owner-b", m.SurfaceVisibility.tenant, [])
    assert non_owner_result is False
    unchanged = await pg_store.get(record.surface_id)
    assert unchanged.visibility is m.SurfaceVisibility.private

    owner_result = await pg_store.update_visibility(
        record.surface_id, "owner-a", m.SurfaceVisibility.groups, ["epson_fieldsync_manager"]
    )
    assert owner_result is True
    updated = await pg_store.get(record.surface_id)
    assert updated.visibility is m.SurfaceVisibility.groups
    assert updated.allowed_groups == ["epson_fieldsync_manager"]
