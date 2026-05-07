"""Render dispatcher for parrot-formdesigner.

Provides a name-keyed registry of renderers (``dict[str, AbstractFormRenderer]``)
and the ``handle_render`` aiohttp handler that delegates
``GET /api/v1/forms/{form_id}/render/{format}`` to the renderer registered
under ``{format}``.

V1 seeds two renderers:

- ``"html"`` → :class:`HTML5Renderer`
- ``"adaptive"`` → :class:`AdaptiveCardRenderer`

Wave 2 plugs in additional renderers (``"xml"``, ``"pdf"``) by calling
:func:`register_renderer` at module-import time. ``GET /api/v1/forms/{id}/render/{unknown}``
returns ``415 Unsupported Media Type`` with ``{"supported": [...]}``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from ..renderers.base import AbstractFormRenderer


logger = logging.getLogger(__name__)


# Module-level renderer registry. Seeded lazily — see ``_seed_default_renderers``.
_RENDERERS: dict[str, AbstractFormRenderer] = {}


def _seed_default_renderers() -> None:
    """Seed the registry with the V1 + V2 default renderers (idempotent).

    Imports of ``HTML5Renderer``, ``AdaptiveCardRenderer``, ``XFormsRenderer``,
    and ``PdfRenderer`` are deferred to avoid pulling Jinja2 / lxml /
    reportlab during ``import parrot_formdesigner.api``.
    """
    from ..renderers.adaptive_card import AdaptiveCardRenderer
    from ..renderers.html5 import HTML5Renderer

    _RENDERERS.setdefault("html", HTML5Renderer())
    _RENDERERS.setdefault("adaptive", AdaptiveCardRenderer())

    # Wave 2 renderers — imported lazily and registered if importable.
    if "xml" not in _RENDERERS:
        try:
            from ..renderers.xforms import XFormsRenderer

            _RENDERERS["xml"] = XFormsRenderer()
        except ImportError as exc:  # pragma: no cover — lxml is hard dep
            logger.debug("XFormsRenderer not available: %s", exc)

    if "pdf" not in _RENDERERS:
        try:
            from ..renderers.pdf import PdfRenderer

            _RENDERERS["pdf"] = PdfRenderer()
        except ImportError as exc:  # pragma: no cover — reportlab is hard dep
            logger.debug("PdfRenderer not available: %s", exc)


def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None:
    """Register (or overwrite) a renderer under ``format_key``.

    Args:
        format_key: The path-param value used in
            ``GET /api/v1/forms/{form_id}/render/{format}``.
        renderer: An ``AbstractFormRenderer`` instance.
    """
    if format_key in _RENDERERS:
        logger.info("register_renderer: overwriting %s", format_key)
    _RENDERERS[format_key] = renderer


def get_renderer(format_key: str) -> AbstractFormRenderer | None:
    """Return the renderer registered under ``format_key`` or ``None``."""
    return _RENDERERS.get(format_key)


def supported_formats() -> list[str]:
    """Return the sorted list of currently registered format keys."""
    return sorted(_RENDERERS.keys())


def _coerce_body(content: Any) -> bytes | str:
    """Normalise renderer output into something ``web.Response.body``/``text`` accepts.

    Args:
        content: The renderer's ``content`` field — may be ``bytes``, ``str``,
            or a JSON-serialisable Python object (dict / list).

    Returns:
        ``bytes`` or ``str`` ready for ``web.Response``.
    """
    if isinstance(content, (bytes, bytearray, memoryview, str)):
        return content if not isinstance(content, (bytearray, memoryview)) else bytes(content)
    return json.dumps(content)


async def handle_render(request: web.Request) -> web.Response:
    """GET /api/v1/forms/{form_id}/render/{format} — render dispatcher.

    Looks up the renderer by ``format`` path-param. On miss returns 415 with
    ``{"supported": [...]}``. On hit, loads the form from
    ``request.app["form_registry"]`` and delegates to ``renderer.render(form)``.

    Args:
        request: Incoming aiohttp request.

    Returns:
        The rendered output with ``Content-Type`` set from the renderer.
    """
    form_id = request.match_info["form_id"]
    format_key = request.match_info["format"]

    renderer = get_renderer(format_key)
    if renderer is None:
        return web.json_response(
            {"supported": supported_formats()},
            status=415,
        )

    registry = request.app.get("form_registry")
    if registry is None:
        logger.error("render dispatcher: app['form_registry'] is unset")
        return web.json_response(
            {"error": "form registry not configured"}, status=500
        )

    form = await registry.get(form_id)
    if form is None:
        return web.json_response(
            {"error": f"Form '{form_id}' not found"}, status=404
        )

    locale = request.query.get("locale", "en")
    rendered = await renderer.render(form, locale=locale)

    body = _coerce_body(rendered.content)
    if isinstance(body, str):
        return web.Response(text=body, content_type=rendered.content_type)
    return web.Response(body=body, content_type=rendered.content_type)
