"""FEAT-550 M2 — resume/snapshot and registry lifecycle (spec §4 rows 'Resume and snapshots', 'Registry lifecycle')."""

from __future__ import annotations

import asyncio
import threading

import pytest

from parrot.clients.budget_scope import (
    TOKEN_BUDGET_STATE_KEY,
    BudgetRegistry,
    BudgetScope,
    current_budget_scope,
)
from parrot.core.exceptions import (
    BudgetRegistryFull,
    BudgetResumeConflict,
    BudgetScopeConflict,
    BudgetSnapshotInvalid,
    BudgetStateMissing,
)
from parrot.models.token_budget import TokenBudgetPolicy

pytestmark = pytest.mark.asyncio

POLICY = TokenBudgetPolicy(token_budget=10_000)


class TestResumeAndSnapshots:
    async def test_suspend_then_resume_reuses_same_identity(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        env = await reg.suspend(scope)
        resumed = await reg.resume({TOKEN_BUDGET_STATE_KEY: env})
        assert resumed.operation_id == scope.operation_id and resumed.is_root

    async def test_duplicate_nonce_rejected(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        env = await reg.suspend(scope)
        await reg.resume({TOKEN_BUDGET_STATE_KEY: env})
        with pytest.raises(BudgetResumeConflict):
            await reg.resume({TOKEN_BUDGET_STATE_KEY: env})

    async def test_missing_live_state_typed(self):
        with pytest.raises(BudgetStateMissing):
            await BudgetRegistry().resume({"messages": []})

    async def test_snapshot_cannot_lower_floor_and_transfer_detaches(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        env = await reg.suspend(scope)
        snapshot = await reg.export_settled(scope.operation_id)

        # The original registry's record is now detached: resume raises.
        with pytest.raises(BudgetResumeConflict):
            await reg.resume({TOKEN_BUDGET_STATE_KEY: env})

        # Importing into a NEW registry with a tampered lower consumed_floor is rejected.
        other = BudgetRegistry()
        tampered_env = dict(env)
        tampered_env["consumed_floor"] = snapshot.consumed_floor + 1
        with pytest.raises(BudgetSnapshotInvalid):
            await other.resume({TOKEN_BUDGET_STATE_KEY: tampered_env}, snapshot=snapshot)

        # Untampered import succeeds once and is idempotent when repeated identically.
        resumed = await other.resume({TOKEN_BUDGET_STATE_KEY: env}, snapshot=snapshot)
        assert resumed.operation_id == scope.operation_id
        resumed_again = await other.resume({TOKEN_BUDGET_STATE_KEY: env}, snapshot=snapshot)
        assert resumed_again.operation_id == scope.operation_id

    async def test_new_question_gets_new_uuid_even_with_same_policy(self):
        reg = BudgetRegistry()
        scope1 = await reg.create(POLICY)
        scope2 = await reg.create(POLICY)
        assert scope1.operation_id != scope2.operation_id

    async def test_expired_suspended_state_fails_state_missing(self):
        reg = BudgetRegistry(retention_seconds=0)
        scope = await reg.create(POLICY)
        env = await reg.suspend(scope)
        # Creating another operation triggers pruning of the expired suspended record.
        await reg.create(POLICY)
        with pytest.raises(BudgetStateMissing):
            await reg.resume({TOKEN_BUDGET_STATE_KEY: env})


class TestRegistryLifecycle:
    async def test_active_never_evicted_and_full_registry_refuses(self):
        reg = BudgetRegistry(max_retained=1, retention_seconds=0)
        await reg.create(POLICY)
        with pytest.raises(BudgetRegistryFull):
            await reg.create(POLICY)

    async def test_release_only_terminal(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        with pytest.raises(BudgetScopeConflict):
            await reg.release(scope.operation_id)
        await reg.suspend(scope)
        await reg.release(scope.operation_id)  # no error

    async def test_contextvar_restored_on_every_exit(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        assert current_budget_scope() is None
        with pytest.raises(RuntimeError):
            async with scope:
                assert current_budget_scope() is scope
                raise RuntimeError("boom")
        assert current_budget_scope() is None

    async def test_cross_loop_scope_rejected(self):
        holder: dict[str, BudgetScope] = {}

        def _create_on_other_loop():
            async def _inner():
                reg = BudgetRegistry()
                holder["scope"] = await reg.create(POLICY)

            asyncio.run(_inner())

        thread = threading.Thread(target=_create_on_other_loop)
        thread.start()
        thread.join()

        scope = holder["scope"]
        with pytest.raises(BudgetScopeConflict):
            async with scope:
                pass


# ── Entry adapter: keyword resolution + coroutine/async-generator wrappers ──

import inspect  # noqa: E402

from parrot.clients.budget_scope import (  # noqa: E402
    BUDGET_KWARGS,
    BudgetDefaults,
    budget_entry,
    resolve_budget_request,
)


class _Stub:
    def __init__(self, token_budget=None):
        self._budget_defaults_active = token_budget is not None
        self._defaults = BudgetDefaults(token_budget=token_budget)

    def _budget_defaults(self):
        return self._defaults

    async def ask(self, prompt: str, model: str = None, **kwargs):
        return {"prompt": prompt, "kwargs": kwargs, "scope": current_budget_scope()}

    async def ask_stream(self, prompt: str):
        yield "a"
        yield current_budget_scope()

    async def resume(self, session_id: str, user_input: str, state: dict):
        return {"scope": current_budget_scope()}


class TestResolveBudgetRequest:
    def test_omitted_inherits_constructor_and_explicit_none_disables(self):
        d = BudgetDefaults(token_budget=500)
        assert resolve_budget_request({}, defaults=d, method_name="ask").policy.token_budget == 500
        assert resolve_budget_request({"token_budget": None}, defaults=d, method_name="ask").disabled

    async def test_child_conflict(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        async with scope:
            # Omitted settings inherit the parent scope/policy unchanged.
            req = resolve_budget_request({}, defaults=BudgetDefaults(), method_name="ask")
            assert req.scope is scope and not req.disabled

            with pytest.raises(BudgetScopeConflict):
                resolve_budget_request({"token_budget": 1}, defaults=BudgetDefaults(), method_name="ask")

    def test_options_without_budget_rejected(self):
        with pytest.raises(ValueError):
            resolve_budget_request({"budget_mode": "strict"}, defaults=BudgetDefaults(), method_name="ask")

    def test_budget_snapshot_rejected_outside_resume(self):
        with pytest.raises(TypeError):
            resolve_budget_request({"budget_snapshot": object()}, defaults=BudgetDefaults(), method_name="ask")


class TestEntryWrappers:
    def test_identity_signature_and_wraps_preserved(self):
        w_ask = budget_entry(_Stub.ask, method_name="ask")
        w_stream = budget_entry(_Stub.ask_stream, method_name="ask_stream")
        assert inspect.iscoroutinefunction(w_ask) and inspect.isasyncgenfunction(w_stream)
        assert w_ask.__name__ == "ask" and w_ask.__wrapped__ is _Stub.ask
        assert BUDGET_KWARGS <= set(inspect.signature(w_stream).parameters)
        assert budget_entry(w_ask, method_name="ask") is w_ask  # idempotent

    async def test_no_budget_pass_through_and_keywords_stripped(self):
        w_ask = budget_entry(_Stub.ask, method_name="ask")
        stub_no_budget = _Stub(token_budget=None)
        result = await w_ask(stub_no_budget, "hi")
        assert result["scope"] is None

        stub_with_budget = _Stub(token_budget=100)
        result2 = await w_ask(stub_with_budget, "hi", token_budget=100)
        assert "token_budget" not in result2["kwargs"]
        assert result2["scope"].is_root

    async def test_stream_holds_scope_through_iteration(self):
        w_stream = budget_entry(_Stub.ask_stream, method_name="ask_stream")
        stub = _Stub(token_budget=100)
        items = []
        async for item in w_stream(stub, "hi", token_budget=100):
            items.append(item)
        assert items[0] == "a"
        assert isinstance(items[1], BudgetScope)
        assert current_budget_scope() is None

    async def test_resume_with_state_envelope_reattaches(self):
        reg = BudgetRegistry()
        scope = await reg.create(POLICY)
        env = await reg.suspend(scope)
        w_resume = budget_entry(_Stub.resume, method_name="resume")
        # The resuming client is constructed with the SAME token_budget as the
        # original session (a real client keeps its constructor config across
        # suspend/resume) so the wrapper's slow path — and resolve_budget_request
        # building a fresh root policy — naturally leads into `_enter_scope`,
        # which then finds the state envelope and calls `registry.resume(...)`.
        stub = _Stub(token_budget=POLICY.token_budget)
        stub._budget_registry = reg
        result = await w_resume(stub, "session-1", "hello", {TOKEN_BUDGET_STATE_KEY: env})
        assert result["scope"].is_root
        assert result["scope"].operation_id == scope.operation_id
