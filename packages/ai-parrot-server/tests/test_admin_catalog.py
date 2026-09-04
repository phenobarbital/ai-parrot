"""Unit tests for the Admin catalog endpoint (FEAT-475, TASK-2584).

Covers ``GET /api/v1/admin/catalog``: auth enforcement, response shape,
and graceful degradation when the ``LocalKB`` lazy import fails.

Follows the same infra-free testing pattern established by
``tests/test_admin_status.py`` (`anon_app` for the real 401 branch,
an authenticated app with a `get_session` stand-in for the 200 branch).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.server.ui.catalog import (
    AdminCatalogHandler,
    KnowledgeBaseOption,
    build_catalog,
)


class _FakeSession(dict):
    """Minimal session stand-in matching the ``user_session()`` contract."""

    def decode(self, key):
        return self.get(f"__decoded_{key}__")


@pytest.fixture
def anon_app():
    """``app["auth"]`` present with zero backends -> the real
    ``is_authenticated()`` "no userdata" 401 branch fires."""
    app = web.Application()
    app["auth"] = SimpleNamespace(backends={})
    app.router.add_view("/api/v1/admin/catalog", AdminCatalogHandler)
    return app


@pytest.fixture
def authenticated_app(monkeypatch):
    """Admin catalog route mounted with every request treated as
    authenticated and a fully-controlled fake session."""

    @web.middleware
    async def _mark_authenticated(request: web.Request, handler):
        request["authenticated"] = True
        return await handler(request)

    async def _fake_get_session(request, new=False):
        return request.app["_test_session"]

    monkeypatch.setattr(
        "navigator_auth.decorators.get_session", _fake_get_session
    )

    app = web.Application(middlewares=[_mark_authenticated])
    app["_test_session"] = _FakeSession()
    app.router.add_view("/api/v1/admin/catalog", AdminCatalogHandler)
    return app


class TestRequiresAuth:
    async def test_unauthenticated_get_returns_401(self, aiohttp_client, anon_app):
        client = await aiohttp_client(anon_app)
        resp = await client.get("/api/v1/admin/catalog")
        assert resp.status == 401


class TestCatalogShape:
    async def test_authenticated_get_matches_admin_catalog_shape(
        self, aiohttp_client, authenticated_app
    ):
        client = await aiohttp_client(authenticated_app)
        resp = await client.get("/api/v1/admin/catalog")
        assert resp.status == 200
        body = await resp.json()

        assert body["llm_providers"] == sorted(body["llm_providers"])
        assert len(body["llm_providers"]) == len(set(body["llm_providers"]))
        assert body["operation_modes"] == ["conversational", "agentic", "adaptive"]
        assert body["memory_types"] == ["memory", "file", "redis"]
        assert body["bot_class_default"] == "BasicBot"
        assert isinstance(body["knowledge_bases"], list)
        for kb in body["knowledge_bases"]:
            assert "class_path" in kb
            assert "name" in kb


def test_build_catalog_shape():
    """`build_catalog()` is pure and unit-testable without aiohttp."""
    catalog = build_catalog()
    assert catalog.operation_modes == ["conversational", "agentic", "adaptive"]
    assert catalog.memory_types == ["memory", "file", "redis"]
    assert catalog.bot_class_default == "BasicBot"
    assert catalog.llm_providers == sorted(catalog.llm_providers)
    assert len(catalog.llm_providers) == len(set(catalog.llm_providers))


def test_build_catalog_dedups_provider_aliases():
    """SUPPORTED_CLIENTS has many alias keys mapping to the same client —
    only the first key per resolved client survives.

    FEAT-523 (TASK-2853): every provider now registers via a real
    `parrot.clients` entry point — "claude" and "anthropic" each carry
    their own `EntryPoint` (and thus their own `.load` bound method) even
    though both target `AnthropicClient`, so the raw registry values are
    no longer `is`-identical; resolve both before comparing.
    """
    catalog = build_catalog()
    # "claude" and "anthropic" both resolve to the same AnthropicClient —
    # only one may appear.
    claude_cls = SUPPORTED_CLIENTS["claude"]
    if callable(claude_cls) and not isinstance(claude_cls, type):
        claude_cls = claude_cls()
    anthropic_cls = SUPPORTED_CLIENTS["anthropic"]
    if callable(anthropic_cls) and not isinstance(anthropic_cls, type):
        anthropic_cls = anthropic_cls()
    assert claude_cls is anthropic_cls
    aliased_present = {
        p for p in catalog.llm_providers if p in ("claude", "anthropic")
    }
    assert len(aliased_present) == 1
    # Every provider returned must be a real, importable key.
    for provider in catalog.llm_providers:
        assert provider in SUPPORTED_CLIENTS


def test_build_catalog_kb_import_failure_degrades(monkeypatch):
    """A failing ``LocalKB`` import must drop that entry, never raise."""
    import parrot.stores.kb as kb_module

    def _raise(name):
        raise ImportError("ai-parrot-embeddings not installed")

    monkeypatch.setattr(kb_module, "__getattr__", _raise)

    catalog = build_catalog()
    names = {kb.name for kb in catalog.knowledge_bases}
    assert "LocalKB" not in names
    assert "RedisKnowledgeBase" in names


def test_knowledge_base_option_class_path_importable():
    """Every catalog KB entry's class_path must resolve to a real class."""
    import importlib

    catalog = build_catalog()
    for kb in catalog.knowledge_bases:
        assert isinstance(kb, KnowledgeBaseOption)
        module_path, _, class_name = kb.class_path.rpartition(".")
        module = importlib.import_module(module_path)
        assert hasattr(module, class_name)
