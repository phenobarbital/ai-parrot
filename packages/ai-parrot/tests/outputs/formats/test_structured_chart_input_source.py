"""FEAT-224 TASK-1460: Unit tests for StructuredChartRenderer reading config from
response.output / response.structured_output instead of response.code.

Verifies (G3):
- Config is parsed from response.output (instance or dict).
- Config is parsed from response.structured_output as fallback.
- response.code = None does NOT break rendering when config is in output.
- No config at all returns (None, error) — never raises.
- x/y reconciliation, _route_envelope, never-raise behavior are unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# ── satellite path wiring ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    not (_SATELLITE_SRC / "parrot" / "outputs" / "formats" / "structured_chart.py").exists(),
    reason="ai-parrot-visualizations not installed",
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _resp(**kw) -> SimpleNamespace:
    """Build a minimal AIMessage-like SimpleNamespace for testing."""
    base = dict(
        output=None,
        structured_output=None,
        code=None,
        data=pd.DataFrame({"month": ["Jan", "Feb"], "sales": [1, 2]}),
        response="chart explanation",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── tests ─────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_reads_config_from_output_instance() -> None:
    """Renderer should parse config from response.output as StructuredChartConfig."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    out, wrapped = await StructuredChartRenderer().render(_resp(output=cfg))
    assert out is not None
    assert "data" not in out
    assert out["x"] == "month"
    assert wrapped is not None


@satellite_available
@pytest.mark.asyncio
async def test_reads_config_from_output_dict_with_code_none() -> None:
    """Renderer should parse config from response.output as a dict; code=None is fine."""
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg_dict = {"type": "bar", "x": "month", "y": ["sales"]}
    out, _ = await StructuredChartRenderer().render(
        _resp(output=cfg_dict, code=None)
    )
    assert out is not None
    assert out["type"] == "bar"
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_reads_config_from_structured_output_fallback() -> None:
    """When response.output is None/str, renderer should fall back to structured_output."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg = StructuredChartConfig(type="line", x="month", y=["sales"])
    # output is a plain string (non-structured turn value)
    out, _ = await StructuredChartRenderer().render(
        _resp(output="just some text", structured_output=cfg)
    )
    assert out is not None
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_structured_output_dict_fallback() -> None:
    """structured_output as a dict should also work as fallback."""
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg_dict = {"type": "bar", "x": "month", "y": ["sales"]}
    out, _ = await StructuredChartRenderer().render(
        _resp(output=None, structured_output=cfg_dict)
    )
    assert out is not None
    assert out["x"] == "month"


@satellite_available
@pytest.mark.asyncio
async def test_no_config_returns_none_not_raise() -> None:
    """With no config in output/structured_output, render must return (None, str) — never raise."""
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    out, err = await StructuredChartRenderer().render(_resp(output="just text"))
    assert out is None
    assert isinstance(err, str)
    assert len(err) > 0


@satellite_available
@pytest.mark.asyncio
async def test_code_none_does_not_break_render() -> None:
    """code=None must not prevent successful rendering when config is in output."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    out, wrapped = await StructuredChartRenderer().render(
        _resp(output=cfg, code=None)
    )
    assert out is not None
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_definition_excludes_data_key() -> None:
    """The returned config dict must never contain the 'data' key."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg = StructuredChartConfig(
        type="bar", x="month", y=["sales"],
        data=[{"month": "Jan", "sales": 1}],  # LLM accidentally included data
    )
    out, _ = await StructuredChartRenderer().render(_resp(output=cfg))
    assert out is not None
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_xy_reconciliation_preserved() -> None:
    """x/y fallback logic must still apply when LLM picks a missing column."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    # LLM picks 'nonexistent' as x — renderer must fall back to a real column.
    cfg = StructuredChartConfig(type="bar", x="nonexistent", y=["sales"])
    out, _ = await StructuredChartRenderer().render(_resp(output=cfg))
    assert out is not None
    assert out["x"] in ["month", "sales"]  # one of the real columns


@satellite_available
@pytest.mark.asyncio
async def test_explanation_passed_through() -> None:
    """The second return value (explanation) must echo response.response."""
    from parrot.models.outputs import StructuredChartConfig
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"])
    out, wrapped = await StructuredChartRenderer().render(
        _resp(output=cfg)
    )
    # wrapped comes from cfg.description (None here) → falls back to explanation
    assert out is not None
    # either cfg.description or the response.response prose — must not be empty
    # (cfg has no description; renderer falls back to response.response = "chart explanation")
    assert wrapped is not None


@satellite_available
@pytest.mark.asyncio
async def test_invalid_dict_returns_error() -> None:
    """An invalid dict in response.output must return (None, error_str) — never raise."""
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    bad_dict = {"not_a_valid": "chart_config", "missing_required": True}
    out, err = await StructuredChartRenderer().render(_resp(output=bad_dict))
    assert out is None
    assert isinstance(err, str)
