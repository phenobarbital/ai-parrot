"""Tests for Telegram suggestion buttons (FEAT-752, TASK-4809)."""

import json
import time

import pytest

from parrot.integrations.telegram.callbacks import CallbackData
from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.integrations.telegram.suggestion_buttons import (
    SUGGESTION_PREFIX,
    SuggestionButtonStore,
    build_suggestion_keyboard,
)
from parrot.models import Suggestion


def test_config_defaults_off():
    cfg = TelegramAgentConfig.from_dict("b", {"chatbot_id": "bot", "bot_token": "x"})
    assert cfg.suggestion_buttons is False and cfg.suggestion_button_ttl_s == 86400


def test_config_reads_both_fields():
    cfg = TelegramAgentConfig.from_dict(
        "b", {"chatbot_id": "bot", "bot_token": "x", "suggestion_buttons": True, "suggestion_button_ttl_s": "60"}
    )
    assert cfg.suggestion_buttons is True and cfg.suggestion_button_ttl_s == 60


@pytest.mark.asyncio
async def test_keyboard_skips_actions_and_caps():
    store = SuggestionButtonStore()
    chips = [Suggestion(label=f"Chip {i}", prompt=f"p{i}") for i in range(8)]
    chips.append(Suggestion(label="Explain this", prompt="Explain", kind="action", action="explain"))
    kb = await build_suggestion_keyboard(chips, store, chat_id=1, user_id=2)
    buttons = [b for row in kb["inline_keyboard"] for b in row]
    assert len(buttons) == 6 and all(len(r) <= 2 for r in kb["inline_keyboard"])
    assert "Explain this" not in [b["text"] for b in buttons]
    for b in buttons:
        assert len(b["callback_data"].encode()) <= CallbackData.MAX_BYTES
        prefix, payload = CallbackData.decode(b["callback_data"])
        assert prefix == SUGGESTION_PREFIX == "sg"
        assert set(payload) == {"raw"}
        assert await store.get(payload["raw"]) is not None


@pytest.mark.asyncio
async def test_keyboard_none_when_only_actions_or_empty():
    store = SuggestionButtonStore()
    only_action = [Suggestion(label="Explain this", prompt="Explain", kind="action", action="explain")]
    assert await build_suggestion_keyboard(only_action, store, chat_id=1, user_id=2) is None
    assert await build_suggestion_keyboard([], store, chat_id=1, user_id=2) is None


@pytest.mark.asyncio
async def test_keyboard_truncates_label_and_accepts_dicts_and_modes():
    store = SuggestionButtonStore()
    long_label = "x" * 60
    chips = [
        {"label": long_label, "prompt": "p", "output_mode": "card", "kind": "presentation"},
        Suggestion(label="Table", prompt="t", output_mode="structured_table", kind="presentation"),
    ]
    kb = await build_suggestion_keyboard(chips, store, chat_id=5, user_id=6)
    buttons = [b for row in kb["inline_keyboard"] for b in row]
    assert len(buttons[0]["text"]) == 40
    token0 = CallbackData.decode(buttons[0]["callback_data"])[1]["raw"]
    record = await store.get(token0)
    assert record == {"prompt": "p", "output_mode": "card", "chat_id": 5, "user_id": 6}
    token1 = CallbackData.decode(buttons[1]["callback_data"])[1]["raw"]
    assert (await store.get(token1))["output_mode"] == "structured_table"


def test_tokens_never_parse_as_json_numbers():
    # a purely numeric token would make CallbackData.decode return an int instead of {"raw": ...}
    for _ in range(2000):
        token = SuggestionButtonStore._new_token()
        assert len(token) == 12
        with pytest.raises(json.JSONDecodeError):
            json.loads(token)
    assert CallbackData.decode("sg:123456789012")[1] == 123456789012  # documents the hazard the prefix avoids


@pytest.mark.asyncio
async def test_store_round_trip_unknown_and_corrupt():
    store = SuggestionButtonStore()
    token = await store.put(prompt="p", output_mode=None, chat_id=1, user_id=2)
    assert await store.get(token) == {"prompt": "p", "output_mode": None, "chat_id": 1, "user_id": 2}
    assert await store.get("nope") is None

    await store._store.set(store._key("bad"), "not json")
    assert await store.get("bad") is None
    await store._store.set(store._key("list"), "[1, 2]")
    assert await store.get("list") is None


@pytest.mark.asyncio
async def test_store_expiry(monkeypatch):
    store = SuggestionButtonStore(ttl_s=1)
    token = await store.put(prompt="p", output_mode=None, chat_id=1, user_id=2)
    assert await store.get(token) is not None
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + 5)
    assert await store.get(token) is None
