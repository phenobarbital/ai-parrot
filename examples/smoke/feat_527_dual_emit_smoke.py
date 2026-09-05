"""FEAT-527 smoke script — Infographic → A2UI dual-emit (offline).

Exercises `InfographicToolkit.render()` (typed blocks lane, the built-in
`financial_variance` template) and `render_template()` (the Jinja lane) with
`emit_a2ui=True` (the FEAT-527 default) and asserts BOTH lanes carry an
`html_url` **and** a validated `a2ui_envelope` — the dual-emit contract this
feature exists to guarantee.

Fully offline: no LLM calls, no network, no real artifact storage (a
`MagicMock` `ArtifactStore` stands in, same pattern as
`tests/tools/test_infographic_toolkit_a2ui_wiring.py`).

Usage:
    python examples/smoke/feat_527_dual_emit_smoke.py

Exit code 0 on success, 1 on any assertion/validation failure.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import ProducerOrigin
from parrot.outputs.a2ui.serialization import deserialize
from parrot.tools.infographic_toolkit import InfographicToolkit

# The spec §4 `variance_response`-shaped blocks, reordered to match the
# built-in "financial_variance" template's exact positional contract
# (title, 4x hero_card, 3x chart [half, half, full], summary) — see
# `parrot.models.infographic_templates.infographic_registry["financial_variance"]`.
_VARIANCE_BLOCKS = [
    {"type": "title", "title": "Q3 Variance", "subtitle": "May 14 - 27, 2026"},
    {"type": "hero_card", "label": "Revenue", "value": "$1.2M"},
    {
        "type": "hero_card",
        "label": "Revenue Variance",
        "value": "+8%",
        "trend": "up",
        "trend_value": "+8%",
    },
    {"type": "hero_card", "label": "EBITDA", "value": "$340K"},
    {
        "type": "hero_card",
        "label": "EBITDA DoD",
        "value": "-3%",
        "trend": "down",
        "trend_value": "-3%",
    },
    {
        "type": "chart",
        "chart_type": "bar",
        "layout": "half",
        "color_by_sign": True,
        "labels": ["Mon", "Tue"],
        "series": [{"name": "delta", "values": [10, -4]}],
    },
    {
        "type": "chart",
        "chart_type": "bar",
        "layout": "half",
        "color_by_sign": True,
        "labels": ["Mon", "Tue"],
        "series": [{"name": "delta", "values": [5, -2]}],
    },
    {
        "type": "chart",
        "chart_type": "line",
        "layout": "full",
        "labels": ["Mon", "Tue"],
        "series": [{"name": "cumulative", "values": [1180000, 1200000]}],
    },
    {"type": "summary", "content": "Revenue grew 8% week-over-week; EBITDA softened slightly."},
]


def _fake_artifact_store() -> MagicMock:
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return store


def _validated_surface(label: str, a2ui_envelope: dict) -> dict:
    """Deserialize the wire envelope and validate it as a TOOL-origin surface."""
    message = deserialize(a2ui_envelope)
    assert message.create_surface is not None, f"{label}: envelope has no createSurface"
    validate_envelope(message.create_surface, origin=ProducerOrigin.TOOL)
    return message.create_surface.components[0].component


async def main() -> int:
    print("=" * 72)
    print("FEAT-527 smoke: Infographic -> A2UI dual-emit (offline)")
    print("=" * 72)

    # -- Lane 1: typed blocks (render()) --------------------------------
    toolkit = InfographicToolkit(artifact_store=_fake_artifact_store())
    assert toolkit._emit_a2ui is True, "emit_a2ui must default to True (FEAT-527)"

    res = await toolkit.render(
        template_name="financial_variance",
        theme="light",
        mode="deterministic",
        data_variables=[],
        blocks=_VARIANCE_BLOCKS,
    )
    assert res.html_url, "render(): html_url must be set"
    assert res.a2ui_envelope, "render(): a2ui_envelope must be set (dual-emit)"
    root_component = _validated_surface("render()", res.a2ui_envelope)
    assert root_component == "Infographic", f"render(): expected Infographic root, got {root_component}"
    print(f"[render()]          html_url={res.html_url}")
    print(f"[render()]          a2ui root component = {root_component!r}")
    print(f"[render()]          a2ui surfaceId       = {res.a2ui_envelope['createSurface']['surfaceId']!r}")

    # -- Lane 2: Jinja template (render_template()) ---------------------
    toolkit2 = InfographicToolkit(
        artifact_store=_fake_artifact_store(),
        templates={"hello": "<html><body><h1>{{ data.title }}</h1></body></html>"},
    )
    res2 = await toolkit2.render_template("hello", data={"title": "Hi"})
    assert res2.html_url, "render_template(): html_url must be set"
    assert res2.a2ui_envelope, "render_template(): a2ui_envelope must be set (dual-emit)"
    root_component2 = _validated_surface("render_template()", res2.a2ui_envelope)
    assert root_component2 == "HtmlDocument", (
        f"render_template(): expected HtmlDocument root, got {root_component2}"
    )
    print(f"[render_template()]  html_url={res2.html_url}")
    print(f"[render_template()]  a2ui root component = {root_component2!r}")
    print(f"[render_template()]  a2ui surfaceId       = {res2.a2ui_envelope['createSurface']['surfaceId']!r}")

    print("-" * 72)
    print("FEAT-527 smoke: OK - both lanes dual-emit (html_url + validated a2ui_envelope)")
    print("-" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
