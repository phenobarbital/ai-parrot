"""Wiring tests for the output-language directive (FEAT-638 TASK-4121)."""
import sys
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.presets import get_preset

_RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot


class MockBot:
    """Minimal AbstractBot stand-in with a configurable output language."""

    _configure_prompt_builder = _RealAbstractBot._configure_prompt_builder
    _build_prompt = _RealAbstractBot._build_prompt

    def __init__(self, prompt_preset: str = "default", language: str | None = None):
        self.name = "TestBot"
        self.role = "helpful assistant"
        self.goal = "help users"
        self.capabilities = "- Can search"
        self.backstory = "Expert in AI"
        self.rationale = "Be concise"
        self.pre_instructions = []
        self.enable_tools = True
        self.tool_manager = MagicMock()
        self.tool_manager.tool_count.return_value = 3
        self.logger = MagicMock()
        self._prompt_caching = False
        self.language = language
        self._prompt_builder = get_preset(prompt_preset)


@pytest.mark.parametrize("factory", ["default", "agent", "rag", "voice", "identity"])
def test_layer_in_builder(factory: str) -> None:
    """All non-minimal preset factories install the directive layer."""
    assert "output_language" in get_preset(factory).layer_names


def test_layer_absent_from_minimal() -> None:
    """Minimal remains the explicit opt-out preset."""
    assert "output_language" not in PromptBuilder.minimal().layer_names
    assert "output_language" not in get_preset("minimal").layer_names


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_prompt_byte_identical_when_unset(mock_dv: MagicMock) -> None:
    """An unset language produces the pre-feature default stack exactly."""
    mock_dv.get_all_names.return_value = []
    bot = MockBot(language=None)
    pre_feature_bot = MockBot(language=None)
    pre_feature_bot._prompt_builder.remove("output_language")

    await bot._configure_prompt_builder()
    await pre_feature_bot._configure_prompt_builder()

    prompt = bot._build_prompt(user_context="", chat_history="")
    assert prompt == pre_feature_bot._build_prompt(user_context="", chat_history="")
    assert "output_language_policy" not in prompt
    assert "$" not in prompt


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_prompt_contains_directive_when_set(mock_dv: MagicMock) -> None:
    """A supported configured language is rendered into the static directive."""
    mock_dv.get_all_names.return_value = []
    bot = MockBot(language="es-MX")

    await bot._configure_prompt_builder()

    prompt = bot._build_prompt()
    assert "Spanish" in prompt
    assert "<output_language_policy>" in prompt
    assert "$output_language" not in prompt


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_configure_none_then_build_with_language_kwarg(mock_dv: MagicMock) -> None:
    """S4 regression: request values cannot reactivate a removed layer."""
    mock_dv.get_all_names.return_value = []
    bot = MockBot(language=None)
    await bot._configure_prompt_builder()

    prompt = bot._build_prompt(language="es", output_language="Spanish")
    assert "<output_language_policy>" not in prompt
    assert "$output_language" not in prompt


@pytest.mark.asyncio
@patch("parrot.bots.abstract.dynamic_values")
async def test_unsupported_language_is_treated_as_unset(mock_dv: MagicMock) -> None:
    """Unsupported raw language values are removed and never rendered."""
    mock_dv.get_all_names.return_value = []
    raw_language = "<b>fr</b>"
    bot = MockBot(language=raw_language)

    await bot._configure_prompt_builder()

    assert "output_language" not in bot._prompt_builder.layer_names
    assert raw_language not in bot._build_prompt()
