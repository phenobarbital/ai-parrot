"""JSON Schema (legacy dialect) → A2UI createSurface by composition (FEAT-650, spec §3 M4)."""

from __future__ import annotations

import logging
from typing import Any

from ..core.schema import RenderedForm
from ..extractors import JsonSchemaExtractor
from ..renderers.base import AbstractFormRenderer

logger = logging.getLogger(__name__)


async def translate_jsonschema_to_a2ui(
    schema: dict[str, Any],
    *,
    form_id: str | None = None,
    title: str | None = None,
    tenant: str | None = None,
    locale: str = "en",
    renderer: AbstractFormRenderer | None = None,
) -> RenderedForm:
    """``JsonSchemaExtractor.extract`` → tenant stamp → ``A2UIFormRenderer.render``.

    Args:
        schema: A JSON Schema document (typically ``JsonSchemaRenderer`` output).
        form_id: Slug for the resulting form (default ``"form"``).
        title: Title override.
        tenant: Stamped on the FormSchema so the surface's submit URL and
            ``parrot_tenant`` carry the caller's tenant (never read from the document).
        locale: BCP 47 tag for label resolution.
        renderer: Injected renderer (tests); default = the registered ``"a2ui"`` one.

    Raises:
        RuntimeError: When no ``"a2ui"`` renderer is available (ai-parrot extra missing).

    Returns:
        The rendered A2UI form.
    """
    if renderer is None:
        from ..api.render import get_renderer  # lazy: avoid api↔services import cycle

        renderer = get_renderer("a2ui")
        if renderer is None:
            raise RuntimeError("translate_jsonschema_to_a2ui requires the 'ai-parrot' extra")
    form = JsonSchemaExtractor().extract(schema, form_id=form_id, title=title)
    if tenant is not None:
        form = form.model_copy(update={"tenant": tenant})
    logger.debug("translate_jsonschema_to_a2ui: %s sections, tenant=%s", len(form.sections), tenant)
    return await renderer.render(form, locale=locale)
