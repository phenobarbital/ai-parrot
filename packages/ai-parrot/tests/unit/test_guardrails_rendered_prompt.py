"""FEAT-761 TASK-4837 — rendered system prompt capture for OUTPUT guardrails."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from parrot.bots import abstract as abstract_mod
from parrot.bots import base as base_mod
from parrot.bots.abstract import AbstractBot
from parrot.bots.prompts.segments import CacheableSegment


class _StubBot(AbstractBot):
    """Minimal concrete AbstractBot (abstract methods stubbed)."""

    async def ask(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def ask_stream(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def conversation(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def invoke(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


def _bot() -> AbstractBot:
    bot = _StubBot.__new__(_StubBot)
    bot.chatbot_id = "cb-1"
    return bot


def _pipeline(*, requires: bool) -> SimpleNamespace:
    g = SimpleNamespace(requires_system_prompt=requires)
    return SimpleNamespace(guardrails=(g,))


@pytest.fixture(autouse=True)
def _reset():
    token = abstract_mod._RENDERED_SYSTEM_PROMPT.set(None)
    yield
    abstract_mod._RENDERED_SYSTEM_PROMPT.reset(token)


def test_capture_str():
    _bot()._capture_rendered_prompt("hello")
    assert abstract_mod._RENDERED_SYSTEM_PROMPT.get() == "hello"


def test_capture_segments():
    segs = [CacheableSegment(text="a", cacheable=True), CacheableSegment(text="b", cacheable=False)]
    _bot()._capture_rendered_prompt(segs)
    assert abstract_mod._RENDERED_SYSTEM_PROMPT.get() == "ab"


def test_capture_none():
    bot = _bot()
    bot._capture_rendered_prompt("x")
    bot._capture_rendered_prompt(None)
    assert abstract_mod._RENDERED_SYSTEM_PROMPT.get() is None


def test_extras_without_requirement():
    bot = _bot()
    bot._capture_rendered_prompt("secret prompt")
    extras = bot._output_extras("resp", _pipeline(requires=False))
    assert "system_prompt" not in extras
    assert extras["chatbot_id"] == "cb-1"


def test_extras_with_requirement():
    bot = _bot()
    bot._capture_rendered_prompt("secret prompt")
    extras = bot._output_extras("resp", _pipeline(requires=True))
    assert extras["system_prompt"] == "secret prompt"


@pytest.mark.asyncio
async def test_concurrent_turns_do_not_cross_talk():
    bot = _bot()

    async def turn(prompt: str, delay: float) -> str:
        bot._capture_rendered_prompt(prompt)
        await asyncio.sleep(delay)
        return bot._output_extras("r", _pipeline(requires=True))["system_prompt"]

    a, b = await asyncio.gather(
        asyncio.create_task(turn("prompt-A", 0.02)),
        asyncio.create_task(turn("prompt-B", 0.0)),
    )
    assert (a, b) == ("prompt-A", "prompt-B")


def test_base_call_sites_capture():
    src = inspect.getsource(base_mod)
    for meth in ("conversation", "ask", "ask_stream"):
        needle = f'self._debug_prompt_dump(\n                method="{meth}",'
        assert src.count("self._capture_rendered_prompt(system_prompt)\n            " + needle) == 1, meth
    one = "system_prompt = await self.create_system_prompt(user_id=user_id, session_id=session_id, **kwargs)\n"
    assert src.count(one + "            self._capture_rendered_prompt(system_prompt)\n") == 1
