"""Unit tests for URL-prefix support in parrot-formdesigner handlers.

When ``setup_form_routes(app, prefix="/form")`` is used, every rendered
link, JS ``fetch()`` URL, and JSON ``url`` response field must carry the
prefix. These tests lock that contract in so a future refactor cannot
silently regress to hardcoded paths.
"""
from __future__ import annotations

import pytest
from aiohttp import web

from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.handlers import setup_form_routes
from parrot.formdesigner.handlers.templates import (
    _normalize_prefix,
    error_page,
    index_page,
    page_shell,
    schema_page,
)
from parrot.formdesigner.services import FormRegistry


PREFIX = "/form"


# ---------------------------------------------------------------------------
# Pure template functions (no aiohttp)
# ---------------------------------------------------------------------------


class TestNormalizePrefix:
    def test_empty_returns_empty(self) -> None:
        assert _normalize_prefix("") == ""

    def test_no_leading_slash_gets_one(self) -> None:
        assert _normalize_prefix("form") == "/form"

    def test_trailing_slash_stripped(self) -> None:
        assert _normalize_prefix("/form/") == "/form"

    def test_multi_segment_kept(self) -> None:
        assert _normalize_prefix("/apps/form") == "/apps/form"


class TestTemplateBuildersHonorPrefix:
    def test_page_shell_nav_uses_prefix(self) -> None:
        html = page_shell("t", "<p>body</p>", prefix=PREFIX)
        assert 'href="/form/"' in html
        assert 'href="/form/gallery"' in html
        # Legacy root-level hrefs MUST NOT leak through when a prefix is set.
        assert 'href="/">New Form' not in html
        assert 'href="/gallery"' not in html

    def test_page_shell_no_prefix_preserves_legacy_paths(self) -> None:
        html = page_shell("t", "<p>body</p>")
        assert 'href="/">New Form' in html
        assert 'href="/gallery"' in html

    def test_auth_script_api_match_carries_prefix(self) -> None:
        html = page_shell("t", "", prefix=PREFIX)
        # JS guard used to decide when to attach the Bearer token.
        assert "url.startsWith('/form/api/')" in html
        assert "url.startsWith('/api/')" not in html

    def test_auth_script_empty_prefix_falls_back_to_api_root(self) -> None:
        html = page_shell("t", "")
        assert "url.startsWith('/api/')" in html

    def test_index_page_fetch_targets_use_prefix(self) -> None:
        html = index_page(prefix=PREFIX)
        # FORM_PREFIX constant + template literal concat.
        assert "const FORM_PREFIX = '/form';" in html
        assert "fetch(FORM_PREFIX + '/api/v1/forms'" in html
        assert "fetch(FORM_PREFIX + '/api/v1/forms/from-db'" in html
        # No absolute hardcoded fetch calls.
        assert "fetch('/api/v1/forms'" not in html
        assert "fetch('/api/v1/forms/from-db'" not in html

    def test_index_page_empty_prefix_uses_empty_form_prefix(self) -> None:
        html = index_page()
        assert "const FORM_PREFIX = '';" in html

    def test_schema_page_links_and_api_docs_use_prefix(self) -> None:
        html = schema_page("abc", "Title", "{}", "{}", prefix=PREFIX)
        assert 'href="/form/forms/abc"' in html
        assert 'href="/form/gallery"' in html
        assert "GET /form/api/v1/forms/abc" in html

    def test_error_page_go_back_uses_prefix(self) -> None:
        html = error_page("oops", prefix=PREFIX)
        assert 'href="/form/"' in html


# ---------------------------------------------------------------------------
# End-to-end aiohttp smoke tests (real request/response cycle)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> FormRegistry:
    return FormRegistry()


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="sample",
        title="Sample Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
            )
        ],
    )


@pytest.fixture
def app_with_prefix(registry: FormRegistry) -> web.Application:
    app = web.Application()
    setup_form_routes(app, registry=registry, prefix=PREFIX, protect_pages=False)
    return app


@pytest.mark.asyncio
class TestPrefixRouting:
    async def test_prefix_stored_in_app(self, app_with_prefix: web.Application) -> None:
        assert app_with_prefix["_form_prefix"] == PREFIX

    async def test_index_served_under_prefix(self, aiohttp_client, app_with_prefix):
        client = await aiohttp_client(app_with_prefix)
        # Legacy root MUST NOT serve the index anymore.
        resp_root = await client.get("/")
        assert resp_root.status == 404
        # Prefixed route does.
        resp = await client.get("/form/")
        assert resp.status == 200
        html = await resp.text()
        assert "const FORM_PREFIX = '/form';" in html
        assert 'href="/form/gallery"' in html
        assert "fetch(FORM_PREFIX + '/api/v1/forms'" in html

    async def test_gallery_page_renders_with_prefix_links(
        self, aiohttp_client, app_with_prefix, registry, sample_schema
    ):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_prefix)
        resp = await client.get("/form/gallery")
        assert resp.status == 200
        html = await resp.text()
        assert 'href="/form/forms/sample"' in html
        assert 'href="/form/forms/sample/schema"' in html

    async def test_render_form_action_uses_prefix(
        self, aiohttp_client, app_with_prefix, registry, sample_schema
    ):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_prefix)
        resp = await client.get("/form/forms/sample")
        assert resp.status == 200
        html = await resp.text()
        assert 'action="/form/forms/sample"' in html
        assert 'href="/form/forms/sample/schema"' in html

    async def test_schema_page_links_use_prefix(
        self, aiohttp_client, app_with_prefix, registry, sample_schema
    ):
        await registry.register(sample_schema)
        client = await aiohttp_client(app_with_prefix)
        resp = await client.get("/form/forms/sample/schema")
        assert resp.status == 200
        html = await resp.text()
        assert 'href="/form/forms/sample"' in html
        assert "GET /form/api/v1/forms/sample" in html

    async def test_unknown_form_error_link_uses_prefix(
        self, aiohttp_client, app_with_prefix
    ):
        client = await aiohttp_client(app_with_prefix)
        resp = await client.get("/form/forms/nonexistent")
        assert resp.status == 404
        html = await resp.text()
        assert 'href="/form/"' in html
