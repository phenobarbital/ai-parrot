"""Unit tests for FieldConstraints.max_inline_size_bytes (FEAT-460)."""

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.constraints import (
    FieldConstraints,
    DEFAULT_MAX_INLINE_SIZE,
)


class TestMaxInlineSizeBytes:
    def test_default_is_none(self):
        c = FieldConstraints()
        assert c.max_inline_size_bytes is None

    def test_accepts_valid_value(self):
        c = FieldConstraints(max_inline_size_bytes=5_242_880)
        assert c.max_inline_size_bytes == 5_242_880

    def test_accepts_zero(self):
        c = FieldConstraints(max_inline_size_bytes=0)
        assert c.max_inline_size_bytes == 0

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            FieldConstraints(max_inline_size_bytes=-1)

    def test_default_constant_value(self):
        assert DEFAULT_MAX_INLINE_SIZE == 10_485_760

    def test_existing_constraints_unaffected(self):
        c = FieldConstraints(
            allowed_mime_types=["image/png"],
            max_file_size_bytes=1024,
            max_inline_size_bytes=2048,
        )
        assert c.allowed_mime_types == ["image/png"]
        assert c.max_file_size_bytes == 1024
        assert c.max_inline_size_bytes == 2048
