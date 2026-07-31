"""Unit tests for FEAT-393 Module 9 — partial saves re-keyed by field_uid.

Spec §4 Module 9 (TASK-2003). ``PartialSaveStore`` stays schema-agnostic;
``FormAPIHandler`` re-keys at the handler boundary so a mid-session
``field_id`` rename never orphans a saved answer, while the wire
request/response contract stays ``field_id``-keyed.

Covers the dedicated Test Specification rows:

* ``test_partial_save_rekeyed_by_uid`` — the raw value persisted to the
  (fake) Redis backend is keyed by ``field_uid``, not ``field_id``.
* ``test_partial_save_response_keyed_by_field_id`` — the save_partial JSON
  response is keyed by ``field_id``.
* ``test_partial_save_survives_rename`` — save under the original
  ``field_id``, rename it (same ``field_uid``), then GET shows the answer
  under the NEW ``field_id``.
* ``test_unknown_field_rejected_not_stored`` — an unknown ``field_id`` in
  the answers dict is rejected (field error) and never persisted.
* ``test_deleted_field_uid_dropped_on_read`` — a UID whose field was
  removed from the form is dropped silently on read, not surfaced as an
  error.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry

_FORM_UID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal fake Redis client backed by a plain dict."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def close(self) -> None:
        pass


class InMemoryPartialStore(PartialSaveStore):
    """PartialSaveStore backed by an in-memory dict (no live Redis needed)."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        super().__init__(ttl_seconds=ttl_seconds, redis_url=None)
        self.raw_store: dict[str, str] = {}

    async def _get_redis(self) -> Any:
        return _FakeRedis(self.raw_store)


def _make_form(fields: list[FormField] | None = None) -> FormSchema:
    if fields is None:
        fields = [
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
        ]
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[FormSection(section_id="s1", fields=fields)],
    )


def _make_request(
    method: str = "POST",
    session_id: str | None = "sess-1",
    body: dict | None = None,
) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.method = method

    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False
        req.__getitem__ = MagicMock(side_effect=KeyError)

    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    return req


def _make_handler(form: FormSchema, store: PartialSaveStore) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    return FormAPIHandler(registry=registry, partial_store=store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_partial_save_rekeyed_by_uid() -> None:
    """The raw Redis-persisted value is keyed by field_uid, not field_id."""
    form = _make_form()
    name_field = form.sections[0].fields[0]
    store = InMemoryPartialStore()
    handler = _make_handler(form, store)

    resp = await handler.save_partial(
        _make_request(body={"answers": {"name": "Alice"}})
    )
    assert resp.status == 200

    # Inspect the raw persisted JSON directly (bypassing the handler's
    # field_id-remapping read path).
    raw_key = f"{PartialSaveStore.REDIS_KEY_PREFIX}{_FORM_UID}:sess-1"
    raw_json = store.raw_store[raw_key]
    raw_data = json.loads(raw_json)["data"]
    assert str(name_field.field_uid) in raw_data
    assert raw_data[str(name_field.field_uid)] == "Alice"
    assert "name" not in raw_data


async def test_partial_save_response_keyed_by_field_id() -> None:
    """The save_partial JSON response is keyed by field_id (wire contract)."""
    form = _make_form()
    store = InMemoryPartialStore()
    handler = _make_handler(form, store)

    resp = await handler.save_partial(
        _make_request(body={"answers": {"name": "Alice", "age": 30}})
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["data"] == {"name": "Alice", "age": 30}


async def test_partial_save_survives_rename() -> None:
    """save under the original field_id, rename it, GET shows the NEW field_id."""
    form = _make_form()
    name_field, age_field = form.sections[0].fields
    store = InMemoryPartialStore()
    handler = _make_handler(form, store)

    resp = await handler.save_partial(
        _make_request(body={"answers": {"name": "Alice"}})
    )
    assert resp.status == 200

    # Simulate an EditToolkit/operations rename: same field_uid, new field_id
    # (mirrors _apply_update_field's allowed field_id rename, TASK-1999).
    renamed_name_field = name_field.model_copy(update={"field_id": "full_name"})
    renamed_form = _make_form(fields=[renamed_name_field, age_field])

    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=renamed_form)
    handler.registry = registry

    resp_get = await handler.get_partial(_make_request(method="GET"))
    assert resp_get.status == 200
    body = json.loads(resp_get.body)
    assert body["data"]["full_name"] == "Alice"
    assert "name" not in body["data"]


async def test_unknown_field_rejected_not_stored() -> None:
    """An unknown field_id is rejected as a field error and never persisted."""
    form = _make_form()
    store = InMemoryPartialStore()
    handler = _make_handler(form, store)

    resp = await handler.save_partial(
        _make_request(body={"answers": {"totally_unknown": "x"}})
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert "totally_unknown" in body["field_errors"]
    assert body["data"] == {}

    # Re-read: nothing was stored for the unknown field.
    resp_get = await handler.get_partial(_make_request(method="GET"))
    assert resp_get.status == 200
    get_body = json.loads(resp_get.body)
    assert "totally_unknown" not in get_body["data"]


async def test_deleted_field_uid_dropped_on_read() -> None:
    """A UID whose field was removed from the form is dropped silently on read."""
    form = _make_form()
    name_field, _age_field = form.sections[0].fields
    store = InMemoryPartialStore()
    handler = _make_handler(form, store)

    resp = await handler.save_partial(
        _make_request(body={"answers": {"name": "Alice", "age": 30}})
    )
    assert resp.status == 200

    # Simulate a field deletion: the current form no longer has "age".
    form_without_age = _make_form(fields=[name_field])
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form_without_age)
    handler.registry = registry

    resp_get = await handler.get_partial(_make_request(method="GET"))
    assert resp_get.status == 200
    body = json.loads(resp_get.body)
    assert body["data"] == {"name": "Alice"}
    assert "age" not in body["data"]
