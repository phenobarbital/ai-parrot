"""Tests for Studio reference catalogs (FEAT-467 TASK-2519).

Covers base-classes introspection (+ graceful lazy-import degradation),
LLM client resolution from ``SUPPORTED_CLIENTS`` (+ graceful lazy-loader
failure), the tools catalog delegating to ``tools_catalog._build_catalog``
(same process-wide cache, identical shape to ``/api/v1/tools/catalog``),
and the vector-stores catalog.
"""
from __future__ import annotations

import json
from typing import ClassVar

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.handlers.studio.catalog import StudioCatalogHandler


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response):
    return json.loads(response.body)


def _make_handler(app, *, kind: str):
    request = make_mocked_request(
        "GET", f"/catalog/{kind}", match_info={"kind": kind}, app=app
    )
    return StudioCatalogHandler(request)


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    """Every catalog is a module-level cache — reset before each test so
    tests don't leak state (and don't corrupt the REAL process-wide
    ``tools_catalog._CATALOG_CACHE`` used by the existing
    ``/api/v1/tools/catalog`` endpoint)."""
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(catalog_module, "_LLM_CLIENTS_CACHE", None)
    monkeypatch.setattr(catalog_module, "_VECTOR_STORES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


class TestStudioCatalogs:
    @pytest.mark.asyncio
    async def test_base_classes_listed_with_params(self):
        app = web.Application()
        handler = _make_handler(app, kind="base-classes")

        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 200
        body = await _decode(response)
        names = {row["name"] for row in body}
        assert "BasicBot" in names
        assert "Agent" in names
        basic_bot = next(row for row in body if row["name"] == "BasicBot")
        assert basic_bot["available"] is True
        assert basic_bot["lazy"] is False
        assert isinstance(basic_bot["params"], dict)
        # Rows are sorted by name.
        assert [row["name"] for row in body] == sorted(row["name"] for row in body)

    @pytest.mark.asyncio
    async def test_base_classes_lazy_import_graceful(self, monkeypatch):
        """A lazy export (``_LAZY_ATTRS``) that fails to import degrades to
        an ``available: false`` row instead of raising — exercised via a
        fake stand-in for ``parrot.bots`` with a real ``__getattr__`` (the
        same lazy-resolution mechanism the catalog code calls through
        plain ``getattr()``)."""
        from parrot.bots.basic import BasicBot

        class _FakeBotsModule:
            __all__ = ("BasicBot", "VoiceBot")
            _LAZY_ATTRS: ClassVar[dict[str, str]] = {"VoiceBot": ".voice"}

            def __getattr__(self, name):
                if name == "VoiceBot":
                    raise ImportError("google-genai is not installed")
                raise AttributeError(name)

        fake = _FakeBotsModule()
        fake.BasicBot = BasicBot  # eager attr — resolves via normal lookup, not __getattr__
        monkeypatch.setattr(catalog_module, "bots_module", fake)

        app = web.Application()
        handler = _make_handler(app, kind="base-classes")
        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 200
        body = await _decode(response)
        voice_row = next(row for row in body if row["name"] == "VoiceBot")
        assert voice_row["available"] is False
        assert voice_row["lazy"] is True
        assert "error" in voice_row
        basic_row = next(row for row in body if row["name"] == "BasicBot")
        assert basic_row["available"] is True
        assert basic_row["lazy"] is False

    @pytest.mark.asyncio
    async def test_llm_clients_from_supported_clients(self):
        app = web.Application()
        handler = _make_handler(app, kind="llm-clients")

        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 200
        body = await _decode(response)
        providers = {row["provider"] for row in body}
        assert "anthropic" in providers
        assert "openai" in providers
        anthropic_row = next(row for row in body if row["provider"] == "anthropic")
        assert anthropic_row["available"] is True
        assert anthropic_row["class_name"] == "AnthropicClient"
        assert anthropic_row["default_model"]

    @pytest.mark.asyncio
    async def test_llm_clients_lazy_loader_failure_graceful(self, monkeypatch):
        app = web.Application()

        def _boom():
            raise ImportError("boto3 extra not installed")

        monkeypatch.setattr(
            catalog_module, "SUPPORTED_CLIENTS", {"broken": _boom, "openai": _real_openai()},
        )
        handler = _make_handler(app, kind="llm-clients")

        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 200
        body = await _decode(response)
        broken_row = next(row for row in body if row["provider"] == "broken")
        assert broken_row["available"] is False
        assert broken_row["lazy"] is True

    @pytest.mark.asyncio
    async def test_tools_catalog_shape(self):
        app = web.Application()
        handler = _make_handler(app, kind="tools")

        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 200
        body = await _decode(response)
        assert isinstance(body, list)
        # Populates (and thus shares) tools_catalog's OWN process-wide
        # cache — content-equal to it (JSON round-tripping the response
        # body necessarily produces a fresh list, so `is` isn't the right
        # check; the shared-cache guarantee is that the module global was
        # populated by THIS call, not a Studio-local duplicate).
        assert tools_catalog_module._CATALOG_CACHE is not None
        assert body == tools_catalog_module._CATALOG_CACHE
        if body:
            assert "slug" in body[0]
            assert "dotted_path" in body[0]

    @pytest.mark.asyncio
    async def test_vector_stores_listed(self):
        app = web.Application()
        handler = _make_handler(app, kind="vector-stores")

        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 200
        body = await _decode(response)
        slugs = {row["slug"] for row in body}
        assert "postgres" in slugs
        assert "milvus" in slugs
        postgres_row = next(row for row in body if row["slug"] == "postgres")
        assert postgres_row["class_name"] == "PgVectorStore"

    @pytest.mark.asyncio
    async def test_unknown_catalog_kind_404(self):
        app = web.Application()
        handler = _make_handler(app, kind="nope")

        response = await _unwrap(StudioCatalogHandler.get)(handler)

        assert response.status == 404


def _real_openai():
    from parrot.clients.gpt import OpenAIClient
    return OpenAIClient


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
