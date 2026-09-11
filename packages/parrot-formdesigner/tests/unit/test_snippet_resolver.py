"""Unit tests for services/snippets/base.py — FEAT-459 / TASK-3163."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import EventResolution, FormEventAbort, FormEventContext
from parrot_formdesigner.core.snippets import (
    AbortSignal,
    CapabilityManifest,
    CapabilityTier,
    SandboxContext,
    SandboxOutcome,
    SnippetBundle,
    SnippetSource,
)
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    get_form_event,
)
from parrot_formdesigner.services.snippets.base import register_resolver


@pytest.fixture(autouse=True)
def _clear_registry():
    _clear_event_registry_for_tests()
    yield
    _clear_event_registry_for_tests()


class _FakeSource:
    def __init__(self, bundle: SnippetBundle | None) -> None:
        self.bundle = bundle
        self.resolve_calls = 0

    async def resolve_current(self, *, tenant, handler_ref) -> SnippetBundle | None:
        self.resolve_calls += 1
        return self.bundle


def _bundle(*, version: int = 1) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        version=version,
        handler_ref="survey_v1.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=CapabilityTier.PURE),
        python_source="def run(): ...",
        python_sha256="a" * 64,
    )


async def _fake_project(ctx: FormEventContext, bundle: SnippetBundle) -> SandboxContext:
    return SandboxContext(event=ctx.event, form_id=ctx.form_id, tenant=ctx.tenant, claims={})


async def _fake_execute(bundle: SnippetBundle, ctx: SandboxContext) -> SandboxOutcome:
    return SandboxOutcome(resolution=EventResolution(), duration_ms=1.0)


def test_resolver_registers_once_per_key() -> None:
    source = _FakeSource(_bundle())
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_fake_project,
        execute=_fake_execute,
    )
    with pytest.raises(ValueError):
        register_resolver(
            "survey_v1.onBeforeSubmit",
            tenant=None,
            source=source,
            project_context=_fake_project,
            execute=_fake_execute,
        )


async def test_resolver_survives_republish() -> None:
    """Swapping `source.bundle` changes behaviour with NO re-registration."""

    async def _project_current_version(ctx: FormEventContext, bundle: SnippetBundle) -> SandboxContext:
        return SandboxContext(event=ctx.event, form_id=ctx.form_id, tenant=ctx.tenant, claims={})

    async def _execute_reports_version(bundle: SnippetBundle, ctx: SandboxContext) -> SandboxOutcome:
        return SandboxOutcome(
            resolution=EventResolution(metadata={"version": bundle.version}),
            duration_ms=1.0,
        )

    source = _FakeSource(_bundle(version=1))
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_project_current_version,
        execute=_execute_reports_version,
    )
    handler = get_form_event("survey_v1.onBeforeSubmit")
    ctx = FormEventContext(event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None)

    first = await handler(ctx)
    assert isinstance(first, EventResolution)
    assert first.metadata == {"version": 1}
    assert source.resolve_calls == 1

    # Republish: swap the underlying bundle in place. NO re-registration.
    source.bundle = _bundle(version=2)

    second = await handler(ctx)
    assert isinstance(second, EventResolution)
    assert second.metadata == {"version": 2}
    assert source.resolve_calls == 2

    # The registry entry itself never changed — registering again for the
    # same key still raises ValueError, proving no second registration
    # occurred on republish.
    with pytest.raises(ValueError):
        register_resolver(
            "survey_v1.onBeforeSubmit",
            tenant=None,
            source=source,
            project_context=_project_current_version,
            execute=_execute_reports_version,
        )


async def test_resolver_calls_injected_project_and_execute() -> None:
    source = _FakeSource(_bundle())
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_fake_project,
        execute=_fake_execute,
    )
    handler = get_form_event("survey_v1.onBeforeSubmit")
    ctx = FormEventContext(event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None)
    result = await handler(ctx)
    assert isinstance(result, EventResolution)
    assert source.resolve_calls == 1


async def test_resolver_rehydrates_abort() -> None:
    """A SandboxOutcome.abort must be rehydrated into FormEventAbort, not swallowed."""

    async def _execute_aborts(bundle: SnippetBundle, ctx: SandboxContext) -> SandboxOutcome:
        return SandboxOutcome(
            abort=AbortSignal(reason="total exceeds limit", user_message="Amount too high", status_code=422),
            duration_ms=1.0,
        )

    source = _FakeSource(_bundle())
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_fake_project,
        execute=_execute_aborts,
    )
    handler = get_form_event("survey_v1.onBeforeSubmit")
    ctx = FormEventContext(event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None)

    with pytest.raises(FormEventAbort) as exc_info:
        await handler(ctx)
    assert exc_info.value.reason == "total exceeds limit"
    assert exc_info.value.user_message == "Amount too high"
    assert exc_info.value.status_code == 422


async def test_resolver_raises_when_no_bundle_resolves() -> None:
    source = _FakeSource(None)
    register_resolver(
        "survey_v1.onBeforeSubmit",
        tenant=None,
        source=source,
        project_context=_fake_project,
        execute=_fake_execute,
    )
    handler = get_form_event("survey_v1.onBeforeSubmit")
    ctx = FormEventContext(event="onBeforeSubmit", form_id="f1", tenant=None, auth_context=None)

    with pytest.raises(RuntimeError):
        await handler(ctx)
