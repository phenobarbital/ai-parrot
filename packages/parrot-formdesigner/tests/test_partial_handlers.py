"""Unit tests for partial save handler methods (TASK-1249).

Tests FormAPIHandler.save_partial(), get_partial(), and delete_partial()
using mocked dependencies — no real Redis or HTTP server required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.partial import PartialFormData
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_partial(
    form_id: str = "test-form",
    session_id: str = "sess-1",
    data: dict | None = None,
    field_errors: dict | None = None,
) -> PartialFormData:
    """Build a minimal PartialFormData."""
    now = datetime.now(tz=timezone.utc)
    return PartialFormData(
        form_id=form_id,
        session_id=session_id,
        data=data or {},
        field_errors=field_errors or {},
        saved_at=now,
        expires_at=now + timedelta(seconds=60),
    )


def _make_form(form_id: str = "test-form") -> FormSchema:
    """Build a minimal FormSchema with a few fields."""
    return FormSchema(
        form_id=form_id,
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                    ),
                    FormField(
                        field_id="age",
                        field_type=FieldType.INTEGER,
                        label="Age",
                    ),
                ],
            )
        ],
    )


def _make_request(
    method: str = "POST",
    form_id: str = "test-form",
    session_id: str | None = "sess-1",
    body: dict | None = None,
) -> MagicMock:
    """Build a mocked aiohttp request."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id}
    req.method = method

    # Session attribute
    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False
        req.__getitem__ = MagicMock(side_effect=KeyError)

    # Body
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    return req


def _make_handler(
    form: FormSchema | None = None,
    partial_store: PartialSaveStore | None = None,
) -> FormAPIHandler:
    """Build a FormAPIHandler with mocked registry and optional store."""
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = FormAPIHandler(
        registry=registry,
        partial_store=partial_store,
    )
    return handler


# ---------------------------------------------------------------------------
# TestSavePartial
# ---------------------------------------------------------------------------


class TestSavePartial:
    """Tests for FormAPIHandler.save_partial()."""

    async def test_save_single_field_returns_partial(self):
        """POST /partial with one field returns 200 with updated state."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        partial = _make_partial(data={"name": "Alice"})
        store.save = AsyncMock(return_value=partial)

        handler = _make_handler(form=form, partial_store=store)
        req = _make_request(body={"answers": {"name": "Alice"}})

        resp = await handler.save_partial(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["form_id"] == "test-form"
        assert body["data"]["name"] == "Alice"

    async def test_save_bulk_fields(self):
        """POST /partial with multiple fields returns all merged data."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        partial = _make_partial(data={"name": "Alice", "age": 30})
        store.save = AsyncMock(return_value=partial)

        handler = _make_handler(form=form, partial_store=store)
        req = _make_request(body={"answers": {"name": "Alice", "age": 30}})

        resp = await handler.save_partial(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["data"]["age"] == 30

    async def test_save_returns_validation_errors(self):
        """Invalid field values produce field_errors in response."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        partial = _make_partial(data={"age": -5})
        store.save = AsyncMock(return_value=partial)

        handler = _make_handler(form=form, partial_store=store)
        # Make validator.validate_field return an error for "age"
        handler.validator.validate_field = AsyncMock(
            side_effect=lambda field, value, **kw: ["Must be positive"] if field.field_id == "age" else []
        )
        req = _make_request(body={"answers": {"age": -5}})

        resp = await handler.save_partial(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert "age" in body["field_errors"]

    async def test_save_form_not_found(self):
        """Returns 404 when form not in registry."""
        store = MagicMock(spec=PartialSaveStore)
        handler = _make_handler(form=None, partial_store=store)
        req = _make_request(body={"answers": {"name": "Alice"}})

        resp = await handler.save_partial(req)

        assert resp.status == 404

    async def test_save_no_session(self):
        """Returns 400 when session_id is missing."""
        store = MagicMock(spec=PartialSaveStore)
        handler = _make_handler(partial_store=store)
        req = _make_request(session_id=None, body={"answers": {}})

        resp = await handler.save_partial(req)

        assert resp.status == 400

    async def test_save_store_not_configured(self):
        """Returns 503 when partial_store is None."""
        handler = _make_handler(partial_store=None)
        req = _make_request(body={"answers": {}})

        resp = await handler.save_partial(req)

        assert resp.status == 503

    async def test_save_invalid_json_body(self):
        """Returns 400 for invalid JSON body."""
        store = MagicMock(spec=PartialSaveStore)
        handler = _make_handler(partial_store=store)
        req = _make_request(session_id="sess-1")
        req.json = AsyncMock(side_effect=ValueError("bad json"))

        resp = await handler.save_partial(req)

        assert resp.status == 400

    async def test_save_store_exception_returns_503(self):
        """Returns 503 when PartialSaveStore.save() raises."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        store.save = AsyncMock(side_effect=Exception("Redis down"))

        handler = _make_handler(form=form, partial_store=store)
        req = _make_request(body={"answers": {"name": "Alice"}})

        resp = await handler.save_partial(req)

        assert resp.status == 503


# ---------------------------------------------------------------------------
# TestGetPartial
# ---------------------------------------------------------------------------


class TestGetPartial:
    """Tests for FormAPIHandler.get_partial()."""

    async def test_get_returns_cached(self):
        """GET /partial returns 200 with cached partial data."""
        store = MagicMock(spec=PartialSaveStore)
        partial = _make_partial(data={"name": "Bob"})
        store.get = AsyncMock(return_value=partial)

        handler = _make_handler(partial_store=store)
        req = _make_request(method="GET")

        resp = await handler.get_partial(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["data"]["name"] == "Bob"

    async def test_get_not_found(self):
        """GET /partial returns 404 when nothing is cached."""
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=None)

        handler = _make_handler(partial_store=store)
        req = _make_request(method="GET")

        resp = await handler.get_partial(req)

        assert resp.status == 404

    async def test_get_no_session(self):
        """Returns 400 when session_id is missing."""
        store = MagicMock(spec=PartialSaveStore)
        handler = _make_handler(partial_store=store)
        req = _make_request(method="GET", session_id=None)

        resp = await handler.get_partial(req)

        assert resp.status == 400

    async def test_get_store_not_configured(self):
        """Returns 503 when partial_store is None."""
        handler = _make_handler(partial_store=None)
        req = _make_request(method="GET")

        resp = await handler.get_partial(req)

        assert resp.status == 503


# ---------------------------------------------------------------------------
# TestDeletePartial
# ---------------------------------------------------------------------------


class TestDeletePartial:
    """Tests for FormAPIHandler.delete_partial()."""

    async def test_delete_returns_204(self):
        """DELETE /partial returns 204."""
        store = MagicMock(spec=PartialSaveStore)
        store.delete = AsyncMock(return_value=True)

        handler = _make_handler(partial_store=store)
        req = _make_request(method="DELETE")

        resp = await handler.delete_partial(req)

        assert resp.status == 204

    async def test_delete_nonexistent_still_returns_204(self):
        """DELETE /partial returns 204 even when nothing was cached."""
        store = MagicMock(spec=PartialSaveStore)
        store.delete = AsyncMock(return_value=False)

        handler = _make_handler(partial_store=store)
        req = _make_request(method="DELETE")

        resp = await handler.delete_partial(req)

        assert resp.status == 204

    async def test_delete_no_session(self):
        """Returns 400 when session_id is missing."""
        store = MagicMock(spec=PartialSaveStore)
        handler = _make_handler(partial_store=store)
        req = _make_request(method="DELETE", session_id=None)

        resp = await handler.delete_partial(req)

        assert resp.status == 400

    async def test_delete_store_not_configured(self):
        """Returns 503 when partial_store is None."""
        handler = _make_handler(partial_store=None)
        req = _make_request(method="DELETE")

        resp = await handler.delete_partial(req)

        assert resp.status == 503


# ---------------------------------------------------------------------------
# TestHelperMethods
# ---------------------------------------------------------------------------


class TestHelperMethods:
    """Tests for _extract_session_id and _find_field."""

    def test_extract_session_id_present(self):
        """_extract_session_id returns session ID when in request."""
        handler = _make_handler()
        req = _make_request(session_id="my-session")
        result = handler._extract_session_id(req)
        assert result == "my-session"

    def test_extract_session_id_absent(self):
        """_extract_session_id returns None when session is missing."""
        handler = _make_handler()
        req = _make_request(session_id=None)
        result = handler._extract_session_id(req)
        assert result is None

    def test_find_field_found(self):
        """_find_field returns the matching FormField."""
        form = _make_form()
        handler = _make_handler()
        field = handler._find_field(form, "name")
        assert field is not None
        assert field.field_id == "name"

    def test_find_field_not_found(self):
        """_find_field returns None for unknown field_id."""
        form = _make_form()
        handler = _make_handler()
        field = handler._find_field(form, "nonexistent")
        assert field is None
