"""Deterministic deck renderer for the "Thales" research flow (FEAT-425 Module 4).

Pure Python rendering only — no LLM anywhere in this package (spec G4).
``SlideSpec`` renders to slide HTML (:mod:`.slides`); slides + a
``Bibliography`` compose one print-CSS final document, with an optional
real ``.pdf`` via lazy ``weasyprint`` (:mod:`.document`). Charts follow the
FEAT-273/SPK-1 convention: ECharts option-JSON for the browser path,
static SVG for anything that must survive weasyprint (:mod:`.charts`).
"""

from __future__ import annotations

from parrot.flows.thales.rendering.charts import echarts_option_block, static_svg_chart
from parrot.flows.thales.rendering.document import rasterize_pdf, render_document
from parrot.flows.thales.rendering.slides import render_slide

__all__ = [
    "echarts_option_block",
    "rasterize_pdf",
    "render_document",
    "render_slide",
    "static_svg_chart",
]
