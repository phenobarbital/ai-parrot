"""Unit tests for `FormSchema.persistence` and its validation (FEAT-457, TASK-2421)."""

import pytest
from parrot_formdesigner.core.schema import FormSchema
from pydantic import ValidationError


@pytest.fixture
def minimal_form_dict():
    return {
        "form_id": "f1",
        "title": "Form 1",
        "sections": [
            {
                "section_id": "s1",
                "fields": [
                    {"field_id": "name", "field_type": "text", "label": "Name"},
                ],
            }
        ],
    }


@pytest.fixture
def form_dict_with_persistence(minimal_form_dict):
    minimal_form_dict["persistence"] = {
        "data": {
            "type": "postgres_table",
            "connection": "survey_db",
            "schema_name": "surveys",
            "table": "nps_2026",
        }
    }
    return minimal_form_dict


@pytest.fixture
def form_dict_with_mongo_persistence(minimal_form_dict):
    minimal_form_dict["persistence"] = {
        "data": {
            "type": "asyncdb",
            "connection": "mongo_alias",
            "driver": "mongo",
            "collection": "responses",
        }
    }
    return minimal_form_dict


class TestFormSchemaPersistence:
    def test_absent_defaults_to_none(self, minimal_form_dict):
        assert FormSchema.model_validate(minimal_form_dict).persistence is None

    def test_roundtrip_with_persistence(self, form_dict_with_persistence):
        form = FormSchema.model_validate(form_dict_with_persistence)
        assert FormSchema.model_validate_json(form.model_dump_json()) == form

    def test_reserved_field_id_rejected(self, form_dict_with_persistence):
        form_dict_with_persistence["sections"][0]["fields"][0]["field_id"] = (
            "submission_id"
        )
        with pytest.raises(ValidationError):
            FormSchema.model_validate(form_dict_with_persistence)

    def test_reserved_metadata_key_rejected(self, form_dict_with_persistence):
        form_dict_with_persistence["metadata"] = [
            {"key": "form_uid", "source": "constant"}
        ]
        with pytest.raises(ValidationError):
            FormSchema.model_validate(form_dict_with_persistence)

    def test_document_target_skips_column_checks(
        self, form_dict_with_mongo_persistence
    ):
        form_dict_with_mongo_persistence["sections"][0]["fields"][0]["field_id"] = (
            "submission_id"
        )
        assert FormSchema.model_validate(form_dict_with_mongo_persistence) is not None

    def test_no_persistence_no_reserved_check(self, minimal_form_dict):
        # Without persistence, a field_id named "submission_id" is fine —
        # exercises the reserved-column check being fully gated on
        # `persistence is not None`.
        minimal_form_dict["sections"][0]["fields"][0]["field_id"] = "submission_id"
        assert FormSchema.model_validate(minimal_form_dict) is not None

    def test_group_path_too_long_rejected(self, minimal_form_dict):
        minimal_form_dict["sections"][0]["fields"] = [
            {
                "field_id": "x" * 20,
                "field_type": "group",
                "label": "X",
                "children": [
                    {
                        "field_id": "y" * 20,
                        "field_type": "group",
                        "label": "Y",
                        "children": [
                            {
                                "field_id": "z" * 20,
                                "field_type": "text",
                                "label": "Z",
                            }
                        ],
                    }
                ],
            }
        ]
        minimal_form_dict["persistence"] = {
            "data": {
                "type": "postgres_table",
                "connection": "survey_db",
                "schema_name": "surveys",
                "table": "nps_2026",
            }
        }
        with pytest.raises(ValidationError):
            FormSchema.model_validate(minimal_form_dict)

    def test_bigquery_driver_is_tabular_and_checked(self, minimal_form_dict):
        minimal_form_dict["sections"][0]["fields"][0]["field_id"] = "submission_id"
        minimal_form_dict["persistence"] = {
            "data": {
                "type": "asyncdb",
                "connection": "bq_alias",
                "driver": "bigquery",
                "collection": "responses",
            }
        }
        with pytest.raises(ValidationError):
            FormSchema.model_validate(minimal_form_dict)
