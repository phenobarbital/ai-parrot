"""Unit tests for AnthropicClient vision parity (FEAT-574, spec Module 4). Offline: SDK mocked."""

from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot.clients.anthropic import AnthropicClient
from parrot.clients.anthropic.models import ClaudeModel
from parrot.memory.render import HistoryMessage


def _response(text: str) -> MagicMock:
    """Build a mocked SDK response whose ``model_dump()`` carries one text block."""
    resp = MagicMock()
    resp.model_dump.return_value = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-5",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    return resp


def _make_client(texts: list[str], **kwargs) -> tuple[AnthropicClient, MagicMock]:
    """An AnthropicClient whose SDK answers ``texts`` in order."""
    client = AnthropicClient(api_key="fake_key", **kwargs)
    client.logger = MagicMock()
    sdk = MagicMock()
    responses = iter([_response(t) for t in texts])
    sdk.payloads = []

    async def _create(**payload):
        # Snapshot: ask_to_image appends the assistant reply to the same list after the call.
        sdk.payloads.append(copy.deepcopy(payload))
        return next(responses)

    sdk.messages.create = AsyncMock(side_effect=_create)
    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=sdk)
    client._backend.translate_model = lambda m: m
    return client, sdk


@pytest.fixture
def image() -> Image.Image:
    """A small white RGB image (200x100)."""
    return Image.new("RGB", (200, 100), "white")


HISTORY = [
    HistoryMessage(role="user", content="earlier question"),
    HistoryMessage(role="assistant", content="earlier answer"),
]


async def test_ask_to_image_no_memory_skips_history(image):
    """no_memory=True ⇒ payload messages == [user multimodal turn] even when history is given."""
    client, sdk = _make_client(["ok"])
    await client.ask_to_image(prompt="what?", image=image, history=HISTORY, no_memory=True)
    messages = sdk.payloads[-1]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert any(block.get("type") == "image" for block in messages[0]["content"])


async def test_ask_to_image_replays_history_by_default(image):
    """no_memory=False ⇒ rendered history precedes the image turn (len(messages) > 1)."""
    client, sdk = _make_client(["ok"])
    await client.ask_to_image(prompt="what?", image=image, history=HISTORY)
    messages = sdk.payloads[-1]["messages"]
    assert len(messages) == 3
    assert messages[0]["content"][0]["text"] == "earlier question"
    assert messages[-1]["role"] == "user"


@pytest.mark.parametrize(
    "ctor_model, call_model, expected",
    [
        (None, None, "claude-sonnet-5"),
        ("claude-opus-4-8", None, "claude-opus-4-8"),
        ("claude-opus-4-8", ClaudeModel.SONNET_4, "claude-sonnet-4-20250514"),
    ],
)
async def test_ask_to_image_model_resolution(image, ctor_model, call_model, expected):
    """explicit > client model > SONNET_5; payload["model"] and AIMessage.model agree."""
    kwargs = {"model": ctor_model} if ctor_model else {}
    client, sdk = _make_client(["ok"], **kwargs)
    message = await client.ask_to_image(prompt="what?", image=image, model=call_model)
    assert sdk.payloads[-1]["model"] == expected
    assert message.model == expected


async def test_detect_objects_shape(image):
    """Normalised boxes are converted to original pixels; degenerate boxes are dropped."""
    answer = json.dumps(
        {
            "objects": [
                {"label": "a", "box_2d": [100, 250, 500, 750], "confidence": 0.9},
                {"label": "bad", "box_2d": [500, 500, 500, 900]},
            ]
        }
    )
    client, sdk = _make_client([answer])
    got = await client.detect_objects(image, "find things")
    assert got == [
        {"label": "a", "box_2d": [50, 10, 150, 50], "confidence": 0.9, "mask_image": None, "overlay_image": None}
    ]
    # detect_objects never replays history.
    assert len(sdk.payloads[-1]["messages"]) == 1


async def test_detect_objects_bad_answer_returns_empty(image, tmp_path):
    """Non-JSON answer ⇒ []; output_dir is created and stays empty."""
    client, _ = _make_client(["this is not json at all"])
    out = tmp_path / "x"
    got = await client.detect_objects(image, "find things", output_dir=out)
    assert got == []
    assert out.is_dir()
    assert list(out.iterdir()) == []


async def test_detect_objects_failed_call_returns_empty(image):
    """An SDK failure is logged and yields [] (Google parity)."""
    client, sdk = _make_client([])
    sdk.messages.create = AsyncMock(side_effect=RuntimeError("network down"))
    assert await client.detect_objects(image, "find things") == []
    client.logger.error.assert_called()
