"""Unit tests for parrot-formdesigner HTTP handlers."""
import pytest
from aiohttp import web

from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.services import FormRegistry
from parrot.formdesigner.services.registry import FormStorage
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


class FakeStorage(FormStorage):
    """In-memory FormStorage stub for unit tests.

    Args:
        rows: Pre-configured list of form descriptor dicts to return from
            ``list_forms()``. Defaults to an empty list.
        raise_on_list: When ``True``, ``list_forms()`` raises a
            ``RuntimeError`` to simulate a storage backend failure.
    """

    def __init__(
        self,
        rows: list[dict] | None = None,
        *,
        raise_on_list: bool = False,
    ) -> None:
        self._rows = rows or []
        self._raise = raise_on_list

    async def save(self, form, style=None) -> str:
        return form.form_id

    async def load(self, form_id, version=None) -> FormSchema | None:
        return None

    async def delete(self, form_id) -> bool:
        return False

    async def list_forms(self) -> list[dict]:
        if self._raise:
            raise RuntimeError("storage offline")
        return list(self._rows)


@pytest.fixture
def app_with_storage():
    """Fixture that creates a registry with FakeStorage and sets up routes.

    Returns:
        Callable that accepts rows and raise_on_list kwargs, returns a
        configured :class:`web.Application` with a fresh registry and storage.
    """
    def _build(rows, *, raise_on_list=False):
        storage = FakeStorage(rows, raise_on_list=raise_on_list)
        reg = FormRegistry(storage=storage)
        app = web.Application()
        setup_form_routes(app, registry=reg)
        return app
    return _build


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
        """Empty registry with no storage returns an empty forms list."""
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        assert resp.status == 200
        data = await resp.json()
        assert data == {"forms": []}

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
        """A registered form appears in the forms list with correct descriptor keys."""
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        assert resp.status == 200
        data = await resp.json()
        ids = [f["form_id"] for f in data["forms"]]
        assert "test" in ids
        desc = next(f for f in data["forms"] if f["form_id"] == "test")
        assert desc["title"] == "Test Form"
        assert desc["version"] == "1.0"
        assert desc["source"] == "memory"
        assert desc["created_at"] is None
        assert desc["description"] is None

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

    async def test_list_forms_dict_shape(self, aiohttp_client, app_with_routes, registry, sample_schema):
        """One registry form yields one descriptor with all required keys."""
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["forms"]) == 1
        d = data["forms"][0]
        for key in ("form_id", "title", "description", "version", "source", "created_at"):
            assert key in d, f"missing key {key!r} in descriptor"
        assert d["source"] == "memory"
        assert d["created_at"] is None

    async def test_list_forms_localized_title_flattening(self, aiohttp_client, app_with_routes, registry):
        """A localized dict title is flattened to the first string value."""
        form = FormSchema(
            form_id="localized",
            title={"en": "Hello", "es": "Hola"},
            sections=[],
        )
        await registry.register(form)
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        data = await resp.json()
        desc = next(f for f in data["forms"] if f["form_id"] == "localized")
        assert desc["title"] == "Hello"

    async def test_list_forms_with_storage_only_form(self, aiohttp_client, app_with_storage):
        """A form in storage but not in registry appears with source='db'."""
        rows = [{
            "form_id": "persisted-only",
            "version": "1.0",
            "title": "Persisted",
            "description": None,
            "created_at": "2026-04-12T10:31:00+00:00",
        }]
        client = await aiohttp_client(app_with_storage(rows))
        resp = await client.get("/api/v1/forms")
        data = await resp.json()
        assert resp.status == 200
        assert len(data["forms"]) == 1
        d = data["forms"][0]
        assert d["form_id"] == "persisted-only"
        assert d["source"] == "db"
        assert d["created_at"] == "2026-04-12T10:31:00+00:00"

    async def test_list_forms_storage_and_registry_dedupe(
        self, aiohttp_client, app_with_storage, registry, sample_schema
    ):
        """Same form_id in both sources yields one descriptor; registry wins for title/version; storage wins for created_at."""
        await registry.register(sample_schema)  # form_id="test", version="1.0"
        rows = [{
            "form_id": "test",
            "version": "0.9",
            "title": "Stale Storage Title",
            "description": "stale",
            "created_at": "2026-01-01T00:00:00+00:00",
        }]
        client = await aiohttp_client(app_with_storage(rows))
        resp = await client.get("/api/v1/forms")
        data = await resp.json()
        assert len(data["forms"]) == 1
        d = data["forms"][0]
        assert d["form_id"] == "test"
        assert d["source"] == "db"
        assert d["title"] == "Test Form"  # registry wins
        assert d["version"] == "1.0"      # registry wins
        assert d["created_at"] == "2026-01-01T00:00:00+00:00"  # storage wins

    async def test_list_forms_sorted_by_form_id(self, aiohttp_client, app_with_routes, registry):
        """Multiple forms are returned sorted ascending by form_id."""
        for fid in ("c-form", "a-form", "b-form"):
            await registry.register(FormSchema(form_id=fid, title=fid, sections=[]))
        client = await aiohttp_client(app_with_routes)
        resp = await client.get("/api/v1/forms")
        data = await resp.json()
        ids = [f["form_id"] for f in data["forms"]]
        assert ids == ["a-form", "b-form", "c-form"]

    async def test_list_forms_storage_failure_falls_back(
        self, aiohttp_client, app_with_storage, registry, sample_schema
    ):
        """When storage raises, handler returns registry-only list with status 200."""
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_storage([], raise_on_list=True))
        resp = await client.get("/api/v1/forms")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["forms"]) == 1
        assert data["forms"][0]["source"] == "memory"


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
