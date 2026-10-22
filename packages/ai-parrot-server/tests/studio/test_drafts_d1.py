"""FEAT-605 W1.4 — D1: POST /drafts never overwrites another user's draft."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient
from asyncdb.exceptions import NoDataFound
from navigator_session.data import SessionData
from parrot.handlers.studio import drafts as drafts_module
from parrot.handlers.studio import setup_studio_routes

SRC_A = "from parrot.bots.basic import BasicBot\n\n\nclass A(BasicBot):\n    pass\n"
SRC_B = "from parrot.bots.basic import BasicBot\n\n\nclass B(BasicBot):\n    pass\n"


@web.middleware
async def _session_mw(request, handler):
    uid = request.headers["X-Uid"]
    request["NAV_SESSION"] = SessionData(data={"session": {"user_id": uid, "groups": [], "superuser": uid == "root"}})
    request["authenticated"] = True
    return await handler(request)


@pytest.fixture
def rows(monkeypatch, tmp_path):
    """In-memory draft table (data layer only) + AGENTS_DIR redirected to tmp_path."""
    monkeypatch.setattr(drafts_module, "AGENTS_DIR", tmp_path)
    table: dict = {}

    async def get_row(self, name):
        return table.get(name)

    async def upsert(self, **fields):
        row = table.get(fields["name"])
        if row is None:
            row = SimpleNamespace(**fields)
            table[fields["name"]] = row
        else:
            for key, value in fields.items():
                setattr(row, key, value)
        return row

    monkeypatch.setattr(drafts_module._StudioDraftsMixin, "_get_draft_row", get_row)
    monkeypatch.setattr(drafts_module._StudioDraftsMixin, "_upsert_draft_row", upsert)
    return table


def _app() -> web.Application:
    app = web.Application(middlewares=[_session_mw])
    setup_studio_routes(app)
    return app


async def _save(client, uid, source, name="x"):
    return await client.post("/api/v1/astudio/drafts", json={"name": name, "source": source}, headers={"X-Uid": uid})


async def test_draft_overwrite_refused(aiohttp_client, rows, tmp_path):
    client = await aiohttp_client(_app())
    assert (await _save(client, "A", SRC_A)).status == 201
    file_path = tmp_path / drafts_module.DRAFTS_SUBDIR / "x.py"
    assert file_path.read_text() == SRC_A

    resp = await _save(client, "B", SRC_B)
    body = await resp.json()
    assert resp.status == 409 and body["code"] == "name_taken"
    assert "A" not in body["message"] and "owner" not in str(body).lower()
    assert file_path.read_text() == SRC_A  # bytes unchanged
    assert rows["x"].owner_user_id == "A"  # row unchanged


async def test_own_draft_still_overwritable(aiohttp_client, rows, tmp_path):
    client = await aiohttp_client(_app())
    assert (await _save(client, "A", SRC_A)).status == 201
    assert (await _save(client, "A", SRC_B)).status == 201
    assert (tmp_path / drafts_module.DRAFTS_SUBDIR / "x.py").read_text() == SRC_B


async def test_superuser_may_overwrite(aiohttp_client, rows, tmp_path):
    client = await aiohttp_client(_app())
    assert (await _save(client, "A", SRC_A)).status == 201
    assert (await _save(client, "root", SRC_B)).status == 201
    assert (tmp_path / drafts_module.DRAFTS_SUBDIR / "x.py").read_text() == SRC_B


@pytest.mark.parametrize("failure", ["acquire", "query", "absent"])
async def test_draft_lookup_failure_preserves_file(
    aiohttp_client: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    """A failed ownership read refuses before writes; a genuinely absent row permits creation."""
    monkeypatch.setattr(drafts_module, "AGENTS_DIR", tmp_path)
    draft_dir = tmp_path / drafts_module.DRAFTS_SUBDIR
    draft_dir.mkdir()
    draft_file = draft_dir / "x.py"
    if failure != "absent":
        draft_file.write_text(SRC_A)
    writes: list[dict[str, Any]] = []

    class Database:
        async def acquire(self) -> "Database":
            if failure == "acquire":
                raise OSError("ownership database unavailable")
            return self

        async def __aenter__(self) -> "Database":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def get_row(**kwargs: Any) -> None:
        if failure == "absent":
            raise NoDataFound("no draft")
        raise OSError("ownership query unavailable")

    async def upsert(self: Any, **fields: Any) -> None:
        writes.append(fields)

    monkeypatch.setattr(drafts_module.StudioDraft, "get", get_row)
    monkeypatch.setattr(drafts_module.StudioDraft.Meta, "connection", None)
    monkeypatch.setattr(drafts_module._StudioDraftsMixin, "_upsert_draft_row", upsert)
    app = web.Application(middlewares=[_session_mw])
    app["database"] = Database()
    app.router.add_view("/api/v1/astudio/drafts", drafts_module.StudioDraftsHandler)
    client: TestClient = await aiohttp_client(app)
    response = await _save(client, "B", SRC_B)
    if failure == "absent":
        assert response.status == 201
        assert draft_file.read_text() == SRC_B
        assert len(writes) == 1
    else:
        assert response.status == 503
        assert (await response.json())["code"] == "draft_lookup_failed"
        assert draft_file.read_text() == SRC_A
        assert writes == []
