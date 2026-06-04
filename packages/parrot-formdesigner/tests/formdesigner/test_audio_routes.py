"""Tests for audio route registration (FEAT-224 TASK-1464)."""

import pytest
from aiohttp import web
from unittest.mock import MagicMock

from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers


class TestAudioRendererRegistration:
    """Tests for AudioFormRenderer registration in _seed_default_renderers."""

    def test_audio_renderer_seeded(self) -> None:
        """_seed_default_renderers registers 'audio' format key."""
        _seed_default_renderers()
        assert "audio" in _RENDERERS

    def test_audio_renderer_type(self) -> None:
        """The 'audio' renderer is an AudioFormRenderer instance."""
        _seed_default_renderers()
        from parrot_formdesigner.renderers.audio import AudioFormRenderer
        assert isinstance(_RENDERERS["audio"], AudioFormRenderer)

    def test_existing_renderers_still_present(self) -> None:
        """Adding audio renderer does not remove existing renderers."""
        _seed_default_renderers()
        for key in ("html", "adaptive", "xml", "pdf"):
            assert key in _RENDERERS


class TestAudioRouteRegistration:
    """Tests for WebSocket route registration in setup_form_api."""

    def test_ws_route_registered_with_voice_services(self) -> None:
        """WS route is mounted when synthesizer and transcriber are provided."""
        app = web.Application()
        registry = MagicMock()
        setup_form_api(
            app,
            registry,
            synthesizer=MagicMock(),
            transcriber=MagicMock(),
        )
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert any("/audio/ws" in r for r in routes)

    def test_ws_route_not_registered_without_voice(self) -> None:
        """WS route is NOT mounted when voice services are None."""
        app = web.Application()
        registry = MagicMock()
        setup_form_api(app, registry)
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert not any("/audio/ws" in r for r in routes)

    def test_ws_route_only_with_synthesizer(self) -> None:
        """WS route is mounted when only synthesizer is provided."""
        app = web.Application()
        registry = MagicMock()
        setup_form_api(app, registry, synthesizer=MagicMock())
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert any("/audio/ws" in r for r in routes)

    def test_ws_route_only_with_transcriber(self) -> None:
        """WS route is mounted when only transcriber is provided."""
        app = web.Application()
        registry = MagicMock()
        setup_form_api(app, registry, transcriber=MagicMock())
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert any("/audio/ws" in r for r in routes)

    def test_setup_form_api_accepts_new_kwargs(self) -> None:
        """setup_form_api accepts synthesizer, transcriber, token_validator."""
        app = web.Application()
        registry = MagicMock()
        # Should not raise TypeError
        setup_form_api(
            app,
            registry,
            synthesizer=MagicMock(),
            transcriber=MagicMock(),
            token_validator=MagicMock(),
        )
