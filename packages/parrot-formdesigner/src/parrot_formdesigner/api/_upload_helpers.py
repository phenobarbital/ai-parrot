"""Shared streaming/auth helpers for upload handlers (FEAT-460).

Extracted from ``api/uploads.py`` so that both the REST upload handler
(``handle_rest_upload``) and the new file-upload handler
(``handle_file_upload``) share the same size-limited streaming and
auth-context extraction logic without importing one handler module from
the other.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from aiohttp import web

from ..services.auth_context import AuthContext

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
