"""Unit tests for the validator's dual-read FileEnvelope coercer (FEAT-460)."""

import pytest

from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


@pytest.fixture
def validator() -> FormValidator:
    return FormValidator()


def _field(field_type: FieldType) -> FormField:
    return FormField(field_id="upload", field_type=field_type, label={"en": "Upload"})


class TestCoerceFileLegacy:
    @pytest.mark.asyncio
    async def test_string_value_accepted(self, validator: FormValidator):
        """Legacy string value for FILE passes through unchanged."""
        errors = await validator.validate_field(_field(FieldType.FILE), "https://example.com/a.pdf")
        assert errors == []

    @pytest.mark.asyncio
    async def test_envelope_dict_accepted(self, validator: FormValidator):
        """FileEnvelope dict for FILE is validated and accepted."""
        envelope = {
            "filename": "report.pdf", "content_type": "application/pdf", "size": 1024,
            "blob_ref": "temp://x", "data_url": None, "thumbnail_url": None, "checksum": None,
        }
        errors = await validator.validate_field(_field(FieldType.FILE), envelope)
        assert errors == []


class TestCoerceImageLegacy:
    @pytest.mark.asyncio
    async def test_string_value_accepted(self, validator: FormValidator):
        """Legacy string value for IMAGE passes through unchanged."""
        errors = await validator.validate_field(_field(FieldType.IMAGE), "data:image/png;base64,AA==")
        assert errors == []

    @pytest.mark.asyncio
    async def test_envelope_dict_accepted(self, validator: FormValidator):
        """FileEnvelope dict for IMAGE is validated and accepted."""
        envelope = {
            "filename": "photo.jpg", "content_type": "image/jpeg", "size": 45000,
            "blob_ref": "temp://y", "data_url": None, "thumbnail_url": None, "checksum": None,
        }
        errors = await validator.validate_field(_field(FieldType.IMAGE), envelope)
        assert errors == []


class TestCoerceDropzoneLegacy:
    @pytest.mark.asyncio
    async def test_legacy_shape_mapped(self, validator: FormValidator):
        """Legacy {name,type,size,dataUrl} mapped to FileEnvelope fields."""
        legacy = {"name": "photo.jpg", "type": "image/jpeg", "size": 45000, "dataUrl": "data:image/jpeg;base64,AA=="}
        result = await validator.validate(
            _one_field_form(FieldType.IMAGE_DROPZONE), {"upload": legacy}
        )
        assert result.is_valid, result.errors
        sanitized = result.sanitized_data["upload"]
        assert sanitized["filename"] == "photo.jpg"
        assert sanitized["content_type"] == "image/jpeg"
        assert sanitized["size"] == 45000
        assert sanitized["data_url"] == "data:image/jpeg;base64,AA=="
        assert sanitized["blob_ref"] is None

    @pytest.mark.asyncio
    async def test_envelope_dict_accepted(self, validator: FormValidator):
        """FileEnvelope dict for IMAGE_DROPZONE accepted directly."""
        envelope = {
            "filename": "photo.jpg", "content_type": "image/jpeg", "size": 45000,
            "blob_ref": "temp://z", "data_url": None, "thumbnail_url": None, "checksum": None,
        }
        errors = await validator.validate_field(_field(FieldType.IMAGE_DROPZONE), envelope)
        assert errors == []

    @pytest.mark.asyncio
    async def test_incomplete_legacy_still_errors(self, validator: FormValidator):
        """Incomplete legacy dropzone dict still reports missing keys (no regression)."""
        errors = await validator.validate_field(_field(FieldType.IMAGE_DROPZONE), {"name": "x"})
        assert errors


class TestCoerceMultiUploadLegacy:
    @pytest.mark.asyncio
    async def test_legacy_list_mapped(self, validator: FormValidator):
        """Legacy [{answer,blob_ref,display}] mapped to FileEnvelopes."""
        legacy = [{"answer": "result", "blob_ref": "s3://bucket/key", "display": "photo.jpg"}]
        result = await validator.validate(
            _one_field_form(FieldType.MULTI_UPLOAD), {"upload": legacy}
        )
        assert result.is_valid, result.errors
        sanitized = result.sanitized_data["upload"][0]
        assert sanitized["filename"] == "photo.jpg"
        assert sanitized["blob_ref"] == "s3://bucket/key"
        assert sanitized["content_type"] == "application/octet-stream"
        assert sanitized["size"] == 0

    @pytest.mark.asyncio
    async def test_envelope_list_accepted(self, validator: FormValidator):
        """List of FileEnvelope dicts accepted directly."""
        envelope = [{
            "filename": "a.jpg", "content_type": "image/jpeg", "size": 100,
            "blob_ref": "temp://a", "data_url": None, "thumbnail_url": None, "checksum": None,
        }]
        errors = await validator.validate_field(_field(FieldType.MULTI_UPLOAD), envelope)
        assert errors == []

    @pytest.mark.asyncio
    async def test_incomplete_legacy_still_errors(self, validator: FormValidator):
        """Incomplete legacy multi-upload item still reports missing keys (no regression)."""
        errors = await validator.validate_field(_field(FieldType.MULTI_UPLOAD), [{"answer": "a1"}])
        assert errors


class TestValidateEnvelope:
    @pytest.mark.asyncio
    async def test_missing_filename_error(self, validator: FormValidator):
        """FileEnvelope dict without 'filename' → validation error."""
        envelope = {"content_type": "application/pdf", "size": 1024}
        errors = await validator.validate_field(_field(FieldType.FILE), envelope)
        assert errors

    @pytest.mark.asyncio
    async def test_missing_content_type_error(self, validator: FormValidator):
        """FileEnvelope dict without 'content_type' → validation error."""
        envelope = {"filename": "a.pdf", "size": 1024}
        errors = await validator.validate_field(_field(FieldType.IMAGE), envelope)
        assert errors

    @pytest.mark.asyncio
    async def test_missing_size_error(self, validator: FormValidator):
        """FileEnvelope dict without 'size' → validation error."""
        envelope = {"filename": "a.pdf", "content_type": "application/pdf"}
        errors = await validator.validate_field(_field(FieldType.FILE), envelope)
        assert errors


def _one_field_form(field_type: FieldType):
    from parrot_formdesigner.core.schema import FormSchema, FormSection

    return FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[FormSection(section_id="s", fields=[_field(field_type)])],
    )
