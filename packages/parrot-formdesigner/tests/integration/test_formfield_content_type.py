"""Integration tests for FEAT-488 (FormField Content-Type) — spec §4
"Integration Tests".

These two tests exercise the feature end to end rather than at the
individual-module level already covered by the unit tests in
``tests/unit/test_core_models.py``, ``tests/unit/services/
test_validators_rest.py``, ``tests/unit/test_renderers.py``,
``tests/unit/renderers/test_xforms.py``, and
``tests/formdesigner/test_audio_form_renderer.py``:

1. A persisted, pre-FEAT-488 ``FormSchema`` JSON payload (no
   ``content_type`` / ``accept_content_types`` keys at all) still
   deserializes without error — backward compatibility.
2. A full ``FormValidator.validate()`` submission carrying a dict answer
   for a field that declares ``accept_content_types=["application/json"]``
   passes that dict through to ``sanitized_data`` untouched, rather than
   being stringified by ``_coerce_value``.
"""

from __future__ import annotations

import json

import pytest
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator

pytestmark = pytest.mark.asyncio


async def test_backward_compatible_schema_deserialization():
    """Existing FormSchema JSON with no content_type deserializes without
    error, and the new fields default to None."""
    raw = json.dumps(
        {
            "form_id": "legacy-form",
            "title": "Test",
            "sections": [
                {
                    "section_id": "s1",
                    "title": "Section",
                    "fields": [
                        {
                            "field_id": "q1",
                            "field_type": "text_area",
                            "label": "Question",
                        }
                    ],
                }
            ],
        }
    )
    schema = FormSchema.model_validate_json(raw)
    assert schema.sections[0].fields[0].content_type is None
    assert schema.sections[0].fields[0].accept_content_types is None


async def test_voice_answer_submission_passthrough():
    """FormValidator.validate() passes a dict answer through to
    sanitized_data unchanged for a TEXT_AREA field that declares
    accept_content_types=["application/json"], rather than coercing it to
    a stringified dict."""
    field = FormField(
        field_id="voice_answer",
        field_type=FieldType.TEXT_AREA,
        label="Voice Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    form = FormSchema(
        form_id="voice-form",
        title="Voice Form",
        sections=[FormSection(section_id="s1", fields=[field])],
    )
    payload = {"answer": "I agree.", "confidence": 0.94}

    validator = FormValidator()
    result = await validator.validate(form, {"voice_answer": payload})

    assert result.is_valid is True, result.errors
    assert result.sanitized_data["voice_answer"] == payload
    assert isinstance(result.sanitized_data["voice_answer"], dict)
