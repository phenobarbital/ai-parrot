"""Integration tests for POST /api/v1/forms/{form_id}/clone (FEAT-183).

End-to-end via aiohttp test client. Auth is bypassed by registering the
handler directly (without _wrap_auth), matching the pattern used by
test_operations_e2e.py.
"""

from __future__ import annotations

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def source_form() -> FormSchema:
    """Source form for all clone REST tests.

    Returns:
        A FormSchema with one section and one field.
    """
    return FormSchema(
        form_id="source-form",
        title={"en": "Source Form"},
        version="2.3",
        sections=[
            FormSection(
                section_id="sec1",
                title={"en": "Section 1"},
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Full Name"},
                        required=True,
                    ),
                ],
            ),
        ],
    )


async def _make_client(aiohttp_client, registry: FormRegistry):
    """Build a test aiohttp client with the clone handler mounted.

    Registers handler.clone_form directly (without navigator-auth wrapping)
    so integration tests run without an auth stack.

    Args:
        aiohttp_client: pytest-aiohttp fixture.
        registry: Pre-configured FormRegistry.

    Returns:
        aiohttp test client connected to the test application.
    """
    handler = FormAPIHandler(registry=registry)
    app = web.Application()
    app.router.add_post(
        "/api/v1/forms/{form_id}/clone", handler.clone_form
    )
    return await aiohttp_client(app)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


async def test_clone_rest_success(aiohttp_client, source_form: FormSchema) -> None:
    """POST /clone returns 201 with full FormSchema body."""
    registry = FormRegistry(require_tenant=False)
    await registry.register(source_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        json={"new_form_id": "cloned-form"},
    )
    assert resp.status == 201
    data = await resp.json()
    assert data["form_id"] == "cloned-form"
    assert data["version"] == "1.0"
    assert data["meta"]["cloned_from"] == "source-form"
    assert "sections" in data


async def test_clone_rest_with_patch(aiohttp_client, source_form: FormSchema) -> None:
    """POST /clone with patch body applies overrides and returns 201."""
    registry = FormRegistry(require_tenant=False)
    await registry.register(source_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        json={
            "new_form_id": "patched-clone",
            "patch": {"title": "Patched Title"},
        },
    )
    assert resp.status == 201
    data = await resp.json()
    assert data["form_id"] == "patched-clone"
    assert data["title"] == "Patched Title"


# ---------------------------------------------------------------------------
# 400 error paths
# ---------------------------------------------------------------------------


async def test_clone_rest_missing_new_form_id(
    aiohttp_client, source_form: FormSchema
) -> None:
    """POST /clone returns 400 when new_form_id is absent from the body."""
    registry = FormRegistry(require_tenant=False)
    await registry.register(source_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        json={},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_clone_rest_empty_new_form_id(
    aiohttp_client, source_form: FormSchema
) -> None:
    """POST /clone returns 400 when new_form_id is an empty string."""
    registry = FormRegistry(require_tenant=False)
    await registry.register(source_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        json={"new_form_id": ""},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_clone_rest_invalid_json(
    aiohttp_client, source_form: FormSchema
) -> None:
    """POST /clone returns 400 for a malformed JSON body."""
    registry = FormRegistry(require_tenant=False)
    await registry.register(source_form)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        data="not json at all",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


# ---------------------------------------------------------------------------
# 404 and 409 paths
# ---------------------------------------------------------------------------


async def test_clone_rest_source_not_found(aiohttp_client) -> None:
    """POST /clone returns 404 when the source form does not exist."""
    registry = FormRegistry(require_tenant=False)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/nonexistent-form/clone",
        json={"new_form_id": "any-clone"},
    )
    assert resp.status == 404
    data = await resp.json()
    assert "error" in data


async def test_clone_rest_duplicate_id(
    aiohttp_client, source_form: FormSchema
) -> None:
    """POST /clone returns 409 when new_form_id already exists in the registry."""
    registry = FormRegistry(require_tenant=False)
    await registry.register(source_form)
    existing = FormSchema(
        form_id="taken-id",
        title={"en": "Taken"},
        sections=[],
    )
    await registry.register(existing)
    client = await _make_client(aiohttp_client, registry)

    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        json={"new_form_id": "taken-id"},
    )
    assert resp.status == 409
    data = await resp.json()
    assert "error" in data
