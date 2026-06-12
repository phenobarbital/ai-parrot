"""Unit tests for the prompt fine-tuning handler (``PromptTunerHandler``).

Testing approach mirrors the rest of the server suite: drive the handler's
pure helper methods directly with a fake bot wrapping a *real* ``PromptBuilder``
so we exercise the override/render/apply logic without a full aiohttp server.

Covers:
- semantic-field edits regenerate their feeding layer from the pristine
  template (role -> identity, rationale -> behavior),
- raw layer-template overrides win and are applied verbatim,
- preview rendering never mutates the live bot,
- ``_apply_draft_to`` mutates the live bot + its builder in place,
- the session draft round-trips through ``_load_draft`` / ``_store_draft``.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from parrot.bots.prompts.builder import PromptBuilder
from parrot.handlers.prompt import PromptTunerHandler


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _Session(dict):
    """Dict that is always truthy so ``_get_session`` returns it as-is."""

    def __bool__(self) -> bool:  # noqa: D401
        return True


class _FakeBot:
    """Minimal stand-in for an AbstractBot exposing a real PromptBuilder."""

    def __init__(self, builder: PromptBuilder) -> None:
        self.name = "TestBot"
        self.role = "helper"
        self.goal = "help users"
        self.backstory = "born in a lab"
        self.rationale = "be concise"
        self.capabilities = "answer questions"
        self.pre_instructions = ["always be nice"]
        self.system_prompt = None
        self._pb = builder

    @property
    def prompt_builder(self) -> PromptBuilder:
        return self._pb


def _baked_builder() -> PromptBuilder:
    """A default builder baked with the fake bot's current field values."""
    builder = PromptBuilder.default()
    builder.configure({
        "name": "TestBot",
        "role": "helper",
        "goal": "help users",
        "backstory": "born in a lab",
        "rationale": "be concise",
        "capabilities": "answer questions",
        "pre_instructions_content": "- always be nice",
        "extra_security_rules": "",
        "extra_tool_instructions": "",
        "has_tools": False,
    })
    return builder


def _handler() -> PromptTunerHandler:
    """Construct the handler without going through BaseView.__init__."""
    h = PromptTunerHandler.__new__(PromptTunerHandler)
    h.logger = logging.getLogger("test.prompt_handler")
    # ``request`` is a read-only property on aiohttp's View — set the backing
    # attribute it returns (``self._request``).
    h._request = SimpleNamespace(app={}, session=_Session(), match_info={}, path="")
    return h


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_current_fields_reads_instance() -> None:
    bot = _FakeBot(_baked_builder())
    fields = _handler()._current_fields(bot)
    assert fields["role"] == "helper"
    assert fields["pre_instructions"] == ["always be nice"]
    assert set(fields) == {
        "name", "role", "goal", "backstory", "rationale", "capabilities",
        "pre_instructions",
    }


def test_layers_payload_flags_field_driven() -> None:
    bot = _FakeBot(_baked_builder())
    payload = _handler()._layers_payload(bot)
    by_name = {layer["name"]: layer for layer in payload}
    assert by_name["identity"]["field_driven"] is True
    assert by_name["security"]["field_driven"] is False
    # baked identity already carries the resolved role text
    assert "You are helper" in by_name["identity"]["template"]


def test_semantic_edit_regenerates_identity_layer() -> None:
    bot = _FakeBot(_baked_builder())
    draft = {"fields": {"role": "a witty pirate"}, "layers": {}}
    overrides = _handler()._effective_overrides(bot, draft, {})
    assert "identity" in overrides
    assert "You are a witty pirate." in overrides["identity"]
    # untouched fields are preserved from the current instance values
    assert "Your name is TestBot." in overrides["identity"]


def test_rationale_edit_regenerates_behavior_layer() -> None:
    bot = _FakeBot(_baked_builder())
    draft = {"fields": {"rationale": "answer only in haiku"}, "layers": {}}
    overrides = _handler()._effective_overrides(bot, draft, {})
    assert "behavior" in overrides
    assert "answer only in haiku" in overrides["behavior"]


def test_raw_layer_override_wins() -> None:
    bot = _FakeBot(_baked_builder())
    custom = "<security_policy>CUSTOM RULES ONLY</security_policy>"
    draft = {"fields": {}, "layers": {"security": custom}}
    overrides = _handler()._effective_overrides(bot, draft, {})
    assert overrides["security"] == custom


def test_apply_overrides_replaces_and_reports_skips() -> None:
    builder = _baked_builder()
    skipped = PromptTunerHandler._apply_overrides(
        builder,
        {"security": "<security_policy>X</security_policy>", "nonexistent": "y"},
    )
    assert skipped == ["nonexistent"]
    assert "<security_policy>X</security_policy>" in builder.get("security").template


async def test_render_preview_does_not_mutate_live_bot() -> None:
    bot = _FakeBot(_baked_builder())
    original_identity = bot.prompt_builder.get("identity").template
    draft = {"fields": {"role": "a witty pirate"}, "layers": {}}
    rendered = await _handler()._render_preview(bot, draft)
    assert "You are a witty pirate." in rendered
    # the live builder is untouched — preview ran on a clone
    assert bot.prompt_builder.get("identity").template == original_identity
    assert "You are helper" in original_identity


async def test_apply_draft_to_mutates_live_bot() -> None:
    bot = _FakeBot(_baked_builder())
    draft = {
        "fields": {"role": "a witty pirate", "rationale": "answer only in haiku"},
        "layers": {},
    }
    skipped = await _handler()._apply_draft_to(bot, draft)
    assert skipped == []
    assert bot.role == "a witty pirate"
    assert bot.rationale == "answer only in haiku"
    assert "You are a witty pirate." in bot.prompt_builder.get("identity").template
    rendered = bot.prompt_builder.build({
        "knowledge_content": "", "user_context": "", "chat_history": "",
        "output_instructions": "",
    })
    assert "a witty pirate" in rendered
    assert "answer only in haiku" in rendered


async def test_draft_round_trips_through_session() -> None:
    h = _handler()
    fresh = await h._load_draft("agentX")
    assert fresh == {"fields": {}, "layers": {}, "test_bot_name": None}
    fresh["fields"]["role"] = "pirate"
    await h._store_draft("agentX", fresh)
    again = await h._load_draft("agentX")
    assert again["fields"]["role"] == "pirate"
