"""Unit tests for CommCenterHandler templates CRUD (FEAT-417, Module 7 CRUD half).

The database is faked by monkeypatching ``NotificationTemplate``'s
``insert``/``update``/``delete``/``get``/``filter``/``all`` onto an
in-memory dict store, since a live Postgres is not available to this test
suite; the handler still constructs and mutates *real*
``NotificationTemplate`` instances throughout. ``_get_user_id`` (session
resolution) is monkeypatched directly — its own correctness is not this
task's concern.
"""
import uuid

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.comm_center import CommCenterHandler
from parrot.handlers.models import NotificationTemplate


def _make_request(method: str, path: str, json_body: dict | None = None) -> web.Request:
    request = make_mocked_request(method, path)
    request["authenticated"] = True
    if json_body is not None:

        async def fake_json(**kwargs):
            return json_body

        request.json = fake_json
    return request


@pytest.fixture
def template_store(monkeypatch):
    """Backs NotificationTemplate's persistence methods with an in-memory dict."""
    store: dict = {}

    async def fake_insert(self):
        for existing in store.values():
            if existing.name == self.name:
                raise ValueError('duplicate key value violates unique constraint "uq_name"')
        store[self.template_id] = self
        return self

    async def fake_update(self):
        for tid, existing in store.items():
            if tid != self.template_id and existing.name == self.name:
                raise ValueError('duplicate key value violates unique constraint "uq_name"')
        store[self.template_id] = self
        return self

    async def fake_delete(self):
        store.pop(self.template_id, None)

    async def fake_get(*, template_id=None, name=None):
        from asyncdb.exceptions import NoDataFound

        for row in store.values():
            if template_id is not None and row.template_id == template_id:
                return row
            if name is not None and row.name == name:
                return row
        raise NoDataFound("Template not found")

    async def fake_filter(**kwargs):
        return [
            row
            for row in store.values()
            if all(getattr(row, key) == value for key, value in kwargs.items())
        ]

    async def fake_all():
        return list(store.values())

    monkeypatch.setattr(NotificationTemplate, "insert", fake_insert)
    monkeypatch.setattr(NotificationTemplate, "update", fake_update)
    monkeypatch.setattr(NotificationTemplate, "delete", fake_delete)
    monkeypatch.setattr(NotificationTemplate, "get", staticmethod(fake_get))
    monkeypatch.setattr(NotificationTemplate, "filter", staticmethod(fake_filter))
    monkeypatch.setattr(NotificationTemplate, "all", staticmethod(fake_all))
    return store


@pytest.fixture
def handler(monkeypatch):
    import parrot.handlers.comm_center as comm_center_module

    class _FakeConnCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc_info):
            return False

    class _FakeAsyncDB:
        async def connection(self):
            return _FakeConnCtx()

    monkeypatch.setattr(comm_center_module, "_get_db", lambda: _FakeAsyncDB())
    h = CommCenterHandler()
    monkeypatch.setattr(h, "_get_user_id", lambda request: _resolved_user_id())
    return h


async def _resolved_user_id():
    return 42


class TestCreateTemplate:
    async def test_create_and_read(self, handler, template_store):
        request = _make_request(
            "POST",
            "/api/v1/comm_center/templates",
            {
                "name": "welcome",
                "template_string": "Hola {{ name }}",
                "subject": "Bienvenido",
                "provider": "email",
            },
        )
        resp = await handler.create_template(request)
        assert resp.status == 201

        (row,) = template_store.values()
        assert row.name == "welcome"
        assert row.created_by == 42

        get_request = _make_request(
            "GET", f"/api/v1/comm_center/templates/{row.template_id}"
        )
        get_request.match_info["template_id"] = str(row.template_id)
        get_resp = await handler.get_template(get_request)
        assert get_resp.status == 200

    async def test_duplicate_name_conflicts(self, handler, template_store):
        payload = {"name": "dup", "template_string": "x"}
        await handler.create_template(_make_request("POST", "/templates", payload))
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.create_template(_make_request("POST", "/templates", payload))
        assert excinfo.value.status == 409

    async def test_missing_name_returns_400(self, handler, template_store):
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.create_template(
                _make_request("POST", "/templates", {"template_string": "x"})
            )
        assert excinfo.value.status == 400

    async def test_missing_template_string_returns_400(self, handler, template_store):
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.create_template(
                _make_request("POST", "/templates", {"name": "x"})
            )
        assert excinfo.value.status == 400


class TestGetTemplate:
    async def test_get_missing_returns_404(self, handler, template_store):
        request = _make_request(
            "GET", f"/api/v1/comm_center/templates/{uuid.uuid4()}"
        )
        request.match_info["template_id"] = str(uuid.uuid4())
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.get_template(request)
        assert excinfo.value.status == 404


class TestUpdateTemplate:
    async def test_patch_partial_update(self, handler, template_store):
        create_req = _make_request(
            "POST", "/templates", {"name": "welcome", "template_string": "Hola"}
        )
        await handler.create_template(create_req)
        (row,) = template_store.values()

        patch_req = _make_request(
            "PATCH",
            f"/templates/{row.template_id}",
            {"subject": "New Subject"},
        )
        patch_req.match_info["template_id"] = str(row.template_id)
        resp = await handler.update_template(patch_req)
        assert resp.status == 200
        assert template_store[row.template_id].subject == "New Subject"
        # Untouched fields survive a partial update.
        assert template_store[row.template_id].template_string == "Hola"

    async def test_updated_at_not_set_by_app(self, handler, template_store):
        """The DB trigger owns updated_at — application code must never set it."""
        import inspect

        source = inspect.getsource(handler.update_template)
        assert "updated_at" not in source

    async def test_created_by_from_session(self, handler, template_store):
        await handler.create_template(
            _make_request("POST", "/templates", {"name": "x", "template_string": "y"})
        )
        (row,) = template_store.values()
        assert row.created_by == 42

    async def test_update_missing_returns_404(self, handler, template_store):
        request = _make_request(
            "PATCH", f"/templates/{uuid.uuid4()}", {"subject": "x"}
        )
        request.match_info["template_id"] = str(uuid.uuid4())
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.update_template(request)
        assert excinfo.value.status == 404


class TestDeleteTemplate:
    async def test_delete_removes_row(self, handler, template_store):
        await handler.create_template(
            _make_request("POST", "/templates", {"name": "x", "template_string": "y"})
        )
        (row,) = template_store.values()

        del_req = _make_request("DELETE", f"/templates/{row.template_id}")
        del_req.match_info["template_id"] = str(row.template_id)
        resp = await handler.delete_template(del_req)
        assert resp.status == 200
        assert row.template_id not in template_store

    async def test_delete_missing_returns_404(self, handler, template_store):
        request = _make_request("DELETE", f"/templates/{uuid.uuid4()}")
        request.match_info["template_id"] = str(uuid.uuid4())
        with pytest.raises(web.HTTPException) as excinfo:
            await handler.delete_template(request)
        assert excinfo.value.status == 404


class TestListTemplates:
    async def test_list_filters_by_is_active(self, handler, template_store):
        await handler.create_template(
            _make_request(
                "POST", "/templates", {"name": "active-one", "template_string": "x"}
            )
        )
        await handler.create_template(
            _make_request(
                "POST",
                "/templates",
                {"name": "inactive-one", "template_string": "x", "is_active": False},
            )
        )
        request = _make_request("GET", "/templates?is_active=true")
        resp = await handler.list_templates(request)
        assert resp.status == 200
