"""PATCH /api/v1/forms/{form_id}/operations — atomic batched-edit endpoint.

Wave 1 (FEAT-152) ships this module as a 501 Not Implemented stub. Wave 2d
(TASK-1048) replaces the body with the real implementation: a Pydantic
discriminated-union envelope, per-op apply functions, optional optimistic
concurrency via ``If-Match``, and version bumping.
"""

from __future__ import annotations

import logging

from aiohttp import web


logger = logging.getLogger(__name__)


async def handle_operations(request: web.Request) -> web.Response:
    """PATCH /api/v1/forms/{form_id}/operations — Wave 1 stub.

    Returns 501 until TASK-1048 lands. See FEAT-152 spec §2.

    Args:
        request: Incoming aiohttp request.

    Returns:
        ``web.Response`` with status 501 and a JSON ``{"detail": ...}`` body.
    """
    logger.info("operations endpoint invoked (stub) — form=%s",
                request.match_info.get("form_id"))
    return web.json_response({"detail": "not implemented"}, status=501)
