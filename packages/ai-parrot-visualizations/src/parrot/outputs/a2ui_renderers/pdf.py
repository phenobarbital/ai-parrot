"""PDF renderer (Module 5, satellite) — SPK-1 backend = weasyprint.

Closes the G5 static-delivery chain: envelope → baked SSR-HTML (TASK-1729) → static-SVG
chart pre-render → weasyprint rasterization → ``RenderedArtifact`` (PDF) suitable as a
``send_notification`` email attachment.

SPK-1 (TASK-1722) confirmed **weasyprint** as the default for all static artifact
classes (deterministic, no browser). weasyprint runs no JavaScript, so Chart components
are pre-rendered to **static SVG** (deterministic data→SVG) before rasterization — no
JS, no ``exec``. No playwright path is shipped (SPK-1 did not require a per-class split).
"""

from __future__ import annotations

import asyncio
import html
import logging

import parrot.outputs.a2ui.catalog.components  # noqa: F401 — ensure registration
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    register_a2ui_renderer,
)
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

logger = logging.getLogger(__name__)

_SURFACE_NAME = "pdf"
_PDF_EXTRA = "ai-parrot-visualizations[a2ui-pdf]"


def _import_weasyprint():
    """Import weasyprint's ``HTML`` (indirection point so tests can force failure)."""
    from weasyprint import HTML  # noqa: PLC0415 — lazy by design

    return HTML


def _load_weasyprint():
    """Lazily load weasyprint with an actionable error naming the extra."""
    try:
        return _import_weasyprint()
    except ImportError as exc:
        raise ImportError(
            "The A2UI pdf renderer requires weasyprint. "
            f"Install it with: pip install {_PDF_EXTRA}"
        ) from exc


def _chart_svg(props: dict) -> str:
    """Build a deterministic static SVG bar chart from baked Chart data (no JS)."""
    rows = props.get("data") or []
    if not isinstance(rows, list):
        rows = []
    x = props.get("x")
    y_cols = props.get("y") or []
    y = y_cols[0] if y_cols else None
    points = [r for r in rows if isinstance(r, dict)]
    values = [r.get(y) for r in points] if y else []
    numeric = [v for v in values if isinstance(v, (int, float))]
    max_v = max(numeric) if numeric else 1
    max_v = max_v or 1

    width, height, pad = 400, 200, 30
    bar_w = (width - 2 * pad) / max(len(points), 1)
    bars = []
    for i, row in enumerate(points):
        val = row.get(y) if y else 0
        val = val if isinstance(val, (int, float)) else 0
        h = (height - 2 * pad) * val / max_v
        bx = pad + i * bar_w
        by = height - pad - h
        label = html.escape(str(row.get(x, "")))
        bars.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w * 0.7:.1f}" '
            f'height="{h:.1f}" fill="#3b7dd8"/>'
            f'<text x="{bx:.1f}" y="{height - pad + 14:.1f}" font-size="10">{label}</text>'
        )
    title = html.escape(str(props.get("title", "")))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'role="img" aria-label="{title}">' + "".join(bars) + "</svg>"
    )


@register_a2ui_renderer(
    _SURFACE_NAME,
    RendererCapabilities(
        interactive=False,
        supports_actions=False,
        supports_updates=False,
        output="application/pdf",
    ),
)
class PDFRenderer(AbstractA2UIRenderer):
    """weasyprint-backed PDF renderer (SSR-HTML → static SVG charts → PDF)."""

    async def render(
        self,
        envelope: CreateSurface,
        *,
        bake: bool = True,
        deep_links=None,
    ) -> RenderedArtifact:
        """Render an envelope to a PDF ``RenderedArtifact`` (weasyprint)."""
        document = await self._build_intermediate_html(envelope, deep_links=deep_links)
        # weasyprint's write_pdf is blocking — run it off the event loop.
        pdf_bytes = await asyncio.to_thread(self._rasterize, document)
        return RenderedArtifact(
            artifact_id=f"{_SURFACE_NAME}-{envelope.surface_id}",
            mime_type="application/pdf",
            content=pdf_bytes,
            filename=f"{envelope.surface_id}.pdf",
            title=envelope.surface_id,
            surface=_SURFACE_NAME,
            deep_links=list(deep_links or []),
        )

    async def _build_intermediate_html(self, envelope: CreateSurface, *, deep_links=None) -> str:
        """Produce the baked, self-contained HTML fed to weasyprint (charts as SVG)."""
        ssr_artifact = await SSRHTMLRenderer().render(envelope, deep_links=deep_links)
        document = ssr_artifact.content.decode("utf-8")

        # Pre-render Chart components to static SVG (weasyprint runs no JS).
        baked = bake_envelope(envelope)
        svgs = "".join(
            _chart_svg(bc["properties"]) for bc in baked if bc["component"] == "Chart"
        )
        if svgs:
            document = document.replace("</body>", f'<div class="a2ui-charts">{svgs}</div></body>')
        return document

    def _rasterize(self, document: str) -> bytes:
        """Rasterize an HTML document to PDF bytes with weasyprint (blocking)."""
        html_cls = _load_weasyprint()
        return html_cls(string=document).write_pdf()
