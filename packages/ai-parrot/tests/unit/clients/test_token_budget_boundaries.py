"""FEAT-550 M3 — public entry compatibility and unsupported-provider gate (spec §4 rows)."""
from __future__ import annotations

import inspect
from typing import Any, AsyncGenerator

import pytest

from parrot.clients.base import AbstractClient
from parrot.clients.budget_scope import BudgetRegistry, current_budget_scope, BudgetDefaults, _CURRENT_SCOPE
from parrot.core.exceptions import BudgetUnsupported
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage, InvokeResult
from parrot.models.token_budget import TokenBudgetPolicy


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
        return AIMessage(input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage())

    async def ask_stream(self, prompt, **kwargs) -> AsyncGenerator[Any, None]:
        self.calls.append(("ask_stream", dict(kwargs)))
        yield "chunk"
        yield AIMessage(input=prompt, output="ok", response="ok", model="stub", provider="stub", usage=CompletionUsage())

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
        assert inspect.iscoroutinefunction(SupportedClient.ask) and inspect.isasyncgenfunction(SupportedClient.ask_stream)
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
