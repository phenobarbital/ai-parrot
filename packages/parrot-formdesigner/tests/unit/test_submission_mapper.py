"""Unit tests for `parrot_formdesigner.services.sinks.mapper` (FEAT-457, TASK-2420)."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.core.schema import (
    FormField,
    FormMetadataField,
    FormSchema,
    FormSection,
    FormSubsection,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sinks.mapper import (
    RESERVED_COLUMNS,
    column_names_for,
    field_types_for,
    flatten_submission,
    nest_submission,
)
from parrot_formdesigner.services.submissions import FormSubmission


def _submission(
    data: dict,
    form_uid: uuid.UUID | None = None,
    *,
    extra_data: dict | None = None,
) -> FormSubmission:
    return FormSubmission(
        form_uid=form_uid or uuid.uuid4(),
        form_id="test-form",
        form_version="1.0",
        data=data,
        is_valid=True,
        created_at=datetime.now(UTC),
        extra_data=extra_data,
    )


@pytest.fixture
def form_with_group():
    address_group = FormField(
        field_id="address",
        field_type=FieldType.GROUP,
        label="Address",
        children=[
            FormField(field_id="city", field_type=FieldType.TEXT, label="City"),
            FormField(field_id="zip", field_type=FieldType.TEXT, label="Zip"),
        ],
    )
    section = FormSection(section_id="s1", fields=[address_group])
    return FormSchema(form_id="f1", title="Form 1", sections=[section])


@pytest.fixture
def submission(form_with_group):
    return _submission(
        {"address": {"city": "Tampa", "zip": "33602"}},
        form_uid=form_with_group.form_uid,
    )


@pytest.fixture
def form_with_array():
    answers = FormField(
        field_id="answers",
        field_type=FieldType.ARRAY,
        label="Answers",
        item_template=FormField(field_id="q", field_type=FieldType.NUMBER, label="Q"),
    )
    section = FormSection(section_id="s1", fields=[answers])
    return FormSchema(form_id="f2", title="Form 2", sections=[section])


@pytest.fixture
def submission_with_array(form_with_array):
    return _submission({"answers": [{"q": 1}, {"q": 2}]}, form_uid=form_with_array.form_uid)


@pytest.fixture
def form_with_metadata():
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    section = FormSection(section_id="s1", fields=[field])
    return FormSchema(
        form_id="f3",
        title="Form 3",
        sections=[section],
        metadata=[FormMetadataField(key="campaign_id", source="constant", default="fall-2026")],
    )


@pytest.fixture
def form_with_deep_group():
    # Build a GROUP path deep enough that the flattened leaf name exceeds
    # 63 characters.
    leaf = FormField(field_id="z" * 20, field_type=FieldType.TEXT, label="Z")
    inner = FormField(field_id="y" * 20, field_type=FieldType.GROUP, label="Y", children=[leaf])
    outer = FormField(field_id="x" * 20, field_type=FieldType.GROUP, label="X", children=[inner])
    section = FormSection(section_id="s1", fields=[outer])
    return FormSchema(form_id="f4", title="Form 4", sections=[section])


@pytest.fixture
def form_with_subsection():
    field = FormField(field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes")
    subsection = FormSubsection(subsection_id="sub1", fields=[field])
    section = FormSection(section_id="s1", fields=[subsection])
    return FormSchema(form_id="f5", title="Form 5", sections=[section])


class TestFlatten:
    def test_group_flattens_by_path(self, form_with_group, submission):
        row = flatten_submission(form_with_group, submission)
        assert "address__city" in row
        assert row["address__city"] == "Tampa"

    def test_array_is_single_json_column(self, form_with_array, submission_with_array):
        row = flatten_submission(form_with_array, submission_with_array)
        assert isinstance(row["answers"], str)
        assert json.loads(row["answers"]) == [{"q": 1}, {"q": 2}]

    def test_metadata_promoted(self, form_with_metadata):
        submission = _submission(
            {"name": "Alice", "campaign_id": "fall-2026"},
            form_uid=form_with_metadata.form_uid,
        )
        assert "campaign_id" in flatten_submission(form_with_metadata, submission)

    def test_reserved_always_present(self, form_with_group, submission):
        row = flatten_submission(form_with_group, submission)
        assert RESERVED_COLUMNS <= set(row)

    def test_long_path_raises(self, form_with_deep_group):
        submission = _submission({}, form_uid=form_with_deep_group.form_uid)
        with pytest.raises(ValueError):
            flatten_submission(form_with_deep_group, submission)

    def test_subsection_is_walked(self, form_with_subsection):
        submission = _submission({"notes": "hello"}, form_uid=form_with_subsection.form_uid)
        assert "notes" in flatten_submission(form_with_subsection, submission)


class TestNest:
    def test_data_stays_nested(self, form_with_group, submission):
        doc = nest_submission(form_with_group, submission)
        assert doc["data"] == submission.data
        assert "address__city" not in doc

    def test_does_not_mutate(self, form_with_group, submission):
        before = dict(submission.data)
        nest_submission(form_with_group, submission)
        assert submission.data == before


class TestColumnNames:
    def test_deterministic(self, form_with_group):
        assert column_names_for(form_with_group) == column_names_for(form_with_group)

    def test_reserved_come_first(self, form_with_group):
        names = column_names_for(form_with_group)
        assert set(names[: len(RESERVED_COLUMNS)]) == RESERVED_COLUMNS


class TestFieldTypesFor:
    def test_matches_flattened_columns(self, form_with_group):
        types = field_types_for(form_with_group)
        assert "address__city" in types
        assert types["address__city"] == FieldType.TEXT

    def test_array_field_type_reported(self, form_with_array):
        types = field_types_for(form_with_array)
        assert types["answers"] == FieldType.ARRAY

    def test_excludes_reserved_and_metadata_columns(self, form_with_metadata):
        types = field_types_for(form_with_metadata)
        assert "campaign_id" not in types  # metadata key, not a form field
        assert "submission_id" not in types  # reserved column
        assert "name" in types


# ---------------------------------------------------------------------------
# FEAT-458 — extra_data reserved column (TASK-2438)
# ---------------------------------------------------------------------------


def test_reserved_columns_includes_extra_data():
    assert "extra_data" in RESERVED_COLUMNS


class TestFlattenExtraData:
    def test_emits_json_column(self, form_with_group):
        submission = _submission({}, form_uid=form_with_group.form_uid, extra_data={"legacy_id": 42})
        row = flatten_submission(form_with_group, submission)
        assert row["extra_data"] == json.dumps({"legacy_id": 42})

    def test_none_stays_none(self, form_with_group):
        submission = _submission({}, form_uid=form_with_group.form_uid, extra_data=None)
        row = flatten_submission(form_with_group, submission)
        assert row["extra_data"] is None

    def test_none_is_not_the_string_null(self, form_with_group):
        submission = _submission({}, form_uid=form_with_group.form_uid, extra_data=None)
        row = flatten_submission(form_with_group, submission)
        assert row["extra_data"] != "null"


class TestNestExtraData:
    def test_included_as_object(self, form_with_group):
        submission = _submission({}, form_uid=form_with_group.form_uid, extra_data={"legacy_id": 42})
        doc = nest_submission(form_with_group, submission)
        assert doc["extra_data"] == {"legacy_id": 42}

    def test_not_stringified(self, form_with_group):
        submission = _submission({}, form_uid=form_with_group.form_uid, extra_data={"a": 1})
        doc = nest_submission(form_with_group, submission)
        assert not isinstance(doc["extra_data"], str)

    def test_none_stays_none(self, form_with_group):
        submission = _submission({}, form_uid=form_with_group.form_uid, extra_data=None)
        doc = nest_submission(form_with_group, submission)
        assert doc["extra_data"] is None


def test_column_names_for_includes_extra_data(form_with_group):
    assert "extra_data" in column_names_for(form_with_group)


class TestFieldIdCollision:
    """Spec AC15 — a field_id (or metadata key) named "extra_data" collides
    with the reserved column at authoring time, for a tabular target."""

    @pytest.fixture
    def form_dict_with_persistence(self):
        return {
            "form_id": "f1",
            "title": "Form 1",
            "sections": [
                {
                    "section_id": "s1",
                    "fields": [
                        {"field_id": "extra_data", "field_type": "text", "label": "Extra Data"},
                    ],
                }
            ],
            "persistence": {
                "data": {
                    "type": "postgres_table",
                    "connection": "survey_db",
                    "schema_name": "surveys",
                    "table": "nps_2026",
                }
            },
        }

    def test_field_id_named_extra_data_rejected(self, form_dict_with_persistence):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="extra_data"):
            FormSchema.model_validate(form_dict_with_persistence)
