"""Tests for deferred suggestions in ask_stream (FEAT-752 rev 0.3, TASK-4806)."""

import asyncio
import inspect
import logging
from pathlib import Path

import pytest

from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.skills.models import SkillDefinition, SkillSource, SkillSuggestion
from parrot.skills.tenancy import (
    current_turn_skill,
    enter_active_skill_scope,
    exit_active_skill_scope,
    set_active_skill,
)


def _base_bot_cls():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 — same guard as test_linked_surface_lifting.py
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


def _msg():
    return AIMessage(input="q", output="a", model="m", provider="p", usage=CompletionUsage())


def _skill(name="s"):
    return SkillDefinition(
        name=name,
        description="d",
        triggers=[f"/{name}"],
        source=SkillSource.AUTHORED,
        template_body="b",
        token_count=1,
        file_path=Path(f"/tmp/{name}.md"),
        suggestions=[SkillSuggestion(label="Skill chip", prompt="from the skill")],
    )


def _bare_bot():
    cls = _base_bot_cls()
    bot = object.__new__(type("BareBot", (cls,), {"__abstractmethods__": frozenset()}))
    bot.logger = logging.getLogger("test")
    bot.suggest_followups = bot.enable_suggestions = False
    bot.suggestion_timeout_s, bot.max_suggestions, bot.suggestion_model = 1.0, 6, None
    bot._suggestion_engine = None
    return bot


def test_private_task_attr_not_serialised():
    msg = _msg()
    assert msg._suggestions_task is None
    assert "_suggestions_task" not in msg.model_dump()
    assert "_suggestions_task" not in msg.model_dump_json()


def test_private_task_attr_is_settable():
    msg = _msg()
    msg._suggestions_task = "sentinel"
    assert msg._suggestions_task == "sentinel"


def test_ask_stream_source_has_deferred_branch():
    src = inspect.getsource(_base_bot_cls().ask_stream)
    assert 'kwargs.pop("defer_suggestions", False)' in src
    assert src.count("_attach_suggestions(") == 1
    assert "asyncio.create_task(_attach)" in src
    assert src.index("asyncio.create_task(_attach)") < src.index("yield ai_message")
    assert "ai_message = await _attach" in src


def test_defer_flag_never_reaches_llm_kwargs():
    src = inspect.getsource(_base_bot_cls().ask_stream)
    pop = src.index('kwargs.pop("defer_suggestions", False)')
    block_start = src.index("llm_kwargs = {")
    block = src[block_start : src.index("}", block_start)]
    assert pop < block_start  # popped before the explicit llm_kwargs dict is built
    assert "defer" not in block and "**kwargs" not in block  # and kwargs is not forwarded wholesale


async def test_deferred_task_keeps_turn_skill_context():
    seen = {}

    async def read_skill():
        await asyncio.sleep(0)  # run after the scope below has been exited
        seen["skill"] = current_turn_skill()

    token = enter_active_skill_scope()
    skill = _skill()
    set_active_skill(skill)
    set_active_skill(None)  # prompt build clears the active skill
    task = asyncio.create_task(read_skill())  # create_task copies the context here
    exit_active_skill_scope(token)  # the generator's finally
    assert current_turn_skill() is None
    await task
    assert seen["skill"] is skill


async def test_deferred_attach_resolves_to_same_message_with_chips():
    bot = _bare_bot()
    token = enter_active_skill_scope()
    try:
        set_active_skill(_skill())
        set_active_skill(None)
        msg = _msg()
        msg._suggestions_task = asyncio.create_task(bot._attach_suggestions("q", msg, output_mode=OutputMode.DEFAULT))
    finally:
        exit_active_skill_scope(token)

    assert msg.suggestions == []  # nothing awaited yet: the envelope can be written first
    result = await msg._suggestions_task
    assert result is msg
    assert [c.label for c in msg.suggestions] == ["Skill chip"]
    assert msg.metadata["suggestions"]["count"] == 1
