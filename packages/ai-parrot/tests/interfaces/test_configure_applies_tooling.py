"""Tests for deferred tooling setup in ``AbstractBot.configure``."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from parrot.bots.abstract import AbstractBot


@pytest.mark.asyncio
async def test_configure_calls_apply_tooling_specs_once() -> None:
    """Configure applies deferred tooling immediately after conversation memory."""
    bot = AbstractBot.__new__(AbstractBot)
    sequence = MagicMock()
    bot.logger = MagicMock()
    sequence.memory = MagicMock()
    sequence.apply = AsyncMock(return_value=[])
    bot.configure_conversation_memory = sequence.memory
    bot.apply_tooling_specs = sequence.apply
    bot.configure_kb = AsyncMock()
    bot._use_local_kb = False
    bot._llm_model_explicit = False
    bot._llm_raw = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_model = None
    bot._resolve_llm_config = MagicMock(return_value=MagicMock(model=None))
    bot._create_llm_client = MagicMock(return_value=MagicMock())
    bot.tool_manager = None
    bot.get_tools_summary = MagicMock(
        return_value={
            "tools_enabled": False,
            "operation_mode": "",
            "tools_count": 0,
            "categories": [],
            "effective_mode": "",
        }
    )
    bot._define_prompt = MagicMock()
    bot._prompt_builder = None
    bot.define_store_config = MagicMock(return_value=None)
    bot._use_vector = False
    bot._vector_store = None
    bot._refresh_context_recs_from_store = MagicMock()
    bot.warmup_on_configure = False
    bot.store = None
    bot.use_kb = False
    bot._credentials = []
    bot.post_configure = AsyncMock()
    bot._llm_config = None
    bot.events = MagicMock()
    bot.name = "test-bot"

    await bot.configure()

    bot.apply_tooling_specs.assert_awaited_once_with()
    assert sequence.mock_calls[:2] == [call.memory(), call.apply()]
