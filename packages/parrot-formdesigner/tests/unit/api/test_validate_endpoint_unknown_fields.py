"""Unit tests for the dry-run validate endpoint honouring the unknown-fields
policy (FEAT-458, TASK-2437 — spec Module 6).

Follows the same mocked-handler pattern as
``tests/unit/api/test_submit_unknown_fields.py`` (TASK-2436): registry and
validator are mocked, no real DB or network I/O.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_form(*, policy: str = "drop") -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[
            FormSection(section_id="s1", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")])
        ],
        unknown_fields=policy,
    )


def _make_request(body: dict | None = None) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body or {"name": "Ana"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
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
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = FormAPIHandler(registry=registry)
    handler.validator = MagicMock(spec=FormValidator)
    handler.validator.validate = AsyncMock(return_value=validation_result or _make_validation_result())
    return handler


async def _body(resp: web.Response) -> dict:
    return json.loads(resp.body)


class TestValidateEndpointPolicy:
    async def test_reject_returns_422(self):
        form = _make_form(policy="reject")
        handler = _make_handler(form, validation_result=_make_validation_result(extras={"junk": 1, "other": 2}))
        resp = await handler.validate(_make_request({"name": "Ana", "junk": 1, "other": 2}))
        assert resp.status == 422
        body = await _body(resp)
        assert body["is_valid"] is False
        assert body["errors"]["__unknown__"] == ["junk", "other"]

    async def test_reject_clean_payload_200(self):
        form = _make_form(policy="reject")
        handler = _make_handler(form, validation_result=_make_validation_result())
        resp = await handler.validate(_make_request({"name": "Ana"}))
        assert resp.status == 200
        body = await _body(resp)
        assert body["is_valid"] is True
        assert body["errors"] == {}

    async def test_reject_merges_with_field_errors(self):
        form = _make_form(policy="reject")
        handler = _make_handler(
            form,
            validation_result=_make_validation_result(
                is_valid=False, errors={"name": ["required"]}, extras={"junk": 1}
            ),
        )
        resp = await handler.validate(_make_request({"name": "", "junk": 1}))
        assert resp.status == 422
        body = await _body(resp)
        assert "__unknown__" in body["errors"]
        assert "name" in body["errors"]

    @pytest.mark.parametrize("policy", ["drop", "keep"])
    async def test_non_reject_policies_unchanged(self, policy):
        form = _make_form(policy=policy)
        handler = _make_handler(form, validation_result=_make_validation_result(extras={"junk": 1}))
        resp = await handler.validate(_make_request({"name": "Ana", "junk": 1}))
        assert resp.status == 200
        assert await _body(resp) == {"is_valid": True, "errors": {}}

    async def test_result_errors_not_mutated(self):
        form = _make_form(policy="reject")
        vr = _make_validation_result(extras={"junk": 1})
        handler = _make_handler(form, validation_result=vr)
        await handler.validate(_make_request({"name": "Ana", "junk": 1}))
        assert vr.errors == {}

    async def test_no_lifecycle_dispatch(self, monkeypatch):
        import parrot_formdesigner.api.handlers as handlers_module

        called = []

        async def spy_dispatch(event_name, **kwargs):
            called.append(event_name)

        monkeypatch.setattr(handlers_module, "dispatch", spy_dispatch)
        form = _make_form(policy="reject")
        handler = _make_handler(form, validation_result=_make_validation_result(extras={"junk": 1}))
        await handler.validate(_make_request({"name": "Ana", "junk": 1}))
        assert called == []
