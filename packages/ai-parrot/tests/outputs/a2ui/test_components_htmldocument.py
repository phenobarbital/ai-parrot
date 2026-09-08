"""Golden + contract tests for HtmlDocument (FEAT-527).

HtmlDocument is tool-only (TASK-2862's gate) — an opaque wrapper around a
trusted, already-rendered HTML document (the Jinja `render_template` lane,
spec G5). Its lowering never embeds the raw HTML string.
"""

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui.builders import build_html_document
from parrot.outputs.a2ui.catalog import get_component, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError, ProducerOrigin
from parrot.outputs.a2ui.catalog.parrot import htmldocument
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _htmldocument_component() -> Component:
    return Component(
        id="blk-000",
        component="HtmlDocument",
        title="Q1 Report",
        html="<html><body>Q1 numbers</body></html>",
    )


class TestHtmlDocumentComponent:
    def test_registration_flags(self):
        entry = get_component("HtmlDocument")
        assert entry.definition.tool_only is True
        assert entry.definition.requires_actions is False
        assert entry.definition.allowed_parents == ["root", "Column"]

    def test_lowering_golden(self):
        comp = _htmldocument_component()
        one = _dump(htmldocument.HtmlDocumentComponent().lower(comp, {}))
        two = _dump(htmldocument.HtmlDocumentComponent().lower(comp, {}))
        assert one == two == (GOLDEN_DIR / "htmldocument_lowered.json").read_bytes()

    def test_lowering_never_embeds_html(self):
        comp = Component(id="blk-001", component="HtmlDocument", title="R", html="<script>evil()</script>")
        tree = get_component("HtmlDocument").component_cls().lower(comp, {})
        assert "evil()" not in tree.model_dump_json()

    def test_lowering_carries_title_and_placeholder(self):
        tree = htmldocument.HtmlDocumentComponent().lower(_htmldocument_component(), {})
        assert tree.component == "Card"
        texts = tree.child.children
        assert texts[0].text == "Q1 Report"
        assert texts[1].text == "[HTML document: Q1 Report]"
        assert texts[1].metadata.extensions.root["parrot_role"] == "html_document"

    def test_lowering_src_url_recorded_in_extensions(self):
        comp = Component(id="blk-002", component="HtmlDocument", title="R", srcUrl="https://x/r.html")
        tree = htmldocument.HtmlDocumentComponent().lower(comp, {})
        placeholder = tree.child.children[1]
        assert placeholder.metadata.extensions.root["parrot_src_url"] == "https://x/r.html"
        assert placeholder.metadata.extensions.root["parrot_inline_html"] is False


class TestBuildHtmlDocument:
    def test_builder_inline_and_url(self):
        env = build_html_document(title="Report", html="<html><body>x</body></html>")
        assert env.components[0].component == "HtmlDocument"
        env2 = build_html_document(title="Report", src_url="https://x/infographic-a.html")
        assert env2.components[0].model_extra["srcUrl"].endswith(".html")

    def test_builder_xor(self):
        with pytest.raises(ValueError):
            build_html_document(title="R")
        with pytest.raises(ValueError):
            build_html_document(title="R", html="<p/>", src_url="https://x")

    def test_llm_origin_rejected(self):
        env = build_html_document(title="R", html="<p>hi</p>")
        with pytest.raises(CatalogValidationError):
            validate_envelope(env, origin=ProducerOrigin.LLM)

    def test_tool_origin_accepted(self):
        env = build_html_document(title="R", html="<p>hi</p>")
        validate_envelope(env, origin=ProducerOrigin.TOOL)  # must not raise
