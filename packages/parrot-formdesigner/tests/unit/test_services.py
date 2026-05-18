"""Unit tests for parrot-formdesigner services."""
import pytest
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services import FormValidator, FormRegistry, FormCache


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        # FEAT-183: tenant is required by default (require_tenant=True).
        tenant="navigator",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


class TestFormRegistry:
    async def test_register_and_retrieve(self, sample_schema):
        registry = FormRegistry()
        await registry.register(sample_schema)
        # FEAT-183: get() now requires tenant= kwarg (None resolves to "navigator").
        retrieved = await registry.get("test-form", tenant="navigator")
        assert retrieved is not None
        assert retrieved.form_id == "test-form"

    async def test_list_forms(self, sample_schema):
        registry = FormRegistry()
        await registry.register(sample_schema)
        # FEAT-183: list_forms() now scoped to a single tenant.
        forms = await registry.list_forms(tenant="navigator")
        assert len(forms) >= 1

    async def test_get_nonexistent_form(self):
        registry = FormRegistry()
        result = await registry.get("nonexistent", tenant="navigator")
        assert result is None


class TestFormValidator:
    async def test_valid_submission(self, sample_schema):
        validator = FormValidator()
        result = await validator.validate(sample_schema, {"name": "John", "email": "john@example.com"})
        assert result.is_valid is True

    async def test_missing_required_field(self, sample_schema):
        validator = FormValidator()
        result = await validator.validate(sample_schema, {"email": "john@example.com"})
        assert result.is_valid is False


class TestFormCache:
    async def test_set_and_get(self, sample_schema):
        cache = FormCache()
        await cache.set(sample_schema)
        result = await cache.get("test-form")
        assert result is not None
        assert result.form_id == "test-form"

    async def test_get_missing_key(self):
        cache = FormCache()
        result = await cache.get("does-not-exist")
        assert result is None


# --- TASK-1156: OptionsLoader service tests ---

class TestOptionsLoader:
    """Unit tests for the OptionsLoader async service."""

    async def test_fetch_uses_value_and_label_fields(self, aiohttp_client, aiohttp_server):
        """Loader uses value_field and label_field from OptionsSource."""
        from parrot_formdesigner.services.options_loader import OptionsLoader
        from parrot_formdesigner.core.options import OptionsSource
        from aiohttp import web

        response_data = [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]

        async def handler(request):
            return web.json_response(response_data)

        app = web.Application()
        app.router.add_get("/options", handler)
        server = await aiohttp_server(app)

        loader = OptionsLoader()
        source = OptionsSource(
            source_type="endpoint",
            source_ref=str(server.make_url("/options")),
            value_field="id",
            label_field="name",
        )
        options = await loader.fetch(source)
        assert len(options) == 2
        assert options[0].value == "1"
        assert options[0].label == "Alice"
        assert options[1].value == "2"
        assert options[1].label == "Bob"

    async def test_cache_hit_within_ttl_no_second_request(self, aiohttp_server):
        """Second call within TTL returns cached result without HTTP call."""
        from parrot_formdesigner.services.options_loader import OptionsLoader
        from parrot_formdesigner.core.options import OptionsSource
        from aiohttp import web

        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            return web.json_response([{"code": "ES", "label": "Spain"}])

        app = web.Application()
        app.router.add_get("/countries", handler)
        server = await aiohttp_server(app)

        loader = OptionsLoader()
        source = OptionsSource(
            source_type="endpoint",
            source_ref=str(server.make_url("/countries")),
            value_field="code",
            label_field="label",
            cache_ttl_seconds=60,
        )
        # First call — fetches from server
        await loader.fetch(source)
        # Second call — should hit cache
        result = await loader.fetch(source)
        assert call_count == 1  # only one HTTP request made
        assert len(result) == 1
        assert result[0].value == "ES"

    async def test_failure_returns_empty_list(self, aiohttp_server):
        """HTTP 500 response yields [] without raising."""
        from parrot_formdesigner.services.options_loader import OptionsLoader
        from parrot_formdesigner.core.options import OptionsSource
        from aiohttp import web

        async def handler(request):
            return web.Response(status=500, text="Internal Server Error")

        app = web.Application()
        app.router.add_get("/fail", handler)
        server = await aiohttp_server(app)

        loader = OptionsLoader()
        source = OptionsSource(
            source_type="endpoint",
            source_ref=str(server.make_url("/fail")),
        )
        options = await loader.fetch(source)
        assert options == []

    async def test_normalise_uses_value_label_fields(self):
        """_normalise maps raw dicts using value_field and label_field."""
        from parrot_formdesigner.services.options_loader import OptionsLoader
        from parrot_formdesigner.core.options import OptionsSource

        loader = OptionsLoader()
        source = OptionsSource(
            source_type="endpoint",
            source_ref="https://example.com",
            value_field="code",
            label_field="display_name",
        )
        raw = [{"code": "US", "display_name": "United States"}, {"code": "VE", "display_name": "Venezuela"}]
        options = loader._normalise(raw, source)
        assert len(options) == 2
        assert options[0].value == "US"
        assert options[0].label == "United States"

    async def test_invalidate_clears_cache_entry(self, aiohttp_server):
        """invalidate() removes cached entry; next call refetches."""
        from parrot_formdesigner.services.options_loader import OptionsLoader
        from parrot_formdesigner.core.options import OptionsSource
        from aiohttp import web

        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            return web.json_response([{"v": str(call_count), "l": "Item"}])

        app = web.Application()
        app.router.add_get("/data", handler)
        server = await aiohttp_server(app)

        url = str(server.make_url("/data"))
        loader = OptionsLoader()
        source = OptionsSource(
            source_type="endpoint",
            source_ref=url,
            value_field="v",
            label_field="l",
            cache_ttl_seconds=60,
        )
        # First fetch
        r1 = await loader.fetch(source)
        assert r1[0].value == "1"
        # Invalidate + refetch
        loader.invalidate(url)
        r2 = await loader.fetch(source)
        assert r2[0].value == "2"
        assert call_count == 2
