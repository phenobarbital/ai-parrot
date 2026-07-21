"""Unit tests for the Adaptive Cards renderer (TASK-1730)."""

import json

import pytest

pytest.importorskip("jsonpointer")

from datetime import datetime, timezone  # noqa: E402

from parrot.outputs.a2ui.artifacts import DeepLink  # noqa: E402
from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui.renderers import get_a2ui_renderer  # noqa: E402
from parrot.outputs.a2ui_renderers.adaptive_cards import (  # noqa: E402
    _AC_SCHEMA,
    _AC_VERSION,
    AdaptiveCardsRenderer,
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
        assert caps.supports_actions is False
        assert caps.output == "application/vnd.microsoft.card.adaptive"

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("adaptive_cards") is AdaptiveCardsRenderer

    async def test_lowered_tree_maps_to_card_deterministic(self):
        env = _envelope(
            Component(id="b0", component="KPICard", properties={"label": "Rev", "value": 10})
        )
        one = (await AdaptiveCardsRenderer().render(env)).content
        two = (await AdaptiveCardsRenderer().render(env)).content
        assert one == two
        card = json.loads(one)
        assert card["type"] == "AdaptiveCard"
        assert any("Rev" in json.dumps(el) for el in card["body"])

    async def test_card_has_schema_and_pinned_version(self):
        env = _envelope(Component(id="b0", component="Card", properties={"title": "T"}))
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        assert card["$schema"] == _AC_SCHEMA
        assert card["version"] == _AC_VERSION

    async def test_no_action_elements_emitted(self):
        env = _envelope(
            Component(id="b0", component="Card", properties={"title": "T", "body": "B"})
        )
        link = DeepLink(
            action_label="Open",
            url="https://x/resume?token=t",
            token_id="t",
            expires_at=datetime.now(timezone.utc),
        )
        blob = (await AdaptiveCardsRenderer().render(env, deep_links=[link])).content.decode()
        assert '"Action.' not in blob
        assert "https://x/resume?token=t" in blob  # deep link as display text

    async def test_output_has_zero_live_bindings(self):
        env = _envelope(
            Component(
                id="b0",
                component="Chart",
                properties={"type": "bar", "x": "m", "y": ["v"], "data": {"$bind": "/d"}},
            ),
            data_model={"d": [1, 2]},
        )
        blob = (await AdaptiveCardsRenderer().render(env)).content.decode()
        assert "$bind" not in blob and "dataModel" not in blob

    async def test_requires_actions_degrades_or_rejects(self):
        env = _envelope(
            Component(
                id="b0",
                component="Form",
                properties={"fields": [{"name": "e", "input": "text"}], "submit": {"action": "s"}},
            )
        )
        blob = (await AdaptiveCardsRenderer().render(env)).content.decode()
        assert "not available" in blob  # stripped with visible notice

    async def test_row_maps_to_columnset(self):
        env = _envelope(
            Component(
                id="b0",
                component="DataTable",
                properties={"columns": [{"name": "a"}, {"name": "b"}], "data": {"$bind": "/r"}},
            ),
            data_model={"r": []},
        )
        card = json.loads((await AdaptiveCardsRenderer().render(env)).content)
        blob = json.dumps(card)
        assert "ColumnSet" in blob
