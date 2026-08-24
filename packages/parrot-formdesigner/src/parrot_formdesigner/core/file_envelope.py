"""Canonical value shape for upload field types (FEAT-460).

This module defines the ``FileEnvelope`` Pydantic model — the unified value
shape adopted by all upload-capable field types (``FILE``, ``IMAGE``,
``IMAGE_DROPZONE``, ``MULTI_UPLOAD``) — along with the ``UPLOAD_FIELD_TYPES``
constant and the ``is_single_cardinality`` helper used to distinguish
single-file fields (FILE, IMAGE) from multi-file fields (IMAGE_DROPZONE,
MULTI_UPLOAD).
"""

from pydantic import BaseModel, ConfigDict, Field

from parrot_formdesigner.core.types import FieldType


class FileEnvelope(BaseModel):
    """Canonical value shape for all upload field types.

    Attributes:
        filename: Original filename with extension (e.g. "report.pdf").
        content_type: MIME type (e.g. "application/pdf").
        size: File size in bytes.
        blob_ref: Server-side storage reference (e.g. "s3://bucket/key").
            None when the file is inline-only (not persisted to blob storage).
        data_url: Inline base64 data URL (e.g. "data:image/png;base64,...").
            None when the file exceeds max_inline_size_bytes.
        thumbnail_url: URL to a server-generated thumbnail (images only).
            None for non-image files or when generation fails.
        checksum: SHA-256 integrity hash (e.g. "sha256:abcdef...").
            Always computed server-side from the received content.
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., description="Original filename with extension")
    content_type: str = Field(..., description="MIME type of the file")
    size: int = Field(..., ge=0, description="File size in bytes")
    blob_ref: str | None = Field(default=None, description="Server storage reference")
    data_url: str | None = Field(default=None, description="Inline base64 data URL")
    thumbnail_url: str | None = Field(
        default=None, description="Thumbnail URL (images)"
    )
    checksum: str | None = Field(default=None, description="SHA-256 hash")


UPLOAD_FIELD_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.FILE,
        FieldType.IMAGE,
        FieldType.IMAGE_DROPZONE,
        FieldType.MULTI_UPLOAD,
    }
)
"""Field types whose value shape is (or maps to) a FileEnvelope."""


_SINGLE_CARDINALITY_TYPES: frozenset[FieldType] = frozenset(
    {FieldType.FILE, FieldType.IMAGE}
)


def is_single_cardinality(field_type: FieldType) -> bool:
    """Return whether an upload field type accepts a single file only.

    Args:
        field_type: The field type to check.

    Returns:
        True for FILE and IMAGE (single-file fields). False for
        IMAGE_DROPZONE and MULTI_UPLOAD (multi-file fields).
    """
    return field_type in _SINGLE_CARDINALITY_TYPES
