"""Unit tests for application wiring of the persistence feature (FEAT-457, TASK-2429)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry


def _make_app(*, alias_registry=None) -> web.Application:
    app = web.Application()
    registry = MagicMock(spec=FormRegistry)
    setup_form_api(app, registry, alias_registry=alias_registry)
    return app


@pytest.fixture
def make_app():
    return _make_app


@pytest.fixture
def alias_registry(monkeypatch):
    monkeypatch.setenv("SURVEY_DB_DSN", "postgresql://u:p@localhost/surveys")
    reg = SinkAliasRegistry()
    reg.register("survey_db", tenant="navigator", dsn_env="SURVEY_DB_DSN")
    return reg


class TestWiring:
    def test_without_registry_is_inactive(self, make_app):
        app = make_app(alias_registry=None)
        assert "form_sink_aliases" not in app

    def test_without_registry_handler_has_no_factory(self, make_app):
        app = make_app(alias_registry=None)
        assert app["form_api_handler"]._sink_factory is None

    def test_with_registry_exposes_app_key(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        assert app["form_sink_aliases"] is alias_registry

    def test_handler_receives_factory(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        assert app["form_api_handler"]._sink_factory is not None

    async def test_close_all_on_shutdown(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        handler = app["form_api_handler"]
        handler._sink_factory.close_all = AsyncMock()
        app.freeze()  # aiohttp requires a frozen signal before .send()
        await app.shutdown()
        handler._sink_factory.close_all.assert_awaited_once()

    def test_no_allowlist_mutation_route(self, make_app, alias_registry):
        app = make_app(alias_registry=alias_registry)
        paths = {r.resource.canonical for r in app.router.routes() if r.resource}
        assert not any("alias" in p for p in paths)


class TestReExports:
    def test_new_names_importable_from_services(self):
        from parrot_formdesigner.services import SinkAliasRegistry as ReExportedRegistry
        from parrot_formdesigner.services import SinkFactory as ReExportedFactory

        assert ReExportedRegistry is SinkAliasRegistry
        assert ReExportedFactory is not None
