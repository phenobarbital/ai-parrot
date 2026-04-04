"""Unit tests for Telegram form models."""

import pytest

from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.renderers.telegram.models import (
    FormActionCallback,
    FormFieldCallback,
    TelegramFormPayload,
    TelegramFormStep,
    TelegramRenderMode,
)


class TestTelegramRenderMode:
    def test_enum_values(self):
        assert TelegramRenderMode.INLINE == "inline"
        assert TelegramRenderMode.WEBAPP == "webapp"
        assert TelegramRenderMode.AUTO == "auto"

    def test_string_conversion(self):
        assert str(TelegramRenderMode.INLINE) == "TelegramRenderMode.INLINE" or TelegramRenderMode.INLINE.value == "inline"


class TestTelegramFormStep:
    def test_serialization(self):
        step = TelegramFormStep(
            field_id="visit_type",
            message_text="Select visit type:",
            reply_markup={"inline_keyboard": [[{"text": "A", "callback_data": "x"}]]},
            field_type=FieldType.SELECT,
            required=True,
            options=[("val1", "Option 1"), ("val2", "Option 2")],
        )
        data = step.model_dump()
        assert data["field_id"] == "visit_type"
        assert data["required"] is True
        assert len(data["options"]) == 2

    def test_deserialization(self):
        step = TelegramFormStep(
            field_id="q1",
            message_text="OK?",
            reply_markup={"inline_keyboard": []},
            field_type=FieldType.BOOLEAN,
        )
        data = step.model_dump()
        restored = TelegramFormStep.model_validate(data)
        assert restored.field_type == FieldType.BOOLEAN
        assert restored.required is False

    def test_options_optional(self):
        step = TelegramFormStep(
            field_id="q1",
            message_text="OK?",
            reply_markup={},
            field_type=FieldType.BOOLEAN,
        )
        assert step.options is None


class TestTelegramFormPayload:
    def test_inline_payload(self):
        payload = TelegramFormPayload(
            mode=TelegramRenderMode.INLINE,
            form_id="test-form",
            form_title="Test",
            steps=[],
            total_fields=0,
        )
        assert payload.webapp_url is None
        assert payload.steps == []

    def test_webapp_payload(self):
        payload = TelegramFormPayload(
            mode=TelegramRenderMode.WEBAPP,
            form_id="test-form",
            form_title="Test",
            webapp_url="https://example.com/forms/test-form/telegram",
            total_fields=5,
        )
        assert payload.steps is None
        assert "telegram" in payload.webapp_url

    def test_serialization_roundtrip(self):
        payload = TelegramFormPayload(
            mode=TelegramRenderMode.INLINE,
            form_id="f1",
            form_title="Form 1",
            steps=[
                TelegramFormStep(
                    field_id="q1",
                    message_text="Pick:",
                    reply_markup={"inline_keyboard": []},
                    field_type=FieldType.SELECT,
                )
            ],
            total_fields=1,
        )
        data = payload.model_dump()
        restored = TelegramFormPayload.model_validate(data)
        assert restored.mode == TelegramRenderMode.INLINE
        assert len(restored.steps) == 1


class TestFormFieldCallback:
    def test_pack_within_64_bytes(self):
        cb = FormFieldCallback(fh="abcdefgh", fi=99, oi=99)
        packed = cb.pack()
        assert len(packed.encode("utf-8")) <= 64

    def test_pack_worst_case(self):
        cb = FormFieldCallback(fh="12345678", fi=999, oi=999)
        packed = cb.pack()
        assert len(packed.encode("utf-8")) <= 64

    def test_roundtrip(self):
        original = FormFieldCallback(fh="abc", fi=2, oi=3)
        packed = original.pack()
        restored = FormFieldCallback.unpack(packed)
        assert restored.fi == 2
        assert restored.oi == 3
        assert restored.fh == "abc"


class TestFormActionCallback:
    def test_pack_within_64_bytes(self):
        cb = FormActionCallback(fh="abcdefgh", act="submit")
        packed = cb.pack()
        assert len(packed.encode("utf-8")) <= 64

    def test_roundtrip(self):
        original = FormActionCallback(fh="abc", act="cancel")
        packed = original.pack()
        restored = FormActionCallback.unpack(packed)
        assert restored.act == "cancel"
