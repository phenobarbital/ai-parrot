"""HTTP handler for ``GET /api/v1/form-controls``.

Returns the registered form-control metadata as ``{"controls": [...]}``.
The registry is seeded by ``parrot_formdesigner.controls.builtin`` on
``import parrot_formdesigner.api``.
"""

from __future__ import annotations

import logging

from aiohttp import web

from ..controls import get_controls


logger = logging.getLogger(__name__)


async def handle_form_controls(request: web.Request) -> web.Response:
    """GET /api/v1/form-controls — return the registered control metadata.

    Args:
        request: Incoming aiohttp request.

    Returns:
        JSON response ``{"controls": [<FieldControlMetadata.model_dump()>, ...]}``.
    """
    controls = [c.model_dump() for c in get_controls()]
    return web.json_response({"controls": controls})
