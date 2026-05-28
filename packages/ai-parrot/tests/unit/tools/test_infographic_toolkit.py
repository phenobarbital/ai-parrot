"""Unit tests for InfographicToolkit core (FEAT-197, TASK-1323)."""
from __future__ import annotations

import sys

import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

# Force real infographic modules (bypass conftest stubs).
for _mod in (
    "parrot.models.infographic",
    "parrot.models.infographic_templates",
    "parrot.tools.infographic_toolkit",
    "parrot.storage.models",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri
import parrot.models.infographic_templates as _rt
import parrot.storage.models as _rsm

sys.modules["parrot.models.infographic"] = _ri
sys.modules["parrot.models.infographic_templates"] = _rt
sys.modules["parrot.storage.models"] = _rsm

import parrot.tools.infographic_toolkit as _rtk
sys.modules["parrot.tools.infographic_toolkit"] = _rtk

from parrot.tools.infographic_toolkit import (  # noqa: E402
    InfographicToolkit,
    InfographicRenderResult,
    InfographicValidationError,
)
from parrot.models.infographic import BlockType
from parrot.models.infographic_templates import (
    BlockSpec,
    InfographicTemplate,
    infographic_registry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_artifact_store():
    """Mock ArtifactStore with save + get_public_url stubbed."""
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return store


@pytest.fixture
def hero_cards_template():
    """Register a test template with one required hero_card slot."""
    t = InfographicTemplate(
        name="_test_four_cards",
        description="four hero cards",
        block_specs=[
            BlockSpec(block_type=BlockType.HERO_CARD, min_items=4, max_items=4)
        ],
    )
    infographic_registry.register(t)
    yield t
    # No unregister API — unique name guarantees test isolation.


@pytest.fixture
def toolkit(fake_artifact_store):
    """InfographicToolkit with a mock bot attached."""
    tk = InfographicToolkit(artifact_store=fake_artifact_store)
    bot = MagicMock()
    bot._get_repl_locals = MagicMock(return_value={})
    bot.user_id = "u"
    bot.agent_id = "agt"
    bot.session_id = "sess"
    tk._bot = bot
    return tk


# ---------------------------------------------------------------------------
# return_direct
# ---------------------------------------------------------------------------

class TestReturnDirect:
    def test_class_attr_is_true(self):
        assert InfographicToolkit.return_direct is True

    def test_generated_tool_propagates_return_direct(self, toolkit):
        tools = toolkit.get_tools()
        assert any(getattr(t, "return_direct", False) for t in tools)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    @pytest.mark.asyncio
    async def test_template_unknown(self, toolkit):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name="does-not-exist",
                theme=None,
                mode="deterministic",
                blocks=[],
                data_variables=[],
            )
        assert ei.value.code == "TEMPLATE_UNKNOWN"

    @pytest.mark.asyncio
    async def test_slot_missing(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme=None,
                mode="deterministic",
                blocks=[],           # missing required slot
                data_variables=[],
            )
        assert ei.value.code == "SLOT_MISSING"

    @pytest.mark.asyncio
    async def test_slot_type_mismatch(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme=None,
                mode="deterministic",
                blocks=[{"type": "title", "text": "wrong type"}],
                data_variables=[],
            )
        assert ei.value.code == "SLOT_TYPE_MISMATCH"

    @pytest.mark.asyncio
    async def test_slot_item_count_invalid(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme=None,
                mode="deterministic",
                blocks=[{"type": "hero_card", "cards": [{}]}],  # 1 < min_items=4
                data_variables=[],
            )
        assert ei.value.code == "SLOT_ITEM_COUNT_INVALID"

    @pytest.mark.asyncio
    async def test_extra_blocks(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme=None,
                mode="deterministic",
                blocks=[
                    {"type": "hero_card", "cards": [{}, {}, {}, {}]},
                    {"type": "title", "text": "extra"},
                ],
                data_variables=[],
            )
        assert ei.value.code == "EXTRA_BLOCKS"

    @pytest.mark.asyncio
    async def test_data_var_missing(self, toolkit, hero_cards_template):
        toolkit._bot._get_repl_locals.return_value = {}
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme=None,
                mode="deterministic",
                blocks=[{"type": "hero_card", "cards": [{}, {}, {}, {}]}],
                data_variables=["revenue"],
            )
        assert ei.value.code == "DATA_VAR_MISSING"

    @pytest.mark.asyncio
    async def test_data_var_empty(self, toolkit, hero_cards_template):
        toolkit._bot._get_repl_locals.return_value = {"revenue": pd.DataFrame()}
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme=None,
                mode="deterministic",
                blocks=[{"type": "hero_card", "cards": [{}, {}, {}, {}]}],
                data_variables=["revenue"],
            )
        assert ei.value.code == "DATA_VAR_EMPTY"

    @pytest.mark.asyncio
    async def test_theme_invalid(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name,
                theme="neon-explosion",
                mode="deterministic",
                blocks=[{"type": "hero_card", "cards": [{}, {}, {}, {}]}],
                data_variables=[],
            )
        assert ei.value.code == "THEME_INVALID"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

class TestRender:
    @pytest.mark.asyncio
    async def test_returns_envelope(self, toolkit, hero_cards_template, fake_artifact_store):
        toolkit._bot._get_repl_locals.return_value = {
            "rev": pd.DataFrame([{"x": 1}])
        }
        result = await toolkit.render(
            template_name=hero_cards_template.name,
            theme="dark",
            mode="deterministic",
            blocks=[{"type": "hero_card", "cards": [
                {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}
            ]}],
            data_variables=["rev"],
        )
        assert isinstance(result, InfographicRenderResult)
        assert result.enhanced is False
        assert result.template_name == hero_cards_template.name
        assert result.html_url == "https://signed/x"

    @pytest.mark.asyncio
    async def test_html_inline_set_for_small_html(
        self, toolkit, hero_cards_template, fake_artifact_store, monkeypatch,
    ):
        """html_inline populated when len(html) < 50 000."""
        monkeypatch.setattr(
            toolkit._renderer, "render_to_html",
            lambda *a, **kw: "<html>tiny</html>",
        )
        toolkit._bot._get_repl_locals.return_value = {"r": pd.DataFrame([{"x": 1}])}
        result = await toolkit.render(
            template_name=hero_cards_template.name,
            theme=None,
            mode="deterministic",
            blocks=[{"type": "hero_card", "cards": [
                {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}
            ]}],
            data_variables=["r"],
        )
        assert result.html_inline is not None
        assert result.html_inline == "<html>tiny</html>"

    @pytest.mark.asyncio
    async def test_html_inline_none_for_large_html(
        self, toolkit, hero_cards_template, fake_artifact_store, monkeypatch,
    ):
        """html_inline is None when len(html) >= 50 000."""
        monkeypatch.setattr(
            toolkit._renderer, "render_to_html",
            lambda *a, **kw: "X" * 60_000,
        )
        toolkit._bot._get_repl_locals.return_value = {"r": pd.DataFrame([{"x": 1}])}
        result = await toolkit.render(
            template_name=hero_cards_template.name,
            theme=None,
            mode="deterministic",
            blocks=[{"type": "hero_card", "cards": [
                {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}
            ]}],
            data_variables=["r"],
        )
        assert result.html_inline is None

    @pytest.mark.asyncio
    async def test_save_artifact_called_once(
        self, toolkit, hero_cards_template, fake_artifact_store,
    ):
        toolkit._bot._get_repl_locals.return_value = {"r": pd.DataFrame([{"x": 1}])}
        await toolkit.render(
            template_name=hero_cards_template.name,
            theme=None,
            mode="deterministic",
            blocks=[{"type": "hero_card", "cards": [
                {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}
            ]}],
            data_variables=["r"],
        )
        assert fake_artifact_store.save_artifact.call_count == 1
        artifact = fake_artifact_store.save_artifact.call_args[0][-1]
        assert artifact.artifact_type.value == "infographic"
        assert "html" in artifact.definition

    @pytest.mark.asyncio
    async def test_get_public_url_called_once(
        self, toolkit, hero_cards_template, fake_artifact_store,
    ):
        toolkit._bot._get_repl_locals.return_value = {"r": pd.DataFrame([{"x": 1}])}
        await toolkit.render(
            template_name=hero_cards_template.name,
            theme=None,
            mode="deterministic",
            blocks=[{"type": "hero_card", "cards": [
                {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}
            ]}],
            data_variables=["r"],
        )
        assert fake_artifact_store.get_public_url.call_count == 1
