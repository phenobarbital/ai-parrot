"""Tests for FormSchema.events field — FEAT-188 TASK-1268.

Verifies that the new optional events field on FormSchema is backward-compatible
and correctly serialises / deserialises with FormEventsConfig.
"""

from parrot_formdesigner.core.events import FormEventBinding, FormEventsConfig
from parrot_formdesigner.core.schema import FormSchema


class TestFormSchemaEventsField:
    """Tests for the FormSchema.events field added by TASK-1268."""

    def test_default_is_none(self) -> None:
        """FormSchema without events has events=None by default."""
        f = FormSchema(form_id="f1", title={"en": "t"}, sections=[])
        assert f.events is None

    def test_accepts_events_config(self) -> None:
        """FormSchema accepts a FormEventsConfig in the events field."""
        f = FormSchema(
            form_id="f1",
            title={"en": "t"},
            sections=[],
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            ),
        )
        assert f.events is not None
        assert f.events.onBeforeSubmit is not None
        assert f.events.onBeforeSubmit.handler_ref == "f1.onBeforeSubmit"

    def test_dump_without_events_omits_field_when_exclude_none(self) -> None:
        """model_dump(exclude_none=True) omits the events key when events=None."""
        f = FormSchema(form_id="f1", title={"en": "t"}, sections=[])
        dumped = f.model_dump(exclude_none=True)
        assert "events" not in dumped

    def test_dump_with_events_includes_field(self) -> None:
        """model_dump(exclude_none=True) includes events when declared."""
        f = FormSchema(
            form_id="f1",
            title={"en": "t"},
            sections=[],
            events=FormEventsConfig(
                onError=FormEventBinding(handler_ref="f1.onError"),
            ),
        )
        dumped = f.model_dump(exclude_none=True)
        assert "events" in dumped
        assert dumped["events"]["onError"]["handler_ref"] == "f1.onError"

    def test_accepts_all_five_event_bindings(self) -> None:
        """FormSchema accepts a fully-populated FormEventsConfig."""
        f = FormSchema(
            form_id="survey",
            title={"en": "Survey"},
            sections=[],
            events=FormEventsConfig(
                onBeforeOpen=FormEventBinding(handler_ref="survey.onBeforeOpen"),
                onSchemaLoaded=FormEventBinding(handler_ref="survey.onSchemaLoaded"),
                onBeforeSubmit=FormEventBinding(handler_ref="survey.onBeforeSubmit"),
                onAfterSubmit=FormEventBinding(handler_ref="survey.onAfterSubmit"),
                onError=FormEventBinding(handler_ref="survey.onError"),
            ),
        )
        assert f.events is not None
        assert f.events.onBeforeOpen is not None
        assert f.events.onAfterSubmit is not None

    def test_events_not_in_default_dump(self) -> None:
        """model_dump() without exclude_none includes events=None explicitly."""
        f = FormSchema(form_id="f1", title={"en": "t"}, sections=[])
        dumped = f.model_dump()
        # events=None is present when not excluding None values
        assert "events" in dumped
        assert dumped["events"] is None

    def test_round_trip_serialisation(self) -> None:
        """FormSchema round-trips through model_dump / model_validate correctly."""
        original = FormSchema(
            form_id="rt",
            title={"en": "RoundTrip"},
            sections=[],
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="rt.onBeforeSubmit", remote=True, required=True
                ),
            ),
        )
        dumped = original.model_dump()
        restored = FormSchema.model_validate(dumped)
        assert restored.events is not None
        assert restored.events.onBeforeSubmit is not None
        assert restored.events.onBeforeSubmit.handler_ref == "rt.onBeforeSubmit"
        assert restored.events.onBeforeSubmit.remote is True
        assert restored.events.onBeforeSubmit.required is True

    def test_form_without_events_unchanged_behaviour(self) -> None:
        """Forms without events have identical serialisation to pre-FEAT-188.

        This is the no-breaking acid test from spec §5.
        """
        f = FormSchema(
            form_id="legacy",
            title={"en": "Legacy Form"},
            sections=[],
        )
        # Serialise with exclude_none (standard API usage)
        dumped = f.model_dump(exclude_none=True)
        # Core fields must be present
        assert dumped["form_id"] == "legacy"
        assert dumped["title"] == {"en": "Legacy Form"}
        # events must NOT appear — backward compatibility guaranteed
        assert "events" not in dumped
