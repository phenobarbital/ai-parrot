"""Unit tests for the A2UI dual-wire branch of ``submit_data`` (FEAT-544, TASK-3075).

Follows the mocked-handler pattern established by
``tests/unit/api/test_submit_unknown_fields.py`` (FEAT-458).
"""

from __future__ import annotations

import json as _json
from unittest.mock import AsyncMock, MagicMock

import parrot_formdesigner.api.handlers as handlers_module
import pytest
from aiohttp import web

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.events import EventResolution
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

from parrot.outputs.a2ui.catalog import validate_message
from parrot.outputs.a2ui.serialization import deserialize

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_form() -> FormSchema:
    return FormSchema(
        form_uid=_FORM_UID,
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[FormSection(section_id="s1", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)])],
    )


def _action_body(*, answers: dict, name: str = "form.submit", surface_id: str | None = None) -> dict:
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


def _make_request(body: dict, *, content_type: str = "application/json") -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body)
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    req.content_type = content_type
    req.content_length = len(_json.dumps(body))
    return req


def _make_validation_result(*, is_valid: bool = True, errors: dict | None = None, sanitized: dict | None = None) -> ValidationResult:
    return ValidationResult(
        is_valid=is_valid,
        errors=errors or {},
        sanitized_data=sanitized or {"name": "Ana"},
        extra_data={},
    )


def _make_handler(form: FormSchema, *, submission_storage=None, validation_result: ValidationResult | None = None) -> FormAPIHandler:
    registry = MagicMock()
    registry.get = AsyncMock(return_value=form)
    handler = FormAPIHandler(registry=registry, submission_storage=submission_storage)
    handler.validator = MagicMock(spec=FormValidator)
    handler.validator.validate = AsyncMock(return_value=validation_result or _make_validation_result())
    return handler


@pytest.fixture
def form() -> FormSchema:
    return _make_form()


async def test_submit_legacy_json_unchanged(form):
    """A plain field_id-keyed JSON body is completely unaffected by the A2UI branch."""
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    handler = _make_handler(form, submission_storage=storage)
    resp = await handler.submit_data(_make_request({"name": "Ana"}))
    assert resp.status == 200
    assert resp.content_type == "application/json"
    body = _json.loads(resp.body)
    assert body["is_valid"] is True
    assert "submission_id" in body


async def test_submit_a2ui_422_returns_error_envelopes_and_persists_nothing(form):
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    handler = _make_handler(
        form,
        submission_storage=storage,
        validation_result=_make_validation_result(is_valid=False, errors={"name": ["Name is required."]}),
    )
    resp = await handler.submit_data(_make_request(_action_body(answers={"name": ""})))
    assert resp.status == 422
    assert resp.content_type == "application/json"
    body = _json.loads(resp.body)
    envelopes = body["messages"]
    error_envelopes = [e for e in envelopes if "error" in e]
    assert len(error_envelopes) == 1
    assert error_envelopes[0]["error"]["code"] == "VALIDATION_FAILED"
    assert error_envelopes[0]["error"]["path"] == "/answers/name"
    for envelope in envelopes:
        validate_message(deserialize(envelope))
    storage.store.assert_not_called()


async def test_submit_a2ui_200_returns_confirmation(form):
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    handler = _make_handler(form, submission_storage=storage)
    resp = await handler.submit_data(_make_request(_action_body(answers={"name": "Ada"})))
    assert resp.status == 200
    assert resp.content_type == "application/json"
    body = _json.loads(resp.body)
    envelopes = body["messages"]

    update_data_model = next(e["updateDataModel"] for e in envelopes if "updateDataModel" in e)
    assert update_data_model["path"] == "/submission"
    stored_submission = storage.store.call_args.args[0]
    assert update_data_model["value"]["submission_id"] == stored_submission.submission_id

    update_components = next(e["updateComponents"] for e in envelopes if "updateComponents" in e)
    assert update_components["components"][0]["id"] == "root-status"

    for envelope in envelopes:
        validate_message(deserialize(envelope))


async def test_submit_a2ui_surface_mismatch_400(form):
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    handler = _make_handler(form, submission_storage=storage)
    resp = await handler.submit_data(
        _make_request(_action_body(answers={"name": "Ada"}, surface_id="form-does-not-exist"))
    )
    assert resp.status == 400
    assert resp.content_type == "application/a2ui+json"
    body = _json.loads(resp.body)
    assert body["error"]["code"] == "NOT_FOUND"
    storage.store.assert_not_called()


async def test_submit_a2ui_wrong_action_name_400(form):
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    handler = _make_handler(form, submission_storage=storage)
    resp = await handler.submit_data(_make_request(_action_body(answers={"name": "Ada"}, name="form.bogus")))
    assert resp.status == 400
    storage.store.assert_not_called()


async def test_submit_a2ui_oversized_413(form, monkeypatch):
    # Patch the `a2ui_wire` module object THROUGH `handlers_module` (imported
    # at collection time, same as the other tests in this suite that patch
    # `handlers_module.dispatch`) rather than via a fresh test-body import —
    # an unrelated test (test_no_navigator_auth_fails_at_import.py) pops
    # `parrot_formdesigner.api.*` from sys.modules elsewhere in this
    # directory's suite, so a test-time-local `from ... import a2ui_wire`
    # can silently resolve to a DIFFERENT module object than the one
    # `submit_data`'s `a2ui_wire.A2UI_MAX_BODY_BYTES` lookup actually uses.
    monkeypatch.setattr(handlers_module.a2ui_wire, "A2UI_MAX_BODY_BYTES", 10)
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    handler = _make_handler(form, submission_storage=storage)
    resp = await handler.submit_data(_make_request(_action_body(answers={"name": "Ada"})))
    assert resp.status == 413
    storage.store.assert_not_called()


async def test_submit_a2ui_unknown_fields_reject_policy_path_is_answers():
    form = _make_form().model_copy(update={"unknown_fields": "reject"})
    handler = _make_handler(
        form,
        validation_result=ValidationResult(
            is_valid=True, errors={}, sanitized_data={"name": "Ada"}, extra_data={"junk": 1}
        ),
    )
    resp = await handler.submit_data(_make_request(_action_body(answers={"name": "Ada", "junk": 1})))
    assert resp.status == 422
    body = _json.loads(resp.body)
    error_envelope = next(e for e in body["messages"] if "error" in e)
    assert error_envelope["error"]["path"] == "/answers"


async def test_submit_a2ui_dispatches_lifecycle_hooks_once(form, monkeypatch):
    events: list[str] = []

    async def spy_dispatch(event_name, **kwargs):
        events.append(event_name)
        return EventResolution()

    monkeypatch.setattr(handlers_module, "dispatch", spy_dispatch)
    handler = _make_handler(form)
    await handler.submit_data(_make_request(_action_body(answers={"name": "Ada"})))
    assert events.count("onBeforeSubmit") == 1
    assert events.count("onAfterSubmit") == 1
    assert "onError" not in events
