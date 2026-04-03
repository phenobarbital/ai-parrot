"""Unit tests for parrot-formdesigner HTTP handlers."""
import pytest
from aiohttp import web
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.services import FormRegistry
from parrot.formdesigner.handlers import setup_form_routes


@pytest.fixture
def registry() -> FormRegistry:
    return FormRegistry()


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                ],
            )
        ],
    )


@pytest.fixture
def app_with_routes(registry) -> web.Application:
    app = web.Application()
    setup_form_routes(app, registry=registry)
    return app


class TestSetupFormRoutes:
    def test_registers_routes(self, app_with_routes):
        routes = list(app_with_routes.router.routes())
        assert len(routes) >= 12

    def test_has_api_forms_route(self, app_with_routes):
        paths = [str(r.resource) for r in app_with_routes.router.routes()]
        assert any("/api/v1/forms" in p for p in paths)

    def test_has_gallery_route(self, app_with_routes):
        paths = [str(r.resource) for r in app_with_routes.router.routes()]
        assert any("/gallery" in p for p in paths)


@pytest.mark.asyncio
class TestFormAPIHandler:
    async def test_list_forms_empty(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        assert resp.status == 200
        data = await resp.json()
        assert "forms" in data
        assert isinstance(data["forms"], list)

    async def test_get_unknown_form_404(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms/nonexistent")
        assert resp.status == 404

    async def test_get_schema_unknown_404(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms/nonexistent/schema")
        assert resp.status == 404

    async def test_get_html_unknown_404(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms/nonexistent/html")
        assert resp.status == 404

    async def test_list_forms_with_registered_form(self, aiohttp_client, app_with_routes, registry, sample_schema):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        assert resp.status == 200
        data = await resp.json()
        assert "test" in data["forms"]

    async def test_get_schema_returns_json(self, aiohttp_client, app_with_routes, registry, sample_schema):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms/test/schema")
        assert resp.status == 200

    async def test_get_html_returns_html(self, aiohttp_client, app_with_routes, registry, sample_schema):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms/test/html")
        assert resp.status == 200
        text = await resp.text()
        assert len(text) > 0

    async def test_validate_form_valid(self, aiohttp_client, app_with_routes, registry, sample_schema):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_routes)
        resp = await client.post("/api/v1/forms/test/validate", json={"name": "John"})
        assert resp.status in (200, 422)
        data = await resp.json()
        assert "is_valid" in data

    async def test_validate_unknown_form_404(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.post("/api/v1/forms/nonexistent/validate", json={"name": "John"})
        assert resp.status == 404

    async def test_create_form_without_client_503(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.post("/api/v1/forms", json={"prompt": "A contact form"})
        assert resp.status == 503


@pytest.mark.asyncio
class TestFormPageHandler:
    async def test_index_returns_html(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "<!DOCTYPE html>" in text

    async def test_gallery_returns_html(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/gallery")
        assert resp.status == 200
        text = await resp.text()
        assert "Gallery" in text

    async def test_render_unknown_form_404(self, aiohttp_client, app_with_routes):
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/forms/nonexistent")
        assert resp.status == 404
