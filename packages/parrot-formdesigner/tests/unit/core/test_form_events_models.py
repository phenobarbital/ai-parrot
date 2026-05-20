"""Unit tests for parrot_formdesigner.core.events — FEAT-188.

Tests cover all Pydantic models and the FormEventAbort exception created
by TASK-1265.
"""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventContext,
    FormEventsConfig,
)


class TestFormEventBinding:
    """Tests for FormEventBinding model."""

    def test_namespaced_handler_ref_valid(self) -> None:
        """handler_ref with at least one dot validates successfully."""
        b = FormEventBinding(handler_ref="survey_v1.onBeforeSubmit")
        assert b.handler_ref == "survey_v1.onBeforeSubmit"
        assert b.remote is False
        assert b.required is False

    def test_deeply_namespaced_handler_ref_valid(self) -> None:
        """handler_ref with multiple dots is also valid."""
        b = FormEventBinding(handler_ref="tenant.form.onError")
        assert b.handler_ref == "tenant.form.onError"

    def test_handler_ref_without_dot_rejected(self) -> None:
        """handler_ref without a dot fails regex validation."""
        with pytest.raises(ValidationError, match="handler_ref"):
            FormEventBinding(handler_ref="no_dot")

    def test_handler_ref_empty_rejected(self) -> None:
        """Empty handler_ref is rejected."""
        with pytest.raises(ValidationError):
            FormEventBinding(handler_ref="")

    def test_handler_ref_leading_dot_rejected(self) -> None:
        """handler_ref starting with a dot fails regex."""
        with pytest.raises(ValidationError, match="handler_ref"):
            FormEventBinding(handler_ref=".start")

    def test_remote_default_false(self) -> None:
        """remote defaults to False."""
        b = FormEventBinding(handler_ref="a.b")
        assert b.remote is False

    def test_remote_can_be_set_true(self) -> None:
        """remote can be explicitly set to True."""
        b = FormEventBinding(handler_ref="a.b", remote=True)
        assert b.remote is True

    def test_required_default_false(self) -> None:
        """required defaults to False."""
        b = FormEventBinding(handler_ref="a.b")
        assert b.required is False

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields trigger ValidationError (extra='forbid')."""
        with pytest.raises(ValidationError):
            FormEventBinding(handler_ref="a.b", unknown=True)


class TestFormEventsConfig:
    """Tests for FormEventsConfig model."""

    def test_all_fields_optional(self) -> None:
        """FormEventsConfig() with no arguments is valid."""
        c = FormEventsConfig()
        assert c.onBeforeOpen is None
        assert c.onSchemaLoaded is None
        assert c.onBeforeSubmit is None
        assert c.onAfterSubmit is None
        assert c.onError is None

    def test_accepts_bindings(self) -> None:
        """Can set individual event bindings."""
        c = FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="x.y"),
        )
        assert c.onBeforeSubmit is not None
        assert c.onBeforeSubmit.handler_ref == "x.y"

    def test_accepts_all_five_events(self) -> None:
        """All five event slots can be populated simultaneously."""
        c = FormEventsConfig(
            onBeforeOpen=FormEventBinding(handler_ref="f.onBeforeOpen"),
            onSchemaLoaded=FormEventBinding(handler_ref="f.onSchemaLoaded"),
            onBeforeSubmit=FormEventBinding(handler_ref="f.onBeforeSubmit"),
            onAfterSubmit=FormEventBinding(handler_ref="f.onAfterSubmit"),
            onError=FormEventBinding(handler_ref="f.onError"),
        )
        assert c.onBeforeOpen is not None
        assert c.onError is not None

    def test_extra_fields_forbidden(self) -> None:
        """Extra event names are rejected (extra='forbid')."""
        with pytest.raises(ValidationError):
            FormEventsConfig(onUnknownEvent=FormEventBinding(handler_ref="a.b"))


class TestFormEventContext:
    """Tests for FormEventContext model."""

    def test_minimal_valid_context(self) -> None:
        """Minimum required fields produce a valid context."""
        ctx = FormEventContext(
            event="onBeforeSubmit",
            form_id="survey_v1",
            tenant="acme",
            auth_context=None,
        )
        assert ctx.event == "onBeforeSubmit"
        assert ctx.form_id == "survey_v1"
        assert ctx.tenant == "acme"
        assert ctx.payload is None
        assert ctx.schema_dump is None
        assert ctx.error is None
        assert ctx.user_message is None
        assert ctx.extra == {}

    def test_extra_dict_default_factory(self) -> None:
        """extra defaults to a fresh empty dict per instance."""
        ctx1 = FormEventContext(event="onError", form_id="f", tenant="t", auth_context=None)
        ctx2 = FormEventContext(event="onError", form_id="g", tenant="t", auth_context=None)
        ctx1.extra["key"] = "value"
        assert ctx2.extra == {}  # no shared mutable default

    def test_auth_context_accepts_any_type(self) -> None:
        """auth_context accepts arbitrary objects (typed Any)."""

        class FakeAuth:
            pass

        ctx = FormEventContext(
            event="onAfterSubmit",
            form_id="f",
            tenant="t",
            auth_context=FakeAuth(),
        )
        assert isinstance(ctx.auth_context, FakeAuth)

    def test_invalid_event_name_rejected(self) -> None:
        """Unknown event names fail Literal validation."""
        with pytest.raises(ValidationError):
            FormEventContext(
                event="onUnknownEvent",
                form_id="f",
                tenant="t",
                auth_context=None,
            )

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields in context are rejected."""
        with pytest.raises(ValidationError):
            FormEventContext(
                event="onBeforeOpen",
                form_id="f",
                tenant="t",
                auth_context=None,
                surprise_field="boom",
            )


class TestFormEventAbort:
    """Tests for FormEventAbort exception."""

    def test_default_status_code(self) -> None:
        """Default status_code is 403."""
        e = FormEventAbort("blocked", user_message="No")
        assert e.reason == "blocked"
        assert e.user_message == "No"
        assert e.status_code == 403

    def test_custom_status_code(self) -> None:
        """Custom status_code is preserved."""
        e = FormEventAbort("nope", user_message="X", status_code=409)
        assert e.status_code == 409

    def test_is_exception(self) -> None:
        """FormEventAbort is a proper Exception subclass that can be raised."""
        with pytest.raises(FormEventAbort):
            raise FormEventAbort("r", user_message="m")

    def test_message_propagates(self) -> None:
        """The reason string becomes the exception args."""
        e = FormEventAbort("technical reason", user_message="friendly")
        assert str(e) == "technical reason"

    def test_not_triggered_by_runtime_error(self) -> None:
        """FormEventAbort is distinct from RuntimeError."""
        with pytest.raises(FormEventAbort):
            try:
                raise FormEventAbort("abort", user_message="msg")
            except RuntimeError:
                pass  # should NOT catch it


class TestEventResolution:
    """Tests for EventResolution model."""

    def test_empty_is_valid(self) -> None:
        """EventResolution() with no arguments is a valid no-op."""
        r = EventResolution()
        assert r.payload is None
        assert r.schema_overrides is None
        assert r.metadata is None
        assert r.user_message is None

    def test_payload_field_accepted(self) -> None:
        """payload field accepts a mapping."""
        r = EventResolution(payload={"email": "test@example.com"})
        assert r.payload == {"email": "test@example.com"}

    def test_schema_overrides_accepted(self) -> None:
        """schema_overrides field accepts a mapping."""
        r = EventResolution(schema_overrides={"title": {"en": "New Title"}})
        assert r.schema_overrides is not None

    def test_user_message_accepted(self) -> None:
        """user_message field is accepted for onError use."""
        r = EventResolution(user_message="Something went wrong")
        assert r.user_message == "Something went wrong"

    def test_extra_forbidden(self) -> None:
        """Extra fields are rejected (extra='forbid')."""
        with pytest.raises(ValidationError):
            EventResolution(unknown_field=True)

    def test_payload_and_schema_overrides_together(self) -> None:
        """payload and schema_overrides can coexist in one resolution."""
        r = EventResolution(
            payload={"x": 1},
            schema_overrides={"title": {"en": "T"}},
            user_message="ok",
        )
        assert r.payload == {"x": 1}
        assert r.schema_overrides == {"title": {"en": "T"}}
        assert r.user_message == "ok"
