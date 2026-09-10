"""End-to-end A2UI form cycle integration tests (FEAT-544, TASK-3077).

Spec §4 Integration Tests / §5 Acceptance Criteria. Exercises the assembled
layers — real ``A2UIFormRenderer``, real ``FormAPIHandler.submit_data``/
``.validate``, real ``a2ui_wire`` unwrap/reply — with only the registry and
storage faked (no live DB/network), following this package's established
"integration" convention (``tests/integration/test_lifecycle_events_e2e.py``,
``tests/integration/test_unknown_fields_e2e.py``): a mocked ``web.Request``
drives the real handler methods directly rather than a live aiohttp
``TestClient`` + ``setup_form_api`` (which would additionally require
navigator-auth session/middleware scaffolding this suite does not otherwise
demonstrate anywhere).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.tenant import TenantForbiddenError
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer
from parrot_formdesigner.services.registry import FormRegistry

_TEST_TENANT = "test-tenant"


class _FakeStorage:
    """A minimal real (non-mock) submission store — read back for assertions."""

    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, submission) -> None:
        self.stored.append(submission)

    def get(self, submission_id: str):
        return next((s for s in self.stored if s.submission_id == submission_id), None)


def _make_form(*, is_public: bool = True) -> FormSchema:
    return FormSchema(
        form_id="a2ui-cycle",
        title="A2UI Cycle",
        tenant=_TEST_TENANT,
        is_public=is_public,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)],
            )
        ],
    )


def _make_request(body: dict, *, programs: list[str] | None = None) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": "placeholder"}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body)
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT] if programs is None else programs}}
    req.content_type = "application/json"
    req.content_length = len(json.dumps(body))
    return req


async def _render_surface(form: FormSchema) -> dict:
    renderer = A2UIFormRenderer()
    rendered = await renderer.render(form)
    return rendered.content["createSurface"]


def _field_pointer_from_surface(surface: dict, field_id: str) -> str:
    """Read the field's `value.path` DIRECTLY off the rendered wire component.

    Proves render and receiver agree on the pointer, rather than trusting a
    hard-coded or renderer-internal shortcut.
    """
    component = next(
        c
        for c in surface["components"]
        if c.get("metadata", {}).get("extensions", {}).get("parrot_field_id") == field_id
    )
    return component["value"]["path"]


def _action_from_surface(surface: dict, answers: dict, *, name: str = "form.submit") -> dict:
    submit = next(c for c in surface["components"] if c["id"] == "root-submit")
    return {
        "version": "v1.0",
        "action": {
            "name": name,
            "surfaceId": surface["surfaceId"],
            "sourceComponentId": "root-submit",
            "timestamp": "2026-09-10T00:00:00Z",
            "context": dict(submit["action"]["event"]["context"]),
            "dataModel": {"answers": answers},
        },
    }


def _make_handler(form: FormSchema, *, storage: _FakeStorage | None = None) -> FormAPIHandler:
    registry = FormRegistry()
    handler = FormAPIHandler(registry=registry, submission_storage=storage)
    return handler, registry


async def test_a2ui_form_cycle_end_to_end():
    form = _make_form()
    storage = _FakeStorage()
    handler, registry = _make_handler(form, storage=storage)
    await registry.register(form)

    # 1. GET .../render/a2ui
    surface = await _render_surface(form)
    assert surface["surfaceId"] == f"form-{form.form_uid}"

    submit = next(c for c in surface["components"] if c["id"] == "root-submit")
    submit_url = submit["action"]["event"]["context"]["submit_url"]
    assert submit_url == f"/api/v1/{form.tenant}/forms/{form.form_uid}/data"

    name_pointer = _field_pointer_from_surface(surface, "name")
    assert name_pointer == "/answers/name"

    # 2. Missing required field -> 422 (handler.validator is the real
    # FormValidator by default — FormAPIHandler.__init__ constructs one)
    request = _make_request(_action_from_surface(surface, {"name": ""}))
    request.match_info = {"form_uid": str(form.form_uid)}
    resp = await handler.submit_data(request)
    assert resp.status == 422
    body = json.loads(resp.body)
    envelopes = body["messages"]
    error = next(e for e in envelopes if "error" in e)
    assert error["error"]["code"] == "VALIDATION_FAILED"
    assert error["error"]["path"] == name_pointer
    assert storage.stored == []

    # 3. Fix and resubmit -> 200 confirmation
    request = _make_request(_action_from_surface(surface, {"name": "Ada"}))
    request.match_info = {"form_uid": str(form.form_uid)}
    resp = await handler.submit_data(request)
    assert resp.status == 200
    body = json.loads(resp.body)
    update_data_model = next(e["updateDataModel"] for e in body["messages"] if "updateDataModel" in e)
    assert len(storage.stored) == 1
    assert update_data_model["value"]["submission_id"] == storage.stored[0].submission_id

    update_components = next(e["updateComponents"] for e in body["messages"] if "updateComponents" in e)
    assert update_components["components"][0]["id"] == "root-status"

    # 4. POST .../validate with the same envelope -> 200 {"messages": []}
    request = _make_request(_action_from_surface(surface, {"name": "Ada"}, name="form.validate"))
    request.match_info = {"form_uid": str(form.form_uid)}
    resp = await handler.validate(request)
    assert resp.status == 200
    assert json.loads(resp.body) == {"messages": []}


async def test_public_and_private_form_membership_on_a2ui_submit():
    private_form = _make_form(is_public=False)
    storage = _FakeStorage()
    handler, registry = _make_handler(private_form, storage=storage)
    await registry.register(private_form)

    surface = await _render_surface(private_form)
    request = _make_request(_action_from_surface(surface, {"name": "Ada"}), programs=[])
    request.match_info = {"form_uid": str(private_form.form_uid)}

    with pytest.raises(TenantForbiddenError) as exc_info:
        await handler.submit_data(request)
    assert exc_info.value.status == 403
    assert storage.stored == []


async def test_legacy_and_a2ui_submissions_persist_identically():
    legacy_form = _make_form()
    a2ui_form = _make_form()
    legacy_storage = _FakeStorage()
    a2ui_storage = _FakeStorage()

    legacy_handler, legacy_registry = _make_handler(legacy_form, storage=legacy_storage)
    await legacy_registry.register(legacy_form)
    legacy_request = _make_request({"name": "Ada"})
    legacy_request.match_info = {"form_uid": str(legacy_form.form_uid)}
    legacy_resp = await legacy_handler.submit_data(legacy_request)
    assert legacy_resp.status == 200

    a2ui_handler, a2ui_registry = _make_handler(a2ui_form, storage=a2ui_storage)
    await a2ui_registry.register(a2ui_form)
    surface = await _render_surface(a2ui_form)
    a2ui_request = _make_request(_action_from_surface(surface, {"name": "Ada"}))
    a2ui_request.match_info = {"form_uid": str(a2ui_form.form_uid)}
    a2ui_resp = await a2ui_handler.submit_data(a2ui_request)
    assert a2ui_resp.status == 200

    assert legacy_storage.stored[0].data == a2ui_storage.stored[0].data == {"name": "Ada"}
