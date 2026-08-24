"""File-upload handler for the raw upload field types (FEAT-460).

Exposes ``handle_file_upload`` — an aiohttp request handler mounted at:

    POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload

Handles the binary pipeline for FILE, IMAGE, IMAGE_DROPZONE, and
MULTI_UPLOAD field types: multipart parsing, MIME/size enforcement, blob
storage persistence, inline data_url encoding, SHA-256 checksums, optional
thumbnail generation, and basic chunked-upload support.

Error codes:
- 400: malformed multipart, no ``file`` part, or multiple files on a
       single-cardinality field (FILE/IMAGE).
- 404: form not found, field not found, or field is not an upload type.
- 413: upload exceeds ``field.constraints.max_file_size_bytes``.
- 415: MIME type not in ``field.constraints.allowed_mime_types``.
- 500: blob storage failure.

Basic chunked upload:
Clients that split a large file into sequential chunks may send each
chunk as a raw (non-multipart) request body, tagged with the
``X-Parrot-Upload-Offset`` and ``X-Parrot-Upload-Length`` headers. Chunks
are buffered in blob storage (one blob per chunk) and reassembled when
the final chunk arrives (``offset + len(chunk) == total_length``). This
is NOT full tus-protocol support — see the spec's Non-Goals.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

from aiohttp import web

from ..core.constraints import DEFAULT_MAX_INLINE_SIZE
from ..core.file_envelope import UPLOAD_FIELD_TYPES, FileEnvelope, is_single_cardinality
from ..core.resolution import find_field_by_uid
from ..core.schema import FormField, FormSchema
from ..services.blob_storage import AbstractBlobStorage, BlobMetadata
from ..services.thumbnail import ThumbnailService
from ._upload_helpers import _stream_with_limit
from .handlers import extract_form_uid, extract_uid
from .tenant import declared_tenant

logger = logging.getLogger(__name__)

# Basic chunked-upload session buffer: (form_uid, field_uid) -> {offset: blob_ref}.
# Process-local — sufficient for the V1 "basic chunked upload" scope (not
# full tus-protocol support; see spec Non-Goals).
_CHUNK_BUFFERS: dict[tuple[str, str], dict[int, str]] = {}


def _get_blob_storage(app: web.Application) -> AbstractBlobStorage:
    """Return the app-level blob storage, or construct an ephemeral default.

    Mirrors the lazy-default pattern in ``api/uploads.py`` so both upload
    handlers share the same cached instance when ``app["blob_storage"]``
    is configured.

    Args:
        app: The aiohttp application.

    Returns:
        An ``AbstractBlobStorage`` instance.
    """
    storage = app.get("blob_storage")
    if storage is not None:
        return storage
    from ..services.blob_storage import TempBlobStorage  # deferred

    storage = TempBlobStorage()
    app["blob_storage"] = storage
    return storage


def _get_thumbnail_service(app: web.Application, blob_storage: AbstractBlobStorage) -> ThumbnailService:
    """Return the app-level ThumbnailService, or construct+cache a default.

    Args:
        app: The aiohttp application.
        blob_storage: Blob storage backend used by a lazily-constructed default.

    Returns:
        A ``ThumbnailService`` instance.
    """
    service = app.get("thumbnail_service")
    if service is not None:
        return service
    service = ThumbnailService(blob_storage)
    app["thumbnail_service"] = service
    return service


async def _bytes_iter(data: bytes) -> AsyncGenerator[bytes, None]:
    """Async generator wrapping a bytes object as a single chunk.

    Args:
        data: The bytes to yield.

    Yields:
        The full data bytes in one chunk.
    """
    yield data


async def handle_file_upload(request: web.Request) -> web.Response:
    """Handle POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload.

    Streams multipart upload(s) through the file upload pipeline:
    multipart -> MIME/size check -> blob storage -> FileEnvelope(s) -> JSON.

    Supports multiple 'file' parts in one request. Returns a single
    FileEnvelope for single-cardinality fields (FILE, IMAGE) or a list
    for multi-cardinality fields (IMAGE_DROPZONE multi, MULTI_UPLOAD).

    Accepts X-Parrot-Prior-Blob-Ref header for replacement uploads, and
    X-Parrot-Upload-Offset / X-Parrot-Upload-Length headers for basic
    chunked uploads.

    Args:
        request: The incoming aiohttp web.Request.

    Returns:
        JSON response with a single FileEnvelope, a list of FileEnvelopes,
        or a chunk-accepted acknowledgement (202) for non-final chunks.

    Raises:
        web.HTTPBadRequest: Malformed multipart, no file part, or multiple
            files on a single-cardinality field.
        web.HTTPNotFound: Form/field not found, or field is not an upload type.
        web.HTTPRequestEntityTooLarge: Upload exceeds the size constraint.
        web.HTTPUnsupportedMediaType: MIME type not allowed.
    """
    form_uid = extract_form_uid(request)
    field_uid = extract_uid(request, "field_uid")
    tenant = declared_tenant(request)

    registry = request.app.get("form_registry")
    if registry is None:
        raise web.HTTPInternalServerError(reason="form_registry not configured")

    form = await registry.get(form_uid, tenant=tenant)
    if form is None:
        raise web.HTTPNotFound(reason=f"Form not found: {form_uid!r}")

    found = find_field_by_uid(form, field_uid)
    if found is None:
        raise web.HTTPNotFound(reason=f"Field not found: {field_uid!r}")
    field: FormField = found[0]
    field_id = field.field_id

    if field.field_type not in UPLOAD_FIELD_TYPES:
        raise web.HTTPNotFound(
            reason=(f"Field {field_id!r} is not an upload field " f"(got {field.field_type.value!r})")
        )

    constraints = field.constraints
    max_size: int | None = None
    allowed_mimes: list[str] | None = None
    max_inline: int = DEFAULT_MAX_INLINE_SIZE
    if constraints is not None:
        max_size = getattr(constraints, "max_file_size_bytes", None)
        allowed_mimes = getattr(constraints, "allowed_mime_types", None)
        configured_inline = getattr(constraints, "max_inline_size_bytes", None)
        if configured_inline is not None:
            max_inline = configured_inline

    single = is_single_cardinality(field.field_type)
    blob_storage = _get_blob_storage(request.app)
    blob_tenant: str | None = request.headers.get("X-Parrot-Tenant") or tenant

    upload_offset = request.headers.get("X-Parrot-Upload-Offset")
    upload_length = request.headers.get("X-Parrot-Upload-Length")

    result: FileEnvelope | list[FileEnvelope]
    if upload_offset is not None and upload_length is not None:
        envelope = await _handle_chunk(
            request,
            request.app,
            form,
            field,
            blob_storage,
            blob_tenant,
            max_size,
            allowed_mimes,
            max_inline,
        )
        if envelope is None:
            return web.json_response({"status": "chunk_received"}, status=202)
        result = envelope
    else:
        content_type_header = request.headers.get("Content-Type", "")
        if "multipart" not in content_type_header:
            raise web.HTTPBadRequest(reason="Expected multipart/form-data upload")

        reader = await request.multipart()
        envelopes: list[FileEnvelope] = []

        while True:
            part = await reader.next()
            if part is None:
                break
            if (part.name or "") != "file":
                continue
            if single and envelopes:
                raise web.HTTPBadRequest(reason=f"Field {field_id!r} accepts a single file only")
            envelope = await _process_file_part(
                part,
                request.app,
                form,
                field,
                blob_storage,
                blob_tenant,
                max_size,
                allowed_mimes,
                max_inline,
            )
            envelopes.append(envelope)

        if not envelopes:
            raise web.HTTPBadRequest(reason="No 'file' part found in multipart body")

        result = envelopes[0] if single else envelopes

    prior_blob_ref = request.headers.get("X-Parrot-Prior-Blob-Ref")
    if prior_blob_ref:
        try:
            await blob_storage.delete(prior_blob_ref)
        except Exception as exc:
            logger.warning(
                "Failed to delete prior blob %r for %s/%s: %s",
                prior_blob_ref,
                form_uid,
                field_id,
                exc,
            )

    if isinstance(result, list):
        return web.json_response([env.model_dump() for env in result])
    return web.json_response(result.model_dump())


async def _process_file_part(
    part: Any,
    app: web.Application,
    form: FormSchema,
    field: FormField,
    blob_storage: AbstractBlobStorage,
    blob_tenant: str | None,
    max_size: int | None,
    allowed_mimes: list[str] | None,
    max_inline: int,
) -> FileEnvelope:
    """Stream, validate, and persist a single multipart file part.

    Args:
        part: The aiohttp multipart BodyPartReader for the 'file' part.
        app: The aiohttp application (for the ThumbnailService lazy default).
        form: The resolved FormSchema.
        field: The resolved FormField (an upload field type).
        blob_storage: Blob storage backend.
        blob_tenant: Tenant tag for blob metadata.
        max_size: Maximum allowed file size in bytes, or None.
        allowed_mimes: Allowed MIME types, or None (any allowed).
        max_inline: Size threshold for inline data_url inclusion.

    Returns:
        The finalized FileEnvelope for this file part.

    Raises:
        web.HTTPUnsupportedMediaType: MIME type not allowed.
        web.HTTPRequestEntityTooLarge: File exceeds max_size.
    """
    content_type = part.headers.get("Content-Type", "application/octet-stream")
    if allowed_mimes and content_type not in allowed_mimes:
        raise web.HTTPUnsupportedMediaType(text=f"MIME type {content_type!r} is not allowed. Allowed: {allowed_mimes}")
    filename = part.filename or "upload"

    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    async for chunk in _stream_with_limit(part, max_size):
        hasher.update(chunk)
        chunks.append(chunk)
    file_bytes = b"".join(chunks)

    return await _finalize_envelope(
        file_bytes,
        filename,
        content_type,
        hasher.hexdigest(),
        app,
        form,
        field,
        blob_storage,
        blob_tenant,
        max_inline,
    )


async def _handle_chunk(
    request: web.Request,
    app: web.Application,
    form: FormSchema,
    field: FormField,
    blob_storage: AbstractBlobStorage,
    blob_tenant: str | None,
    max_size: int | None,
    allowed_mimes: list[str] | None,
    max_inline: int,
) -> FileEnvelope | None:
    """Handle one chunk of a basic chunked upload.

    Args:
        request: The incoming request (chunk body is the raw request body).
        app: The aiohttp application (for the ThumbnailService lazy default).
        form: The resolved FormSchema.
        field: The resolved FormField (an upload field type).
        blob_storage: Blob storage backend.
        blob_tenant: Tenant tag for blob metadata.
        max_size: Maximum allowed assembled file size in bytes, or None.
        allowed_mimes: Allowed MIME types, or None (any allowed).
        max_inline: Size threshold for inline data_url inclusion.

    Returns:
        The finalized FileEnvelope once the final chunk is received and
        the file is reassembled, or None if more chunks are still expected.

    Raises:
        web.HTTPBadRequest: Offset/length headers are malformed.
        web.HTTPUnsupportedMediaType: Assembled file's MIME type not allowed.
        web.HTTPRequestEntityTooLarge: Assembled file exceeds max_size.
    """
    field_id = field.field_id
    try:
        offset = int(request.headers["X-Parrot-Upload-Offset"])
        total_length = int(request.headers["X-Parrot-Upload-Length"])
    except (KeyError, ValueError) as exc:
        raise web.HTTPBadRequest(reason="Invalid X-Parrot-Upload-Offset/X-Parrot-Upload-Length headers") from exc

    chunk_bytes = await request.read()
    key = (str(form.form_uid), str(field.field_uid))
    session = _CHUNK_BUFFERS.setdefault(key, {})

    chunk_meta = BlobMetadata(
        form_uid=form.form_uid,
        form_id=form.form_id,
        field_uid=field.field_uid,
        field_id=f"{field_id}__chunk_{offset}",
        tenant=blob_tenant,
        content_type="application/octet-stream",
        size_bytes=len(chunk_bytes),
    )
    session[offset] = await blob_storage.put(_bytes_iter(chunk_bytes), metadata=chunk_meta)

    if offset + len(chunk_bytes) < total_length:
        return None

    # Final chunk received — reassemble in offset order.
    ordered_offsets = sorted(session)
    assembled = bytearray()
    for off in ordered_offsets:
        ref = session[off]
        stream = await blob_storage.get(ref)
        async for part_bytes in stream:
            assembled.extend(part_bytes)
    del _CHUNK_BUFFERS[key]

    for off in ordered_offsets:
        try:
            await blob_storage.delete(session[off])
        except Exception as exc:
            logger.warning("Failed to delete chunk blob %r: %s", session[off], exc)

    file_bytes = bytes(assembled)
    if max_size is not None and len(file_bytes) > max_size:
        raise web.HTTPRequestEntityTooLarge(max_size=max_size, actual_size=len(file_bytes))

    content_type = (
        request.headers.get("X-Parrot-Upload-Content-Type")
        or request.headers.get("Content-Type")
        or "application/octet-stream"
    )
    if allowed_mimes and content_type not in allowed_mimes:
        raise web.HTTPUnsupportedMediaType(text=f"MIME type {content_type!r} is not allowed. Allowed: {allowed_mimes}")
    filename = request.headers.get("X-Parrot-Upload-Filename", f"{field_id}-upload")
    checksum_hex = hashlib.sha256(file_bytes).hexdigest()

    return await _finalize_envelope(
        file_bytes,
        filename,
        content_type,
        checksum_hex,
        app,
        form,
        field,
        blob_storage,
        blob_tenant,
        max_inline,
    )


async def _finalize_envelope(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    checksum_hex: str,
    app: web.Application,
    form: FormSchema,
    field: FormField,
    blob_storage: AbstractBlobStorage,
    blob_tenant: str | None,
    max_inline: int,
) -> FileEnvelope:
    """Persist file bytes to blob storage and build the FileEnvelope.

    Args:
        file_bytes: The complete file content.
        filename: Original filename.
        content_type: MIME type of the file.
        checksum_hex: Hex-encoded SHA-256 digest of file_bytes.
        app: The aiohttp application (for the ThumbnailService lazy default).
        form: The resolved FormSchema.
        field: The resolved FormField.
        blob_storage: Blob storage backend.
        blob_tenant: Tenant tag for blob metadata.
        max_inline: Size threshold for inline data_url inclusion.

    Returns:
        The finalized FileEnvelope.

    Raises:
        web.HTTPInternalServerError: Blob storage persistence failed.
    """
    blob_meta = BlobMetadata(
        form_uid=form.form_uid,
        form_id=form.form_id,
        field_uid=field.field_uid,
        field_id=field.field_id,
        tenant=blob_tenant,
        content_type=content_type,
        size_bytes=len(file_bytes),
    )

    try:
        blob_ref = await blob_storage.put(_bytes_iter(file_bytes), metadata=blob_meta)
    except Exception as exc:
        logger.exception("blob_storage.put failed for %s/%s", form.form_uid, field.field_id)
        raise web.HTTPInternalServerError(
            reason="Blob storage error",
            text="Blob storage error. Check server logs for details.",
        ) from exc

    data_url: str | None = None
    if len(file_bytes) <= max_inline:
        encoded = base64.b64encode(file_bytes).decode("ascii")
        data_url = f"data:{content_type};base64,{encoded}"

    thumbnail_url: str | None = None
    if content_type.startswith("image/"):
        thumbnail_service = _get_thumbnail_service(app, blob_storage)
        thumbnail_url = await thumbnail_service.generate(file_bytes, blob_meta)

    return FileEnvelope(
        filename=filename,
        content_type=content_type,
        size=len(file_bytes),
        blob_ref=blob_ref,
        data_url=data_url,
        thumbnail_url=thumbnail_url,
        checksum=f"sha256:{checksum_hex}",
    )
