"""Unit tests for the render dispatcher in ``parrot_formdesigner.api.render``."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from parrot_formdesigner.api.render import (
    _RENDERERS,
    _seed_default_renderers,
    get_renderer,
    handle_render,
    register_renderer,
    supported_formats,
)
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    RenderedForm,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.services.registry import FormRegistry


async def _tenant_wrapped_render(request: web.Request) -> web.Response:
    """Stash the URL-declared tenant, mirroring what @requires_tenant does.

    These tests exercise the render DISPATCHER's own logic (format
    resolution, delegation, 404s), not tenant enforcement (covered by
    TASK-2199's decorator tests) — so this stashes ``request["tenant"]``
    directly from ``match_info`` rather than pulling in navigator-auth
    session/programs scaffolding these tests don't otherwise need.
    """
    request["tenant"] = request.match_info["tenant"]
    return await handle_render(request)


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title={"en": "Test"},
        # FEAT-183: tenant required by FormRegistry (require_tenant=True default).
        tenant="navigator",
        # FEAT-421: handle_render() calls enforce_membership_unless_public()
        # after resolving the form; mark it public so these dispatcher tests
        # (not tenant-enforcement tests) don't need session/programs scaffolding.
        is_public=True,
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                    ),
                ],
            )
        ],
    )


def test_default_seed_includes_html_and_adaptive():
    _seed_default_renderers()
    assert "html" in _RENDERERS
    assert "adaptive" in _RENDERERS


def test_default_seed_includes_a2ui_when_available():
    pytest.importorskip("parrot.outputs.a2ui")
    _seed_default_renderers()
    assert "a2ui" in _RENDERERS


def test_seed_skips_a2ui_when_spec_missing(monkeypatch, caplog):
    import importlib.util

    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args, **kwargs: (
            None if name == "parrot.outputs.a2ui" else real_find_spec(name, *args, **kwargs)
        ),
    )
    with caplog.at_level("INFO"):
        _seed_default_renderers()
    assert "a2ui" not in _RENDERERS
    assert {"html", "adaptive", "xml", "pdf", "audio"} <= set(_RENDERERS)
    assert any("a2ui" in message for message in caplog.messages)


def test_seed_skips_a2ui_when_parent_package_genuinely_absent(monkeypatch, caplog):
    """Code review fix (TASK-3073): a dotted find_spec() RAISES

    ``ModuleNotFoundError`` — it does not return ``None`` — when a parent
    package earlier in the chain (here: ``parrot`` itself) cannot be
    imported at all. This is the REAL "ai-parrot extra not installed"
    deployment shape; ``test_seed_skips_a2ui_when_spec_missing`` above only
    covers the (also real, but different) "parrot exists, the a2ui
    submodule doesn't" shape by monkeypatching a ``None`` return directly.
    """
    import importlib.util

    real_find_spec = importlib.util.find_spec

    def _raising_find_spec(name, *args, **kwargs):
        if name == "parrot.outputs.a2ui":
            raise ModuleNotFoundError("No module named 'parrot'")
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _raising_find_spec)
    with caplog.at_level("INFO"):
        _seed_default_renderers()  # must NOT raise
    assert "a2ui" not in _RENDERERS
    assert {"html", "adaptive", "xml", "pdf", "audio"} <= set(_RENDERERS)
    assert any("a2ui" in message for message in caplog.messages)


async def test_render_a2ui_via_dispatcher(aiohttp_client, sample_form):
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot.outputs.a2ui.serialization import deserialize

    _seed_default_renderers()
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/a2ui")
    assert resp.status == 200
    assert resp.content_type == "application/a2ui+json"
    body = await resp.json()
    message = deserialize(body)
    assert message.create_surface.surface_id == f"form-{sample_form.form_uid}"


def test_register_renderer_overwrites():
    class _R(AbstractFormRenderer):
        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
        ) -> RenderedForm:
            return RenderedForm(content="<x/>", content_type="application/xml")

    r = _R()
    register_renderer("xml", r)
    assert get_renderer("xml") is r
    register_renderer("xml", r)  # idempotent
    assert get_renderer("xml") is r


def test_supported_formats_sorted():
    register_renderer("zeta", _make_dummy_renderer())
    register_renderer("alpha", _make_dummy_renderer())
    assert supported_formats() == sorted(supported_formats())


def _make_dummy_renderer() -> AbstractFormRenderer:
    class _Dummy(AbstractFormRenderer):
        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
        ) -> RenderedForm:
            return RenderedForm(content="<x/>", content_type="application/xml")

    return _Dummy()


async def test_dispatcher_returns_415_for_unknown_format(aiohttp_client, sample_form):
    register_renderer("html", _make_dummy_renderer())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/foo")
    assert resp.status == 415
    body = await resp.json()
    assert "supported" in body
    assert "html" in body["supported"]


async def test_dispatcher_html_delegates(aiohttp_client, sample_form):
    captured: dict[str, Any] = {}

    class _R(AbstractFormRenderer):
        async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None):
            captured["form_id"] = form.form_id
            captured["locale"] = locale
            return RenderedForm(content="<html/>", content_type="text/html")

    register_renderer("html", _R())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/html")
    assert resp.status == 200
    assert resp.content_type == "text/html"
    assert captured["form_id"] == sample_form.form_id
    assert captured["locale"] == "en"


async def test_dispatcher_adaptive_delegates(aiohttp_client, sample_form):
    """Companion to ``test_dispatcher_html_delegates`` for the adaptive key.

    Spec §4 Test Specification — both `html` and `adaptive` paths must be
    exercised through the dispatcher.
    """
    captured: dict[str, Any] = {}

    class _R(AbstractFormRenderer):
        async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None):
            captured["form_id"] = form.form_id
            captured["locale"] = locale
            return RenderedForm(
                content={"type": "AdaptiveCard"},
                content_type="application/json",
            )

    register_renderer("adaptive", _R())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/adaptive")
    assert resp.status == 200
    assert resp.content_type == "application/json"
    assert captured["form_id"] == sample_form.form_id


async def test_dispatcher_404_when_form_unknown(aiohttp_client):
    register_renderer("html", _make_dummy_renderer())
    registry = FormRegistry()

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    # FEAT-389: must be a well-formed (but unregistered) UUID — extract_form_uid()
    # validates format before the registry lookup runs.
    resp = await client.get("/api/v1/navigator/forms/00000000-0000-0000-0000-000000000000/render/html")
    assert resp.status == 404


# =============================================================================
# FEAT-551 M3: Teams format registration and dispatcher extensions
# =============================================================================


def test_register_teams_renderer_noop_without_url(monkeypatch):
    """When no public base URL is configured, teams format is not registered."""
    monkeypatch.delenv("FORMDESIGNER_PUBLIC_URL", raising=False)
    from parrot_formdesigner.api.render import register_teams_renderer, supported_formats

    result = register_teams_renderer()
    assert result is False
    assert "teams" not in supported_formats()


async def test_dispatcher_teams_415_when_unregistered(aiohttp_client, sample_form):
    """When teams is not registered, render request returns 415."""
    # Don't register teams - it should not be in supported formats
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/teams")
    assert resp.status == 415
    body = await resp.json()
    assert "supported" in body
    assert "teams" not in body["supported"]


async def test_dispatcher_teams_passes_tenant(aiohttp_client, sample_form):
    """When renderer declares accepts_tenant, tenant is passed to render()."""
    captured: dict[str, Any] = {}

    class _TenantAwareRenderer(AbstractFormRenderer):
        accepts_tenant = True

        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
            tenant=None,
        ) -> RenderedForm:
            captured["tenant"] = tenant
            return RenderedForm(
                content={"type": "AdaptiveCard"},
                content_type="application/json",
            )

    register_renderer("teams", _TenantAwareRenderer())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/teams")
    assert resp.status == 200
    assert captured["tenant"] == "navigator"


async def test_dispatcher_teams_without_accepts_tenant(aiohttp_client, sample_form):
    """When renderer does NOT declare accepts_tenant, tenant is NOT passed."""
    captured: dict[str, Any] = {}

    class _PlainRenderer(AbstractFormRenderer):
        # Does NOT have accepts_tenant = True

        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
            tenant=None,  # Should NOT be passed
        ) -> RenderedForm:
            captured["tenant"] = tenant
            return RenderedForm(
                content={"type": "AdaptiveCard"},
                content_type="application/json",
            )

    register_renderer("teams", _PlainRenderer())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/teams")
    assert resp.status == 200
    assert captured["tenant"] is None  # Not passed


async def test_dispatcher_with_meta_envelope(aiohttp_client, sample_form):
    """With ?with_meta=true, response includes content, content_type, warnings, metadata."""
    from parrot_formdesigner.core.schema import RenderWarning

    class _MetaRenderer(AbstractFormRenderer):
        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
        ) -> RenderedForm:
            return RenderedForm(
                content={"type": "AdaptiveCard"},
                content_type="application/json",
                warnings=[
                    RenderWarning(
                        field_id="avatar",
                        field_type="image",
                        renderer="teams",
                        reason="image fields not fully supported in Teams",
                    )
                ],
                metadata={"channel": "msteams"},
            )

    register_renderer("teams", _MetaRenderer())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)

    # Test with_meta=true
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/teams?with_meta=true")
    assert resp.status == 200
    body = await resp.json()
    assert "content" in body
    assert "content_type" in body
    assert "warnings" in body
    assert "metadata" in body
    assert body["content"]["type"] == "AdaptiveCard"
    assert body["content_type"] == "application/json"
    assert len(body["warnings"]) == 1
    assert body["warnings"][0]["field_id"] == "avatar"
    assert body["metadata"]["channel"] == "msteams"

    # Test without with_meta - should return raw content
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/teams")
    assert resp.status == 200
    assert resp.content_type == "application/json"
    body_raw = await resp.json()
    assert body_raw["type"] == "AdaptiveCard"


async def test_dispatcher_render_config_error_400(aiohttp_client, sample_form):
    """When renderer raises ValueError, dispatcher returns 400 with error message."""

    class _FailingRenderer(AbstractFormRenderer):
        async def render(
            self,
            form: FormSchema,
            style=None,
            *,
            locale: str = "en",
            prefilled=None,
            errors=None,
        ) -> RenderedForm:
            raise ValueError("no base url configured")

    register_renderer("teams", _FailingRenderer())
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/render/{format}",
        _tenant_wrapped_render,
    )

    client = await aiohttp_client(app)
    resp = await client.get(f"/api/v1/navigator/forms/{sample_form.form_uid}/render/teams")
    assert resp.status == 400
    body = await resp.json()
    assert "error" in body
    assert body["error"] == "no base url configured"
