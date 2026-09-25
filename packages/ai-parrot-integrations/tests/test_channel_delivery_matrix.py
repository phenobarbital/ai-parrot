"""One presigned figure delivered through each FEAT-601 channel seam."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
from parrot.integrations.parser import parse_response
from parrot.integrations.slack.wrapper import SlackAgentWrapper
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

URL = "https://files.example/fig1.png?sig=x"


def _released() -> AIMessage:
    """Build the released procedure message produced by ``ProceduresAgent``."""
    return AIMessage(
        input="how do I assemble X",
        output="1. Fit the base plate.",
        model="procedures-service",
        provider="parrot",
        usage=CompletionUsage(),
        image_urls=[URL],
    )


def test_channel_delivery_matrix_teams() -> None:
    """Teams turns a presigned figure into an adaptive-card image section."""
    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.logger = MagicMock()
    spec = wrapper._parsed_to_card_spec(parse_response(_released()))
    assert any(getattr(entry, "url", None) == URL for section in spec.sections for entry in getattr(section, "images", []))


def test_channel_delivery_matrix_slack() -> None:
    """Slack emits one image block with the presigned URL."""
    blocks = SlackAgentWrapper._build_blocks(parse_response(_released()))
    assert any(block.get("type") == "image" and block.get("image_url") == URL for block in blocks)


@pytest.mark.asyncio
async def test_channel_delivery_matrix_telegram(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Telegram downloads the allowlisted URL and sends it as a photo."""
    TelegramAgentWrapper = pytest.importorskip(
        "parrot.integrations.telegram.wrapper",
        reason="Telegram wrapper requires the task environment's compiled parrot.utils.types extension",
    ).TelegramAgentWrapper

    image = tmp_path / "figure.png"
    image.write_bytes(b"png")

    @asynccontextmanager
    async def fake_download(*args, **kwargs):
        del args, kwargs
        yield image

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.bot = MagicMock(send_photo=AsyncMock())
    wrapper.logger = MagicMock()
    monkeypatch.setattr("parrot.integrations.telegram.wrapper.temp_download", fake_download)
    await wrapper._send_attachments(1, parse_response(_released()))
    wrapper.bot.send_photo.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_delivery_matrix_whatsapp() -> None:
    """WhatsApp forwards the presigned URL without downloading it locally."""
    from parrot.integrations.whatsapp.wrapper import WhatsAppAgentWrapper

    wrapper = WhatsAppAgentWrapper.__new__(WhatsAppAgentWrapper)
    wrapper.config = MagicMock(max_message_length=4096)
    wrapper.logger = MagicMock()
    client = MagicMock(send_image=MagicMock())
    await wrapper._send_parsed_response("+100", parse_response(_released()), client)
    client.send_image.assert_called_once_with(to="+100", image=URL)
