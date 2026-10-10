"""Blob persistence for spoken-answer recordings (FEAT-649, Module 6)."""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator

from ..core.schema import FormField, FormSchema
from ..services.blob_storage import AbstractBlobStorage, BlobMetadata

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def recording_blob_id(session_id: str, field_uid: uuid.UUID) -> str:
    """``f"voice-{session_id}-{field_uid}"`` — matches BlobMetadata.blob_id regex (services/blob_storage.py:93)."""
    suffix = f"-{field_uid}"
    safe_session = _SAFE.sub("_", session_id)[: 128 - len("voice-") - len(suffix)]
    return f"voice-{safe_session}{suffix}"


async def _one_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def store_recording(storage: AbstractBlobStorage, *, audio: bytes, mime: str, form: FormSchema, field: FormField,
                          session_id: str, submission_id: str, tenant: str | None) -> str:
    """storage.put(<one-chunk async stream>, metadata=BlobMetadata(...)) → blob_ref; same session+field overwrites."""
    metadata = BlobMetadata(
        form_uid=form.form_uid,
        form_id=form.form_id,
        field_uid=field.field_uid,
        field_id=field.field_id,
        submission_id=submission_id,
        tenant=tenant,
        content_type=mime,
        size_bytes=len(audio),
        blob_id=recording_blob_id(session_id, field.field_uid),
    )
    blob_ref = await storage.put(_one_chunk(audio), metadata=metadata)
    logger.debug("Stored recording for field %s (%d bytes)", field.field_id, len(audio))
    return blob_ref


async def delete_recording(storage: AbstractBlobStorage, blob_ref: str) -> None:
    """Delete a stored recording; idempotent, never raises for a missing blob."""
    try:
        await storage.delete(blob_ref)
    except Exception as exc:  # noqa: BLE001 — cleanup is best-effort (cascade_clear / failed commit)
        logger.warning("delete_recording failed: %s", type(exc).__name__)
