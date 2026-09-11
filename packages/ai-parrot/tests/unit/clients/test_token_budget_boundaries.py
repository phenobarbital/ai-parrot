"""FEAT-550 M3 — public entry compatibility and unsupported-provider gate (spec §4 rows)."""

from __future__ import annotations

import inspect
from typing import Any, AsyncGenerator

import pytest

from parrot.clients.base import AbstractClient
from parrot.clients.budget_scope import (
    BudgetRegistry,
    current_budget_scope,
    BudgetDefaults,
    _CURRENT_SCOPE,
    TOKEN_BUDGET_STATE_KEY,
)
from parrot.core.exceptions import BudgetUnsupported, BudgetExhausted
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage, InvokeResult
from parrot.models.token_budget import TokenBudgetPolicy
from parrot.bots.base import BaseBot


class _Base(AbstractClient):
    client_type = "stub"

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("model", "stub")
        super().__init__(**kw)
        self.calls: list[tuple[str, dict]] = []

    async def get_client(self):
        return self

    async def ask(self, prompt, model=None, **kwargs):
        self.calls.append(("ask", dict(kwargs)))
        if kwargs.get("raise_exhausted"):
            from parrot.core.exceptions import BudgetExhausted

            raise BudgetExhausted("exhausted", report={"partial_text": "partial text", "total_tokens": 120})
        return AIMessage(
            input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage()
        )

    async def ask_stream(self, prompt, **kwargs) -> AsyncGenerator[Any, None]:
        self.calls.append(("ask_stream", dict(kwargs)))
        if kwargs.get("raise_exhausted"):
            from parrot.core.exceptions import BudgetExhausted

            yield "chunk1"
            raise BudgetExhausted("exhausted", report={"partial_text": "chunk1 partial text", "total_tokens": 150})
        yield "chunk"
        yield AIMessage(
            input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage()
        )

    async def resume(self, session_id, user_input, state):
        self.calls.append(("resume", {}))
        return await self.ask(user_input)

    async def invoke(self, prompt, **kwargs):
        self.calls.append(("invoke", dict(kwargs)))
        return InvokeResult(output="ok", model="stub", usage=CompletionUsage())


class SupportedClient(_Base):
    budget_supported_methods = frozenset({"ask", "ask_stream", "resume", "invoke"})


class UnsupportedClient(_Base):
    pass


class ThinSubclass(SupportedClient):
    """Overrides none of the four — must inherit wrapped methods without re-wrapping."""


class TestPublicEntryCompatibility:
    def test_wrappers_installed_once_and_identity_preserved(self):
        assert getattr(SupportedClient.ask, "__parrot_budget_wrapped__", False)
        assert ThinSubclass.ask is SupportedClient.ask
        assert inspect.iscoroutinefunction(SupportedClient.ask) and inspect.isasyncgenfunction(
            SupportedClient.ask_stream
        )
        assert inspect.isabstract(AbstractClient)

    async def test_no_budget_pass_through(self):
        c = SupportedClient()
        msg = await c.ask("hi")
        assert msg.output == "ok" and c.calls[0][1] == {} and current_budget_scope() is None

    async def test_budget_keywords_stripped_and_scope_bound(self):
        c = SupportedClient()
        scopes_seen = []

        # We subclass SupportedClient to capture the active scope inside the method
        class ScopeCapturingClient(SupportedClient):
            async def ask(self, prompt, model=None, **kwargs):
                scopes_seen.append(current_budget_scope())
                return await super().ask(prompt, model=model, **kwargs)

        client = ScopeCapturingClient()
        msg = await client.ask("hi", token_budget=1000)
        assert msg.output == "ok"
        assert len(scopes_seen) == 1
        assert scopes_seen[0] is not None
        assert scopes_seen[0].policy.token_budget == 1000
        # Verify budget keywords were stripped before reaching the implementation
        assert "token_budget" not in client.calls[0][1]

    async def test_nested_super_call_is_child_not_new_root(self):
        registry = BudgetRegistry()
        scopes_seen = []

        # Let's define a class hierarchy where only the leaf class captures scopes,
        # but we call super().ask which is wrapped.
        class NestedClient(SupportedClient):
            async def ask(self, prompt, model=None, **kwargs):
                scopes_seen.append(current_budget_scope())
                # Call super().ask which is also wrapped
                res = await super().ask(prompt, model=model, **kwargs)
                scopes_seen.append(current_budget_scope())
                return res

        client = NestedClient(budget_registry=registry)
        await client.ask("hi", token_budget=1000)

        # Outer ask wrapper runs -> enters root scope.
        # NestedClient.ask runs -> appends root scope (scopes_seen[0]).
        # NestedClient.ask calls super().ask.
        # super().ask is SupportedClient.ask, which is wrapped.
        # SupportedClient.ask wrapper runs -> sees current_budget_scope() is not None -> enters child scope.
        # SupportedClient.ask implementation runs (which is _Base.ask, not overridden in SupportedClient).
        # SupportedClient.ask wrapper exits -> restores root scope.
        # NestedClient.ask appends root scope again (scopes_seen[1]).
        # NestedClient.ask wrapper exits -> restores None.
        assert len(scopes_seen) == 2
        assert scopes_seen[0] is not None
        assert scopes_seen[1] is not None
        assert scopes_seen[0] is scopes_seen[1]  # Both are the same root scope

    async def test_constructor_budget_applies_without_per_call_kwarg(self):
        registry = BudgetRegistry()
        scopes_seen = []

        class CapturingClient(SupportedClient):
            async def ask(self, prompt, model=None, **kwargs):
                scopes_seen.append(current_budget_scope())
                return await super().ask(prompt, model=model, **kwargs)

        client = CapturingClient(token_budget=500, budget_registry=registry)
        await client.ask("x")
        assert len(scopes_seen) == 1
        assert scopes_seen[0] is not None
        assert scopes_seen[0].policy.token_budget == 500

    def test_bad_constructor_budget_fails_at_construction(self):
        with pytest.raises(ValueError):
            SupportedClient(token_budget=-100)
        with pytest.raises(ValueError):
            SupportedClient(token_budget=True)
        with pytest.raises(ValueError):
            SupportedClient(token_budget="invalid")

    async def test_budget_snapshot_only_on_resume(self):
        c = SupportedClient()
        with pytest.raises(TypeError):
            await c.ask("hi", budget_snapshot=object())


class TestUnsupportedProviders:
    async def test_explicit_budget_rejected_before_implementation(self):
        c = UnsupportedClient()
        with pytest.raises(BudgetUnsupported):
            await c.ask("hi", token_budget=100)
        assert c.calls == []

    async def test_inherited_scope_rejected_even_with_cached_client(self):
        registry = BudgetRegistry()
        policy = TokenBudgetPolicy(token_budget=1000)
        scope = await registry.create(policy)

        c = UnsupportedClient(budget_registry=registry)

        with pytest.raises(BudgetUnsupported):
            # Call under an inherited scope
            token = _CURRENT_SCOPE.set(scope)
            try:
                await c.ask("hi")
            finally:
                _CURRENT_SCOPE.reset(token)

        assert c.calls == []

    async def test_no_budget_keeps_behavior(self):
        c = UnsupportedClient()
        assert (await c.invoke("x")).output == "ok"


async def _make_budget_bot(client: SupportedClient, **bot_kwargs: Any) -> BaseBot:
    """A configured ``BaseBot`` wired to *client* (mirrors tests/unit/bots/test_bot_history_wiring.py)."""
    bot = BaseBot(
        name="budget-boundary-probe",
        llm=client,
        memory_type="memory",
        injection_detection=False,
        **bot_kwargs,
    )
    await bot.configure()
    return bot


class ExhaustingAskClient(SupportedClient):
    """Always raises ``BudgetExhausted`` from ``ask`` (bot.ask's llm_kwargs do not
    forward arbitrary caller kwargs, so a dedicated subclass — not a flag — is
    the deterministic way to exercise the bot boundary's translation)."""

    async def ask(self, prompt, model=None, **kwargs):
        self.calls.append(("ask", dict(kwargs)))
        raise BudgetExhausted("exhausted", report={"partial_text": "partial text", "total_tokens": 120})


class ExhaustingStreamClient(SupportedClient):
    """Always yields one chunk then raises ``BudgetExhausted`` from ``ask_stream``."""

    async def ask_stream(self, prompt, **kwargs):
        self.calls.append(("ask_stream", dict(kwargs)))
        yield "chunk1"
        raise BudgetExhausted("exhausted", report={"partial_text": "chunk1 partial text", "total_tokens": 150})


class TestBotBoundary:
    async def test_bot_ask_translates_budget_exhausted(self):
        client = ExhaustingAskClient()
        bot = await _make_budget_bot(client)
        response = await bot.ask("hello", token_budget=1000)
        assert response.stop_reason == "budget_exhausted"
        assert response.output == "partial text"
        assert response.metadata["token_budget"]["total_tokens"] == 120
        assert response.metadata["budget_exhausted"] is True

    async def test_bot_ask_stream_translates_budget_exhausted(self):
        client = ExhaustingStreamClient()
        bot = await _make_budget_bot(client)
        chunks = []
        async for chunk in bot.ask_stream("hello", token_budget=1000):
            chunks.append(chunk)
        # The first chunk "chunk1" is yielded before the exception, then the terminal AIMessage is yielded
        assert len(chunks) == 2
        assert chunks[0] == "chunk1"
        assert isinstance(chunks[1], AIMessage)
        assert chunks[1].stop_reason == "budget_exhausted"
        assert chunks[1].output == "chunk1 partial text"
        assert chunks[1].metadata["token_budget"]["total_tokens"] == 150
        assert chunks[1].metadata["budget_exhausted"] is True

    async def test_successful_answer_carries_report(self):
        client = SupportedClient()
        bot = await _make_budget_bot(client)
        response = await bot.ask("hello", token_budget=1000)
        assert response.metadata["token_budget"]["budget_exhausted"] is False

    async def test_typed_errors_still_propagate(self):
        client = UnsupportedClient()
        bot = await _make_budget_bot(client)
        with pytest.raises(BudgetUnsupported):
            await bot.ask("hello", token_budget=1000)

    async def test_child_bot_reraises_to_owner(self):
        registry = BudgetRegistry()
        policy = TokenBudgetPolicy(token_budget=1000)
        scope = await registry.create(policy)
        client = ExhaustingAskClient(budget_registry=registry)
        bot = await _make_budget_bot(client)
        token = _CURRENT_SCOPE.set(scope)
        try:
            with pytest.raises(BudgetExhausted):
                await bot.ask("hello")
        finally:
            _CURRENT_SCOPE.reset(token)

    async def test_owner_designated_once_on_execute_llm_call(self):
        # The client sees a CHILD scope (its own `owner_designated` default), since
        # execute_llm_call forwards `budget_scope=<root>` and the entry adapter turns
        # an inherited parent into a child (spec §2.1) — so designation must be
        # observed on the ROOT scope, which is what stays bound around the client
        # call, not what the client itself sees.
        seen_owner_designated: list[bool] = []

        class OwnerCapturingBot(BaseBot):
            async def execute_llm_call(self, client, method="ask", **llm_kwargs):
                result = await super().execute_llm_call(client, method, **llm_kwargs)
                scope = current_budget_scope()
                seen_owner_designated.append(scope.owner_designated if scope else None)
                return result

        client = SupportedClient()
        bot = OwnerCapturingBot(name="owner-probe", llm=client, memory_type="memory", injection_detection=False)
        await bot.configure()
        await bot.ask("hello", token_budget=1000)
        # execute_llm_call designates the root owner exactly once, before the client call returns.
        assert seen_owner_designated == [True]

    async def test_resume_with_envelope_reattaches(self):
        registry = BudgetRegistry()
        policy = TokenBudgetPolicy(token_budget=1000)
        scope = await registry.create(policy)
        env = await registry.suspend(scope)

        seen_operation_ids: list[str] = []

        class ResumeRecordingClient(SupportedClient):
            async def resume(self, session_id, user_input, state):
                s = current_budget_scope()
                seen_operation_ids.append(s.operation_id if s else None)
                return await self.ask(user_input)

        client = ResumeRecordingClient(budget_registry=registry)
        bot = await _make_budget_bot(client, budget_registry=registry)
        # NOTE: AbstractBot.resume() references `self.client`, an attribute that is
        # never assigned anywhere in the class today (pre-existing on `dev`, unrelated
        # to FEAT-550 — confirmed via `git show dev:.../abstract.py`). Out of scope
        # for this task to fix; set it directly here so the FEAT-550 reattachment
        # logic (which runs BEFORE that pre-existing reference) can be exercised.
        bot.client = client
        await bot.resume("session-1", "hello", {TOKEN_BUDGET_STATE_KEY: env})
        assert seen_operation_ids == [scope.operation_id]
