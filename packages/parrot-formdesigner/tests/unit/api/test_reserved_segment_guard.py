"""Unit tests for the reserved-segment guard (FEAT-429 TASK-2250, spec Module 5).

Removing the `/t/` marker (FEAT-429 Module 1) put the dynamic `{tenant}`
segment at the same URL tree level as literal segments (`org`,
`form-controls`). Verified behavior (spec §2, real server, aiohttp 3.14.3):
aiohttp falls through from a literal branch with no matching sub-route to
the dynamic sibling, so a tenant slug equal to a reserved literal gets a
MIXED surface. The guard in ``requires_tenant`` (``api/tenant.py``) rejects
a declared tenant in the reserved set with a plain 404, turning that mixed
surface into a consistent one.

These tests exercise ``setup_form_api``'s REAL registered routes end to
end via ``aiohttp.test_utils.TestClient``/``TestServer`` directly (this
environment lacks the ``pytest-aiohttp`` plugin that provides the
``aiohttp_client`` fixture used elsewhere in this suite — that gap
pre-dates this task and already shows up as baseline errors; using the
underlying test utilities directly sidesteps it without touching anyone
else's environment). Navigator-auth's ``is_authenticated``/``user_session``
(a hard dependency of ``_wrap_auth``) are monkeypatched to pass-through
decorators so no real auth backend is needed — the same bypass philosophy
this repo's other API-layer integration tests use (e.g.
``tests/integration/test_operations_e2e.py``, which mounts bare handlers
instead of going through ``_wrap_auth`` at all). The guard itself fires
BEFORE authorization, so bypassing auth does not weaken these assertions.
"""

from __future__ import annotations

import logging

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from parrot_formdesigner.api import routes as api_routes
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


def _passthrough_decorator_factory(*_args, **_kwargs):
    """Stand-in for ``is_authenticated(...)``/``user_session()`` that
    returns the handler untouched — see module docstring for rationale."""

    def _decorator(handler):
        return handler

    return _decorator


@pytest.fixture(autouse=True)
def _bypass_navigator_auth(monkeypatch):
    monkeypatch.setattr(
        api_routes, "is_authenticated", _passthrough_decorator_factory
    )
    monkeypatch.setattr(api_routes, "user_session", _passthrough_decorator_factory)


def _build_app(session: dict | None = None) -> tuple[web.Application, FormRegistry]:
    """Build a bare app with ``setup_form_api`` mounted.

    Args:
        session: When given, installs a middleware stashing
            ``request.session = {"session": session}`` before the handler
            chain runs — mirrors navigator-auth's ``user_session()``
            (real requires_tenant()'s ``_authorize`` reads exactly this
            shape). ``None`` leaves ``request.session`` unset.
    """
    middlewares = []
    if session is not None:

        @web.middleware
        async def _inject_session(request: web.Request, handler):
            request.session = {"session": session}
            return await handler(request)

        middlewares.append(_inject_session)

    app = web.Application(middlewares=middlewares)
    registry = FormRegistry()
    setup_form_api(app, registry)
    return app, registry


class TestReservedSegmentDeclared404:
    """spec §4 / task Test Specification: test_reserved_segment_declared_404."""

    @pytest.mark.parametrize("segment", ["org", "form-controls"])
    @pytest.mark.parametrize(
        "session",
        [
            {"programs": ["org"], "superuser": False},
            {"programs": ["other"], "superuser": False},
            {"programs": [], "superuser": True},
        ],
        ids=["member", "non-member", "superuser"],
    )
    async def test_declared_reserved_segment_404_regardless_of_session(
        self, segment, session
    ):
        """A declared tenant equal to a reserved literal 404s on a forms
        route for members, non-members AND superusers alike — the guard
        runs before ``_authorize()``, so no session state can bypass it,
        which is exactly what makes the surface CONSISTENT rather than
        mixed (spec §2/§7)."""
        app, _registry = _build_app(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/api/v1/{segment}/forms")

            assert resp.status == 404, (
                f"expected 404 for reserved segment {segment!r} "
                f"(session={session}), got {resp.status}: {await resp.text()}"
            )

    async def test_declared_reserved_segment_404_on_multiple_routes(self):
        """Consistent surface across several distinct forms routes, not a
        single lucky one."""
        app, _registry = _build_app({"programs": ["org"], "superuser": False})
        async with TestClient(TestServer(app)) as client:
            for method, path in (
                ("get", "/api/v1/org/forms"),
                ("post", "/api/v1/org/forms/from-db"),
                ("get", "/api/v1/form-controls/forms"),
            ):
                resp = await getattr(client, method)(path)
                assert resp.status == 404, f"{method.upper()} {path} -> {resp.status}"


class TestLiteralFallthroughDocumented:
    """spec §4 / task Test Specification: test_literal_fallthrough_documented."""

    async def test_org_literal_route_unaffected_by_guard(self):
        """``/api/v1/org/graph`` is org's OWN literal sub-route (registered
        with ``tenant="none"`` — no ``requires_tenant`` layer at all), so it
        is served by the org handler directly, never touching the
        dynamic ``{tenant}`` branch or the guard. Response is 501 (no
        ``org_graph_service`` configured) rather than 404 — proof the
        request reached ``get_org_graph``, not a router miss (AC3: /org/*
        routes stay byte-identical to their FEAT-421 state)."""
        app, _registry = _build_app({"programs": [], "superuser": True})
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/org/graph")

            assert resp.status == 501, (
                f"expected 501 (org handler reached, no org_graph_service "
                f"configured), got {resp.status}: {await resp.text()}"
            )

    async def test_org_forms_fallthrough_is_blocked_by_guard(self):
        """``/api/v1/org/forms`` has NO literal sub-route registered under
        the literal ``org`` branch — verified behavior (spec §2, real
        server) is that aiohttp falls through to the dynamic ``{tenant}``
        sibling with ``tenant="org"``, which without the guard would 200
        (the mixed-surface finding this task exists to close). With the
        guard active, ``requires_tenant()`` intercepts that fallthrough and
        returns 404 instead — the regression net for the exact behavior
        Module 5 was built to prevent."""
        app, _registry = _build_app({"programs": ["org"], "superuser": False})
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/org/forms")

            assert resp.status == 404, (
                f"fallthrough to tenant='org' must be blocked by the "
                f"reserved-segment guard, got {resp.status}: {await resp.text()}"
            )


class TestBootWarningOnCollidingTenant:
    """spec §4 / task Test Specification: test_boot_warning_on_colliding_tenant."""

    async def test_warning_logged_when_registry_tenant_collides(self, caplog):
        registry = FormRegistry()
        form = FormSchema(
            form_id="colliding-form",
            title={"en": "Colliding"},
            tenant="org",
            is_public=True,
            sections=[
                FormSection(
                    section_id="s1",
                    fields=[
                        FormField(
                            field_id="name",
                            field_type=FieldType.TEXT,
                            label={"en": "Name"},
                        )
                    ],
                )
            ],
        )
        await registry.register(form)

        app = web.Application()
        setup_form_api(app, registry)

        with caplog.at_level(logging.WARNING, logger="parrot_formdesigner.api.routes"):
            # Starting the TestServer runs app.startup() -> fires the
            # app.on_startup signals, including the boot-warning coroutine
            # registered by setup_form_api (FEAT-429 Module 5).
            async with TestClient(TestServer(app)):
                pass

        assert any(
            "org" in record.getMessage() and "collide" in record.getMessage().lower()
            for record in caplog.records
        ), (
            "expected a boot-time WARNING naming the colliding tenant 'org'; "
            f"captured records: {[r.getMessage() for r in caplog.records]}"
        )

    async def test_no_warning_when_no_collision(self, caplog):
        registry = FormRegistry()
        form = FormSchema(
            form_id="safe-form",
            title={"en": "Safe"},
            tenant="flexroc",
            is_public=True,
            sections=[
                FormSection(
                    section_id="s1",
                    fields=[
                        FormField(
                            field_id="name",
                            field_type=FieldType.TEXT,
                            label={"en": "Name"},
                        )
                    ],
                )
            ],
        )
        await registry.register(form)

        app = web.Application()
        setup_form_api(app, registry)

        with caplog.at_level(logging.WARNING, logger="parrot_formdesigner.api.routes"):
            async with TestClient(TestServer(app)):
                pass

        assert not any(
            "collide" in record.getMessage().lower() for record in caplog.records
        ), "no reserved-tenant collision WARNING expected for a non-colliding tenant"
