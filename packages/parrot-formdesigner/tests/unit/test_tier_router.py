"""Unit tests for TierRouter — FEAT-459 / TASK-3172."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import EventResolution, FormEventAbort, FormEventContext
from parrot_formdesigner.core.snippets import (
    AbortSignal,
    CapabilityManifest,
    CapabilityTier,
    SandboxOutcome,
    SnippetBundle,
    SnippetSource,
)
from parrot_formdesigner.services.sandbox.router import TierRouter


def _bundle(tier: CapabilityTier) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref="f.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=tier),
        python_source="def run(): ...",
        python_sha256="a" * 64,
    )


def _ctx() -> FormEventContext:
    return FormEventContext(event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None)


class _FakeSandbox:
    pass


class _FakePool:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    async def acquire(self, spec):
        self.acquired += 1
        return _FakeSandbox()

    async def release(self, sandbox):
        self.released += 1


async def test_router_selects_cheapest_tier() -> None:
    subprocess_pool, gvisor_pool = _FakePool(), _FakePool()
    router = TierRouter(subprocess_pool, gvisor_pool)

    async def _fake_run(sandbox, bundle, sandbox_ctx):
        return SandboxOutcome(resolution=EventResolution(), duration_ms=1.0)

    router._run_on_sandbox = _fake_run  # type: ignore[method-assign]

    await router.execute(_bundle(CapabilityTier.PURE), _ctx())
    assert subprocess_pool.acquired == 1
    assert gvisor_pool.acquired == 0

    await router.execute(_bundle(CapabilityTier.BROKERED), _ctx())
    assert subprocess_pool.acquired == 1
    assert gvisor_pool.acquired == 1


def test_pool_for_tier_raises_without_gvisor_pool() -> None:
    router = TierRouter(_FakePool(), None)
    with pytest.raises(RuntimeError):
        router._pool_for_tier(CapabilityTier.BROKERED)


async def test_router_abort_rehydrates_exception() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    outcome = SandboxOutcome(
        abort=AbortSignal(
            reason="policy violation", user_message="Not allowed", status_code=403
        ),
        duration_ms=1.0,
    )
    with pytest.raises(FormEventAbort) as excinfo:
        raise router._rehydrate_abort(outcome)
    assert excinfo.value.reason == "policy violation"
    assert excinfo.value.user_message == "Not allowed"
    assert excinfo.value.status_code == 403


def test_validate_outcome_rejects_both_set() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    malformed = SandboxOutcome(
        resolution=EventResolution(),
        abort=AbortSignal(reason="x", user_message="y"),
        duration_ms=1.0,
    )
    result = router._validate_outcome(malformed, duration_ms=1.0)
    assert result.abort is not None
    assert result.resolution is None


def test_validate_outcome_rejects_neither_set() -> None:
    router = TierRouter(_FakePool(), _FakePool())
    malformed = SandboxOutcome(duration_ms=1.0)
    result = router._validate_outcome(malformed, duration_ms=1.0)
    assert result.abort is not None


async def test_router_on_failure_abort() -> None:
    router = TierRouter(_FakePool(), _FakePool())

    async def _fake_execute(bundle, ctx):
        return SandboxOutcome(
            abort=AbortSignal(reason="boom", user_message="Failed", status_code=500),
            duration_ms=1.0,
        )

    router.execute = _fake_execute  # type: ignore[method-assign]

    with pytest.raises(FormEventAbort):
        await router.execute_with_policy(
            _bundle(CapabilityTier.PURE), _ctx(), on_failure="abort"
        )


async def test_router_on_failure_continue() -> None:
    router = TierRouter(_FakePool(), _FakePool())

    async def _fake_execute(bundle, ctx):
        return SandboxOutcome(
            abort=AbortSignal(reason="boom", user_message="Failed", status_code=500),
            duration_ms=1.0,
        )

    router.execute = _fake_execute  # type: ignore[method-assign]

    result = await router.execute_with_policy(
        _bundle(CapabilityTier.PURE), _ctx(), on_failure="continue"
    )
    assert result == EventResolution()


async def test_router_invalid_resolution_is_failure() -> None:
    subprocess_pool, gvisor_pool = _FakePool(), _FakePool()
    router = TierRouter(subprocess_pool, gvisor_pool)

    async def _fake_run(sandbox, bundle, sandbox_ctx):
        # Malformed: neither resolution nor abort set.
        return SandboxOutcome(duration_ms=1.0)

    router._run_on_sandbox = _fake_run  # type: ignore[method-assign]

    outcome = await router.execute(_bundle(CapabilityTier.PURE), _ctx())
    assert outcome.abort is not None
    assert outcome.resolution is None


async def test_router_execute_converts_raised_exception_to_abort() -> None:
    router = TierRouter(_FakePool(), _FakePool())

    async def _fake_run(sandbox, bundle, sandbox_ctx):
        raise RuntimeError("worker crashed")

    router._run_on_sandbox = _fake_run  # type: ignore[method-assign]

    outcome = await router.execute(_bundle(CapabilityTier.PURE), _ctx())
    assert outcome.abort is not None
    assert outcome.abort.user_message == "An internal error occurred."
