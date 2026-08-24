"""Unit tests for FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality."""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.file_envelope import (
    FileEnvelope,
    UPLOAD_FIELD_TYPES,
    is_single_cardinality,
)
from parrot_formdesigner.core.types import FieldType


class TestFileEnvelope:
    def test_required_fields(self):
        env = FileEnvelope(filename="report.pdf", content_type="application/pdf", size=1024)
        assert env.filename == "report.pdf"
        assert env.content_type == "application/pdf"
        assert env.size == 1024

    def test_optional_fields_default_none(self):
        env = FileEnvelope(filename="x.txt", content_type="text/plain", size=0)
        assert env.blob_ref is None
        assert env.data_url is None
        assert env.thumbnail_url is None
        assert env.checksum is None

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            FileEnvelope(filename="x", content_type="text/plain", size=0, unknown="bad")

    def test_size_ge_zero(self):
        with pytest.raises(ValidationError):
            FileEnvelope(filename="x", content_type="text/plain", size=-1)

    def test_full_envelope(self):
        env = FileEnvelope(
            filename="photo.jpg", content_type="image/jpeg", size=45000,
            blob_ref="s3://bucket/key", data_url="data:image/jpeg;base64,/9j/...",
            thumbnail_url="/thumb/abc", checksum="sha256:abc123",
        )
        assert env.blob_ref == "s3://bucket/key"


class TestUploadFieldTypes:
    def test_contains_exactly_four(self):
        assert UPLOAD_FIELD_TYPES == frozenset({
            FieldType.FILE, FieldType.IMAGE,
            FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD,
        })

    def test_is_frozenset(self):
        assert isinstance(UPLOAD_FIELD_TYPES, frozenset)


class TestIsSingleCardinality:
    @pytest.mark.parametrize("ft", [FieldType.FILE, FieldType.IMAGE])
    def test_single(self, ft):
        assert is_single_cardinality(ft) is True

    @pytest.mark.parametrize("ft", [FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD])
    def test_multi(self, ft):
        assert is_single_cardinality(ft) is False
