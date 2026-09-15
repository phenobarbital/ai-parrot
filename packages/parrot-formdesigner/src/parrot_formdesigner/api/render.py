"""Render dispatcher for parrot-formdesigner.

Provides a name-keyed registry of renderers (``dict[str, AbstractFormRenderer]``)
and the ``handle_render`` aiohttp handler that delegates
``GET /api/v1/forms/{form_uid}/render/{format}`` to the renderer registered
under ``{format}``.

V1 seeds two renderers:

- ``"html"`` → :class:`HTML5Renderer`
- ``"adaptive"`` → :class:`AdaptiveCardRenderer`

Wave 2 plugs in additional renderers (``"xml"``, ``"pdf"``, ``"audio"``,
``"a2ui"``) by calling :func:`register_renderer` at module-import time.
``"a2ui"`` (FEAT-544) is the one OPTIONAL seed — it requires the
``ai-parrot`` extra and is simply absent (one INFO log) when that extra is
not installed. ``GET /api/v1/forms/{id}/render/{unknown}`` returns
``415 Unsupported Media Type`` with ``{"supported": [...]}``.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import logging
from typing import Any

from aiohttp import web

from ..renderers.base import AbstractFormRenderer
from .handlers import extract_form_uid
from .tenant import declared_tenant, enforce_membership_unless_public

logger = logging.getLogger(__name__)


# Module-level renderer registry. Seeded lazily — see ``_seed_default_renderers``.
_RENDERERS: dict[str, AbstractFormRenderer] = {}


def _seed_default_renderers() -> None:
    """Seed the registry with the V1 + V2 default renderers (idempotent).

    Imports of ``HTML5Renderer``, ``AdaptiveCardRenderer``, ``XFormsRenderer``,
    and ``PdfRenderer`` are deferred to avoid pulling Jinja2 / lxml /
    reportlab during ``import parrot_formdesigner.api``.

    All four renderers depend on hard deps (``jinja2``, ``lxml``,
    ``reportlab``) declared in ``pyproject.toml [project.dependencies]`` —
    if any of these imports fails, ``parrot-formdesigner`` is mis-installed
    and the loud ``ImportError`` is the right outcome.
    """
    from ..renderers.adaptive_card import AdaptiveCardRenderer
    from ..renderers.audio import AudioFormRenderer
    from ..renderers.html5 import HTML5Renderer
    from ..renderers.pdf import PdfRenderer
    from ..renderers.xforms import XFormsRenderer

    _RENDERERS.setdefault("html", HTML5Renderer())
    _RENDERERS.setdefault("adaptive", AdaptiveCardRenderer())
    _RENDERERS.setdefault("xml", XFormsRenderer())
    _RENDERERS.setdefault("pdf", PdfRenderer())
    _RENDERERS.setdefault("audio", AudioFormRenderer())

    # FEAT-544: "a2ui" is the ONE optional seed — ai-parrot is an optional
    # extra of parrot-formdesigner (unlike the hard deps above). Probe with
    # find_spec() first: A2UIFormRenderer itself imports parrot.* lazily
    # (TASK-3071), so a bare `except ImportError` around the constructor
    # call would only catch a failure that never actually surfaces here.
    #
    # Code review fix (TASK-3073): find_spec() on a dotted name RAISES
    # ModuleNotFoundError — it does not return None — when a parent package
    # earlier in the chain fails to import (e.g. "parrot" itself is entirely
    # absent, exactly the real "ai-parrot not installed" deployment this
    # guard exists for). An unguarded find_spec() call would crash
    # setup_form_api() at app startup instead of gracefully degrading.
    try:
        a2ui_available = importlib.util.find_spec("parrot.outputs.a2ui") is not None
    except (ImportError, ModuleNotFoundError):
        a2ui_available = False

    if a2ui_available:
        from ..renderers.a2ui import A2UIFormRenderer

        _RENDERERS.setdefault("a2ui", A2UIFormRenderer())
    else:
        logger.info("render dispatcher: 'a2ui' format unavailable (install parrot-formdesigner[ai-parrot])")


def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None:
    """Register (or overwrite) a renderer under ``format_key``.

    Args:
        format_key: The path-param value used in
            ``GET /api/v1/forms/{form_uid}/render/{format}``.
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


TEAMS_FORMAT_KEY: str = "teams"


def register_teams_renderer(
    *,
    public_base_url: str | None = None,
    api_base_path: str = "/api/v1",
    ui_base_path: str = "",
    signing_secret: str | None = None,
    renderer: AbstractFormRenderer | None = None,
) -> bool:
    """Register the MS Teams renderer under ``"teams"`` when a public base URL is resolvable (FEAT-551 M3).

    Returns:
        ``True`` when registered; ``False`` (logged at INFO) when neither ``renderer`` nor a public
        base URL (argument or env ``FORMDESIGNER_PUBLIC_URL``) is available — nothing is registered.
    """
    # Lazy import to keep `import parrot_formdesigner.api` light, same posture as _seed_default_renderers
    import os

    from ..renderers.teams import PUBLIC_URL_ENV, TeamsFormRenderer

    if renderer is None:
        if not (public_base_url or os.environ.get(PUBLIC_URL_ENV)):
            logger.info("register_teams_renderer: no public base URL — 'teams' format not registered")
            return False
        renderer = TeamsFormRenderer(
            public_base_url,
            api_base_path=api_base_path,
            ui_base_path=ui_base_path,
            signing_secret=signing_secret,
        )
    register_renderer(TEAMS_FORMAT_KEY, renderer)
    return True


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
    """GET /api/v1/forms/{form_uid}/render/{format} — render dispatcher.

    Looks up the renderer by ``format`` path-param. On miss returns 415 with
    ``{"supported": [...]}``. On hit, loads the form from
    ``request.app["form_registry"]`` and delegates to ``renderer.render(form)``.

    Args:
        request: Incoming aiohttp request.

    Returns:
        The rendered output with ``Content-Type`` set from the renderer.
    """
    form_uid = extract_form_uid(request)
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
        return web.json_response({"error": "form registry not configured"}, status=500)

    tenant = declared_tenant(request)
    form = await registry.get(form_uid, tenant=tenant)
    if form is None:
        return web.json_response({"error": f"Form '{form_uid}' not found"}, status=404)
    # FEAT-421 review fix: this route is mounted tenant="public" (the same
    # route serves public and private forms) — requires_tenant skipped
    # membership authorization at the decorator level because it can't
    # know the specific form's is_public flag before it's resolved. Close
    # that gap here: private forms still require membership; a truly
    # public form is exempt.
    enforce_membership_unless_public(request, form, tenant)

    locale = request.query.get("locale", "en")
    render_kwargs: dict[str, Any] = {"locale": locale}
    if getattr(renderer, "accepts_tenant", False):
        render_kwargs["tenant"] = tenant
    try:
        rendered = await renderer.render(form, **render_kwargs)
    except ValueError as exc:  # TeamsRenderConfigError is a ValueError
        logger.warning("render dispatcher: %s renderer refused: %s", format_key, exc)
        return web.json_response({"error": str(exc)}, status=400)

    # ?with_meta=true returns a JSON envelope with content, content_type, warnings, metadata.
    # Binary renderer output (e.g. PdfRenderer's raw PDF bytes) is not JSON-serialisable —
    # base64-encode it and flag that with `content_encoding` so callers know to decode it.
    if request.query.get("with_meta", "").lower() in ("1", "true", "yes"):
        content: Any = rendered.content
        content_encoding: str | None = None
        if isinstance(content, (bytes, bytearray, memoryview)):
            content = base64.b64encode(bytes(content)).decode("ascii")
            content_encoding = "base64"
        return web.json_response(
            {
                "content": content,
                "content_type": rendered.content_type,
                "content_encoding": content_encoding,
                "warnings": [w.model_dump(mode="json") for w in rendered.warnings],
                "metadata": rendered.metadata,
            }
        )

    body = _coerce_body(rendered.content)
    if isinstance(body, str):
        return web.Response(text=body, content_type=rendered.content_type)
    return web.Response(body=body, content_type=rendered.content_type)
