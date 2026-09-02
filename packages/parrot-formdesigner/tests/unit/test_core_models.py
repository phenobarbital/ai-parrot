"""Unit tests for parrot-formdesigner core models (TASK-548, TASK-1033, TASK-1972)."""

import uuid
from datetime import datetime, timezone

import pytest

from parrot_formdesigner.core import FormSchema, FormField, FieldType, FormSection
from parrot_formdesigner.core.style import FormStyle, StyleSchema
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.options import FieldOption


@pytest.fixture
def sample_form_schema() -> FormSchema:
    """Create a sample FormSchema for testing."""
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


class TestFormSchema:
    """Tests for the FormSchema model."""

    def test_initialization(self, sample_form_schema: FormSchema) -> None:
        """FormSchema should initialize with correct form_id and sections."""
        assert sample_form_schema.form_id == "test-form"
        assert len(sample_form_schema.sections) == 1

    def test_field_access(self, sample_form_schema: FormSchema) -> None:
        """Fields should be accessible through sections."""
        fields = sample_form_schema.sections[0].fields
        assert len(fields) == 2

    def test_field_types(self, sample_form_schema: FormSchema) -> None:
        """Field types should be correctly assigned."""
        fields = sample_form_schema.sections[0].fields
        assert fields[0].field_type == FieldType.TEXT
        assert fields[1].field_type == FieldType.EMAIL

    def test_style_default(self) -> None:
        """FormStyle should have defaults and be instantiable without arguments."""
        style = FormStyle()
        assert style is not None

    def test_style_schema_default(self) -> None:
        """StyleSchema should have defaults and be instantiable without arguments."""
        style = StyleSchema()
        assert style is not None

    def test_field_constraints(self) -> None:
        """FieldConstraints should be instantiable with defaults."""
        constraints = FieldConstraints()
        assert constraints is not None
        assert constraints.min_length is None
        assert constraints.max_length is None

    def test_field_option(self) -> None:
        """FieldOption should store value and label."""
        option = FieldOption(value="opt1", label="Option 1")
        assert option.value == "opt1"
        assert option.label == "Option 1"
        assert option.disabled is False

    def test_field_type_enum_values(self) -> None:
        """FieldType enum should contain expected values."""
        assert FieldType.TEXT == "text"
        assert FieldType.EMAIL == "email"
        assert FieldType.SELECT == "select"
        assert FieldType.BOOLEAN == "boolean"


class TestFormSchemaFormUid:
    """Tests for FormSchema.form_uid (FEAT-389 / TASK-1972)."""

    def test_auto_generated(self) -> None:
        """form_uid should be auto-generated as a valid UUID4 string."""
        form = FormSchema(
            form_id="test",
            title="Test",
            sections=[FormSection(section_id="s1", title="S1", fields=[])],
        )
        assert form.form_uid is not None
        assert isinstance(form.form_uid, uuid.UUID)  # already a validated UUID

    def test_explicit_uid_respected(self) -> None:
        """An explicitly provided form_uid should be respected, not overridden."""
        uid = str(uuid.uuid4())
        form = FormSchema(
            form_uid=uid,
            form_id="test",
            title="Test",
            sections=[FormSection(section_id="s1", title="S1", fields=[])],
        )
        assert form.form_uid == uuid.UUID(uid)

    def test_unique_per_instance(self) -> None:
        """Each FormSchema instance should get a distinct form_uid."""
        f1 = FormSchema(form_id="a", title="A", sections=[])
        f2 = FormSchema(form_id="b", title="B", sections=[])
        assert f1.form_uid != f2.form_uid

    def test_included_in_dump(self) -> None:
        """form_uid should be present in model_dump() output."""
        form = FormSchema(form_id="t", title="T", sections=[])
        data = form.model_dump()
        assert "form_uid" in data

    def test_form_uid_immutable_on_rename(self) -> None:
        """Changing form_id should not change form_uid."""
        form = FormSchema(form_id="original-slug", title="T", sections=[])
        original_uid = form.form_uid
        form.form_id = "renamed-slug"
        assert form.form_uid == original_uid

    def test_form_schema_created_at_optional(self) -> None:
        """FormSchema without created_at parses correctly with created_at=None."""
        f = FormSchema(form_id="x", title="t", sections=[])
        assert f.created_at is None

    def test_form_schema_created_at_serializes_iso(self) -> None:
        """FormSchema with a tz-aware datetime serializes created_at as ISO-8601."""
        ts = datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc)
        f = FormSchema(form_id="x", title="t", sections=[], created_at=ts)
        js = f.model_dump_json()
        # Pydantic v2 may emit "Z" or "+00:00" suffix — both are valid ISO-8601.
        assert '"created_at":"2026-04-12T10:31:00' in js
        assert "created_at" in js
        f2 = FormSchema.model_validate_json(js)
        assert f2.created_at == ts


# TASK-1149: OptionsSource extensions tests
from parrot_formdesigner.core.options import OptionsSource


def test_options_source_http_method_default_get() -> None:
    """New OptionsSource defaults http_method to GET."""
    src = OptionsSource(source_type="endpoint", source_ref="https://api.test/users")
    assert src.http_method == "GET"


def test_options_source_auth_ref_optional() -> None:
    """auth_ref is optional; legacy schemas without it deserialize unchanged."""
    src = OptionsSource(source_type="endpoint", source_ref="https://api.test/users")
    assert src.auth_ref is None


def test_options_source_with_post_and_auth() -> None:
    """OptionsSource accepts POST method and auth_ref."""
    src = OptionsSource(
        source_type="endpoint",
        source_ref="https://api.test/users",
        http_method="POST",
        auth_ref="MY_API_KEY",
    )
    assert src.http_method == "POST"
    assert src.auth_ref == "MY_API_KEY"


def test_options_source_value_label_field_names_unchanged() -> None:
    """value_field and label_field names are preserved."""
    src = OptionsSource(
        source_type="endpoint",
        source_ref="https://api.test/users",
        value_field="id",
        label_field="full_name",
    )
    assert src.value_field == "id"
    assert src.label_field == "full_name"


# TASK-1148: FieldConstraints scale fields tests
from pydantic import ValidationError


def test_field_constraints_scale_validator_rejects_inverted_range() -> None:
    """scale_max < scale_min raises ValidationError."""
    with pytest.raises(ValidationError, match="scale_max"):
        FieldConstraints(scale_min=5, scale_max=3)


def test_field_constraints_scale_equal_raises() -> None:
    """scale_max == scale_min raises ValidationError."""
    with pytest.raises(ValidationError):
        FieldConstraints(scale_min=5, scale_max=5)


def test_field_constraints_anchor_labels_in_bounds() -> None:
    """Anchor label keys outside [scale_min, scale_max] raise."""
    with pytest.raises(ValidationError, match="anchor_labels"):
        FieldConstraints(scale_min=0, scale_max=10, anchor_labels={11: "Extreme"})


def test_field_constraints_anchor_labels_valid() -> None:
    """Anchor labels within bounds are accepted."""
    fc = FieldConstraints(
        scale_min=0, scale_max=10,
        anchor_labels={0: "Not at all", 5: "Neutral", 10: "Extremely likely"}
    )
    assert len(fc.anchor_labels) == 3


def test_field_constraints_scale_none_is_ok() -> None:
    """scale_* fields default to None — existing usage unchanged."""
    fc = FieldConstraints()
    assert fc.scale_min is None
    assert fc.scale_max is None


# TASK-1147: New FieldType enum values tests
from parrot_formdesigner.core.types import FieldType


def test_field_type_enum_has_new_values() -> None:
    """All 10 new FieldType values are present with stable string aliases."""
    new_types = {
        FieldType.SIGNATURE: "signature",
        FieldType.DYNAMIC_SELECT: "dynamic_select",
        FieldType.TRANSFER_LIST: "transfer_list",
        FieldType.REMOTE_RESPONSE: "remote_response",
        FieldType.AVAILABILITY: "availability",
        FieldType.LOCATION: "location",
        FieldType.TAGS: "tags",
        FieldType.NPS: "nps",
        FieldType.LIKERT: "likert",
        FieldType.RANKING: "ranking",
    }
    for ft, expected_value in new_types.items():
        assert ft.value == expected_value, f"{ft} has wrong value"
        assert FieldType(expected_value) == ft, f"String alias broken for {expected_value}"


def test_field_type_enum_total_count() -> None:
    """FieldType now has exactly 32 values (20 existing + 10 FEAT-167 + 1 FEAT-170 REST + 1 FEAT-300 FORMULA)."""
    assert len(FieldType) == 32


def test_field_type_existing_values_unchanged() -> None:
    """All original 20 FieldType values are unchanged."""
    assert FieldType.TEXT.value == "text"
    assert FieldType.ARRAY.value == "array"
    assert FieldType.GROUP.value == "group"


# TASK-1146: RenderWarning and RenderedForm.warnings tests
from parrot_formdesigner.core.schema import RenderedForm, RenderWarning


def test_rendered_form_warnings_default_empty() -> None:
    """RenderedForm defaults warnings to empty list."""
    rf = RenderedForm(content="<form/>", content_type="text/html")
    assert rf.warnings == []


def test_render_warning_model() -> None:
    """RenderWarning has all required fields."""
    w = RenderWarning(
        field_id="sig1",
        field_type="signature",
        renderer="pdf",
        reason="unsupported in PDF — rendered as placeholder",
    )
    assert w.field_id == "sig1"
    assert w.renderer == "pdf"


def test_rendered_form_with_warnings() -> None:
    """RenderedForm accepts and stores warnings."""
    w = RenderWarning(field_id="f1", field_type="nps", renderer="xforms", reason="fallback")
    rf = RenderedForm(content={}, content_type="application/json", warnings=[w])
    assert len(rf.warnings) == 1
    assert rf.warnings[0].field_type == "nps"


# --- TASK-1154: pycountry / LOCATION reference data tests ---

def test_pycountry_dependency_resolves_es() -> None:
    """Wrapper returns ISO-2 ES → name Spain, flag 🇪🇸, dial code +34."""
    pytest.importorskip("pycountry")
    from parrot_formdesigner.core._location_data import get_country_info, is_valid_iso_country_code

    info = get_country_info("ES")
    assert info is not None
    assert info["name"] == "Spain"
    assert info["flag"] == "\U0001F1EA\U0001F1F8"  # 🇪🇸
    assert info["dial_code"] == "+34"
    assert is_valid_iso_country_code("ES") is True


def test_location_rejects_unknown_code() -> None:
    """is_valid_iso_country_code('XX') returns False."""
    pytest.importorskip("pycountry")
    from parrot_formdesigner.core._location_data import is_valid_iso_country_code

    assert is_valid_iso_country_code("XX") is False


def test_list_country_options_has_entries() -> None:
    """list_country_options returns a non-empty list of FieldOption."""
    pytest.importorskip("pycountry")
    from parrot_formdesigner.core._location_data import list_country_options

    options = list_country_options()
    assert len(options) >= 200
    values = {o.value for o in options}
    assert "ES" in values
    assert "US" in values
    assert "VE" in values


def test_location_data_importable_without_pycountry(monkeypatch) -> None:
    """_location_data degrades gracefully when pycountry is not installed."""
    import sys
    import importlib

    # Simulate pycountry absent
    monkeypatch.setitem(sys.modules, "pycountry", None)
    sys.modules.pop("parrot_formdesigner.core._location_data", None)
    try:
        mod = importlib.import_module("parrot_formdesigner.core._location_data")
        # is_valid should return True (skip validation)
        assert mod.is_valid_iso_country_code("US") is True
        # get_country_info should return None
        assert mod.get_country_info("US") is None
        # list_country_options should return []
        assert mod.list_country_options() == []
    finally:
        sys.modules.pop("parrot_formdesigner.core._location_data", None)
        monkeypatch.delitem(sys.modules, "pycountry", raising=False)


# ---------------------------------------------------------------------------
# FEAT-488: FormField content_type and accept_content_types
# ---------------------------------------------------------------------------

from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope


class TestFormFieldContentType:
    """Tests for FormField.content_type and accept_content_types (FEAT-488)."""

    def test_content_type_defaults_none(self) -> None:
        """content_type defaults to None for backward compatibility."""
        field = FormField(field_id="f1", field_type=FieldType.TEXT_AREA, label="F1")
        assert field.content_type is None

    def test_accept_content_types_defaults_none(self) -> None:
        """accept_content_types defaults to None for backward compatibility."""
        field = FormField(field_id="f1", field_type=FieldType.TEXT_AREA, label="F1")
        assert field.accept_content_types is None

    def test_content_type_set(self) -> None:
        """content_type can be set and round-trips correctly."""
        field = FormField(
            field_id="f1",
            field_type=FieldType.TEXT_AREA,
            label="F1",
            content_type="text/markdown",
        )
        assert field.content_type == "text/markdown"
        # Verify round-trip through JSON
        json_str = field.model_dump_json()
        assert '"content_type":"text/markdown"' in json_str
        field2 = FormField.model_validate_json(json_str)
        assert field2.content_type == "text/markdown"

    def test_accept_content_types_set(self) -> None:
        """accept_content_types can be set and round-trips correctly."""
        field = FormField(
            field_id="f1",
            field_type=FieldType.TEXT_AREA,
            label="F1",
            accept_content_types=["text/plain", "application/json"],
        )
        assert field.accept_content_types == ["text/plain", "application/json"]
        # Verify round-trip through JSON
        json_str = field.model_dump_json()
        assert '"accept_content_types":["text/plain","application/json"]' in json_str
        field2 = FormField.model_validate_json(json_str)
        assert field2.accept_content_types == ["text/plain", "application/json"]

    def test_both_content_type_and_accept_content_types(self) -> None:
        """Both fields can be set together."""
        field = FormField(
            field_id="voice",
            field_type=FieldType.TEXT_AREA,
            label="Voice note",
            content_type="text/plain",
            accept_content_types=["text/plain", "application/json"],
        )
        assert field.content_type == "text/plain"
        assert field.accept_content_types == ["text/plain", "application/json"]


class TestVoiceAnswerEnvelope:
    """Tests for VoiceAnswerEnvelope model (FEAT-488 Module 1)."""

    def test_required_answer(self) -> None:
        """answer is required."""
        env = VoiceAnswerEnvelope(answer="I agree with the terms.")
        assert env.answer == "I agree with the terms."

    def test_optional_blob_ref(self) -> None:
        """blob_ref defaults to None."""
        env = VoiceAnswerEnvelope(answer="Test")
        assert env.blob_ref is None

    def test_optional_data_url(self) -> None:
        """data_url defaults to None."""
        env = VoiceAnswerEnvelope(answer="Test")
        assert env.data_url is None

    def test_full_envelope(self) -> None:
        """Full envelope with all fields."""
        env = VoiceAnswerEnvelope(
            answer="I agree with the terms.",
            blob_ref="s3://bucket/voice-notes/abc123.wav",
            data_url=None,
        )
        assert env.answer == "I agree with the terms."
        assert env.blob_ref == "s3://bucket/voice-notes/abc123.wav"
        assert env.data_url is None

    def test_extra_forbid(self) -> None:
        """extra='forbid' rejects unknown fields."""
        with pytest.raises(ValidationError):
            VoiceAnswerEnvelope(answer="test", unknown_field="bad")

    def test_roundtrip_json(self) -> None:
        """Envelope round-trips through JSON serialization."""
        original = VoiceAnswerEnvelope(
            answer="Test answer",
            blob_ref="s3://bucket/key.wav",
            data_url="data:audio/wav;base64,ABC==",
        )
        json_str = original.model_dump_json()
        restored = VoiceAnswerEnvelope.model_validate_json(json_str)
        assert restored.answer == original.answer
        assert restored.blob_ref == original.blob_ref
        assert restored.data_url == original.data_url