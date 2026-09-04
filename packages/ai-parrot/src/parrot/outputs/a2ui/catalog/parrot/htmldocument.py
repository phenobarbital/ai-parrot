"""A2UI ``HtmlDocument`` catalog component (Module 5, FEAT-527).

An opaque, display-only wrapper around a TRUSTED, already-rendered HTML
document (the Jinja `render_template`/`render_data_template` lane — spec G5,
resolved U4). ``tool_only=True``: only deterministic tool builders
(:func:`~parrot.outputs.a2ui.builders.build_html_document`) may emit this
component — an LLM-origin envelope containing it fails
:func:`~parrot.outputs.a2ui.catalog.validate_envelope` (the same gate
mechanism as ``requires_actions``, TASK-2862). This is a security boundary:
the raw ``html`` is never LLM-authorable and never copied into the lowered
Basic Catalog tree — static renderers must not echo it; only a renderer that
can safely embed it (sandboxed iframe) reads ``component.model_extra["html"]``
directly, before lowering (TASK-2865).
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

HTMLDOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "html": {
            "type": "string",
            "description": "Trusted, fully rendered HTML document (inline when < 50 KB).",
        },
        "srcUrl": {
            "type": "string",
            "description": "Signed artifact URL when the document is too large to inline.",
        },
        "theme": {"type": "string"},
    },
    "required": ["title"],
    "oneOf": [{"required": ["html"]}, {"required": ["srcUrl"]}],
}

HTMLDOCUMENT_INSTRUCTIONS = (
    "HtmlDocument is tool-only and display-only: it is NEVER LLM-authored. "
    "Deterministic tool builders (build_html_document) emit it to wrap a "
    "trusted, already-rendered HTML document (e.g. the Jinja render_template "
    "lane) as an opaque A2UI surface. Provide `title` and exactly one of "
    "`html` (inline, < 50 KB) or `srcUrl` (signed artifact URL); optional `theme`."
)


@register_component("HtmlDocument", allowed_parents=["root", "Column"], tool_only=True)
class HtmlDocumentComponent:
    """The ``HtmlDocument`` catalog component (tool-only, display-only)."""

    SCHEMA = HTMLDOCUMENT_SCHEMA
    INSTRUCTIONS = HTMLDOCUMENT_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower to a title Text + a titled placeholder Text — never the raw HTML.

        The placeholder carries ``metadata.extensions`` (``parrot_role:
        "html_document"``, ``parrot_src_url``, ``parrot_inline_html``) so a
        renderer that can safely embed the document (sandboxed iframe) knows
        to look at the ORIGINAL, not-yet-lowered component's ``html``/
        ``srcUrl`` instead of this static degradation.
        """
        props = component.model_extra or {}
        title = props.get("title", "")
        src_url = props.get("srcUrl")
        children: list[BasicNode] = [
            BasicNode(component="Text", text=title, metadata={"extensions": {"parrot_role": "title"}}),
            BasicNode(
                component="Text",
                text=f"[HTML document: {title}]",
                metadata={
                    "extensions": {
                        "parrot_role": "html_document",
                        "parrot_src_url": src_url,
                        "parrot_inline_html": props.get("html") is not None,
                    }
                },
            ),
        ]
        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "html-document"}},
        )
