"""Unit tests for the Adaptive Cards renderer (TASK-1730, rewritten to v1.0 by
FEAT-470 TASK-2543/TASK-2545)."""

import json

import pytest

pytest.importorskip("jsonpointer")

from datetime import UTC, datetime

from parrot.outputs.a2ui.artifacts import DeepLink
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.outputs.a2ui_renderers.adaptive_cards import (
    _AC_SCHEMA,
    _AC_VERSION,
    AdaptiveCardsRenderer,
    _decode_binding_id,
    _encode_binding_id,
)

pytestmark = pytest.mark.asyncio


def _envelope(*components, data_model=None) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=list(components),
        dataModel=data_model or {},
    )


class TestAdaptiveCardsRenderer:
    async def test_capabilities_declared(self):
        caps = AdaptiveCardsRenderer.capabilities
        assert caps.interactive is False
        # TASK-2545: native inputs + Action.Submit/Action.OpenUrl.
        assert caps.supports_actions is True
        assert caps.output == "application/vnd.microsoft.card.adaptive"
        assert "TextField" in caps.supported_components
        assert "Button" in caps.supported_components

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("adaptive_cards") is AdaptiveCardsRenderer

    async def test_card_has_schema_and_pinned_version(self):
        env = _envelope(Component(id="root", component="Text", text="hi"))
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        assert card["$schema"] == _AC_SCHEMA
        assert card["version"] == _AC_VERSION

    async def test_composite_component_still_lowers_and_renders(self):
        """A Parrot composite (KPICard) nested under a primitive Card still
        lowers via its own `.lower()` and renders through the same dispatch."""
        env = _envelope(
            Component(id="root", component="Card", child="k1"),
            Component(id="k1", component="KPICard", label="Rev", value=10),
        )
        blob = (await AdaptiveCardsRenderer().render(env)).content.decode()
        assert "Rev" in blob and "10" in blob

    async def test_output_has_zero_live_bindings(self):
        env = _envelope(
            Component(id="root", component="Text", text={"path": "/d"}),
            data_model={"d": "resolved"},
        )
        blob = (await AdaptiveCardsRenderer().render(env)).content.decode()
        assert "resolved" in blob
        assert '"path"' not in blob

    async def test_row_maps_to_columnset(self):
        env = _envelope(
            Component(id="root", component="Row", children=["t1"]),
            Component(id="t1", component="Text", text="row child"),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        blob = json.dumps(card)
        assert "ColumnSet" in blob
        assert "row child" in blob

    async def test_deep_links_rendered_as_display_text_never_action(self):
        env = _envelope(Component(id="root", component="Text", text="hi"))
        link = DeepLink(
            action_label="Open",
            url="https://x/resume?token=t",
            token_id="t",
            expires_at=datetime.now(UTC),
        )
        art = await AdaptiveCardsRenderer().render(env, deep_links=[link])
        blob = art.content.decode()
        assert "https://x/resume?token=t" in blob  # deep link as display text
        card = json.loads(blob)
        assert card.get("actions", []) == []  # never Action.OpenUrl for a deep link

    async def test_unsupported_primitive_degrades(self):
        env = _envelope(Component(id="root", component="Video", url="https://x/v.mp4"))
        art = await AdaptiveCardsRenderer().render(env)
        assert len(art.metadata["degraded"]) == 1
        record = art.metadata["degraded"][0]
        assert record["component"] == "Video"
        assert record["id"] == "root"


class TestTASK2545:
    """FEAT-470 TASK-2545: Adaptive Cards native inputs + Action.Submit/OpenUrl,
    Teams wrapper routes `a2ui_action` (spec §4)."""

    async def test_adaptive_cards_native_inputs(self):
        env = _envelope(
            Component(
                id="root",
                component="Column",
                children=["tf1", "cb1", "cp1", "sl1", "dt1"],
            ),
            Component(id="tf1", component="TextField", label="Name", value="Alice"),
            Component(id="cb1", component="CheckBox", label="Agree", value=True),
            Component(
                id="cp1",
                component="ChoicePicker",
                label="Pick",
                options=[{"label": "A", "value": "a"}],
                value=["a"],
            ),
            Component(id="sl1", component="Slider", label="Vol", value=5, max=10),
            Component(id="dt1", component="DateTimeInput", label="When", value="2020-01-01"),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        types = {el["type"] for el in card["body"][0]["items"]}
        assert types == {
            "Input.Text",
            "Input.Toggle",
            "Input.ChoiceSet",
            "Input.Number",
            "Input.Date",
        }

    async def test_textfield_variant_number_maps_to_input_number(self):
        env = _envelope(
            Component(id="root", component="TextField", label="Age", variant="number", value=42),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        element = card["body"][0]
        assert element["type"] == "Input.Number"
        assert element["value"] == 42

    async def test_textfield_variant_obscured_maps_to_password_style(self):
        env = _envelope(
            Component(id="root", component="TextField", label="Secret", variant="obscured", value="x"),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        element = card["body"][0]
        assert element["type"] == "Input.Text"
        assert element["style"] == "Password"

    async def test_textfield_variant_longtext_sets_is_multiline(self):
        env = _envelope(
            Component(id="root", component="TextField", label="Bio", variant="longText", value="x"),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        element = card["body"][0]
        assert element["type"] == "Input.Text"
        assert element["isMultiline"] is True

    async def test_adaptive_cards_submit_carries_action(self):
        env = _envelope(
            Component(
                id="root",
                component="Button",
                child="bt1",
                action={"event": {"name": "go", "context": {"k": "v"}}},
            ),
            Component(id="bt1", component="Text", text="Click me"),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        assert len(card["actions"]) == 1
        action = card["actions"][0]
        assert action["type"] == "Action.Submit"
        assert set(action["data"]) == {"a2ui_action", "surfaceId"}
        assert action["data"]["surfaceId"] == "main"
        sobre = action["data"]["a2ui_action"]
        assert sobre["version"] == "v1.0"
        assert sobre["action"]["name"] == "go"
        assert sobre["action"]["context"] == {"k": "v"}
        assert sobre["action"]["surfaceId"] == "main"
        assert sobre["action"]["sourceComponentId"] == "root"

    async def test_adaptive_cards_submit_resolves_context_bindings(self):
        env = _envelope(
            Component(
                id="root",
                component="Button",
                child="bt1",
                action={"event": {"name": "go", "context": {"k": {"path": "/v"}}}},
            ),
            Component(id="bt1", component="Text", text="Click me"),
            data_model={"v": "resolved-value"},
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        sobre = card["actions"][0]["data"]["a2ui_action"]
        assert sobre["action"]["context"] == {"k": "resolved-value"}

    async def test_adaptive_cards_openurl(self):
        env = _envelope(
            Component(
                id="root",
                component="Button",
                child="bt1",
                action={"functionCall": {"call": "openUrl", "args": {"url": "https://example.com"}}},
            ),
            Component(id="bt1", component="Text", text="Open"),
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        assert len(card["actions"]) == 1
        action = card["actions"][0]
        assert action["type"] == "Action.OpenUrl"
        assert action["url"] == "https://example.com"
        assert action["title"] == "Open"

    async def test_adaptive_cards_button_unsupported_function_call_degrades(self):
        env = _envelope(
            Component(
                id="root",
                component="Button",
                child="bt1",
                action={"functionCall": {"call": "formatCurrency", "args": {}}},
            ),
            Component(id="bt1", component="Text", text="Nope"),
        )
        art = await AdaptiveCardsRenderer().render(env)
        card = json.loads(art.content)
        assert card.get("actions", []) == []
        assert len(art.metadata["degraded"]) == 1
        assert art.metadata["degraded"][0]["component"] == "Button"

    async def test_input_id_is_encoded_binding_path(self):
        env = _envelope(
            Component(id="root", component="TextField", label="Name", value={"path": "/form/name"}),
            data_model={"form": {"name": "Alice"}},
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        element = card["body"][0]
        assert "/" not in element["id"]
        assert _decode_binding_id(element["id"]) == "/form/name"
        assert element["value"] == "Alice"

    async def test_input_id_encoding_roundtrip(self):
        for path in ("/form/name", "/a/b/c", "/weird~name/x", "/", ""):
            encoded = _encode_binding_id(path)
            assert "/" not in encoded
            assert _decode_binding_id(encoded) == path

    async def test_input_id_falls_back_to_component_id_without_binding(self):
        env = _envelope(Component(id="root", component="TextField", label="Name", value="literal"))
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        element = card["body"][0]
        assert _decode_binding_id(element["id"]) == "root"


class TestHtmlDocumentDegradesToTextBlockAndOpenUrl:
    """FEAT-527: adaptive_cards cannot embed HtmlDocument — a TextBlock with
    the title, plus a top-level Action.OpenUrl when a srcUrl exists."""

    async def test_htmldocument_with_src_url_gets_openurl_action(self):
        env = _envelope(
            Component(id="root", component="HtmlDocument", title="Doc", srcUrl="https://x/infographic-a.html")
        )
        art = await AdaptiveCardsRenderer().render(env)
        card = json.loads(art.content)

        assert len(card["actions"]) == 1
        action = card["actions"][0]
        assert action["type"] == "Action.OpenUrl"
        assert action["url"] == "https://x/infographic-a.html"
        assert action["title"] == "Doc"
        assert any("HtmlDocument" in d.get("reason", "") for d in art.metadata["degraded"])

    async def test_htmldocument_inline_only_no_action(self):
        env = _envelope(Component(id="root", component="HtmlDocument", title="Doc", html="<p>hi</p>"))
        art = await AdaptiveCardsRenderer().render(env)
        card = json.loads(art.content)

        assert card.get("actions", []) == []
        assert any("HtmlDocument" in d.get("reason", "") for d in art.metadata["degraded"])
        body_text = json.dumps(card["body"])
        assert "<p>hi</p>" not in body_text
