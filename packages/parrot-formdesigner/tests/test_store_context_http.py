"""Unit tests for HTTP visit_context passthrough (FEAT-440 TASK-2316, spec §3 Module 5).

Both ``FormAPIHandler.validate()`` and ``FormAPIHandler.submit_data()`` call
``FormValidator.validate(form, data, visit_context=...)``. These tests mock
the validator and assert the caller-supplied ``visit_context`` (a reserved
top-level key in the same JSON body used for answers) reaches it — and that
its absence resolves to ``None`` rather than being silently dropped or
mistaken for an answer field. Follows the mocking pattern established in
``test_submit_merge.py`` (TASK-1250).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    LogicGroup,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_form() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
            )
        ],
    )


def _make_request(body: dict) -> MagicMock:
    """Minimal aiohttp request mock for validate()/submit_data() (no merge_partials)."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.json = AsyncMock(return_value=body)
    req.__contains__ = lambda self, key: False
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    return req


def _make_handler(form: FormSchema) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    handler = FormAPIHandler(registry=registry)
    handler.validator = MagicMock(spec=FormValidator)
    return handler


def _capture_validate(handler: FormAPIHandler) -> dict:
    """Wire a fake validate() onto handler.validator that records its kwargs."""
    captured: dict = {}

    async def fake_validate(form, data, **kwargs):
        captured["data"] = data
        captured["visit_context"] = kwargs.get("visit_context")
        return ValidationResult(is_valid=True, errors={}, sanitized_data=data)

    handler.validator.validate = fake_validate
    return captured


class TestValidateEndpointVisitContext:
    """POST /api/v1/forms/{form_uid}/validate."""

    async def test_visit_context_forwarded_to_validator(self):
        form = _make_form()
        handler = _make_handler(form)
        captured = _capture_validate(handler)

        req = _make_request({"name": "Alice", "visit_context": {"store_groups": ["Ring of Fire"]}})
        await handler.validate(req)

        assert captured["visit_context"] == {"store_groups": ["Ring of Fire"]}
        # The reserved key must not leak into the answers dict.
        assert "visit_context" not in captured["data"]
        assert captured["data"] == {"name": "Alice"}

    async def test_absent_visit_context_resolves_to_none(self):
        """Fail closed: no context supplied means None, not {} or missing kwarg."""
        form = _make_form()
        handler = _make_handler(form)
        captured = _capture_validate(handler)

        req = _make_request({"name": "Alice"})
        await handler.validate(req)

        assert captured["visit_context"] is None
        assert captured["data"] == {"name": "Alice"}

    async def test_non_dict_visit_context_is_ignored(self):
        """A malformed visit_context (not a dict) must not crash the handler."""
        form = _make_form()
        handler = _make_handler(form)
        captured = _capture_validate(handler)

        req = _make_request({"name": "Alice", "visit_context": "not-a-dict"})
        await handler.validate(req)

        assert captured["visit_context"] is None
        # Left untouched in `data` since it wasn't recognised as context.
        assert captured["data"] == {"name": "Alice", "visit_context": "not-a-dict"}


class TestSubmitDataVisitContext:
    """POST /api/v1/forms/{form_uid}/data."""

    async def test_visit_context_forwarded_and_stripped_from_answers(self):
        form = _make_form()
        handler = _make_handler(form)
        captured = _capture_validate(handler)

        req = _make_request({"name": "Alice", "visit_context": {"store_groups": ["Best Buy"]}})
        await handler.submit_data(req)

        assert captured["visit_context"] == {"store_groups": ["Best Buy"]}
        assert captured["data"] == {"name": "Alice"}

    async def test_no_visit_context_still_succeeds(self):
        form = _make_form()
        handler = _make_handler(form)
        captured = _capture_validate(handler)

        req = _make_request({"name": "Alice"})
        await handler.submit_data(req)

        assert captured["visit_context"] is None
        assert captured["data"] == {"name": "Alice"}


def _make_store_gated_form() -> FormSchema:
    """A required field shown only when the caller's store context matches.

    ``depends_on`` uses the SAME shape the networkninja importer emits
    (TASK-2315) — a ``groups``-only rule with a single ``visit_context``
    ``CONTAINS`` alternative. No ``field`` reference, so no
    ``resolve_rule_references`` pass is needed for this fixture.
    """
    gated_field = FormField(
        field_id="ring_of_fire_photo",
        field_type=FieldType.TEXT,
        label="Ring of Fire photo",
        required=True,
        depends_on=DependencyRule(
            conditions=[],
            effect="show",
            groups=[
                LogicGroup(
                    conditions=[
                        FieldCondition(
                            source="visit_context",
                            key="store_groups",
                            operator=ConditionOperator.CONTAINS,
                            value="Ring of Fire",
                        )
                    ]
                )
            ],
        ),
    )
    return FormSchema(
        form_id="gated-form",
        title="Gated Form",
        tenant=_TEST_TENANT,
        sections=[FormSection(section_id="s1", fields=[gated_field])],
    )


class TestEndToEndStoreGatedRule:
    """AC: 'An end-to-end request carrying a store context resolves a
    store-gated rule correctly; the same request without it leaves the rule
    unfired.' Uses the REAL FormValidator (not mocked) end to end through
    the HTTP handler."""

    async def test_matching_store_context_requires_the_gated_field(self):
        """Store matches -> field is shown -> required -> unanswered fails."""
        form = _make_store_gated_form()
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=form)
        handler = FormAPIHandler(registry=registry)  # real FormValidator

        req = _make_request({"visit_context": {"store_groups": ["Ring of Fire"]}})
        resp = await handler.validate(req)

        assert resp.status == 422
        assert "ring_of_fire_photo" in resp.text

    async def test_non_matching_store_context_leaves_rule_unfired(self):
        """Store doesn't match -> field stays hidden -> not required -> valid."""
        form = _make_store_gated_form()
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=form)
        handler = FormAPIHandler(registry=registry)

        req = _make_request({"visit_context": {"store_groups": ["Best Buy"]}})
        resp = await handler.validate(req)

        assert resp.status == 200

    async def test_absent_store_context_fails_closed(self):
        """No context at all -> rule cannot fire -> field stays hidden -> valid.

        Fail-closed by design (spec §3 Module 5): a rule referencing a store
        the caller never described must not reveal the gated field.
        """
        form = _make_store_gated_form()
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=form)
        handler = FormAPIHandler(registry=registry)

        req = _make_request({})
        resp = await handler.validate(req)

        assert resp.status == 200
