"""MS Teams: an oversize answer is shrunk to fit, never dropped with an error."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("botbuilder")

from parrot.integrations.msteams.wrapper import (  # noqa: E402
    TEAMS_MAX_CARD_BYTES,
    TEAMS_MAX_TEXT_BYTES,
    MSTeamsAgentWrapper,
)
from parrot.integrations.parser import ParsedResponse  # noqa: E402
from parrot.outputs.cards import CardRenderError  # noqa: E402


def _markdown_table(n_rows: int, n_cols: int) -> str:
    """Build an agent answer holding a markdown table."""
    header = "| " + " | ".join(f"column_{c}" for c in range(n_cols)) + " |"
    separator = "|" + "---|" * n_cols
    rows = ["| " + " | ".join(f"val {r}-{c} 12,345.67" for c in range(n_cols)) + " |" for r in range(n_rows)]
    return "\n".join(["Here is the compliance summary:", "", header, separator, *rows, "", "Notes follow."])


def _wrapper() -> MSTeamsAgentWrapper:
    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.logger = MagicMock()
    wrapper.send_card = AsyncMock()
    wrapper.send_text = AsyncMock()
    return wrapper


def test_large_markdown_table_card_fits() -> None:
    """A 50x8 table (~43 KB as a card) is shrunk under the Teams limit."""
    wrapper = _wrapper()
    card = wrapper._build_adaptive_card(ParsedResponse(text=_markdown_table(50, 8)))
    assert len(json.dumps(card).encode("utf-8")) <= TEAMS_MAX_CARD_BYTES
    texts = [b.get("text", "") for b in card["body"] if b.get("type") == "TextBlock"]
    assert "Showing 15 of 50" in texts


@pytest.mark.asyncio
async def test_send_large_table_sends_card() -> None:
    """The oversize answer still goes out as a card."""
    wrapper = _wrapper()
    turn_context = MagicMock()
    await wrapper._send_parsed_response(ParsedResponse(text=_markdown_table(50, 8)), turn_context)
    wrapper.send_card.assert_awaited_once()
    wrapper.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_unfittable_card_falls_back_to_text() -> None:
    """When no card version fits, a plain-text reply is sent instead of raising."""
    wrapper = _wrapper()
    wrapper._build_adaptive_card = MagicMock(side_effect=CardRenderError("card size 99999 exceeds"))
    turn_context = MagicMock()
    await wrapper._send_parsed_response(ParsedResponse(text="hello world"), turn_context)
    wrapper.send_card.assert_not_awaited()
    wrapper.send_text.assert_awaited_once()
    sent_text = wrapper.send_text.await_args.args[0]
    assert "hello world" in sent_text


def test_fallback_text_is_cut_to_limit() -> None:
    """The text fallback stays under the byte budget, multi-byte chars included."""
    text = _wrapper()._build_fallback_text(ParsedResponse(text="ñandú " * 10_000))
    assert len(text.encode("utf-8")) <= TEAMS_MAX_TEXT_BYTES
    assert text.endswith("(response truncated to fit the message size limit)")
