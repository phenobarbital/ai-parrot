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
