"""FEAT-721 — AbstractBot.configure() is idempotent per instance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot


class _ConfigureTestBot(AbstractBot):
    """Concrete shell used to exercise AbstractBot lifecycle behavior."""

    async def ask(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def ask_stream(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def conversation(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def invoke(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None


def _stub_bot() -> AbstractBot:
    """Return an AbstractBot with every configure collaborator stubbed."""
    bot = object.__new__(_ConfigureTestBot)
    bot.logger = MagicMock()
    bot.configure_conversation_memory = MagicMock()
    bot.apply_tooling_specs = AsyncMock(return_value=[])
    bot.configure_kb = AsyncMock()
    bot._use_local_kb = False
    bot._llm_model_explicit = False
    bot._llm_raw = None
    bot._llm_preset = None
    bot._llm_kwargs = {}
    bot._llm_model = None
    bot._resolve_llm_config = MagicMock(return_value=MagicMock(model=None))
    bot._create_llm_client = MagicMock(return_value=MagicMock())
    bot.tool_manager = MagicMock(_server_param_source=None)
    bot.sync_tools = MagicMock()
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
    bot._events_registry = MagicMock()
    bot.name = "test-bot"
    return bot


def _app() -> SimpleNamespace:
    """Return a truthy app wrapper around a stable resolved app object."""
    real = web.Application()
    real["configured"] = True
    return SimpleNamespace(get_app=lambda: real)


@pytest.mark.asyncio
async def test_second_configure_is_noop() -> None:
    """A duplicate app entry does not repeat the configuration pipeline."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)
    await bot.configure(app)

    assert bot.configure_count == 2
    bot.post_configure.assert_awaited_once()
    assert bot.events.emit_nowait.call_count == 1


@pytest.mark.asyncio
async def test_configure_with_new_app_reruns() -> None:
    """An app that arrives after CLI configuration reruns the pipeline."""
    bot = _stub_bot()
    app = _app()

    await bot.configure()
    await bot.configure(app)

    assert bot.configure_count == 2
    assert bot.app is app.get_app()
    assert bot.post_configure.await_count == 2


@pytest.mark.asyncio
async def test_configure_without_app_after_app_keeps_binding() -> None:
    """A bare re-entry retains the previously bound app and skips work."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)
    bound_app = bot.app
    await bot.configure()

    assert bot.app is bound_app
    bot.post_configure.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconfigure_reruns_pipeline() -> None:
    """reconfigure resets the counter and deliberately reruns the pipeline."""
    bot, app = _stub_bot(), _app()

    await bot.configure(app)
    await bot.reconfigure()

    assert bot.configure_count == 1
    assert bot.post_configure.await_count == 2


@pytest.mark.asyncio
async def test_failed_configure_still_marks_configured() -> None:
    """The configure finally contract still holds when a hook raises."""
    bot = _stub_bot()
    bot.post_configure = AsyncMock(side_effect=RuntimeError("hook failed"))

    with pytest.raises(RuntimeError, match="hook failed"):
        await bot.configure()

    assert bot.is_configured is True
