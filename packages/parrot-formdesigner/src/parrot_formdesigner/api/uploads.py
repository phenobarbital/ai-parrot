"""REST field upload handler for FormDesigner (FEAT-170).

Exposes ``handle_rest_upload`` — an aiohttp request handler mounted at:

    POST /api/v1/forms/{form_id}/fields/{field_id}/upload

The handler follows this pipeline:

1. Resolve the ``FormField`` via ``app["form_registry"]``.
2. Verify the field is ``FieldType.REST``; return 404 otherwise.
3. Parse the multipart body, streaming bytes to ``AbstractBlobStorage``.
4. Enforce MIME and size constraints from ``field.constraints``.
5. Build ``AuthContext`` from the inbound request.
6. Honour ``X-Parrot-Prior-Blob-Ref`` header — delete the prior blob
   after the new one is durably written (delete failure appends a
   warning string, does NOT 500).
7. Call ``RestFieldResolver.resolve()`` with the spec and payload.
8. Return a JSON envelope:

    {
        "success": bool,
        "answer": <any>,
        "raw_value": <any>,
        "blob_ref": str | null,
        "display": str | null,
        "warnings": [str, ...],
        "error": str | null
    }

Error codes:
- 400: malformed multipart or no ``file`` part.
- 404: form not found or field not found / not of type REST.
- 413: upload exceeds ``field.constraints.max_file_size_bytes``.
- 415: MIME type not in ``field.constraints.allowed_mime_types``.
- 500: unexpected exception (resolver contract guarantees never-raise for
       known errors; ``RestFieldResult.success=False`` maps to 200).

Lazy-init contract:
``app["blob_storage"]`` and ``app["rest_resolver"]`` may be ``None``.
On first request, this module constructs default instances from env vars.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from aiohttp import web

from pydantic import TypeAdapter

from ..core.schema import FormField
from ..core.types import FieldType
from ..services.auth_context import AuthContext
from ..services.rest_field_resolver import RestCallbackInput, RestFieldResolver, RestFieldSpec

_rest_spec_adapter: TypeAdapter | None = None


def _get_rest_spec_adapter() -> TypeAdapter:
    """Return a lazily-constructed TypeAdapter for RestFieldSpec.

    Returns:
        TypeAdapter for the RestFieldSpec discriminated union.
    """
    global _rest_spec_adapter
    if _rest_spec_adapter is None:
        _rest_spec_adapter = TypeAdapter(RestFieldSpec)
    return _rest_spec_adapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_default_resolver: RestFieldResolver | None = None


def _get_resolver(app: web.Application) -> RestFieldResolver:
    """Return the app-level resolver, or construct a default one lazily.

    Args:
        app: The aiohttp application.

    Returns:
        A ``RestFieldResolver`` instance.
    """
    global _default_resolver
    resolver = app.get("rest_resolver")
    if resolver is not None:
        return resolver
    if _default_resolver is None:
        _default_resolver = RestFieldResolver()
    return _default_resolver


def _get_blob_storage(app: web.Application) -> Any:
    """Return the app-level blob storage, or construct a default S3 one lazily.

    Args:
        app: The aiohttp application.

    Returns:
        An ``AbstractBlobStorage`` instance.
    """
    storage = app.get("blob_storage")
    if storage is not None:
        return storage
    # Lazy default: S3BlobStorage reads from environment variables.
    from ..services.blob_storage import S3BlobStorage  # deferred
    return S3BlobStorage()


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


async def _stream_with_limit(
    part: Any,
    limit: int | None,
) -> AsyncIterator[bytes]:
    """Stream multipart part chunks, raising 413 if total exceeds limit.

    Args:
        part: An aiohttp multipart BodyPartReader.
        limit: Maximum allowed bytes, or None for no limit.

    Yields:
        Chunks of bytes.

    Raises:
        web.HTTPRequestEntityTooLarge: When total bytes exceed limit.
    """
    total = 0
    while True:
        chunk = await part.read_chunk(65536)
        if not chunk:
            break
        total += len(chunk)
        if limit is not None and total > limit:
            raise web.HTTPRequestEntityTooLarge(
                max_size=limit,
                actual_size=total,
            )
        yield chunk


def _build_auth_context(request: web.Request) -> AuthContext:
    """Build AuthContext from the inbound request.

    Checks (in order):
    1. ``request["auth_context"]`` — set by navigator-auth middleware.
    2. ``Authorization: Bearer <token>`` header.
    3. ``Authorization: ApiKey <token>`` header.
    4. Defaults to ``AuthContext(scheme="none")``.

    Args:
        request: The incoming aiohttp request.

    Returns:
        AuthContext for the request.
    """
    if "auth_context" in request:
        existing = request["auth_context"]
        if isinstance(existing, AuthContext):
            return existing

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return AuthContext(
            scheme="bearer",
            token=token,
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


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def handle_rest_upload(request: web.Request) -> web.Response:
    """Handle POST /api/v1/forms/{form_id}/fields/{field_id}/upload.

    Streams a multipart upload through the REST field pipeline:
    multipart → MIME/size check → blob storage → resolver → JSON envelope.

    The ``X-Parrot-Prior-Blob-Ref`` request header, if present, identifies
    a previously-uploaded blob that should be deleted after the new blob
    is durably written (idempotent; delete failure appends a warning).

    Args:
        request: The incoming aiohttp web.Request.

    Returns:
        JSON response with the resolver result envelope.

    Raises:
        web.HTTPNotFound: If form or field not found, or field is not REST.
        web.HTTPBadRequest: If multipart is malformed or has no ``file`` part.
        web.HTTPRequestEntityTooLarge: If upload exceeds size constraint.
        web.HTTPUnsupportedMediaType: If MIME is not in allowed list.
    """
    form_id: str = request.match_info["form_id"]
    field_id: str = request.match_info["field_id"]
    warnings: list[str] = []

    # --- 1. Resolve the field -----------------------------------------------
    registry = request.app.get("form_registry")
    if registry is None:
        raise web.HTTPInternalServerError(reason="form_registry not configured")

    form = await registry.get(form_id)
    if form is None:
        raise web.HTTPNotFound(reason=f"Form not found: {form_id!r}")

    field: FormField | None = None
    for section in form.sections:
        for item in section.iter_fields():
            if item.field_id == field_id:
                field = item
                break
        if field is not None:
            break

    if field is None:
        raise web.HTTPNotFound(reason=f"Field not found: {field_id!r}")

    if field.field_type != FieldType.REST:
        raise web.HTTPNotFound(
            reason=f"Field {field_id!r} is not a REST field (got {field.field_type.value!r})"
        )

    # --- 2. Parse constraints ------------------------------------------------
    constraints = field.constraints
    max_size: int | None = None
    allowed_mimes: list[str] | None = None
    if constraints is not None:
        max_size = getattr(constraints, "max_file_size_bytes", None)
        allowed_mimes = getattr(constraints, "allowed_mime_types", None)

    # --- 3. Parse multipart ---------------------------------------------------
    content_type_header = request.headers.get("Content-Type", "")
    if "multipart" not in content_type_header:
        raise web.HTTPBadRequest(reason="Expected multipart/form-data upload")

    reader = await request.multipart()

    file_bytes: bytes | None = None
    detected_mime: str | None = None

    while True:
        part = await reader.next()
        if part is None:
            break
        part_name = part.name or ""
        if part_name == "file":
            detected_mime = part.headers.get("Content-Type", "application/octet-stream")
            # MIME validation
            if allowed_mimes and detected_mime not in allowed_mimes:
                raise web.HTTPUnsupportedMediaType(
                    text=f"MIME type {detected_mime!r} is not allowed. "
                    f"Allowed: {allowed_mimes}"
                )
            # Stream with size limit
            chunks: list[bytes] = []
            async for chunk in _stream_with_limit(part, max_size):
                chunks.append(chunk)
            file_bytes = b"".join(chunks)
            break  # only care about the first 'file' part

    if file_bytes is None:
        raise web.HTTPBadRequest(reason="No 'file' part found in multipart body")

    # --- 4. Auth context ------------------------------------------------------
    auth_context = _build_auth_context(request)
    tenant: str | None = request.headers.get("X-Parrot-Tenant")

    # --- 5. Parse RestFieldSpec ----------------------------------------------
    rest_meta = (field.meta or {}).get("rest", {})
    try:
        spec = _get_rest_spec_adapter().validate_python(rest_meta)
    except Exception as exc:
        raise web.HTTPBadRequest(reason=f"Invalid REST field spec: {exc}") from exc

    # --- 6. Write blob --------------------------------------------------------
    blob_storage = _get_blob_storage(request.app)
    from ..services.blob_storage import BlobMetadata  # deferred

    session_id: str | None = None
    if "session" in request:
        session_id = str(request["session"].get("id", ""))

    blob_meta = BlobMetadata(
        form_id=form_id,
        field_id=field_id,
        submission_id=session_id or "",
        tenant=tenant or "",
        content_type=detected_mime or "application/octet-stream",
        size_bytes=len(file_bytes),
    )

    blob_ref: str | None = None
    try:
        blob_ref = await blob_storage.put(
            blob_meta,
            _bytes_iter(file_bytes),
        )
    except Exception as exc:
        logger.exception("blob_storage.put failed for %s/%s", form_id, field_id)
        raise web.HTTPInternalServerError(reason=f"Blob storage error: {exc}") from exc

    # --- 7. Delete prior blob -------------------------------------------------
    prior_blob_ref = request.headers.get("X-Parrot-Prior-Blob-Ref")
    if prior_blob_ref and prior_blob_ref != blob_ref:
        try:
            await blob_storage.delete(prior_blob_ref)
        except Exception as exc:
            warnings.append(f"prior blob delete failed: {exc}")
            logger.warning(
                "Failed to delete prior blob %r for %s/%s: %s",
                prior_blob_ref, form_id, field_id, exc,
            )

    # --- 8. Resolve -----------------------------------------------------------
    payload = RestCallbackInput(
        form_id=form_id,
        field_id=field_id,
        session_id=session_id or "",
        user_id=str(auth_context.token or ""),
        tenant=tenant or "",
        content_type=detected_mime or "application/octet-stream",
        content=file_bytes,
    )

    resolver = _get_resolver(request.app)
    result = await resolver.resolve(
        spec,
        payload,
        auth_context=auth_context,
        tenant=tenant,
    )

    # Merge any resolver warnings with ours
    all_warnings = warnings + (result.warnings or [])

    return web.json_response(
        {
            "success": result.success,
            "answer": result.answer,
            "raw_value": result.raw_value,
            "blob_ref": blob_ref,
            "display": result.display,
            "warnings": all_warnings,
            "error": result.error,
        }
    )


async def _bytes_iter(data: bytes):
    """Async generator wrapping a bytes object as a single chunk.

    Args:
        data: The bytes to yield.

    Yields:
        The full data bytes in one chunk.
    """
    yield data
