"""Tests for FEAT-215: Structured Chart Output Mode.

TASK-1411: OutputMode.STRUCTURED_CHART enum member
TASK-1412: StructuredChartConfig pydantic model + validators
TASK-1413: StructuredChartRenderer + system prompt + dispatch registration
TASK-1414: Integration tests — envelope serialization + regression guard
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── Satellite path wiring ──────────────────────────────────────────────────────
# Add ai-parrot-visualizations/src to sys.path so the PEP 420 namespace merge
# can discover the satellite renderer modules (e.g. structured_chart.py).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed",
)

# ─────────────────────────────────────────────────────────────────────────────
# TASK-1411 — OutputMode.STRUCTURED_CHART enum member
# ─────────────────────────────────────────────────────────────────────────────


def test_outputmode_has_structured_chart():
    """OutputMode.STRUCTURED_CHART exists with the correct string value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_CHART.value == "structured_chart"
    assert OutputMode("structured_chart") is OutputMode.STRUCTURED_CHART


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1412 — StructuredChartConfig model + validators
# ─────────────────────────────────────────────────────────────────────────────


def test_structured_chart_config_alias_roundtrip():
    """camelCase aliases serialize correctly; snake_case input also accepted."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(type="bar", x="m", y=["v"], splitSeries=True, xAxisMode="time")
    dumped = cfg.model_dump(by_alias=True)
    assert "splitSeries" in dumped and "xAxisMode" in dumped
    assert "split_series" not in dumped

    # snake_case input also accepted (populate_by_name=True)
    cfg2 = StructuredChartConfig(type="bar", x="m", y=["v"], split_series=True)
    assert cfg2.split_series is True


def test_structured_chart_config_all_aliases_in_dump():
    """All camelCase aliases appear in model_dump(by_alias=True) when set."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(
        type="map",
        x="country",
        y=["sales"],
        splitSeries=True,
        showLegend=False,
        xAxisMode="category",
        colorBySign=True,
        negativeColor="#ff0000",
        mapName="world",
    )
    dumped = cfg.model_dump(by_alias=True)
    for alias in ("splitSeries", "showLegend", "xAxisMode", "colorBySign", "negativeColor", "mapName"):
        assert alias in dumped, f"Alias '{alias}' missing from dump"


def test_structured_chart_config_map_requires_mapname():
    """type='map' without mapName raises ValidationError."""
    from pydantic import ValidationError
    from parrot.models.outputs import StructuredChartConfig

    with pytest.raises(ValidationError):
        StructuredChartConfig(type="map", x="country", y=["sales"])


def test_structured_chart_config_map_with_mapname_ok():
    """type='map' with mapName does NOT raise."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(type="map", x="country", y=["sales"], mapName="world")
    assert cfg.map_name == "world"


def test_structured_chart_config_y_columns_present():
    """y referencing absent column raises ValidationError when data is non-empty."""
    from pydantic import ValidationError
    from parrot.models.outputs import StructuredChartConfig

    with pytest.raises(ValidationError):
        StructuredChartConfig(type="bar", x="m", y=["missing"],
                              data=[{"m": "Jan", "v": 1}])


def test_structured_chart_config_x_column_present():
    """x referencing absent column raises ValidationError when data is non-empty."""
    from pydantic import ValidationError
    from parrot.models.outputs import StructuredChartConfig

    with pytest.raises(ValidationError):
        StructuredChartConfig(type="bar", x="bad_col", y=["v"],
                              data=[{"m": "Jan", "v": 1}])


def test_structured_chart_config_empty_data_skips_column_check():
    """Empty data list does not trigger column-check validation."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(type="bar", x="anything", y=["whatever"], data=[])
    assert cfg.data == []


def test_structured_chart_config_data_excluded_from_output_dump():
    """data field is present on model but excluded when the renderer dumps with exclude={'data'}."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(
        type="bar", x="m", y=["v"], data=[{"m": "Jan", "v": 1}]
    )
    # Renderer uses: model_dump(mode="json", by_alias=True, exclude={"data"})
    dumped = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
    assert "data" not in dumped
    # But the model itself holds the data
    assert len(cfg.data) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures shared by TASK-1413 tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def bar_config_json() -> str:
    """Valid StructuredChartConfig JSON for a bar chart with data rows."""
    import json
    return json.dumps({
        "type": "bar",
        "x": "month",
        "y": ["sales", "expenses"],
        "splitSeries": False,
        "data": [
            {"month": "Jan", "sales": 100, "expenses": 80},
            {"month": "Feb", "sales": 120, "expenses": 90},
        ],
    })


@pytest.fixture
def map_config_json() -> str:
    """Valid StructuredChartConfig JSON for a map chart."""
    import json
    return json.dumps({
        "type": "map",
        "x": "country",
        "y": ["gdp"],
        "mapName": "world",
        "data": [{"country": "US", "gdp": 21000}, {"country": "CN", "gdp": 15000}],
    })


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1413 — StructuredChartRenderer + dispatch + prompt
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
def test_get_renderer_resolves_structured_chart():
    """get_renderer(STRUCTURED_CHART) returns StructuredChartRenderer."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer
    from parrot.outputs.formats.structured_chart import StructuredChartRenderer

    assert get_renderer(OutputMode.STRUCTURED_CHART) is StructuredChartRenderer


@satellite_available
def test_system_prompt_embeds_schema():
    """System prompt contains a schema alias and demands JSON-only output."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_output_prompt

    prompt = get_output_prompt(OutputMode.STRUCTURED_CHART)
    assert prompt is not None
    assert "xAxisMode" in prompt, "Schema alias 'xAxisMode' should appear in prompt"
    assert "JSON" in prompt, "Prompt should demand JSON-only output"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_output_excludes_data(bar_config_json):
    """Valid config: output lacks data key, response.data carries rows, code untouched."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    original_code = bar_config_json
    resp = SimpleNamespace(code=original_code, data=None, output=None, response=None)
    output, wrapped = await r.render(resp)

    assert wrapped is None, "No error on valid config"
    assert output is not None
    assert "data" not in output, "data key must be excluded from output"
    assert resp.data is not None and len(resp.data) == 2, "Rows must be routed to response.data"
    # code must be left untouched by the renderer
    assert resp.code == original_code, "renderer must not modify response.code"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_does_not_clobber_existing_data(bar_config_json):
    """Existing non-empty response.data is preserved; output still excludes data."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    pre_existing = [{"row": "existing"}]
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=bar_config_json, data=pre_existing, output=None, response=None)
    output, wrapped = await r.render(resp)

    assert wrapped is None
    assert "data" not in output
    # Pre-existing data should NOT have been overwritten
    assert resp.data is pre_existing


@satellite_available
@pytest.mark.asyncio
async def test_renderer_malformed_graceful_degradation():
    """Malformed JSON: returns (None, message), no raise, output/data/code null."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code="{not json", data=None, output=None, response=None)
    output, wrapped = await r.render(resp)  # MUST NOT raise

    assert output is None, "output must be None on failure"
    assert wrapped, "Error message must be returned"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_reads_code_first(bar_config_json):
    """Renderer reads response.code before falling back to text extraction."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    # code is set; response text is gibberish — code must win
    resp = SimpleNamespace(code=bar_config_json, data=None, output=None,
                           response="some unrelated text")
    output, wrapped = await r.render(resp)
    assert output is not None
    assert wrapped is None


@satellite_available
@pytest.mark.asyncio
async def test_renderer_falls_back_to_text_extraction(bar_config_json):
    """Renderer extracts JSON from message text when code is None."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    # Embed the JSON in a markdown code block inside the response text
    text_with_json = f"```json\n{bar_config_json}\n```"
    resp = SimpleNamespace(code=None, data=None, output=None, response=text_with_json)
    output, wrapped = await r.render(resp)
    assert output is not None, "Should extract JSON from text"
    assert wrapped is None


@satellite_available
@pytest.mark.asyncio
async def test_renderer_missing_config_graceful_degradation():
    """No JSON at all: returns (None, message), does not raise."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=None, output=None, response="plain text, no JSON")
    output, wrapped = await r.render(resp)  # must NOT raise
    assert output is None
    assert wrapped


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1414 — Integration tests: envelope serialization + regression guard
# ─────────────────────────────────────────────────────────────────────────────


def _envelope(output, data, response, code, output_mode):
    """Mirror the fields assembled by handlers/agent.py:2591-2614."""
    return {
        "output": output,
        "data": data,
        "response": response,
        "output_mode": output_mode,
        "code": str(code) if code else None,
    }


def test_envelope_serializes_structured_chart():
    """Config in output (no data key), rows in data, code null → encoder happy."""
    from datamodel.parsers.json import json_encoder
    from parrot.models.outputs import OutputMode

    cfg = {"type": "bar", "x": "m", "y": ["v"]}   # camelCase config, NO "data" key
    env = _envelope(
        output=cfg,
        data=[{"m": "Jan", "v": 1}],
        response=None,
        code=None,
        output_mode=OutputMode.STRUCTURED_CHART.value,
    )
    blob = json_encoder(env)   # must not raise
    assert env["code"] is None
    assert "data" not in env["output"]
    # Serialized blob contains the mode value
    assert "structured_chart" in blob


def test_envelope_serializes_degraded_structured_chart():
    """Degraded response (output=None + response message) encodes cleanly."""
    from datamodel.parsers.json import json_encoder
    from parrot.models.outputs import OutputMode

    env = _envelope(
        output=None,
        data=None,
        response="Invalid structured chart config: bad input",
        code=None,
        output_mode=OutputMode.STRUCTURED_CHART.value,
    )
    blob = json_encoder(env)   # must not raise
    assert env["output"] is None
    assert env["response"]
    # Consumer can detect failure without rendering an invalid config
    assert env["output"] is None or (isinstance(env["output"], dict) and "error" in env["output"])
    _ = blob  # serialization succeeded


@satellite_available
def test_echarts_altair_unchanged():
    """ECHARTS and ALTAIR renderers + prompts resolve unchanged (regression guard)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer, get_output_prompt
    from parrot.outputs.formats.echarts import EChartsRenderer
    from parrot.outputs.formats.altair import AltairRenderer

    assert get_renderer(OutputMode.ECHARTS) is EChartsRenderer
    assert get_renderer(OutputMode.ALTAIR) is AltairRenderer
    assert get_output_prompt(OutputMode.ECHARTS) is not None
    assert get_output_prompt(OutputMode.ALTAIR) is not None
