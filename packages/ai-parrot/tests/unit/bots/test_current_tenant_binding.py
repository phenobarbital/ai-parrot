"""FEAT-710 TASK-4545 — BaseBot binds current_tenant on every call."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.bots.base import with_call_identity
from parrot.observability.context import current_agent_name, current_tenant
from parrot.skills.mixin import SkillRegistryMixin
from parrot.utils.helpers import RequestContext

_ASK_KWARGS = {
    "use_conversation_history": False,
    "use_tools": False,
    "use_vector_context": False,
}


@pytest.mark.asyncio
async def test_plain_bot_sees_tenant_inside_ask_and_stream(make_bot: Any) -> None:
    """A non-skill bot binds tenant context for normal and streaming calls."""
    bot = make_bot()
    seen: list[str | None] = []

    async def stop_after_recording(*args: Any, **kwargs: Any) -> Any:
        seen.append(current_tenant.get())
        raise RuntimeError("stop after context observation")

    bot._run_input_pipeline = stop_after_recording

    with pytest.raises(RuntimeError, match="stop after context observation"):
        await bot.ask("hello", tenant="t1", **_ASK_KWARGS)
    assert seen == ["t1"]
    assert current_tenant.get() is None

    with pytest.raises(RuntimeError, match="stop after context observation"):
        async for _ in bot.ask_stream("hello", tenant="t1", **_ASK_KWARGS):
            pass
    assert seen == ["t1", "t1"]
    assert current_tenant.get() is None


@pytest.mark.asyncio
async def test_nested_ask_restores_outer_tenant(make_bot: Any) -> None:
    """An inner tenant binding restores the outer call's tenant after return."""
    bot = make_bot()
    seen: list[str | None] = []
    call_count = 0

    async def record_nested_call(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        seen.append(current_tenant.get())
        if call_count == 1:
            with pytest.raises(RuntimeError, match="stop after context observation"):
                await bot.ask("inner", tenant="b", **_ASK_KWARGS)
            seen.append(current_tenant.get())
        raise RuntimeError("stop after context observation")

    bot._run_input_pipeline = record_nested_call

    with pytest.raises(RuntimeError, match="stop after context observation"):
        await bot.ask("outer", tenant="a", **_ASK_KWARGS)

    assert seen == ["a", "b", "a"]
    assert current_tenant.get() is None


@pytest.mark.asyncio
async def test_conversation_binds_tenant(make_bot: Any) -> None:
    """Conversation binds and resets an explicit tenant when its body raises."""
    bot = make_bot()
    seen: list[str | None] = []

    async def stop_after_recording(*args: Any, **kwargs: Any) -> Any:
        seen.append(current_tenant.get())
        raise RuntimeError("stop after context observation")

    bot._conversation_body = stop_after_recording

    with pytest.raises(RuntimeError, match="stop after context observation"):
        await bot.conversation("hi", tenant="t1")

    assert seen == ["t1"]
    assert current_tenant.get() is None


@pytest.mark.asyncio
async def test_invoke_binds_tenant(make_bot: Any) -> None:
    """Invoke binds and resets an explicit tenant when prompt creation raises."""
    bot = make_bot()
    seen: list[str | None] = []

    async def stop_after_recording(*args: Any, **kwargs: Any) -> Any:
        seen.append(current_tenant.get())
        raise RuntimeError("stop after context observation")

    bot.create_system_prompt = stop_after_recording

    with pytest.raises(RuntimeError, match="stop after context observation"):
        await bot.invoke("hi", tenant="t1", use_conversation_history=False)

    assert seen == ["t1"]
    assert current_tenant.get() is None


@pytest.mark.asyncio
async def test_invoke_tenant_from_request_context(make_bot: Any) -> None:
    """Invoke resolves a tenant from RequestContext when none is explicit."""
    bot = make_bot()
    seen: list[str | None] = []

    async def stop_after_recording(*args: Any, **kwargs: Any) -> Any:
        seen.append(current_tenant.get())
        raise RuntimeError("stop after context observation")

    bot.create_system_prompt = stop_after_recording
    ctx = RequestContext(tenant="t2")

    with pytest.raises(RuntimeError, match="stop after context observation"):
        await bot.invoke("hi", ctx=ctx, use_conversation_history=False)

    assert seen == ["t2"]
    assert current_tenant.get() is None


def test_bind_and_reset_call_identity_restore_outer_values(make_bot: Any) -> None:
    """Shared identity helpers restore enclosing agent and tenant values."""
    bot = make_bot(name="inner-agent")
    outer_agent_token = current_agent_name.set("outer-agent")
    outer_tenant_token = current_tenant.set("outer-tenant")
    try:
        tokens = bot._bind_call_identity("inner-tenant")
        assert current_agent_name.get() == "inner-agent"
        assert current_tenant.get() == "inner-tenant"

        bot._reset_call_identity(tokens)
        assert current_agent_name.get() == "outer-agent"
        assert current_tenant.get() == "outer-tenant"
    finally:
        current_tenant.reset(outer_tenant_token)
        current_agent_name.reset(outer_agent_token)


@pytest.mark.asyncio
async def test_with_call_identity_named_and_var_keyword_tenant(make_bot: Any) -> None:
    """The decorator resolves both signature shapes without changing arguments."""
    bot = make_bot(name="decorated-agent")
    seen: list[tuple[str | None, str | None, tuple[Any, ...]]] = []

    @with_call_identity
    async def named(
        self: Any, value: str, tenant: str | None = None, ctx: Any = None
    ) -> tuple[str, str | None, Any]:
        seen.append((current_agent_name.get(), current_tenant.get(), (value, tenant, ctx)))
        return value, tenant, ctx

    @with_call_identity
    async def variadic(self: Any, value: str, **extra: Any) -> tuple[str, dict[str, Any]]:
        seen.append((current_agent_name.get(), current_tenant.get(), (value, extra)))
        return value, extra

    named_ctx = RequestContext(tenant="ctx-tenant")
    variadic_ctx = RequestContext(tenant="ignored-context-tenant")
    assert await named(bot, "named-value", tenant="named-tenant", ctx=named_ctx) == (
        "named-value",
        "named-tenant",
        named_ctx,
    )
    assert await variadic(
        bot,
        "variadic-value",
        tenant="variadic-tenant",
        ctx=variadic_ctx,
        marker=42,
    ) == (
        "variadic-value",
        {"tenant": "variadic-tenant", "ctx": variadic_ctx, "marker": 42},
    )

    assert seen == [
        ("decorated-agent", "named-tenant", ("named-value", "named-tenant", named_ctx)),
        (
            "decorated-agent",
            "variadic-tenant",
            (
                "variadic-value",
                {"tenant": "variadic-tenant", "ctx": variadic_ctx, "marker": 42},
            ),
        ),
    ]
    assert current_agent_name.get() is None
    assert current_tenant.get() is None


def test_non_tenant_skill_bot_keeps_global_view() -> None:
    """FEAT-707 skill views remain global when tenant_based is disabled."""

    class _NonTenantSkillBot(SkillRegistryMixin):
        name = "non-tenant-skill-bot"
        enable_skill_registry = False

    bot = _NonTenantSkillBot()
    global_view = object()
    bot._global_view = global_view
    token = current_tenant.set("t1")
    try:
        assert bot._enter_skill_tenant("t1", None) is None
        assert bot.current_skill_view() is global_view
    finally:
        current_tenant.reset(token)


def test_resolve_call_tenant_precedence() -> None:
    """Explicit tenants override request-context tenants without clearing outer state."""
    from parrot.bots.base import _resolve_call_tenant

    class _Ctx:
        kwargs = {"tenant": "from-ctx"}

    assert _resolve_call_tenant("explicit", _Ctx()) == "explicit"
    assert _resolve_call_tenant(None, _Ctx()) == "from-ctx"
    assert _resolve_call_tenant(None, None) is None
