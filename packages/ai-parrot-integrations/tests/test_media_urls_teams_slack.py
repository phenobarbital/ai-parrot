"""FEAT-601 M12 — Teams/Slack render ParsedResponse.image_urls (TASK-3717)."""

from __future__ import annotations

import logging

import pytest

from parrot.integrations.parser import ParsedResponse
from parrot.integrations.slack.wrapper import SlackAgentWrapper

URLS = [f"https://cdn.example/fig{i}.png" for i in range(1, 5)]


def test_slack_renders_image_urls() -> None:
    """One image block per URL, after any Path image blocks."""
    blocks = SlackAgentWrapper._build_blocks(ParsedResponse(text="t", image_urls=URLS))
    image_blocks = [b for b in blocks if b.get("type") == "image"]
    assert len(image_blocks) == 4
    for i, block in enumerate(image_blocks):
        assert block["image_url"] == URLS[i]
        assert block["alt_text"] == f"Figure {i + 1}"


def test_slack_path_only_output_unchanged() -> None:
    """ParsedResponse without URLs yields the same blocks as before (no extra blocks)."""
    blocks = SlackAgentWrapper._build_blocks(ParsedResponse(text="t"))
    # No image_urls / media_urls provided ⇒ no extra image/context blocks introduced.
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"


def test_slack_assistant_paths_render_url() -> None:
    """slack/assistant.py:185 and :238 both call wrapper._build_blocks — assert a URL survives that call."""

    class _FakeWrapper:
        _build_blocks = staticmethod(SlackAgentWrapper._build_blocks)

    fake_wrapper = _FakeWrapper()
    parsed = ParsedResponse(text="t", image_urls=URLS[:1])
    blocks = fake_wrapper._build_blocks(parsed)
    image_blocks = [b for b in blocks if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"] == URLS[0]


def test_slack_renders_media_urls_as_context_links() -> None:
    """media_urls render as one context block with mrkdwn video links."""
    blocks = SlackAgentWrapper._build_blocks(ParsedResponse(text="t", media_urls=["https://cdn.example/clip.mp4"]))
    context_blocks = [b for b in blocks if b.get("type") == "context"]
    assert len(context_blocks) == 1
    assert context_blocks[0]["elements"][0]["text"] == "<https://cdn.example/clip.mp4|Video 1>"


def test_teams_renders_image_urls_cap3_with_overflow_links() -> None:
    """4 URLs ⇒ 3 ImageEntry in the ImageSection + 1 labelled link TextSection."""
    pytest.importorskip("botbuilder")
    from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
    from parrot.outputs.cards import ImageSection, TextSection

    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.logger = logging.getLogger("test")

    spec = wrapper._parsed_to_card_spec(ParsedResponse(text="t", image_urls=URLS))

    image_sections = [s for s in spec.sections if isinstance(s, ImageSection)]
    assert len(image_sections) == 1
    assert len(image_sections[0].images) == 3
    assert [img.url for img in image_sections[0].images] == URLS[:3]

    overflow_sections = [s for s in spec.sections if isinstance(s, TextSection) and "[Figure 4]" in s.text]
    assert len(overflow_sections) == 1
    assert f"[Figure 4]({URLS[3]})" in overflow_sections[0].text


def test_teams_path_only_output_unchanged() -> None:
    """No image_urls/media_urls ⇒ no overflow-link TextSection is added."""
    pytest.importorskip("botbuilder")
    from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
    from parrot.outputs.cards import TextSection

    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.logger = logging.getLogger("test")

    spec = wrapper._parsed_to_card_spec(ParsedResponse(text="t"))
    overflow_sections = [s for s in spec.sections if isinstance(s, TextSection) and "Figure" in s.text]
    assert overflow_sections == []
