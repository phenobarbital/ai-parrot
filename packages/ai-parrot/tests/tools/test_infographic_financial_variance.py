"""Unit tests for FEAT-206 — Flatten financial_variance template to 9 positional slots.

Verifies:
- The template exposes exactly 9 flat specs (TITLE, HERO_CARD×4, CHART×3, SUMMARY).
- Chart constraints are correct (positions 5,6: bar/half; position 7: line/full).
- _validate_blocks coerces all 9 blocks (regression for the .blocks[0] drop).
- Both half-width bar ChartBlocks preserve layout == 'half'.
- Legacy single-hero_card-with-items payload is rejected (intended breaking change).
- A flat 9-block payload passes infographic_validate_blocks (returns {"ok": True}).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.models.infographic_templates import infographic_registry
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_store():
    """Minimal mock ArtifactStore for InfographicToolkit construction."""
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/artifact-1")
    return store


@pytest.fixture
def toolkit(fake_store):
    """InfographicToolkit with mocked store — enough to call _validate_blocks."""
    return InfographicToolkit(artifact_store=fake_store)


@pytest.fixture
def fv_blocks():
    """Minimal valid 9-block financial_variance payload."""
    bar = lambda t: {  # noqa: E731
        "type": "chart",
        "chart_type": "bar",
        "layout": "half",
        "title": t,
        "labels": ["D1", "D2"],
        "series": [{"name": "x", "values": [1.0, 2.0]}],
    }
    card = lambda lbl, v: {"type": "hero_card", "label": lbl, "value": v}  # noqa: E731
    return [
        {"type": "title", "title": "T", "date": "May 14 – 27, 2026"},
        card("Revenue", "$3.7M"),
        card("Change", "$1.4M"),
        card("EBITDA", "$31K"),
        card("DoD", "$107K"),
        bar("Revenue DoD"),
        bar("EBITDA DoD"),
        {
            "type": "chart",
            "chart_type": "line",
            "layout": "full",
            "title": "Cumulative",
            "labels": ["D1", "D2"],
            "series": [{"name": "rev", "values": [2.3, 3.7]}],
        },
        {"type": "summary", "content": "Summary text."},
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_financial_variance_contract_is_flat():
    """The template must have exactly 9 specs: title, hero_card×4, chart×3, summary."""
    tpl = infographic_registry.get("financial_variance")
    assert tpl is not None, "financial_variance template not registered"
    types = [spec.block_type.value for spec in tpl.block_specs]
    assert types == [
        "title",
        "hero_card", "hero_card", "hero_card", "hero_card",
        "chart", "chart", "chart",
        "summary",
    ], f"Unexpected block_spec types: {types}"


def test_financial_variance_chart_constraints():
    """Positions 5,6 carry bar/half constraints; position 7 carries line/full."""
    tpl = infographic_registry.get("financial_variance")
    specs = tpl.block_specs
    assert specs[5].constraints == {"chart_type": "bar", "layout": "half"}, (
        f"Slot 5 constraints wrong: {specs[5].constraints}"
    )
    assert specs[6].constraints == {"chart_type": "bar", "layout": "half"}, (
        f"Slot 6 constraints wrong: {specs[6].constraints}"
    )
    assert specs[7].constraints == {"chart_type": "line", "layout": "full"}, (
        f"Slot 7 constraints wrong: {specs[7].constraints}"
    )


def test_validate_coerces_all_nine_blocks(toolkit, fv_blocks):
    """_validate_blocks must return a list of length 9 — regression for .blocks[0] drop."""
    tpl = infographic_registry.get("financial_variance")
    coerced = toolkit._validate_blocks(tpl, fv_blocks)
    assert len(coerced) == 9, (
        f"Expected 9 coerced blocks, got {len(coerced)}"
    )


def test_two_half_charts_preserve_layout(toolkit, fv_blocks):
    """Both coerced bar ChartBlocks at positions 5,6 must keep layout == 'half'."""
    tpl = infographic_registry.get("financial_variance")
    coerced = toolkit._validate_blocks(tpl, fv_blocks)
    assert coerced[5].layout == "half", (
        f"Block at position 5 should have layout='half', got {coerced[5].layout!r}"
    )
    assert coerced[6].layout == "half", (
        f"Block at position 6 should have layout='half', got {coerced[6].layout!r}"
    )


def test_legacy_items_payload_now_rejected(toolkit):
    """Old shape (1 hero_card w/ items=[4] + fewer blocks) no longer validates."""
    tpl = infographic_registry.get("financial_variance")
    legacy = [
        {"type": "title", "title": "T"},
        {
            "type": "hero_card",
            "items": [{"label": f"c{i}", "value": "1"} for i in range(4)],
        },
        {
            "type": "chart",
            "chart_type": "bar",
            "labels": ["a"],
            "series": [{"name": "s", "values": [1]}],
        },
        {
            "type": "chart",
            "chart_type": "line",
            "labels": ["a"],
            "series": [{"name": "s", "values": [1]}],
        },
    ]
    with pytest.raises(InfographicValidationError):
        toolkit._validate_blocks(tpl, legacy)


async def test_validate_flat_payload_ok(toolkit, fv_blocks):
    """A flat 9-block payload must return {"ok": True} from validate_blocks."""
    result = await toolkit.validate_blocks("financial_variance", fv_blocks)
    assert result == {"ok": True}, f"validate_blocks returned: {result}"


async def test_get_template_contract_returns_nine_specs(toolkit):
    """get_template_contract('financial_variance') returns 9 specs in the correct order."""
    contract = await toolkit.get_template_contract("financial_variance")
    specs = contract["block_specs"]
    assert len(specs) == 9, f"Expected 9 specs, got {len(specs)}"
    types = [s["block_type"] for s in specs]
    assert types == [
        "title",
        "hero_card", "hero_card", "hero_card", "hero_card",
        "chart", "chart", "chart",
        "summary",
    ], f"Unexpected block_type sequence: {types}"
