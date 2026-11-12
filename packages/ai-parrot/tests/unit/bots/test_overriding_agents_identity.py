"""HOTFIX-otel-attribution-3 — agents overriding ask() still bind agent and tenant."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from parrot.bots.base import BaseBot, with_call_identity
from parrot.bots.data import PandasAgent
from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.voice import VoiceBot
from parrot.observability.context import current_agent_name, current_tenant


@pytest.mark.parametrize("agent_cls", [PandasAgent, DatabaseAgent])
def test_overriding_ask_is_wrapped_with_call_identity(agent_cls: type) -> None:
    """The override is the decorated wrapper, not the bare coroutine."""
    ask = agent_cls.__dict__["ask"]
    assert hasattr(ask, "__wrapped__")
    assert inspect.iscoroutinefunction(ask)


@pytest.mark.asyncio
async def test_decorator_binds_agent_and_tenant_on_overriding_ask() -> None:
    """A decorated override sees agent and tenant inside, and they reset after."""
    seen: dict[str, Any] = {}

    class _Probe(BaseBot):
        @with_call_identity
        async def ask(self, question: str, ctx: Any = None, **kwargs: Any) -> str:
            seen["agent"] = current_agent_name.get()
            seen["tenant"] = current_tenant.get()
            return question

    probe = object.__new__(_Probe)
    probe.name = "probe-agent"
    before = (current_agent_name.get(), current_tenant.get())
    assert await probe.ask("hi", tenant="t1") == "hi"
    assert seen == {"agent": "probe-agent", "tenant": "t1"}
    assert (current_agent_name.get(), current_tenant.get()) == before


@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_voicebot_binds_and_resets_identity(method: str) -> None:
    """VoiceBot's async generators bind identity and reset it in ``finally``."""
    source = inspect.getsource(getattr(VoiceBot, method))
    assert "self._bind_call_identity(" in source
    assert "self._reset_call_identity(_identity)" in source
    assert source.index("_bind_call_identity") < source.index("finally:")
    finally_body = source.split("finally:", 1)[1]
    assert finally_body.lstrip().startswith("self._reset_call_identity(_identity)")
