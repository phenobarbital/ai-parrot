"""REST field upload handler for FieldType.REST (FEAT-170).

Route: POST /api/v1/forms/{form_id}/fields/{field_id}/upload

Pipeline:
  multipart parse → MIME/size check → blob storage → RestFieldResolver
  → JSON envelope {success, answer, raw_value, blob_ref, display, warnings, error}

The ``X-Parrot-Prior-Blob-Ref`` request header carries the previous blob URI
so this handler can schedule its deletion after the new blob is durably
written. Deletion failure is appended as a warning — it never causes a 500.

Bootstrap wiring (``app["blob_storage"]``, ``app["rest_resolver"]``) is
done by TASK-1171.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from aiohttp import web
from pydantic import ValidationError

from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..services.auth_context import AuthContext
from ..services.blob_storage import BlobMetadata, BlobRejectedError
from ..services.rest_field_resolver import RestCallbackInput, RestFieldSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_field(form: FormSchema, field_id: str) -> FormField | None:
    """Search all sections for a field by ID."""
    for section in form.sections:
        for field in section.fields:
            if field.field_id == field_id:
                return field
    return None


def _build_auth_context(request: web.Request) -> AuthContext:
    """Build AuthContext from the inbound request.

    Mirrors ``FormAPIHandler._build_auth_context`` as a module-level helper.
    """
    if "auth_context" in request:
        existing = request["auth_context"]
        if isinstance(existing, AuthContext):
            return existing
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return AuthContext(
            scheme="bearer",
            token=auth_header[7:],
            headers={"Authorization": auth_header},
        )
    if auth_header.startswith("ApiKey "):
        token = auth_header[7:]
        return AuthContext(
            scheme="api_key",
            token=token,
            headers={"X-API-Key": token},
        )
    return AuthContext(scheme="none")


def _get_tenant(request: web.Request) -> str | None:
    """Extract first program slug as tenant context from the user session."""
    session = getattr(request, "session", None)
    if session:
        programs = session.get("session", {}).get("programs", [])
        return programs[0] if programs else None
    return None


async def _iter_bytes(content: bytes) -> AsyncIterator[bytes]:
    """Wrap buffered bytes as a single-chunk async iterator for blob storage."""
    yield content


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def handle_rest_upload(request: web.Request) -> web.Response:
    """Handle a REST-field file upload and resolve via RestFieldResolver.

    Args:
        request: aiohttp request. Must have multipart/form-data body and
            route params ``form_id`` / ``field_id``.

    Returns:
        JSON response with envelope::

            {
                "success": bool,
                "answer": Any,
                "raw_value": Any,
                "blob_ref": str | None,
                "display": str | None,
                "warnings": list[str],
                "error": str | None,
            }

    Raises:
        HTTPNotFound: Form not found or field is not FieldType.REST.
        HTTPBadRequest: Missing/malformed multipart or invalid spec.
        HTTPRequestEntityTooLarge: Upload exceeds max_file_size_bytes.
        HTTPUnsupportedMediaType: MIME type not in allowed_mime_types.
        HTTPInternalServerError: rest_resolver not wired or unexpected exception.
    """
    form_id: str = request.match_info["form_id"]
    field_id: str = request.match_info["field_id"]

    # --- 1. Resolve registry + form + field ---
    registry = request.app.get("form_registry")
    if registry is None:
        raise web.HTTPInternalServerError(reason="form_registry not configured")

    form = await registry.get(form_id)
    if form is None:
        raise web.HTTPNotFound(reason=f"Form {form_id!r} not found")

    field = _find_field(form, field_id)
    if field is None or field.field_type != FieldType.REST:
        raise web.HTTPNotFound(
            reason=f"REST field {field_id!r} not found in form {form_id!r}"
        )

    # --- 2. Validate Content-Type ---
    if "multipart" not in (request.content_type or ""):
        raise web.HTTPBadRequest(reason="Expected multipart/form-data")

    # --- 3. Parse multipart ---
    try:
        reader = await request.multipart()
    except Exception as exc:
        raise web.HTTPBadRequest(reason=f"Malformed multipart: {exc}") from exc

    part = await reader.next()
    if part is None:
        raise web.HTTPBadRequest(reason="No file part in multipart body")

    file_content_type: str = part.headers.get("Content-Type", "application/octet-stream")

    # --- 4. MIME validation ---
    allowed_mimes: set[str] = set()
    if field.constraints and field.constraints.allowed_mime_types:
        allowed_mimes = set(field.constraints.allowed_mime_types)

    if allowed_mimes and file_content_type not in allowed_mimes:
        raise web.HTTPUnsupportedMediaType(
            reason=f"Content-Type {file_content_type!r} not in allowed types"
        )

    # --- 5. Buffer with size limit ---
    max_size: int | None = None
    if field.constraints and field.constraints.max_file_size_bytes is not None:
        max_size = field.constraints.max_file_size_bytes

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk: bytes = await part.read_chunk()
        if not chunk:
            break
        total += len(chunk)
        if max_size is not None and total > max_size:
            raise web.HTTPRequestEntityTooLarge(
                max_size=max_size,
                actual_size=total,
            )
        chunks.append(chunk)

    content_bytes = b"".join(chunks)

    # --- 6. Parse RestFieldSpec ---
    rest_meta: dict[str, Any] = (field.meta or {}).get("rest") or {}
    try:
        spec = RestFieldSpec.model_validate(rest_meta)
    except ValidationError as exc:
        raise web.HTTPBadRequest(reason=f"Invalid REST field spec: {exc}") from exc

    # --- 7. Auth context + tenant ---
    auth_context = _build_auth_context(request)
    tenant = _get_tenant(request)

    # --- 8. Blob storage (optional — wired by TASK-1171) ---
    blob_ref: str | None = None
    blob_storage = request.app.get("blob_storage")

    if blob_storage is not None and spec.persist_binary:
        blob_meta = BlobMetadata(
            form_id=form_id,
            field_id=field_id,
            content_type=file_content_type,
            size_bytes=total,
            tenant=tenant,
        )
        try:
            blob_ref = await blob_storage.put(
                _iter_bytes(content_bytes), metadata=blob_meta
            )
        except BlobRejectedError as exc:
            raise web.HTTPBadRequest(reason=f"Upload rejected by pre-persist hook: {exc}") from exc

    # --- 9. Resolve ---
    rest_resolver = request.app.get("rest_resolver")
    if rest_resolver is None:
        raise web.HTTPInternalServerError(reason="rest_resolver not configured")

    payload = RestCallbackInput(
        form_id=form_id,
        field_id=field_id,
        content_type=file_content_type,
        content=content_bytes,
        tenant=tenant,
    )

    result = await rest_resolver.resolve(
        spec, payload, auth_context=auth_context, tenant=tenant
    )
    warnings: list[str] = list(result.warnings)

    # --- 10. Prior blob cleanup (best-effort; failure → warning, not 500) ---
    prior_blob_ref = request.headers.get("X-Parrot-Prior-Blob-Ref")
    if prior_blob_ref and blob_storage is not None:
        try:
            await blob_storage.delete(prior_blob_ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete prior blob %r: %s", prior_blob_ref, exc)
            warnings.append(f"prior_blob_delete_failed: {exc}")

    # --- 11. Return JSON envelope ---
    return web.json_response(
        {
            "success": result.success,
            "answer": result.answer,
            "raw_value": result.raw_value,
            "blob_ref": blob_ref or result.blob_ref,
            "display": result.display,
            "warnings": warnings,
            "error": result.error,
        }
    )
