"""Integration tests for FEAT-086: form-designer-edition.

Tests the full create → edit → submit lifecycle using the in-memory FormRegistry
and aiohttp test client. No live database or external services are required.

Auth is disabled via ``_AUTH_AVAILABLE = False`` patch (same pattern as
``test_api_auth.py``).
"""

import pytest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient

from parrot.formdesigner.core.schema import FormField, FormSchema, FormSection, SubmitAction
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_form() -> FormSchema:
    """A minimal valid FormSchema for integration tests."""
    return FormSchema(
        form_id="test-form",
        version="1.0",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                    ),
                    FormField(
                        field_id="email",
                        field_type=FieldType.EMAIL,
                        label="Email",
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def registry() -> FormRegistry:
    """A fresh FormRegistry for each test."""
    return FormRegistry()


@pytest.fixture
def app(registry: FormRegistry) -> web.Application:
    """An aiohttp app with form routes registered (auth disabled for tests)."""
    with patch("parrot.formdesigner.handlers.routes._AUTH_AVAILABLE", False):
        application = web.Application()
        setup_form_routes(application, registry=registry)
    return application


# ---------------------------------------------------------------------------
# Helper: register a form in the registry
# ---------------------------------------------------------------------------

async def _register(registry: FormRegistry, form: FormSchema) -> None:
    """Register a form in the registry (async helper)."""
    await registry.register(form, persist=False, overwrite=True)


# ---------------------------------------------------------------------------
# 404 / error tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_form_not_found(aiohttp_client, app: web.Application) -> None:
    """GET on non-existent form returns 404."""
    client: TestClient = await aiohttp_client(app)
    resp = await client.get("/api/v1/forms/nonexistent-form")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_put_form_not_found(aiohttp_client, app: web.Application) -> None:
    """PUT on non-existent form returns 404."""
    client: TestClient = await aiohttp_client(app)
    resp = await client.put(
        "/api/v1/forms/nonexistent-form",
        json={"form_id": "nonexistent-form", "title": "X", "sections": []},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_patch_form_not_found(aiohttp_client, app: web.Application) -> None:
    """PATCH on non-existent form returns 404."""
    client: TestClient = await aiohttp_client(app)
    resp = await client.patch("/api/v1/forms/nonexistent-form", json={"title": "X"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_put_form_id_mismatch(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """PUT with mismatched form_id in body vs URL returns 400."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)
    body = sample_form.model_dump()
    body["form_id"] = "wrong-id"
    resp = await client.put("/api/v1/forms/test-form", json=body)
    assert resp.status == 400


# ---------------------------------------------------------------------------
# PUT tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_full_replacement(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """PUT replaces the form entirely and bumps the version."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)

    new_form = sample_form.model_dump()
    new_form["title"] = "Updated Title"
    resp = await client.put("/api/v1/forms/test-form", json=new_form)

    assert resp.status == 200
    data = await resp.json()
    assert data["title"] == "Updated Title"
    assert data["version"] != "1.0"  # version was bumped


# ---------------------------------------------------------------------------
# PATCH tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_form_partial_update(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """PATCH merges partial JSON and bumps the version."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)

    resp = await client.patch(
        "/api/v1/forms/test-form",
        json={"title": "Patched Title"},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["title"] == "Patched Title"
    assert data["version"] != "1.0"
    assert data["form_id"] == "test-form"  # form_id unchanged


@pytest.mark.asyncio
async def test_patch_form_cannot_change_form_id(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """PATCH ignores attempts to change form_id."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)

    resp = await client.patch(
        "/api/v1/forms/test-form",
        json={"form_id": "hacked-id", "title": "Title"},
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["form_id"] == "test-form"


@pytest.mark.asyncio
async def test_patch_empty_body_returns_400(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """PATCH with empty body returns 400."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)
    resp = await client.patch("/api/v1/forms/test-form", json={})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_version_bumped_multiple_times(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Each PUT/PATCH call increments the version."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)

    # First PATCH
    resp1 = await client.patch("/api/v1/forms/test-form", json={"title": "V1"})
    assert resp1.status == 200
    version1 = (await resp1.json())["version"]

    # Second PATCH
    resp2 = await client.patch("/api/v1/forms/test-form", json={"title": "V2"})
    assert resp2.status == 200
    version2 = (await resp2.json())["version"]

    assert version1 != "1.0"
    assert version2 != version1


# ---------------------------------------------------------------------------
# Submit endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_data_form_not_found(
    aiohttp_client, app: web.Application
) -> None:
    """POST /data on non-existent form returns 404."""
    client: TestClient = await aiohttp_client(app)
    resp = await client.post(
        "/api/v1/forms/nonexistent-form/data",
        json={"name": "John"},
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_submit_data_valid_no_storage(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Valid submission returns 200 even with no storage configured."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)
    resp = await client.post(
        "/api/v1/forms/test-form/data",
        json={"name": "Alice"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["is_valid"] is True
    assert "submission_id" in data
    assert data["forwarded"] is False


@pytest.mark.asyncio
async def test_submit_data_invalid_data_returns_422(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Invalid submission (missing required field) returns 422."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)
    # 'name' is required but omitted
    resp = await client.post(
        "/api/v1/forms/test-form/data",
        json={"email": "alice@example.com"},
    )
    assert resp.status == 422
    data = await resp.json()
    assert data["is_valid"] is False
    assert "errors" in data


# ---------------------------------------------------------------------------
# Full lifecycle integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_edit_submit_lifecycle(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Full lifecycle: register form → PATCH edit → submit data."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)

    # 1. Verify form exists
    get_resp = await client.get("/api/v1/forms/test-form")
    assert get_resp.status == 200

    # 2. PATCH to update title
    patch_resp = await client.patch(
        "/api/v1/forms/test-form",
        json={"title": "Edited Title"},
    )
    assert patch_resp.status == 200
    updated = await patch_resp.json()
    assert updated["title"] == "Edited Title"

    # 3. Submit valid data
    submit_resp = await client.post(
        "/api/v1/forms/test-form/data",
        json={"name": "Bob"},
    )
    assert submit_resp.status == 200
    result = await submit_resp.json()
    assert result["is_valid"] is True
    assert result["submission_id"] is not None


@pytest.mark.asyncio
async def test_put_then_submit(
    aiohttp_client, app: web.Application, registry: FormRegistry, sample_form: FormSchema
) -> None:
    """After PUT replacement, the form can be submitted successfully."""
    await _register(registry, sample_form)
    client: TestClient = await aiohttp_client(app)

    # PUT full replacement
    new_form = sample_form.model_dump()
    new_form["title"] = "Replaced Form"
    put_resp = await client.put("/api/v1/forms/test-form", json=new_form)
    assert put_resp.status == 200

    # Submit to the replaced form
    submit_resp = await client.post(
        "/api/v1/forms/test-form/data",
        json={"name": "Charlie"},
    )
    assert submit_resp.status == 200
    result = await submit_resp.json()
    assert result["is_valid"] is True


@pytest.mark.asyncio
async def test_exports_accessible(aiohttp_client, app: web.Application) -> None:
    """All new public classes are importable from parrot.formdesigner."""
    from parrot.formdesigner import (  # noqa: F401
        ApiKeyAuth,
        AuthConfig,
        BearerAuth,
        FormSubmission,
        FormSubmissionStorage,
        ForwardResult,
        NoAuth,
        SubmissionForwarder,
    )
