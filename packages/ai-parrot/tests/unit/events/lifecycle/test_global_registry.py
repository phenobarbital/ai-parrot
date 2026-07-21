"""Unit tests for global registry singleton and scope() context manager.

FEAT-176 — Lifecycle Events System (TASK-1187).
"""
from __future__ import annotations

import pytest

from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.registry import EventRegistry


class TestGlobalRegistry:
    def test_singleton_identity(self) -> None:
        """get_global_registry() returns the same instance within a scope."""
        with scope():
            a = get_global_registry()
            b = get_global_registry()
            assert a is b

    def test_scope_swaps(self) -> None:
        """scope() yields a fresh registry that becomes the global for the block."""
        with scope() as outer:
            assert get_global_registry() is outer

    def test_scope_restores(self) -> None:
        """Nested scope() restores the outer registry after the inner block exits."""
        with scope() as outer:
            with scope() as inner:
                assert get_global_registry() is inner
                assert inner is not outer
            assert get_global_registry() is outer

    def test_scope_restores_on_exception(self) -> None:
        """scope() restores the previous registry even if the block raises."""
        with scope() as outer:
            with pytest.raises(RuntimeError):
                with scope() as inner:
                    assert get_global_registry() is inner
                    raise RuntimeError("boom")
            assert get_global_registry() is outer

    def test_global_does_not_self_forward(self) -> None:
        """The global registry is never constructed with forward_to_global=True."""
        with scope() as reg:
            assert reg._forward_to_global is False

    def test_scope_yields_event_registry(self) -> None:
        """scope() yields an EventRegistry instance."""
        with scope() as reg:
            assert isinstance(reg, EventRegistry)

    def test_triple_nested_scopes(self) -> None:
        """Three nested scopes each see independent registries."""
        with scope() as r1:
            with scope() as r2:
                with scope() as r3:
                    assert get_global_registry() is r3
                    assert r3 is not r2
                    assert r3 is not r1
                assert get_global_registry() is r2
            assert get_global_registry() is r1

    def test_scope_isolates_subscriptions(self) -> None:
        """Subscriptions added inside a scope are invisible outside it."""
        calls: list[int] = []

        async def listener(e: object) -> None:
            calls.append(1)

        from parrot.core.events.lifecycle.events import BeforeInvokeEvent

        with scope() as inner_reg:
            inner_reg.subscribe(BeforeInvokeEvent, listener)
            assert len(inner_reg._subscriptions) == 1

        # After scope exit, the outer registry has no subscriptions for this listener
        with scope() as outer_reg:
            assert len(outer_reg._subscriptions) == 0
