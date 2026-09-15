"""Unit tests for ContextProjector — FEAT-459 / TASK-3167."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import FormEventContext
from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource
from parrot_formdesigner.services.auth_context import AuthContext
from parrot_formdesigner.services.sandbox.projector import ContextProjector


def _bundle(tier: CapabilityTier, auth_claims: tuple[str, ...] = ()) -> SnippetBundle:
    return SnippetBundle(
        source=SnippetSource.GIT,
        handler_ref="f.onBeforeSubmit",
        event="onBeforeSubmit",
        manifest=CapabilityManifest(tier=tier, auth_claims=auth_claims),
        python_source="def run(): ...",
        python_sha256="a" * 64,
    )


def _ctx(auth: AuthContext | None) -> FormEventContext:
    return FormEventContext(
        event="onBeforeSubmit",
        form_id="f1",
        tenant="acme",
        auth_context=auth,
        payload={"a": 1},
    )


async def test_projector_tier1_has_no_claims() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", token="secret", claims={"sub": "u1"})
    result = await projector.project(_ctx(auth), _bundle(CapabilityTier.PURE))
    assert result.claims == {}


async def test_projector_never_emits_token() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", token="super-secret", headers={"Authorization": "Bearer x"})
    result = await projector.project(_ctx(auth), _bundle(CapabilityTier.HELPERS, auth_claims=("sub",)))
    assert "token" not in result.__class__.model_fields
    assert "super-secret" not in str(result.model_dump())


async def test_projector_claims_are_allowlisted() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", claims={"sub": "u1", "password_hint": "nope"})
    bundle = _bundle(CapabilityTier.HELPERS, auth_claims=("sub", "password_hint"))
    result = await projector.project(_ctx(auth), bundle)
    assert result.claims.get("sub") == "u1"
    assert "password_hint" not in result.claims  # not in SAFE_CLAIM_KEYS


async def test_projector_tier4_claims_equal_tier2() -> None:
    projector = ContextProjector()
    auth = AuthContext(scheme="bearer", claims={"sub": "u1"})
    tier2 = await projector.project(_ctx(auth), _bundle(CapabilityTier.HELPERS, auth_claims=("sub",)))
    tier4 = await projector.project(_ctx(auth), _bundle(CapabilityTier.TOOLKIT, auth_claims=("sub",)))
    assert tier2.claims == tier4.claims


async def test_projector_rejects_unserialisable() -> None:
    projector = ContextProjector()
    ctx = FormEventContext(
        event="onBeforeSubmit",
        form_id="f1",
        tenant="acme",
        auth_context=None,
        payload={"bad": object()},
    )
    with pytest.raises(TypeError):
        await projector.project(ctx, _bundle(CapabilityTier.PURE))


async def test_projector_handles_missing_auth_context_gracefully() -> None:
    projector = ContextProjector()
    # Project with auth_context=None at tier HELPERS, assert no exception and claims == {}
    result = await projector.project(_ctx(None), _bundle(CapabilityTier.HELPERS, auth_claims=("sub",)))
    assert result.claims == {}
