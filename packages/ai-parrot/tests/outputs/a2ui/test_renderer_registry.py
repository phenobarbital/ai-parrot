"""Unit tests for the A2UI renderer registry (TASK-1723 / Module 4)."""

import pytest

from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.renderers import (
    AbstractA2UIRenderer,
    RendererCapabilities,
    get_a2ui_renderer,
    register_a2ui_renderer,
)


class TestRendererCapabilities:
    def test_capabilities_model_fields(self):
        caps = RendererCapabilities(
            interactive=False,
            supports_actions=False,
            supports_updates=False,
            output="text/html",
        )
        assert caps.output == "text/html"
        assert caps.interactive is False

    def test_capabilities_requires_all_fields(self):
        with pytest.raises(Exception):
            RendererCapabilities(interactive=True)  # type: ignore[call-arg]


class TestRendererRegistry:
    def test_register_and_resolve_dummy_renderer(self):
        caps = RendererCapabilities(
            interactive=False,
            supports_actions=False,
            supports_updates=False,
            output="text/plain",
        )

        @register_a2ui_renderer("dummy_test", caps)
        class DummyRenderer(AbstractA2UIRenderer):
            async def render(self, envelope: CreateSurface, *, bake: bool = True):
                return "ok"

        resolved = get_a2ui_renderer("dummy_test")
        assert resolved is DummyRenderer
        assert resolved.capabilities.output == "text/plain"

    def test_renderer_registry_missing_extra(self):
        with pytest.raises(ImportError) as exc:
            get_a2ui_renderer("ssr_html")
        assert "ai-parrot-visualizations[a2ui]" in str(exc.value)

    def test_missing_pdf_extra_named(self):
        with pytest.raises(ImportError) as exc:
            get_a2ui_renderer("pdf")
        assert "a2ui-pdf" in str(exc.value)

    def test_abstract_renderer_not_instantiable(self):
        with pytest.raises(TypeError):
            AbstractA2UIRenderer()  # type: ignore[abstract]

    def test_registration_requires_capabilities(self):
        with pytest.raises(TypeError):

            @register_a2ui_renderer("bad", capabilities=object())  # type: ignore[arg-type]
            class Bad(AbstractA2UIRenderer):
                async def render(self, envelope, *, bake=True):
                    return "x"
