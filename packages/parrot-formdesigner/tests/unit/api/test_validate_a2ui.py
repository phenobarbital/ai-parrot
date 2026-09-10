"""Unit tests for the A2UI dual-wire branch of ``validate`` (FEAT-544, TASK-3076).

Follows the mocked-handler pattern established by
``tests/unit/api/test_validate_endpoint_unknown_fields.py`` (FEAT-458) and
``tests/unit/api/test_submit_a2ui.py`` (TASK-3075).
"""

from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

from parrot.outputs.a2ui.catalog import validate_message
from parrot.outputs.a2ui.serialization import deserialize

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_form(*, policy: str = "drop") -> FormSchema:
    return FormSchema(
        form_uid=_FORM_UID,
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)],
            )
        ],
        unknown_fields=policy,
    )


def _action_body(*, answers: dict, name: str = "form.validate", surface_id: str | None = None) -> dict:
    return {
        "version": "v1.0",
        "action": {
            "name": name,
            "surfaceId": surface_id or f"form-{_FORM_UID}",
            "sourceComponentId": "root-submit",
            "timestamp": "2026-09-10T00:00:00Z",
            "context": {"form_uid": _FORM_UID},
            "dataModel": {"answers": answers},
        },
    }


def _make_request(body: dict) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body)
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    req.content_type = "application/json"
    req.content_length = len(_json.dumps(body))
    return req


def _make_validation_result(
    *, is_valid: bool = True, errors: dict | None = None, extras: dict | None = None
) -> ValidationResult:
    return ValidationResult(
        is_valid=is_valid,
        errors=errors or {},
        sanitized_data={"name": "Ana"},
        extra_data=extras or {},
    )


def _make_handler(form: FormSchema, *, validation_result: ValidationResult | None = None) -> FormAPIHandler:
    registry = MagicMock()
    registry.get = AsyncMock(return_value=form)
    handler = FormAPIHandler(registry=registry)
    handler.validator = MagicMock(spec=FormValidator)
    handler.validator.validate = AsyncMock(return_value=validation_result or _make_validation_result())
    return handler


async def test_validate_legacy_unchanged():
    form = _make_form()
    handler = _make_handler(form)
    resp = await handler.validate(_make_request({"name": "Ana"}))
    assert resp.status == 200
    assert resp.content_type == "application/json"
    body = _json.loads(resp.body)
    assert body == {"is_valid": True, "errors": {}}


async def test_validate_a2ui_422_errors():
    form = _make_form()
    handler = _make_handler(
        form, validation_result=_make_validation_result(is_valid=False, errors={"name": ["Name is required."]})
    )
    resp = await handler.validate(_make_request(_action_body(answers={"name": ""})))
    assert resp.status == 422
    body = _json.loads(resp.body)
    envelopes = body["messages"]
    error_envelopes = [e for e in envelopes if "error" in e]
    assert len(error_envelopes) == 1
    assert error_envelopes[0]["error"]["code"] == "VALIDATION_FAILED"
    assert error_envelopes[0]["error"]["path"] == "/answers/name"
    assert any("updateDataModel" in e for e in envelopes)
    for envelope in envelopes:
        validate_message(deserialize(envelope))


async def test_validate_a2ui_200_empty_messages():
    form = _make_form()
    handler = _make_handler(form)
    resp = await handler.validate(_make_request(_action_body(answers={"name": "Ada"})))
    assert resp.status == 200
    assert resp.content_type == "application/json"
    body = _json.loads(resp.body)
    assert body == {"messages": []}


async def test_validate_a2ui_unknown_fields_reject():
    form = _make_form(policy="reject")
    handler = _make_handler(
        form,
        validation_result=_make_validation_result(extras={"junk": 1}),
    )
    resp = await handler.validate(_make_request(_action_body(answers={"name": "Ada", "junk": 1})))
    assert resp.status == 422
    body = _json.loads(resp.body)
    error_envelope = next(e for e in body["messages"] if "error" in e)
    assert error_envelope["error"]["path"] == "/answers"


async def test_validate_a2ui_surface_mismatch_400():
    form = _make_form()
    handler = _make_handler(form)
    resp = await handler.validate(
        _make_request(_action_body(answers={"name": "Ada"}, surface_id="form-does-not-exist"))
    )
    assert resp.status == 400
    assert resp.content_type == "application/a2ui+json"
    body = _json.loads(resp.body)
    assert body["error"]["code"] == "NOT_FOUND"


async def test_validate_a2ui_accepts_form_submit_action_name():
    """`unwrap_action` accepts both `form.validate` and `form.submit`."""
    form = _make_form()
    handler = _make_handler(form)
    resp = await handler.validate(_make_request(_action_body(answers={"name": "Ada"}, name="form.submit")))
    assert resp.status == 200
