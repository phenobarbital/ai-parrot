"""Dialect negotiation for the form contract endpoints (FEAT-650, spec §3 M2).

Effective dialect = ``?dialect=`` query > ``Accept: application/a2ui+json`` >
``form.dialect``. ``GET /forms/{uid}`` never consults this module.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from ..core import FormDialect
from ..core.schema import FormSchema, RenderedForm
from .render import get_renderer, supported_formats

logger = logging.getLogger(__name__)

A2UI_MEDIA_TYPE = "application/a2ui+json"
DIALECT_QUERY_PARAM = "dialect"
A2UI_LIST_MAX = int(os.environ.get("FORMDESIGNER_A2UI_LIST_MAX", "50"))
_SUPPORTED = [dialect.value for dialect in FormDialect]


class DialectError(Exception):
    """A negotiation failure with an HTTP status and JSON payload."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        """Initialize the negotiation failure.

        Args:
            status: HTTP status code, either 400 or 415.
            payload: JSON response body for the client.
        """
        super().__init__(payload.get("error") or f"dialect error {status}")
        self.status = status
        self.payload = payload


def resolve_dialect(request: web.Request, form: FormSchema) -> FormDialect:
    """Return the effective dialect for ``form`` on this request.

    Args:
        request: Incoming request whose query and Accept header are negotiated.
        form: Form whose stored dialect supplies the fallback.

    Raises:
        DialectError: When the query dialect is unknown or A2UI is unavailable.
    """
    raw = request.query.get(DIALECT_QUERY_PARAM)
    if raw is not None:
        try:
            dialect = FormDialect(raw)
        except ValueError as exc:
            raise DialectError(400, {"error": f"unknown dialect {raw!r}", "supported": _SUPPORTED}) from exc
    elif A2UI_MEDIA_TYPE in request.headers.get("Accept", ""):
        dialect = FormDialect.A2UI
    else:
        dialect = form.dialect

    if dialect is FormDialect.A2UI and get_renderer("a2ui") is None:
        raise DialectError(415, {"supported": supported_formats()})
    return dialect


async def render_a2ui_schema(
    form: FormSchema, *, locale: str = "en", overrides: Mapping[str, Any] | None = None
) -> tuple[list[dict[str, Any]], RenderedForm, list[str]]:
    """Render a form through the registered A2UI renderer.

    Args:
        form: Form schema to render.
        locale: BCP 47 locale passed to the renderer.
        overrides: Optional shallow schema overrides to translate.

    Returns:
        A tuple of A2UI envelopes, the raw renderer result, and warning strings.

    Raises:
        RuntimeError: If an A2UI renderer is not registered.
    """
    renderer = get_renderer("a2ui")
    if renderer is None:
        raise RuntimeError("render_a2ui_schema: no 'a2ui' renderer registered (install parrot-formdesigner[ai-parrot])")

    rendered = await renderer.render(form, locale=locale)
    envelopes: list[dict[str, Any]] = [rendered.content]
    warnings = [warning.reason for warning in rendered.warnings]
    if overrides:
        extra, extra_warnings = overrides_to_envelopes(form, rendered, overrides, locale=locale)
        envelopes.extend(extra)
        warnings.extend(extra_warnings)
    return envelopes, rendered, warnings


def overrides_to_envelopes(
    form: FormSchema,
    rendered: RenderedForm,
    overrides: Mapping[str, Any],
    *,
    locale: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Translate shallow schema overrides into A2UI envelopes.

    This baseline implementation reports every override as untranslatable.
    TASK-4193 implements the translation table while preserving this signature.

    Args:
        form: Source form schema.
        rendered: Existing A2UI render result.
        overrides: Shallow JSON Schema override mapping.
        locale: BCP 47 locale selected for rendering.

    Returns:
        No envelopes and one warning for every override key.
    """
    del form, rendered, locale
    return [], [f"override_not_translatable:{key}" for key in overrides]
