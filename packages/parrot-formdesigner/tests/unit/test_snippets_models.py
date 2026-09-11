"""Unit tests for core/snippets.py models — FEAT-459 / TASK-3161."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core.snippets import (
    BrokerAllowlist,
    CapabilityManifest,
    CapabilityTier,
    SandboxContext,
    SnippetBundle,
    SnippetSource,
    SnippetStatus,
)


def test_manifest_rejects_unknown_tier() -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest(tier="omniscient")  # type: ignore[arg-type]


def test_manifest_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest(tier=CapabilityTier.PURE, extra_field="nope")  # type: ignore[call-arg]


def test_manifest_defaults() -> None:
    m = CapabilityManifest(tier=CapabilityTier.PURE)
    assert m.timeout_ms == 5_000
    assert m.max_memory_mb == 128
    assert m.allowlist == BrokerAllowlist()


@pytest.mark.parametrize("timeout_ms", [0, 30_001])
def test_manifest_timeout_bounds(timeout_ms: int) -> None:
    with pytest.raises(ValidationError):
        CapabilityManifest(tier=CapabilityTier.PURE, timeout_ms=timeout_ms)


def test_bundle_handler_ref_pattern() -> None:
    manifest = CapabilityManifest(tier=CapabilityTier.PURE)
    with pytest.raises(ValidationError):
        SnippetBundle(
            source=SnippetSource.GIT,
            handler_ref="no_dot_here",
            event="onBeforeSubmit",
            manifest=manifest,
            python_source="def run(): ...",
            python_sha256="a" * 64,
        )


def test_bundle_defaults_to_published_status() -> None:
    manifest = CapabilityManifest(tier=CapabilityTier.PURE)
    bundle = SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref="my_form.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=manifest,
        python_source="def run(): ...",
        python_sha256="a" * 64,
    )
    assert bundle.status == SnippetStatus.PUBLISHED
    assert bundle.version == 1


def test_sandbox_context_has_no_token_or_headers_field() -> None:
    """Structural OQ-5 enforcement: the fields must not exist on the model."""
    field_names = set(SandboxContext.model_fields)
    assert "token" not in field_names
    assert "headers" not in field_names


def test_sandbox_context_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SandboxContext(
            event="onBeforeSubmit",
            form_id="test_form",
            tenant="test_tenant",
            claims={},
            token="leaked",
        )