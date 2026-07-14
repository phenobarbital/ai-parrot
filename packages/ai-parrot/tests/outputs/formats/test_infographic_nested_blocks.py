"""Regression tests for nested-block rendering in InfographicHTMLRenderer.

Blocks nested inside a ``TabPane`` (``blocks``) or an ``AccordionItem``
(``content_blocks``) are typed ``List[Any]`` on the Pydantic models, so they
are never coerced into block models — they reach the renderer as raw dicts.

The renderer previously read the discriminator via ``getattr(block, "type")``,
which returns ``None`` for a dict, so every nested block was silently skipped
and tab panes / accordion bodies rendered empty (the AgentCrew infographic bug:
per-agent tabs and the executive summary appeared, but no content inside).

These tests lock in that the renderer coerces nested dict blocks into their
models and renders their content.
"""
import asyncio

from parrot.models.infographic import InfographicResponse
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


def _render(resp: InfographicResponse) -> str:
    r = InfographicHTMLRenderer()
    html, _ = asyncio.run(r.render(resp))
    return html


def test_tab_pane_dict_blocks_render_content():
    """SummaryBlock dicts inside tab panes must render their content."""
    resp = InfographicResponse(blocks=[
        {"type": "title", "title": "Crew Execution Report"},
        {"type": "tab_view", "tabs": [
            {
                "id": "executive-summary",
                "label": "Executive Summary",
                "blocks": [{"type": "summary", "content": "EXEC_SUMMARY_MARKER"}],
            },
            {
                "id": "final-result",
                "label": "Final Result",
                "blocks": [{"type": "summary", "content": "FINAL_RESULT_MARKER"}],
            },
            {
                "id": "agent-research",
                "label": "Research Agent",
                "blocks": [{"type": "summary", "content": "AGENT_TAB_MARKER"}],
            },
        ]},
    ])

    html = _render(resp)

    assert "EXEC_SUMMARY_MARKER" in html
    assert "FINAL_RESULT_MARKER" in html
    assert "AGENT_TAB_MARKER" in html


def test_accordion_item_dict_blocks_render_content():
    """content_blocks dicts inside accordion items must render their content."""
    resp = InfographicResponse(blocks=[
        {"type": "accordion", "items": [
            {
                "title": "Section One",
                "content_blocks": [
                    {"type": "summary", "content": "ACCORDION_BODY_MARKER"},
                ],
            },
            {
                "title": "Section Two",
                "content_blocks": [
                    {"type": "summary", "content": "ACCORDION_BODY_TWO"},
                ],
            },
        ]},
    ])

    html = _render(resp)

    assert "ACCORDION_BODY_MARKER" in html
    assert "ACCORDION_BODY_TWO" in html


def test_unknown_nested_block_type_is_skipped_gracefully():
    """An unknown nested block type must not raise — it is skipped."""
    resp = InfographicResponse(blocks=[
        {"type": "tab_view", "tabs": [
            {
                "id": "tab-a",
                "label": "A",
                "blocks": [
                    {"type": "bogus_type", "content": "ignored"},
                    {"type": "summary", "content": "GOOD_MARKER"},
                ],
            },
            {
                "id": "tab-b",
                "label": "B",
                "blocks": [{"type": "summary", "content": "OTHER_MARKER"}],
            },
        ]},
    ])

    html = _render(resp)

    assert "GOOD_MARKER" in html
    assert "OTHER_MARKER" in html
