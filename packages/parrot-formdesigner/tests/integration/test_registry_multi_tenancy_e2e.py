"""Integration tests for FEAT-183 — FormRegistry Multi-Tenancy.

Verifies that tenant context propagates end-to-end through:
1. aiohttp handler → registry.get(tenant=...)
2. TelegramFormRouter.start_form(tenant=...) → registry.get(tenant=...)
3. tag_yaml_fixtures.py idempotency (running twice produces no diff).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, handle_render
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.telegram.renderer import TelegramRenderer
from parrot_formdesigner.renderers.telegram.router import TelegramFormRouter
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Registry spy
# ---------------------------------------------------------------------------


class TenantCapturingRegistry(FormRegistry):
    """FormRegistry subclass that records the last tenant kwarg passed to get()."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.last_get_tenant: str | None = "_not_called_"

    async def get(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None:
        self.last_get_tenant = tenant
        return await super().get(form_id, tenant=tenant)


# ---------------------------------------------------------------------------
# Middleware helper: inject a navigator-auth session onto each request
# ---------------------------------------------------------------------------


def _make_session_middleware(programs: list[str]):
    """Return an aiohttp middleware that attaches a fake navigator-auth session.

    Args:
        programs: List of program slugs to expose as ``programs`` in the session.
            The first slug is what ``_get_request_tenant`` returns.

    Returns:
        An aiohttp-compatible middleware coroutine.
    """

    @web.middleware
    async def _middleware(request: web.Request, handler):
        request.session = {"session": {"programs": programs}}  # type: ignore[attr-defined]
        return await handler(request)

    return _middleware


# ---------------------------------------------------------------------------
# Test 1: aiohttp handler passes session tenant to registry.get()
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _seed_renderers():
    _RENDERERS.clear()
    _seed_default_renderers()
    yield
    _RENDERERS.clear()


@pytest.mark.asyncio
async def test_handlers_pass_tenant_to_registry(aiohttp_client) -> None:
    """End-to-end: a session carrying tenant='epson' flows into registry.get(tenant='epson').

    Uses the render handler (``handle_render``) with the ``html`` format,
    which calls ``_get_request_tenant(request)`` to extract the tenant from
    the navigator-auth session, then passes it to ``registry.get()``.

    The ``TenantCapturingRegistry`` spy records the ``tenant=`` kwarg so we
    can assert it equals ``"epson"`` rather than ``None`` or ``"navigator"``.
    """
    registry = TenantCapturingRegistry()
    await registry.register(
        FormSchema(
            form_id="intake-epson",
            title={"en": "Intake"},
            tenant="epson",
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
    )

    middleware = _make_session_middleware(["epson"])
    app = web.Application(middlewares=[middleware])
    app["form_registry"] = registry
    app.router.add_get("/api/v1/forms/{form_id}/render/{format}", handle_render)

    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/forms/intake-epson/render/html")

    # The form exists under tenant="epson"; with the session carrying "epson",
    # the handler should find it and return 200.
    assert resp.status == 200, f"unexpected status {resp.status}"
    assert registry.last_get_tenant == "epson", (
        f"registry.get() received tenant={registry.last_get_tenant!r}, expected 'epson'"
    )


# ---------------------------------------------------------------------------
# Test 2: TelegramFormRouter.start_form(tenant=...) propagates to registry.get()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_router_tenant_propagation() -> None:
    """Telegram session's tenant flows into registry.get(tenant=...).

    Mirrors the unit test in ``test_telegram_router.py`` but exercises the
    ``tenant=`` propagation path introduced by FEAT-183.  We use an
    AsyncMock registry so the spy logic is trivial.
    """
    form = FormSchema(
        form_id="tg-form",
        title="Telegram Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="q1",
                        field_type=FieldType.TEXT,
                        label="Your name",
                    )
                ],
            )
        ],
    )

    mock_registry = AsyncMock(spec=FormRegistry)
    mock_registry.get = AsyncMock(return_value=form)

    renderer = TelegramRenderer(base_url="https://example.com")
    router = TelegramFormRouter(renderer=renderer, registry=mock_registry)

    bot = AsyncMock()
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})

    await router.start_form("tg-form", 123, bot, state, tenant="acme")

    # registry.get() must have been called with tenant="acme"
    mock_registry.get.assert_called_once()
    _, call_kwargs = mock_registry.get.call_args
    assert call_kwargs.get("tenant") == "acme", (
        f"expected tenant='acme' but got tenant={call_kwargs.get('tenant')!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: tag_yaml_fixtures.py idempotency
# ---------------------------------------------------------------------------


def test_bulk_fixture_tagger_idempotent(tmp_path: Path) -> None:
    """Running tag_yaml_fixtures twice on the same directory produces no diff.

    Creates a single YAML form fixture without a ``tenant:`` key, runs the
    tagger once (which inserts ``tenant: navigator``), then runs it again and
    asserts the file content is unchanged — proving idempotency.

    Uses ``tmp_path`` so the repository's real fixtures are never touched.
    """
    # Ensure the scripts package is importable from the worktree root.
    worktree_root = Path(__file__).parents[5]  # .../feat-183-formregistry-multi-tenancy
    scripts_root = str(worktree_root)
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)

    from scripts.sdd.tag_yaml_fixtures import main as tagger_main

    fixture_path = tmp_path / "sample_form.yaml"
    fixture_path.write_text(
        "form_id: sample-form\nversion: '1.0'\nsections: []\n",
        encoding="utf-8",
    )

    # First run: should tag the file.
    tagger_main(["--roots", str(tmp_path)])
    after_first = fixture_path.read_text(encoding="utf-8")
    assert "tenant: navigator" in after_first, (
        "tagger should have inserted 'tenant: navigator' on the first run"
    )

    # Second run: must be a no-op.
    tagger_main(["--roots", str(tmp_path)])
    after_second = fixture_path.read_text(encoding="utf-8")
    assert after_first == after_second, (
        "tagger should be idempotent — second run must not change the file"
    )
