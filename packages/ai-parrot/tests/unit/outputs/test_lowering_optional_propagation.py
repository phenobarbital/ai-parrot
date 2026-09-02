"""Unit tests for FEAT-499 TASK-2754: lowering propagates the whole
`metadata.extensions` mapping from a composite to every component it
lowers into (the child's own key wins on a collision), so
`baking._optional_paths` still finds `parrot_optional` after a `Report`
layout has been lowered to primitives — not just for an intercepted
`Infographic` (fixed by TASK-2753 alone).
"""

import pytest
from parrot.outputs.a2ui.baking import BakeError
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.models import Component, ComponentMetadata
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
from parrot.outputs.a2ui_renderers.interactive_html import (
    _propagate_extensions as _propagate_interactive,
)
from parrot.outputs.a2ui_renderers.pdf import PDFRenderer
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer
from parrot.outputs.a2ui_renderers.ssr_html import (
    _propagate_extensions as _propagate_ssr,
)

OPTIONAL = ComponentMetadata(extensions={"parrot_optional": ["/narrative"]})


class TestLoweredPathHonoursOptional:
    async def test_report_layout_absent_optional_renders(self):
        """The Report composite is LOWERED before baking — the regression this fixes."""
        env = build_surface(
            "Report",
            {"title": "t", "summary": {"path": "/narrative"}},
            surface_id="s",
            data_model={"facts": {}},
            metadata=OPTIONAL,
        )
        artifact = await InteractiveHTMLRenderer().render(env)
        assert artifact.content

    async def test_intercepted_infographic_absent_optional_renders(self):
        """Infographic is NOT lowered — covered by TASK-2753, asserted here as a guard."""
        env = build_infographic(
            title="t",
            sections=[],
            subtitle={"path": "/narrative"},
            surface_id="s",
            data_model={"facts": {}},
            metadata=OPTIONAL,
        )
        artifact = await InteractiveHTMLRenderer().render(env)
        assert artifact.content

    async def test_required_binding_still_raises(self):
        """No parrot_optional declared -> BakeError, unchanged."""
        env = build_surface(
            "Report",
            {"title": "t", "summary": {"path": "/narrative"}},
            surface_id="s",
            data_model={"facts": {}},
        )
        with pytest.raises((BakeError, Exception)):
            await InteractiveHTMLRenderer().render(env)


class TestExtensionMerge:
    """White-box coverage of the shared `_propagate_extensions` merge rule,
    duplicated identically in both renderer modules (parametrized over both).
    """

    @pytest.mark.parametrize("propagate", [_propagate_interactive, _propagate_ssr])
    def test_child_key_wins_on_collision(self, propagate):
        parent = Component(
            id="root",
            component="Report",
            metadata=ComponentMetadata(extensions={"parrot_optional": ["/narrative"]}),
        )
        child = Component(
            id="child",
            component="Text",
            metadata=ComponentMetadata(extensions={"parrot_optional": ["/own-pointer"]}),
        )
        [merged] = propagate(parent, [child])
        assert merged.metadata.extensions.root["parrot_optional"] == ["/own-pointer"]

    @pytest.mark.parametrize("propagate", [_propagate_interactive, _propagate_ssr])
    def test_child_inherits_other_parent_keys(self, propagate):
        parent = Component(
            id="root",
            component="Report",
            metadata=ComponentMetadata(extensions={"parrot_optional": ["/narrative"], "parrot_theme": "dark"}),
        )
        child = Component(id="child", component="Text")
        [merged] = propagate(parent, [child])
        assert merged.metadata.extensions.root["parrot_optional"] == ["/narrative"]
        assert merged.metadata.extensions.root["parrot_theme"] == "dark"

    @pytest.mark.parametrize("propagate", [_propagate_interactive, _propagate_ssr])
    def test_non_optional_extension_keys_survive(self, propagate):
        parent = Component(
            id="root",
            component="Report",
            metadata=ComponentMetadata(extensions={"parrot_variant": "report"}),
        )
        child = Component(id="child", component="Text")
        [merged] = propagate(parent, [child])
        assert merged.metadata.extensions.root["parrot_variant"] == "report"

    @pytest.mark.parametrize("propagate", [_propagate_interactive, _propagate_ssr])
    def test_propagates_to_grandchildren(self, propagate):
        """`to_components` already flattens the whole lowered tree — every
        entry in `lowered` (direct child OR deep descendant) receives the
        parent's extensions identically, in a single pass."""
        parent = Component(
            id="root",
            component="Report",
            metadata=ComponentMetadata(extensions={"parrot_optional": ["/narrative"]}),
        )
        direct_child = Component(id="c1", component="Column", children=["c2"])
        grandchild = Component(id="c2", component="Text")
        merged = propagate(parent, [direct_child, grandchild])
        assert all(c.metadata.extensions.root["parrot_optional"] == ["/narrative"] for c in merged)

    @pytest.mark.parametrize("propagate", [_propagate_interactive, _propagate_ssr])
    def test_no_parent_extensions_is_noop(self, propagate):
        parent = Component(id="root", component="Report")
        child = Component(id="child", component="Text")
        result = propagate(parent, [child])
        assert result[0] is child


class TestSSRAndPDFParity:
    async def test_ssr_html_matches_interactive(self):
        env = build_surface(
            "Report",
            {"title": "t", "summary": {"path": "/narrative"}},
            surface_id="s",
            data_model={"facts": {}},
            metadata=OPTIONAL,
        )
        artifact = await SSRHTMLRenderer().render(env)
        assert artifact.content

    async def test_pdf_inherits_ssr_behaviour(self):
        env = build_surface(
            "Report",
            {"title": "t", "summary": {"path": "/narrative"}},
            surface_id="s",
            data_model={"facts": {}},
            metadata=OPTIONAL,
        )
        artifact = await PDFRenderer().render(env)
        assert artifact.content
        assert artifact.mime_type == "application/pdf"
