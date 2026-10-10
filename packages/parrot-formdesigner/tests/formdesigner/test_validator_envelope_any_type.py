"""FEAT-649: FormValidator accepts voice evidence envelopes on any field type."""
import pytest

from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


def _env(answer, **kw):
    return {"answer": answer, "blob_ref": "voice-s1-x", "source": "speech", "confidence": 0.9, **kw}


def _opts(*vals):
    return [FieldOption(value=v, label=v) for v in vals]


@pytest.fixture
def form() -> FormSchema:
    fields = [
        FormField(field_id="color", field_type=FieldType.SELECT, label="Color", required=True,
                  options=_opts("red", "green")),
        FormField(field_id="tags", field_type=FieldType.MULTI_SELECT, label="Tags", options=_opts("a", "b", "c")),
        FormField(field_id="ok", field_type=FieldType.BOOLEAN, label="Ok"),
        FormField(field_id="age", field_type=FieldType.NUMBER, label="Age",
                  constraints=FieldConstraints(min_value=0)),
        FormField(field_id="note", field_type=FieldType.TEXT, label="Note", answer_envelope="voice",
                  accept_content_types=["application/json"]),
    ]
    return FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s", fields=fields)])


async def _run(form, data):
    return await FormValidator().validate(form, data)


class TestEnvelopeAnyType:
    async def test_select_envelope_valid_refolds(self, form):
        r = await _run(form, {"color": _env("red")})
        assert r.is_valid, r.errors
        assert r.sanitized_data["color"]["answer"] == "red"
        assert r.sanitized_data["color"]["blob_ref"] == "voice-s1-x"

    async def test_select_envelope_invalid_option_errors(self, form):
        r = await _run(form, {"color": _env("blue")})
        assert not r.is_valid
        assert "color" in r.errors

    async def test_multi_select_envelope_list(self, form):
        r = await _run(form, {"color": "red", "tags": _env(["a", "b"])})
        assert r.is_valid, r.errors
        assert r.sanitized_data["tags"]["answer"] == ["a", "b"]

    async def test_boolean_and_number_coerced(self, form):
        r = await _run(form, {"color": "red", "ok": _env(True), "age": _env("42")})
        assert r.is_valid, r.errors
        assert r.sanitized_data["ok"]["answer"] is True
        assert r.sanitized_data["age"]["answer"] == 42

    async def test_number_invalid(self, form):
        r = await _run(form, {"color": "red", "age": _env("abc")})
        assert not r.is_valid

    async def test_required_envelope_with_empty_answer(self, form):
        r = await _run(form, {"color": _env("")})
        assert not r.is_valid
        assert "color" in r.errors


class TestFeat488Unchanged:
    async def test_plain_text_envelope_dump_identical(self, form):
        v = FormValidator()
        out = v._coerce_value({"answer": "hi"}, form.sections[0].fields[4])
        assert out == {"answer": "hi", "blob_ref": None, "data_url": None}

    async def test_text_envelope_with_evidence_keys_accepted(self, form):
        r = await _run(form, {"color": "red", "note": _env("hello", language="en")})
        assert r.is_valid, r.errors
        assert r.sanitized_data["note"]["answer"] == "hello"
        assert r.sanitized_data["note"]["language"] == "en"


class TestEnvelopeRulesAndShape:
    """Review fixes: rules see scalars (ledger 67089d7203f4); bad envelope -> field error (ledger ea847adb2d3b)."""

    @pytest.fixture
    def rule_form(self) -> FormSchema:
        from parrot_formdesigner.core.constraints import ConditionOperator, DependencyRule, FieldCondition

        rule = DependencyRule(
            conditions=[FieldCondition(field_id="has_pet", operator=ConditionOperator.EQ, value=True)],
            effect="require",
        )
        fields = [
            FormField(field_id="has_pet", field_type=FieldType.BOOLEAN, label="Pet"),
            FormField(field_id="pet_name", field_type=FieldType.TEXT, label="Pet name", depends_on=rule),
        ]
        from parrot_formdesigner.core.resolution import resolve_rule_references

        return resolve_rule_references(
            FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s", fields=fields)])
        )

    async def test_require_rule_fires_on_spoken_trigger(self, rule_form):
        r = await _run(rule_form, {"has_pet": _env(True)})
        assert not r.is_valid
        assert "pet_name" in r.errors

    async def test_require_rule_not_fired_when_false(self, rule_form):
        r = await _run(rule_form, {"has_pet": _env(False)})
        assert r.is_valid, r.errors

    async def test_malformed_envelope_is_field_error(self, form):
        bad = _env("red", confidence="not-a-number")
        r = await _run(form, {"color": bad})
        assert not r.is_valid
        assert "color" in r.errors
