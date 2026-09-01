"""Shared document shell for A2UI HTML renderers (FEAT-493, TASK-2709).

Both :class:`~parrot.outputs.a2ui_renderers.interactive_html.InteractiveHTMLRenderer`
and :class:`~parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer` used to
build their document inline, each with its own hardcoded stylesheet and
neither emitting a viewport meta tag. This module extracts the one shared
shell both call, so the design system's ``div.ds-page[data-layout]
[data-theme]`` wrapper and viewport meta tag are consistent across every
backend-rendered HTML lane.
"""
from __future__ import annotations

import html
from collections.abc import Sequence


def document_shell(
    *,
    title: str,
    style: str,
    body: str,
    theme: str,
    layout: str,
    scripts: Sequence[str] = (),
) -> str:
    """Build a complete, self-contained HTML document.

    Args:
        title: Document title, HTML-escaped.
        style: The composed CSS (from
            :class:`~parrot.outputs.formats.assets.design_system.DesignSystem`)
            to inline in a single ``<style>`` block.
        body: Already-rendered HTML body content.
        theme: The resolved theme name, exposed as ``data-theme`` on the
            page wrapper so layout/theme CSS (and an embedding container)
            can scope themselves without a bespoke ``:root``.
        layout: The resolved layout name, exposed as ``data-layout``.
        scripts: Complete, already-formed ``<script ...>...</script>``
            (or ``<script type="application/json" ...>...</script>``)
            HTML strings, emitted verbatim, in order, after the page
            wrapper closes. Each caller is responsible for its own script
            tag attributes (e.g. ``id="report-data"``,
            ``type="application/json"``).

    Returns:
        A complete ``"<!DOCTYPE html>...</html>"`` document string.
    """
    scripts_html = "".join(scripts)
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{style}</style></head>"
        f'<body><div class="ds-page" data-layout="{html.escape(layout)}" '
        f'data-theme="{html.escape(theme)}">{body}</div>'
        f"{scripts_html}"
        "</body></html>"
    )
