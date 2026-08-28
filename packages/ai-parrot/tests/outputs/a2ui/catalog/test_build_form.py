"""Tests for build_form (FEAT-470 TASK-2540)."""

from __future__ import annotations

import pytest
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.catalog.parrot.form import FormField, FormSubmit, build_form
from parrot.outputs.a2ui.models import CreateSurface


def _fields() -> list[FormField]:
    return [
        FormField(name="email", label="Email", input="text", required=True),
        FormField(name="age", label="Age", input="number"),
        FormField(
            name="plan", label="Plan", input="select",
            options=[{"label": "Basic", "value": "basic"}, {"label": "Pro", "value": "pro"}],
        ),
        FormField(name="subscribe", label="Subscribe", input="checkbox"),
        FormField(name="start", label="Start date", input="date"),
    ]


class TestBuildFormComposition:
    def test_build_form_composition(self):
        components = build_form(
            id_prefix="root",
            title="Signup",
            fields=_fields(),
            submit=FormSubmit(label="Send", action="signup"),
        )
        by_id = {c.id: c for c in components}
        assert components[0].id == "root"
        assert components[0].component == "Column"

        assert by_id["root-email"].component == "TextField"
        assert by_id["root-age"].component == "TextField"
        assert by_id["root-plan"].component == "ChoicePicker"
        assert by_id["root-subscribe"].component == "CheckBox"
        assert by_id["root-start"].component == "DateTimeInput"

        button = by_id["root-submit"]
        assert button.component == "Button"
        assert button.action.event.name == "signup"
        assert button.action.event.context["email"] == {"path": "/root/email"}

    def test_required_field_carries_check(self):
        components = build_form(
            id_prefix="f", title=None, fields=_fields(), submit=FormSubmit(label="Go", action="go")
        )
        by_id = {c.id: c for c in components}
        email = by_id["f-email"]
        assert email.checks is not None
        assert email.checks[0].condition.call == "required"
        age = by_id["f-age"]
        assert age.checks is None

    def test_build_form_validates_as_tool_origin(self):
        components = build_form(
            id_prefix="root", title="T", fields=_fields(), submit=FormSubmit(label="Go", action="go")
        )
        surface = CreateSurface(
            surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=components
        )
        validate_envelope(surface, origin=ProducerOrigin.TOOL)

    def test_build_form_rejected_for_llm_origin(self):
        components = build_form(
            id_prefix="root", title="T", fields=_fields(), submit=FormSubmit(label="Go", action="go")
        )
        surface = CreateSurface(
            surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=components
        )
        with pytest.raises(CatalogValidationError):
            validate_envelope(surface, origin=ProducerOrigin.LLM)

    def test_unsupported_input_type_raises(self):
        with pytest.raises(ValueError):  # pydantic ValidationError on FormField itself
            FormField(name="x", label="X", input="bogus")
