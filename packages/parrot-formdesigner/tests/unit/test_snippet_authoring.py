"""Unit tests for SnippetAuthoringToolkit — FEAT-459 / TASK-3176."""

from __future__ import annotations

import inspect

from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    CapabilityTier,
    SnippetBundle,
    SnippetSource,
)
from parrot_formdesigner.tools.snippet_authoring import GeneratedBundle, SnippetAuthoringToolkit
from scripts.check_snippet_conformance import EquivalenceFixture


def _pure_bundle(handler_ref: str = "f.onBeforeSubmit") -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref=handler_ref,
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=CapabilityTier.PURE),
        python_source="def run(ctx): return {}",
        python_sha256="a" * 64,
    )


async def test_draft_from_description_runs_gate_before_returning() -> None:
    async def _generate(description: str) -> GeneratedBundle:
        return GeneratedBundle(
            bundle=_pure_bundle(),
            fixtures=[EquivalenceFixture(name="basic", input_payload={}, expected_output={})],
        )

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    result = await toolkit.draft_from_description("if total > 5000, require approver_email")
    assert result["ready"] is True
    assert result["gate_errors"] == []


async def test_draft_from_description_surfaces_gate_failures_without_raising() -> None:
    async def _generate(description: str) -> GeneratedBundle:
        bad_bundle = SnippetBundle(
            source=SnippetSource.GIT,
            handler_ref="f.onBeforeSubmit",
            event="onBeforeSubmit",
            manifest=CapabilityManifest(tier=CapabilityTier.PURE),
            python_source="import socket\ndef run(ctx): return {}",
            python_sha256="a" * 64,
        )
        return GeneratedBundle(bundle=bad_bundle, fixtures=[])

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    result = await toolkit.draft_from_description("some rule")
    assert result["ready"] is False
    assert len(result["gate_errors"]) > 0
    assert result["bundle"] is not None  # still returned for retry context


async def test_summarize_capabilities_is_plain_language_not_json() -> None:
    async def _generate(description: str) -> GeneratedBundle:  # pragma: no cover — unused
        raise AssertionError("should not be called")

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    summary = await toolkit.summarize_capabilities(CapabilityManifest(tier=CapabilityTier.HELPERS))
    assert "{" not in summary
    assert "helpers" in summary.lower()


def test_toolkit_never_calls_publish_or_exec() -> None:
    """Structural C4 enforcement: no method in this toolkit's source calls
    SnippetApprovalService.publish() or exec()."""
    source = inspect.getsource(SnippetAuthoringToolkit)
    assert ".publish(" not in source
    assert "exec(" not in source  # only run_gate()'s OWN module (TASK-3175) may exec, not this toolkit


class _SpyApprovalService:
    """Records draft() calls; raises loudly if publish is ever touched."""

    def __init__(self) -> None:
        self.draft_calls: list[tuple[SnippetBundle, str]] = []

    async def draft(self, bundle: SnippetBundle, *, tenant: str) -> SnippetBundle:
        self.draft_calls.append((bundle, tenant))
        return bundle.model_copy(update={"version": 1})

    def __getattr__(self, name: str):
        if name == "publish":
            raise AssertionError("propose_for_tenant must never touch .publish")
        raise AttributeError(name)


async def test_propose_for_tenant_calls_draft_never_publish() -> None:
    async def _generate(description: str) -> GeneratedBundle:
        return GeneratedBundle(
            bundle=_pure_bundle(),
            fixtures=[EquivalenceFixture(name="basic", input_payload={}, expected_output={})],
        )

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    spy = _SpyApprovalService()

    result = await toolkit.propose_for_tenant(
        "if total > 5000, require approver_email", tenant="acme", approval_service=spy
    )

    assert result["ready"] is True
    assert result["draft_version"] == 1
    assert len(spy.draft_calls) == 1
    drafted_bundle, drafted_tenant = spy.draft_calls[0]
    assert drafted_tenant == "acme"
    assert drafted_bundle.source == SnippetSource.DB
    assert drafted_bundle.tenant == "acme"


async def test_propose_for_tenant_skips_draft_when_gate_fails() -> None:
    async def _generate(description: str) -> GeneratedBundle:
        bad_bundle = SnippetBundle(
            source=SnippetSource.GIT,
            handler_ref="f.onBeforeSubmit",
            event="onBeforeSubmit",
            manifest=CapabilityManifest(tier=CapabilityTier.PURE),
            python_source="import socket\ndef run(ctx): return {}",
            python_sha256="a" * 64,
        )
        return GeneratedBundle(bundle=bad_bundle, fixtures=[])

    toolkit = SnippetAuthoringToolkit(generate_bundle=_generate)
    spy = _SpyApprovalService()

    result = await toolkit.propose_for_tenant("some rule", tenant="acme", approval_service=spy)

    assert result["ready"] is False
    assert "draft_version" not in result
    assert len(spy.draft_calls) == 0
