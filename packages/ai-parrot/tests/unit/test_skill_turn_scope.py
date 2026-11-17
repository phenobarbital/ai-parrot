"""Tests for the request-local turn skill (FEAT-752, TASK-4795)."""

import asyncio
from pathlib import Path

from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tenancy import (
    current_active_skill,
    current_turn_skill,
    enter_active_skill_scope,
    exit_active_skill_scope,
    set_active_skill,
)


def _skill(name: str = "s") -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description="d",
        triggers=[f"/{name}"],
        source=SkillSource.AUTHORED,
        template_body="b",
        token_count=1,
        file_path=Path(f"/tmp/{name}.md"),
    )


def test_turn_skill_survives_prompt_clear():
    token = enter_active_skill_scope()
    try:
        s = _skill()
        set_active_skill(s)
        set_active_skill(None)  # what create_system_prompt does
        assert current_active_skill() is None
        assert current_turn_skill() is s
    finally:
        exit_active_skill_scope(token)


def test_scope_restores_both():
    before_active = current_active_skill()
    before_turn = current_turn_skill()
    token = enter_active_skill_scope()
    set_active_skill(_skill("inner"))
    assert current_turn_skill() is not None
    exit_active_skill_scope(token)
    assert current_active_skill() is before_active
    assert current_turn_skill() is before_turn


def test_scope_restores_values_set_before_enter():
    outer = _skill("outer")
    outer_token = enter_active_skill_scope()
    try:
        set_active_skill(outer)
        inner_token = enter_active_skill_scope()
        set_active_skill(_skill("inner"))
        set_active_skill(None)
        exit_active_skill_scope(inner_token)
        assert current_active_skill() is outer
        assert current_turn_skill() is outer
    finally:
        exit_active_skill_scope(outer_token)


async def test_turn_skill_is_task_local():
    started = asyncio.Event()
    release = asyncio.Event()

    async def setter() -> object:
        token = enter_active_skill_scope()
        try:
            set_active_skill(_skill("task"))
            started.set()
            await release.wait()
            return current_turn_skill()
        finally:
            exit_active_skill_scope(token)

    async def sibling() -> object:
        await started.wait()
        seen = current_turn_skill()
        release.set()
        return seen

    set_task = asyncio.create_task(setter())
    sibling_task = asyncio.create_task(sibling())
    set_result, sibling_result = await asyncio.gather(set_task, sibling_task)
    assert set_result is not None
    assert sibling_result is None
    assert current_turn_skill() is None
