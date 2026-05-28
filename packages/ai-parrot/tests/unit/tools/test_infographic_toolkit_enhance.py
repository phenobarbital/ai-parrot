"""Unit tests for InfographicToolkit enhance pipeline (FEAT-197, TASK-1325)."""
from __future__ import annotations

import sys
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

# Force real modules.
for _mod in (
    "parrot.models.infographic",
    "parrot.models.infographic_templates",
    "parrot.tools.infographic_toolkit",
    "parrot.tools._enhance_html_check",
    "parrot.storage.models",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri
import parrot.models.infographic_templates as _rt
import parrot.storage.models as _rsm

sys.modules.update({
    "parrot.models.infographic": _ri,
    "parrot.models.infographic_templates": _rt,
    "parrot.storage.models": _rsm,
})

import parrot.tools.infographic_toolkit as _rtk
import parrot.tools._enhance_html_check as _rcheck

sys.modules["parrot.tools.infographic_toolkit"] = _rtk
sys.modules["parrot.tools._enhance_html_check"] = _rcheck

from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult  # noqa: E402
from parrot.models.infographic import BlockType, JSBundle  # noqa: E402
from parrot.models.infographic_templates import BlockSpec, InfographicTemplate, infographic_registry  # noqa: E402


@pytest.fixture
def cdn_bundle():
    return JSBundle(
        name="echarts",
        scope="cdn",
        url="https://cdn.example/echarts.min.js",
        sri_hash="sha384-AAAA",
    )


@pytest.fixture
def template_with_bundle(cdn_bundle):
    t = InfographicTemplate(
        name="_test_enhance_hero",
        description="one hero slot for enhance tests",
        block_specs=[BlockSpec(block_type=BlockType.HERO_CARD, min_items=4, max_items=4)],
        js_bundles=[cdn_bundle],
    )
    infographic_registry.register(t)
    yield t


@pytest.fixture
def fake_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return store


@pytest.fixture
def toolkit_with_bot(fake_store):
    tk = InfographicToolkit(artifact_store=fake_store)
    bot = MagicMock()
    bot._get_repl_locals = MagicMock(return_value={"r": pd.DataFrame([{"x": 1}])})
    bot.user_id = "u"
    bot.agent_id = "agt"
    bot.session_id = "s"
    tk._bot = bot
    return tk


_VALID_HERO_BLOCKS = [
    {"type": "hero_card", "cards": [
        {"value": 1}, {"value": 2}, {"value": 3}, {"value": 4}
    ]}
]


@pytest.mark.asyncio
async def test_enhance_fallback_on_invalid_html(toolkit_with_bot, template_with_bundle, caplog):
    """Malicious HTML triggers ENHANCE_OUTPUT_INVALID and falls back to skeleton."""
    toolkit_with_bot._bot.enhance_infographic = AsyncMock(
        return_value='<script src="https://evil/x.js"></script>'
    )
    with caplog.at_level("WARNING"):
        result = await toolkit_with_bot.render(
            template_name=template_with_bundle.name,
            theme=None,
            mode="enhance",
            enhance_brief="add interactivity",
            blocks=_VALID_HERO_BLOCKS,
            data_variables=["r"],
        )
    assert result.enhanced is False
    assert any("ENHANCE_OUTPUT_INVALID" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_enhance_accepted_on_whitelisted_html(
    toolkit_with_bot, template_with_bundle, cdn_bundle,
):
    """Whitelisted CDN script → enhanced=True."""
    good_html = (
        '<html><body>'
        f'<script src="{cdn_bundle.url}" integrity="{cdn_bundle.sri_hash}"></script>'
        '</body></html>'
    )
    toolkit_with_bot._bot.enhance_infographic = AsyncMock(return_value=good_html)

    result = await toolkit_with_bot.render(
        template_name=template_with_bundle.name,
        theme=None,
        mode="enhance",
        enhance_brief="add tooltips",
        blocks=_VALID_HERO_BLOCKS,
        data_variables=["r"],
    )
    assert result.enhanced is True


@pytest.mark.asyncio
async def test_deterministic_mode_skips_enhance(toolkit_with_bot, template_with_bundle):
    """mode='deterministic' must NOT call bot.enhance_infographic."""
    toolkit_with_bot._bot.enhance_infographic = AsyncMock(return_value="<html/>")

    result = await toolkit_with_bot.render(
        template_name=template_with_bundle.name,
        theme=None,
        mode="deterministic",
        blocks=_VALID_HERO_BLOCKS,
        data_variables=["r"],
    )
    assert result.enhanced is False
    toolkit_with_bot._bot.enhance_infographic.assert_not_called()


@pytest.mark.asyncio
async def test_enhance_without_brief_falls_back(toolkit_with_bot, template_with_bundle, caplog):
    """mode='enhance' without enhance_brief falls back silently."""
    toolkit_with_bot._bot.enhance_infographic = AsyncMock(return_value="<html/>")
    with caplog.at_level("WARNING"):
        result = await toolkit_with_bot.render(
            template_name=template_with_bundle.name,
            theme=None,
            mode="enhance",
            enhance_brief=None,
            blocks=_VALID_HERO_BLOCKS,
            data_variables=["r"],
        )
    assert result.enhanced is False


@pytest.mark.asyncio
async def test_enhance_without_bot_falls_back(fake_store, template_with_bundle):
    """If _bot is None, enhance falls back."""
    tk = InfographicToolkit(artifact_store=fake_store)
    # No _bot set — _resolve_scope returns sentinels
    result = await tk.render(
        template_name=template_with_bundle.name,
        theme=None,
        mode="enhance",
        enhance_brief="please enhance",
        blocks=_VALID_HERO_BLOCKS,
        data_variables=[],   # no data_variables needed for fallback
    )
    assert result.enhanced is False
