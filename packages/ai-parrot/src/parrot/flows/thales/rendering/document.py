"""Final-document composition + optional PDF rasterization (FEAT-425 Module 4).

Pure, deterministic print-CSS composition. Optional real-``.pdf`` emission
via a lazily-imported ``weasyprint`` (mirrors the ``_import_weasyprint``
pattern at ``a2ui_renderers/pdf.py:36``) — the ``pdf`` extra stays optional
and its absence is never fatal (spec AC).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.flows.thales.models import Bibliography
from parrot.template.engine import TemplateEngine

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_engine: TemplateEngine | None = None


def _get_engine() -> TemplateEngine:
    """Lazily construct the module-level :class:`TemplateEngine` singleton."""
    global _engine
    if _engine is None:
        _engine = TemplateEngine(template_dirs=_TEMPLATES_DIR)
    return _engine


def _import_weasyprint() -> Any | None:
    """Lazily import ``weasyprint`` (indirection point so tests can force absence).

    Returns:
        The ``weasyprint`` module, or ``None`` when it is not installed.
    """
    try:
        import weasyprint
    except ImportError:
        return None
    return weasyprint


async def render_document(
    slides_html: list[str],
    bibliography: Bibliography,
    *,
    title: str,
) -> str:
    """Compose the final print-CSS HTML document.

    Args:
        slides_html: Already-rendered slide HTML fragments (see
            :func:`~parrot.flows.thales.rendering.slides.render_slide`), in
            display order.
        bibliography: The deduplicated, APA-ish formatted bibliography —
            always rendered as the document's final section.
        title: The document title.

    Returns:
        Deterministic HTML: ``@page`` rules, a page-break after every
        slide, and the bibliography as the last section.
    """
    return await _get_engine().render(
        "document.html.j2",
        {
            "title": title,
            "slides_html": slides_html,
            "bibliography_entries": list(bibliography.entries),
        },
    )


def rasterize_pdf(html: str) -> bytes | None:
    """Rasterize a final-document HTML string to PDF bytes via weasyprint.

    Weasyprint executes no JavaScript, so charts in ``html`` must already
    be the static-SVG variant for this to render correctly (handled by
    :mod:`~parrot.flows.thales.rendering.slides`, which always emits both
    paths).

    Args:
        html: The document HTML (see :func:`render_document`).

    Returns:
        PDF bytes, or ``None`` (with a warning logged) when weasyprint is
        not importable.
    """
    weasyprint = _import_weasyprint()
    if weasyprint is None:
        logger.warning(
            "weasyprint is not installed — skipping .pdf rasterization "
            "(install the 'pdf' extra to enable it)."
        )
        return None
    return weasyprint.HTML(string=html).write_pdf()
