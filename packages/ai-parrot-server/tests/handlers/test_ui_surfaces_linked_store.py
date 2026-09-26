"""FEAT-598 M8 — refreshable widening + conditional update_envelope (spec §4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from parrot.handlers.models import ui_surfaces as m
from parrot.outputs.a2ui.linked import LinkedDataSource, LinkedSources, SourceRequest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# In-memory fake AsyncDB — bounded by the ``test_ui_surfaces_store.py`` idiom
# (``_FakeConnCtx`` / ``_FakeConn`` / ``_FakeAsyncDB``), copied minimally here
# since only ``update_envelope``'s two SQL constants are exercised.
# ---------------------------------------------------------------------------


class _FakeConnCtx:
    """Bypasses the real ``AsyncDB('pg')`` connection entirely."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc_info):
        return False


class _FakeConn:
    """In-memory fake matching only the ``update_envelope`` SQL constants."""

    def __init__(self, state):
        self.state = state

    async def fetchval(self, sql, *args):
        state = self.state
        if sql == m._UPDATE_ENVELOPE_SQL:
            surface_id, envelope, recipe_params = args
            row = state.surfaces.get(surface_id)
            if row is None:
                return None
            row["envelope"] = envelope
            row["recipe_params"] = recipe_params
            row["updated_at"] = datetime.now(UTC)
            return surface_id
        if sql == m._UPDATE_ENVELOPE_IF_UNCHANGED_SQL:
            surface_id, envelope, recipe_params, expected_updated_at = args
            row = state.surfaces.get(surface_id)
            if row is None or row["updated_at"] != expected_updated_at:
                return None
            row["envelope"] = envelope
            row["recipe_params"] = recipe_params
            row["updated_at"] = datetime.now(UTC)
            return surface_id
        raise AssertionError(f"Unexpected fetchval SQL: {sql!r}")


class _FakeAsyncDB:
    def __init__(self, state):
        self.state = state

    async def connection(self):
        return _FakeConnCtx(_FakeConn(self.state))


@pytest.fixture
def fake_state():
    return SimpleNamespace(surfaces={})


@pytest.fixture
def pg_store(monkeypatch, fake_state):
    store = m.PgUISurfaceStore(dsn="postgres://fake/test")
    monkeypatch.setattr(store, "_get_db", lambda: _FakeAsyncDB(fake_state))
    # Skip the lazy `ensure_schema()` DDL pass — this fake conn only
    # implements `fetchval` for the two `update_envelope` SQL constants.
    store._schema_ensured = True
    return store


def _linked_envelope() -> dict:
    """A minimal envelope carrying a non-empty ``parrot_data_sources`` extension."""
    source = LinkedDataSource(
        slug="orders_query",
        conditions={},
        request=SourceRequest(),
        target="/orders",
    )
    sources = LinkedSources({"orders": source})
    return {
        "surfaceId": "surface-linked-1",
        "components": [{"type": "Card", "id": "root"}],
        "dataModel": {"orders": []},
        "metadata": {"extensions": {"parrot_data_sources": sources.model_dump(mode="json")}},
    }


def _baked_envelope() -> dict:
    """A minimal envelope with no linked data-source extension."""
    return {
        "surfaceId": "surface-baked-1",
        "components": [{"type": "Card", "id": "root"}],
        "dataModel": {"filters": {"window": "all"}},
    }


def _record(envelope: dict, *, recipe_name: str | None = None) -> m.UISurfaceRecord:
    now = datetime.now(UTC)
    return m.UISurfaceRecord(
        surface_id=str(uuid.uuid4()),
        kind=m.UISurfaceKind.dashboard,
        title="Q3 Revenue",
        envelope=envelope,
        agent_id="agent-1",
        user_id="user-1",
        recipe_name=recipe_name,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_refreshable_with_data_sources():
    record = _record(_linked_envelope())
    assert record.refreshable is True


def test_refreshable_baked_without_recipe():
    record = _record(_baked_envelope())
    assert record.refreshable is False


async def test_update_envelope_expected_updated_at(pg_store, fake_state):
    surface_uuid = uuid.uuid4()
    now = datetime.now(UTC)
    fake_state.surfaces[surface_uuid] = {"envelope": {"a": 1}, "recipe_params": {}, "updated_at": now}

    stale = now - timedelta(seconds=5)
    stale_result = await pg_store.update_envelope(str(surface_uuid), {"a": 2}, {}, expected_updated_at=stale)
    assert stale_result is False
    assert fake_state.surfaces[surface_uuid]["envelope"] == {"a": 1}

    match_result = await pg_store.update_envelope(
        str(surface_uuid), {"a": 3}, {"window": "7d"}, expected_updated_at=now
    )
    assert match_result is True
    assert fake_state.surfaces[surface_uuid]["envelope"] == {"a": 3}
    assert fake_state.surfaces[surface_uuid]["recipe_params"] == {"window": "7d"}


async def test_update_envelope_unconditional_unchanged(pg_store, fake_state):
    surface_uuid = uuid.uuid4()
    now = datetime.now(UTC)
    fake_state.surfaces[surface_uuid] = {"envelope": {"a": 1}, "recipe_params": {}, "updated_at": now}

    result = await pg_store.update_envelope(str(surface_uuid), {"a": 9}, {"x": 1})
    assert result is True
    assert fake_state.surfaces[surface_uuid]["envelope"] == {"a": 9}
    assert fake_state.surfaces[surface_uuid]["recipe_params"] == {"x": 1}


async def test_update_envelope_unknown_surface(pg_store):
    result = await pg_store.update_envelope("not-a-uuid", {"a": 1}, {})
    assert result is False
