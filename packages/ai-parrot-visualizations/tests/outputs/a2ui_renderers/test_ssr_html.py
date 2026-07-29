"""Unit tests for the SSR-HTML renderer (TASK-1729)."""

import re

import pytest

pytest.importorskip("jsonpointer")

from datetime import datetime, timezone  # noqa: E402

from parrot.outputs.a2ui.artifacts import DeepLink  # noqa: E402
from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui.renderers import get_a2ui_renderer  # noqa: E402
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer  # noqa: E402

pytestmark = pytest.mark.asyncio


def _envelope(*components: Component, data_model=None) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=list(components),
        dataModel=data_model or {},
    )


class TestSSRHTMLRenderer:
    async def test_capabilities_declared(self):
        caps = SSRHTMLRenderer.capabilities
        assert caps.interactive is False
        assert caps.supports_actions is False
        assert caps.output == "text/html"

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("ssr_html") is SSRHTMLRenderer

    async def test_renders_lowered_basic_tree(self):
        env = _envelope(
            Component(id="b0", component="KPICard", properties={"label": "Rev", "value": 10})
        )
        art = await SSRHTMLRenderer().render(env)
        html_doc = art.content.decode()
        assert html_doc.startswith("<!DOCTYPE html>")
        assert "Rev" in html_doc and art.mime_type == "text/html"

    async def test_output_is_self_contained(self):
        env = _envelope(
            Component(id="b0", component="Card", properties={"title": "T", "image": "https://x/y.png"})
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        # No external src=/href= (deep-link anchors are the only allowed exception).
        externals = re.findall(r'(?:src|href)="https?://[^"]+"', doc)
        assert externals == []

    async def test_data_values_are_escaped_no_script_injection(self):
        payload = '<script>alert(1)</script>'
        env = _envelope(
            Component(id="b0", component="Card", properties={"title": payload})
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "<script>alert(1)</script>" not in doc
        assert "&lt;script&gt;" in doc

    async def test_output_has_zero_live_bindings(self):
        env = _envelope(
            Component(
                id="b0",
                component="Chart",
                properties={"type": "bar", "x": "m", "y": ["v"], "data": {"$bind": "/d"}},
            ),
            data_model={"d": [1, 2, 3]},
        )
        art = await SSRHTMLRenderer().render(env)
        assert "$bind" not in art.content.decode()

    async def test_requires_actions_degrades_to_deep_link_or_notice(self):
        env = _envelope(
            Component(
                id="b0",
                component="Form",
                properties={"fields": [{"name": "e", "input": "text"}], "submit": {"action": "s"}},
            )
        )
        # Without deep links → stripped with a visible notice (from Form lowering).
        art = await SSRHTMLRenderer().render(env)
        assert "not available" in art.content.decode()
        # With a deep link → rendered as an anchor.
        link = DeepLink(
            action_label="Open form",
            url="https://resume/x?token=t",
            token_id="t",
            expires_at=datetime.now(timezone.utc),
        )
        art2 = await SSRHTMLRenderer().render(env, deep_links=[link])
        assert 'href="https://resume/x?token=t"' in art2.content.decode()
        assert art2.deep_links[0].token_id == "t"
