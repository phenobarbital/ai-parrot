"""Unit tests for check_snippet_conformance.py — FEAT-459 / TASK-3175."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    CapabilityTier,
    SnippetBundle,
    SnippetSource,
)
from scripts.check_snippet_conformance import (
    EquivalenceFixture,
    check_equivalence,
    check_tier_conformance,
)


def _bundle(
    source: str,
    tier: CapabilityTier = CapabilityTier.PURE,
    stdlib_modules: tuple[str, ...] = (),
    client_source: str | None = None,
) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref="f.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=tier, stdlib_modules=stdlib_modules),
        python_source=source,
        python_sha256="a" * 64,
        client_source=client_source,
    )


def test_conformance_rejects_undeclared_import() -> None:
    bundle = _bundle("import socket\ndef run(ctx): return {}")
    result = check_tier_conformance(bundle)
    assert result.passed is False
    assert any("socket" in e for e in result.errors)


def test_conformance_allows_declared_import() -> None:
    bundle = _bundle("import re\ndef run(ctx): return {}", stdlib_modules=("re",))
    result = check_tier_conformance(bundle)
    assert result.passed is True


def test_conformance_rejects_io_call_at_pure_tier() -> None:
    bundle = _bundle("def run(ctx):\n    open('/etc/passwd')\n    return {}", tier=CapabilityTier.PURE)
    result = check_tier_conformance(bundle)
    assert result.passed is False


def test_conformance_rejects_half_mismatch() -> None:
    # FILL IN: this test's real name in spec §4 covers "Python/TS halves
    #   disagreeing on handler_ref" — that check belongs in
    #   check_tier_conformance or a small dedicated function comparing
    #   bundle.handler_ref parsing between python_source and
    #   client_source, which the current blueprint does NOT implement
    #   (a gap — the spec names this test but the blueprint's
    #   check_tier_conformance only checks imports/IO, not cross-half
    #   handler_ref agreement). Implement the missing check first, then
    #   this test.
    pass


async def test_equivalence_gate_requires_fixtures() -> None:
    bundle = _bundle("def run(ctx): return {}")
    result = await check_equivalence(bundle, fixtures=[])
    assert result.passed is False
    assert "zero equivalence fixtures" in result.errors[0]


async def test_equivalence_gate_detects_divergence() -> None:
    bundle = _bundle("def run(ctx): return {'total': ctx['a'] + 1}")
    fixture = EquivalenceFixture(name="basic", input_payload={"a": 1}, expected_output={"total": 3})
    result = await check_equivalence(bundle, fixtures=[fixture])
    assert result.passed is False


async def test_equivalence_gate_passes_matching_python_only_bundle() -> None:
    bundle = _bundle("def run(ctx): return {'total': ctx['a'] + 1}")
    fixture = EquivalenceFixture(name="basic", input_payload={"a": 1}, expected_output={"total": 2})
    result = await check_equivalence(bundle, fixtures=[fixture])
    assert result.passed is True


async def test_equivalence_gate_fails_loudly_without_js_runner_when_client_source_present() -> None:
    bundle = _bundle("def run(ctx): return {}", client_source="function run(){return {}}")
    fixture = EquivalenceFixture(name="basic", input_payload={}, expected_output={})
    result = await check_equivalence(bundle, fixtures=[fixture], run_js=None)
    assert result.passed is False
    assert any("no JS runner" in e for e in result.errors)
