"""Unit tests for Telegram WebApp handler."""

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from parrot.formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.handlers.telegram import TelegramWebAppHandler
from parrot.formdesigner.services.registry import FormRegistry


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="tg-test",
        title="Telegram Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Your Name",
                        required=True,
                    ),
                ],
            )
        ],
    )


@pytest.fixture
async def registry_with_form(sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)
    return registry


@pytest.fixture
def app_with_handler(registry_with_form):
    app = web.Application()
    handler = TelegramWebAppHandler(registry=registry_with_form)
    app.router.add_get("/forms/{form_id}/telegram", handler.serve_webapp)
    app.router.add_post(
        "/api/v1/forms/{form_id}/telegram-submit", handler.rest_fallback
    )
    return app


class TestServeWebApp:
    @pytest.mark.asyncio
    async def test_serves_html_with_sdk(self, aiohttp_client, app_with_handler):
        client = await aiohttp_client(app_with_handler)
        resp = await client.get("/forms/tg-test/telegram")
        assert resp.status == 200
        text = await resp.text()
        assert "telegram-web-app.js" in text
        assert "tg-test" in text

    @pytest.mark.asyncio
    async def test_contains_form_html(self, aiohttp_client, app_with_handler):
        client = await aiohttp_client(app_with_handler)
        resp = await client.get("/forms/tg-test/telegram")
        text = await resp.text()
        assert "Your Name" in text

    @pytest.mark.asyncio
    async def test_contains_main_button_js(self, aiohttp_client, app_with_handler):
        client = await aiohttp_client(app_with_handler)
        resp = await client.get("/forms/tg-test/telegram")
        text = await resp.text()
        assert "MainButton" in text
        assert "sendData" in text

    @pytest.mark.asyncio
    async def test_404_for_unknown_form(self, aiohttp_client, app_with_handler):
        client = await aiohttp_client(app_with_handler)
        resp = await client.get("/forms/nonexistent/telegram")
        assert resp.status == 404


class TestRestFallback:
    @pytest.mark.asyncio
    async def test_validates_valid_submission(
        self, aiohttp_client, app_with_handler
    ):
        client = await aiohttp_client(app_with_handler)
        resp = await client.post(
            "/api/v1/forms/tg-test/telegram-submit",
            json={"_form_id": "tg-test", "name": "John"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["is_valid"] is True

    @pytest.mark.asyncio
    async def test_validates_invalid_submission(
        self, aiohttp_client, app_with_handler
    ):
        client = await aiohttp_client(app_with_handler)
        resp = await client.post(
            "/api/v1/forms/tg-test/telegram-submit",
            json={"_form_id": "tg-test"},
        )
        # Required field missing → 422
        assert resp.status == 422
        data = await resp.json()
        assert data["is_valid"] is False
        assert "name" in data["errors"]

    @pytest.mark.asyncio
    async def test_404_for_unknown_form(self, aiohttp_client, app_with_handler):
        client = await aiohttp_client(app_with_handler)
        resp = await client.post(
            "/api/v1/forms/nonexistent/telegram-submit",
            json={"foo": "bar"},
        )
        assert resp.status == 404
