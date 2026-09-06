"""Live round-trip for ``PgUISurfaceStore`` against a real Postgres (2026-09-05).

Regression for the asyncdb-compatibility defect FieldSync FEAT-559's review found:
with ``asyncdb 2.15.x`` every write silently failed (``execute`` returns
``[result, error]`` instead of raising), ``str`` uuids were rejected by the
driver's binary uuid codec, and ``get`` called the cursor method ``fetchrow``.
Skipped without ``NAVIGATOR_PG_DSN``.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceKind, UISurfaceRecord

pytestmark = pytest.mark.integration

DSN = os.getenv("NAVIGATOR_PG_DSN", "")


def _record(user_id: str, **overrides) -> UISurfaceRecord:
    now = datetime.now(UTC)
    base = dict(
        surface_id=str(uuid.uuid4()),
        kind=UISurfaceKind.dashboard,
        title="live probe",
        envelope={"surfaceId": "s", "catalogId": "c", "components": []},
        agent_id="probe",
        user_id=user_id,
        recipe_name="flex-program-dashboard",
        recipe_params={"month": "2025-10"},
        created_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return UISurfaceRecord(**base)


@pytest.fixture
async def store():
    if not DSN:
        pytest.skip("NAVIGATOR_PG_DSN not set")
    s = PgUISurfaceStore(DSN)
    await s.ensure_schema()
    yield s


async def test_save_get_list_update_delete_roundtrip(store):
    owner = f"probe-{uuid.uuid4().hex[:8]}"
    rec = _record(owner)
    sid = await store.save(rec)
    try:
        got = await store.get(sid)
        assert got is not None and got.surface_id == sid and got.recipe_params == {"month": "2025-10"}
        assert [r.surface_id for r in await store.list(owner)] == [sid]
        assert [r.surface_id for r in await store.list(owner, kind=UISurfaceKind.dashboard)] == [sid]
        assert await store.list(owner, kind=UISurfaceKind.widget) == []
        await store.update_envelope(sid, {"surfaceId": "s2", "catalogId": "c", "components": []}, {"month": "2025-11"})
        again = await store.get(sid)
        assert again is not None and again.recipe_params == {"month": "2025-11"} and again.envelope["surfaceId"] == "s2"
    finally:
        assert await store.delete(sid, owner) is True
    assert await store.get(sid) is None
    assert await store.list(owner) == []


async def test_duplicate_save_raises_and_overwrite_upserts(store):
    owner = f"probe-{uuid.uuid4().hex[:8]}"
    rec = _record(owner)
    sid = await store.save(rec)
    try:
        with pytest.raises(ValueError):
            await store.save(rec)
        await store.save(rec.model_copy(update={"title": "renamed"}), overwrite=True)
        assert (await store.get(sid)).title == "renamed"
    finally:
        await store.delete(sid, owner)


async def test_share_lifecycle(store):
    owner = f"probe-{uuid.uuid4().hex[:8]}"
    viewer = f"viewer-{uuid.uuid4().hex[:8]}"
    sid = await store.save(_record(owner))
    try:
        share = await store.mint_share(sid)
        assert (await store.resolve_share(share.token)).surface_id == sid
        await store.claim_share(share.token, viewer)
        assert [r.surface_id for r in await store.list_shared_with(viewer)] == [sid]
        assert [s.token for s in await store.list_shares(sid)] == [share.token]
        assert await store.revoke_share(share.token, sid) is True
        assert await store.resolve_share(share.token) is None
        assert await store.list_shared_with(viewer) == []
    finally:
        await store.delete(sid, owner)


async def test_malformed_id_is_not_found_not_an_error(store):
    assert await store.get("not-a-uuid") is None
    assert await store.delete("not-a-uuid", "nobody") is False
    assert await store.list_shares("not-a-uuid") == []
