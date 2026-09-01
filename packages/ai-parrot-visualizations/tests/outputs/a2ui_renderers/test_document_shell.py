"""Unit tests for the shared document shell (FEAT-493, TASK-2709)."""
import pytest
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer


@pytest.fixture
def simple_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="shell-test",
        components=[Component(id="root", component="Text", text="hello")],
    )


class TestDocumentShell:
    async def test_shell_emits_viewport_and_wrapper(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert '<meta name="viewport"' in doc
        assert 'class="ds-page"' in doc
        assert 'data-layout="analytics"' in doc
        assert 'data-theme="light"' in doc

    async def test_constructor_defaults_preserved(self, simple_envelope):
        """runner.py:635 calls renderer_cls() with no args — this must keep working."""
        assert await InteractiveHTMLRenderer().render(simple_envelope)
        assert await SSRHTMLRenderer().render(simple_envelope)

    async def test_explicit_pair_reaches_the_document(self, simple_envelope):
        doc = (
            await InteractiveHTMLRenderer(theme="midnight", layout="report").render(simple_envelope)
        ).content.decode()
        assert 'data-theme="midnight"' in doc
        assert 'data-layout="report"' in doc

    async def test_design_system_css_inlined(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert ".kpi-card" in doc          # components.css reached the document
        assert "--content-width" in doc    # tokens reached the document

    async def test_self_contained_invariant(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert "<script src=" not in doc
        assert "<link " not in doc
        assert "@import" not in doc

    async def test_interactive_keeps_its_scripts(self, simple_envelope):
        doc = (await InteractiveHTMLRenderer().render(simple_envelope)).content.decode()
        assert 'id="report-data"' in doc
        assert "Chart.js" in doc

    async def test_ssr_shell_also_gets_viewport_and_wrapper(self, simple_envelope):
        doc = (await SSRHTMLRenderer().render(simple_envelope)).content.decode()
        assert '<meta name="viewport"' in doc
        assert 'class="ds-page"' in doc
        assert 'data-layout="analytics"' in doc
        assert 'data-theme="light"' in doc

    async def test_neither_renderer_module_has_a_style_constant(self):
        import parrot.outputs.a2ui_renderers.interactive_html as interactive_mod
        import parrot.outputs.a2ui_renderers.ssr_html as ssr_mod

        assert not hasattr(interactive_mod, "_STYLE")
        assert not hasattr(ssr_mod, "_STYLE")
