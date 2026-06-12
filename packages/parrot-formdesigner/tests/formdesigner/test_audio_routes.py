"""Tests for audio route registration (FEAT-224 TASK-1464, FEAT-236 TASK-1542)."""

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


def _audio_handler(app: web.Application):
    """Return the mounted AudioFormWSHandler instance (or None)."""
    for r in app.router.routes():
        resource = getattr(r, "resource", None)
        if resource and "/audio/ws" in getattr(resource, "canonical", ""):
            return r.handler.__self__  # bound method → handler instance
    return None


class TestSuperTonicLazyWiring:
    """FEAT-236 TASK-1542: SuperTonic-first lazy synthesizer wiring."""

    def test_setup_mounts_audio_ws_when_transcriber_only(self) -> None:
        """Transcriber-only mounts the WS with auto_synthesize enabled."""
        app = web.Application()
        setup_form_api(app, MagicMock(), transcriber=MagicMock())
        handler = _audio_handler(app)
        assert handler is not None
        assert handler.synthesizer is None
        assert handler._auto_synthesize is True

    def test_explicit_synthesizer_takes_precedence(self) -> None:
        """An injected synthesizer is used as-is; auto_synthesize stays off."""
        app = web.Application()
        synth = MagicMock()
        setup_form_api(app, MagicMock(), synthesizer=synth, transcriber=MagicMock())
        handler = _audio_handler(app)
        assert handler is not None
        assert handler.synthesizer is synth
        assert handler._auto_synthesize is False

    def test_route_setup_does_not_load_onnx_model(self, monkeypatch) -> None:
        """Route setup loads no ONNX model (no SUPERTONIC_MODEL_PATH needed)."""
        monkeypatch.delenv("SUPERTONIC_MODEL_PATH", raising=False)
        app = web.Application()
        # Must not raise and must not construct/load any synthesizer eagerly.
        setup_form_api(app, MagicMock(), token_validator=MagicMock())
        handler = _audio_handler(app)
        assert handler is not None
        # No synthesizer object was built at setup time — lazy on first synth.
        assert handler.synthesizer is None
        assert handler._auto_synthesize is True
