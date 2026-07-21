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

    rows = [{"m": "Jan", "v": 1}]
    cfg = StructuredChartConfig(
        type="bar", x="m", y=["v"], splitSeries=True, xAxisMode="time", data=rows
    )
    dumped = cfg.model_dump(by_alias=True)
    assert "splitSeries" in dumped and "xAxisMode" in dumped
    assert "split_series" not in dumped

    # snake_case input also accepted (populate_by_name=True)
    cfg2 = StructuredChartConfig(type="bar", x="m", y=["v"], split_series=True, data=rows)
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
        data=[{"country": "US", "sales": 1}],
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

    cfg = StructuredChartConfig(
        type="map", x="country", y=["sales"], mapName="world",
        data=[{"country": "US", "sales": 1}],
    )
    assert cfg.map_name == "world"


def test_structured_chart_config_mismatched_columns_accepted():
    """x/y not matching the embedded data is ACCEPTED (renderer reconciles).

    The model_validator no longer rejects column mismatches: the LLM often names
    semantic axes that differ from the embedded keys, and StructuredChartRenderer
    reconciles x/y downstream. Raising here would force a slow reformat and
    pre-empt that reconciliation.
    """
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(type="bar", x="m", y=["missing"],
                                data=[{"m": "Jan", "v": 1}])
    assert cfg.y == ["missing"]  # kept as-is; renderer reconciles at render time

    cfg2 = StructuredChartConfig(type="bar", x="bad_col", y=["v"],
                                 data=[{"m": "Jan", "v": 1}])
    assert cfg2.x == "bad_col"


def test_structured_chart_config_empty_data_skips_column_check():
    """Empty/placeholder data does not trigger column-check validation.

    The LLM does not reliably embed rows (emits [{}]); the renderer reconciles
    columns against the agent-injected DataFrame, so an empty/placeholder data
    list is accepted at the model level.
    """
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(type="bar", x="anything", y=["whatever"], data=[])
    assert cfg.data == []

    cfg2 = StructuredChartConfig(type="bar", x="anything", y=["whatever"], data=[{}])
    assert cfg2.data == [{}]


def test_structured_chart_config_data_split_orientation_normalized():
    """data in pandas 'split' orientation ({columns, data}) is coerced to records."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(
        type="radar",
        x="cat",
        y=["val"],
        data={
            "columns": ["cat", "val"],
            "data": [["A", 1], ["B", 2]],
        },
    )
    assert cfg.data == [
        {"cat": "A", "val": 1},
        {"cat": "B", "val": 2},
    ]


def test_structured_chart_config_data_split_rows_key_normalized():
    """split orientation with the 'rows' key (not 'data') is also coerced.

    Replays the exact radar failure: the model emitted
    {"columns": [...], "rows": [[...]]} which previously got wrapped as one bogus
    row with columns ['columns','rows'].
    """
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(
        type="radar",
        x="cat",
        y=["val"],
        data={"columns": ["cat", "val"], "rows": [["A", 1], ["B", 2]]},
    )
    assert cfg.data == [{"cat": "A", "val": 1}, {"cat": "B", "val": 2}]


def test_structured_chart_config_data_dict_orientation_normalized():
    """data in pandas default 'dict' orientation ({col: {idx: val}}) → records."""
    from parrot.models.outputs import StructuredChartConfig

    cfg = StructuredChartConfig(
        type="bar",
        x="m",
        y=["v"],
        data={"m": {0: "Jan", 1: "Feb"}, "v": {0: 1, 1: 2}},
    )
    assert cfg.data == [{"m": "Jan", "v": 1}, {"m": "Feb", "v": 2}]


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
    """Valid StructuredChartConfig JSON for a bar chart (no embedded data rows).

    FEAT-224: kept for the text-fallback path test. Prefer bar_config_obj
    for renderer tests (config now travels via response.output).
    """
    import json
    return json.dumps({
        "type": "bar",
        "x": "month",
        "y": ["sales", "expenses"],
        "splitSeries": False,
        "data": [],
    })


@pytest.fixture
def bar_config_obj():
    """Valid StructuredChartConfig instance for bar chart tests.

    FEAT-224: chart config now travels via response.output, not response.code.
    Use this fixture when testing the renderer directly.
    """
    from parrot.models.outputs import StructuredChartConfig
    return StructuredChartConfig(
        type="bar",
        x="month",
        y=["sales", "expenses"],
        data=[],
    )


@pytest.fixture
def bar_data_df():
    """Matching DataFrame that the agent would inject into response.data."""
    import pandas as pd
    return pd.DataFrame([
        {"month": "Jan", "sales": 100, "expenses": 80},
        {"month": "Feb", "sales": 120, "expenses": 90},
    ])


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
async def test_renderer_output_excludes_data(bar_config_obj, bar_data_df):
    """Valid config + DataFrame: output lacks data key; response.data carries rows.

    FEAT-224: config now travels via response.output (not response.code).
    """
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=bar_data_df, output=bar_config_obj, response=None)
    output, wrapped = await r.render(resp)

    assert output is not None
    assert "data" not in output, "data key must be excluded from output"
    assert isinstance(resp.data, list) and len(resp.data) == 2, "Rows routed to response.data"
    # code must remain None — renderer no longer reads/writes response.code for config
    assert resp.code is None, "renderer must not set response.code"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_response_data_is_authoritative_source(bar_config_obj, bar_data_df):
    """FEAT-223: response.data (DataFrame) is the authoritative row source — not cfg.data.

    The renderer ignores any rows the LLM embedded in the config JSON and uses the
    agent-injected DataFrame exclusively. FEAT-224: config via response.output.
    """
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=bar_data_df, output=bar_config_obj, response=None)
    output, wrapped = await r.render(resp)

    assert output is not None
    assert "data" not in output
    assert isinstance(resp.data, list) and len(resp.data) == 2
    assert resp.data[0].get("month") == "Jan"
    assert output["x"] == "month"
    assert "sales" in output["y"]


@satellite_available
@pytest.mark.asyncio
async def test_renderer_large_dataframe_rows_used(bar_config_obj):
    """FEAT-223: a large DataFrame in response.data provides ALL rows to the chart.

    The LLM does not emit rows; the backend uses the full DataFrame.
    No truthiness crash — pd.DataFrame truthiness is never evaluated.
    FEAT-224: config via response.output.
    """
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    big_df = pd.DataFrame({
        "month": [f"M{i}" for i in range(142)],
        "sales": range(142),
        "expenses": range(142),
    })
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=big_df, output=bar_config_obj, response=None)

    # Must NOT raise "truth value of a DataFrame is ambiguous"
    output, wrapped = await r.render(resp)

    assert output is not None
    assert "data" not in output
    assert isinstance(resp.data, list) and len(resp.data) == 142, (
        "All 142 DataFrame rows must be present in response.data"
    )


@satellite_available
@pytest.mark.asyncio
async def test_renderer_uses_existing_data_when_cfg_data_empty():
    """FEAT-223: response.data list is extracted deterministically; x/y kept when valid.

    When the config's x/y match the real columns, they are preserved unchanged.
    """
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode, StructuredChartConfig
    from parrot.outputs.formats import get_renderer

    # FEAT-224: config via response.output, not response.code
    config_obj = StructuredChartConfig(type="bar", x="m", y=["v"])
    pre_existing = [{"m": "Jan", "v": 1}]
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=pre_existing, output=config_obj, response=None)
    output, wrapped = await r.render(resp)

    assert output is not None
    assert "data" not in output
    assert output["x"] == "m" and output["y"] == ["v"]  # already valid → unchanged
    # response.data is the canonical list (may be a new object; values must match)
    assert isinstance(resp.data, list) and len(resp.data) == 1
    assert resp.data[0]["m"] == "Jan"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_reconciles_mismatched_columns():
    """LLM names x/y that don't exist → renderer infers them from the data.

    Mirrors the real failure shape: the config says x="category" but the injected
    DataFrame has columns grp / sub / amount. The renderer rewrites x to the
    first non-numeric column and y to the numeric columns so the frontend can
    actually render. (Placeholder column names/values only.)
    """
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode, StructuredChartConfig
    from parrot.outputs.formats import get_renderer

    # FEAT-224: config via response.output
    config_obj = StructuredChartConfig(type="pie", x="category", y=["amount"])
    injected = [
        {"grp": "X", "sub": "A", "amount": 10},
        {"grp": "X", "sub": "B", "amount": 20},
    ]
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=injected, output=config_obj, response=None)
    output, wrapped = await r.render(resp)

    assert wrapped is None
    assert output is not None
    # x was "category" (absent) → first non-numeric column
    assert output["x"] == "grp"
    # y "amount" exists → kept
    assert output["y"] == ["amount"]
    # response.data is the canonical list (new object; check values)
    assert isinstance(resp.data, list) and len(resp.data) == 2
    assert resp.data[0]["grp"] == "X"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_reconciles_from_dataframe():
    """A pandas DataFrame in response.data is converted to records + reconciled."""
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # FEAT-224: config via response.output; config invents x/y that don't match df cols
    from parrot.models.outputs import StructuredChartConfig
    config_obj = StructuredChartConfig(type="bar", x="metric", y=["value"])
    df = pd.DataFrame({"region": ["N", "S"], "sales": [100, 200]})
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=df, output=config_obj, response=None)
    output, wrapped = await r.render(resp)

    assert wrapped is None
    assert output is not None
    assert output["x"] == "region"      # first non-numeric column
    assert output["y"] == ["sales"]     # numeric column
    assert isinstance(resp.data, list) and len(resp.data) == 2


@satellite_available
@pytest.mark.asyncio
async def test_renderer_output_columns_always_match_data():
    """INVARIANT: after render, config.x and every config.y exist in response.data.

    This is exactly what the frontend guard checks before rendering. We exercise
    several shapes the radar/finance agent produced (matching cols, mismatched
    cols, index column, DataFrame source) and assert the config/data stay aligned
    so the frontend never shows "columns don't match".
    """
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # FEAT-224: config via response.output (StructuredChartConfig instances)
    from parrot.models.outputs import StructuredChartConfig
    cases = [
        # radar: config matches the injected DataFrame columns
        (StructuredChartConfig(type="radar", x="cat", y=["amount"]),
         pd.DataFrame({"cat": ["A", "B"], "amount": [10, 20]})),
        # config invents x/y; data has different real columns
        (StructuredChartConfig(type="radar", x="expense_category", y=["total_amount"]),
         pd.DataFrame({"grp": ["A", "B"], "amt": [1, 2]})),
        # data carries a leaked pandas index column
        (StructuredChartConfig(type="bar", x="cat", y=["amount"]),
         [{"index": 0, "cat": "A", "amount": 10}, {"index": 1, "cat": "B", "amount": 20}]),
    ]
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    for cfg_obj, data in cases:
        resp = SimpleNamespace(code=None, data=data, output=cfg_obj, response=None)
        output, wrapped = await r.render(resp)
        assert output is not None, f"render failed for {cfg_obj}"
        rows = resp.data
        assert isinstance(rows, list) and rows, "response.data must be non-empty rows"
        cols = set(rows[0].keys())
        # The exact invariant the frontend's hasValidColumns enforces:
        assert output["x"] in cols, f"x={output['x']} not in {cols}"
        assert all(y in cols for y in output["y"]), f"y={output['y']} not all in {cols}"
        assert "index" not in output["y"], "index must never be a y series"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_drops_index_column_from_y():
    """An 'index' column (pandas row index) is never emitted as a y series."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # FEAT-224: config via response.output
    from parrot.models.outputs import StructuredChartConfig
    config_obj = StructuredChartConfig(type="radar", x="cat", y=["index", "val"])
    rows = [{"index": 0, "cat": "A", "val": 10}, {"index": 1, "cat": "B", "val": 20}]
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=rows, output=config_obj, response=None)
    output, wrapped = await r.render(resp)

    assert wrapped is None
    assert output["x"] == "cat"
    assert output["y"] == ["val"]  # "index" dropped → single meaningful series


@satellite_available
@pytest.mark.asyncio
async def test_renderer_code_as_dict(bar_config_json, bar_data_df):
    """response.output as a pre-parsed dict is validated directly.

    FEAT-224: config dict now travels via response.output (not response.code).
    This test verifies the dict path in the new renderer logic.
    """
    import json
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # The config dict (as the PandasAgent would place it in response.output).
    config_dict = json.loads(bar_config_json)   # dict, not string
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=bar_data_df, output=config_dict, response=None)
    output, wrapped = await r.render(resp)

    assert output is not None
    assert "data" not in output
    assert isinstance(resp.data, list) and len(resp.data) == 2


@satellite_available
@pytest.mark.asyncio
async def test_renderer_preserves_explanation_as_wrapped(bar_config_obj, bar_data_df):
    """Explanation from PandasAgentResponse is returned as wrapped so callers see prose.

    FEAT-224: config via response.output.
    """
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    explanation = "For Q1 2026, here is the expense breakdown by category."
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    # Simulate PandasAgent state: output = config object, response = explanation text
    resp = SimpleNamespace(
        code=None,
        data=bar_data_df,
        output=bar_config_obj,
        response=explanation,
    )
    output, wrapped = await r.render(resp)

    assert output is not None, "config dict must be returned"
    assert "data" not in output
    # The explanation must be returned as wrapped so data.py sets
    # response.response = explanation (not None).
    assert wrapped == explanation, "explanation must be surfaced as wrapped text"


@satellite_available
@pytest.mark.asyncio
async def test_renderer_explanation_preserved_on_failure():
    """On parse failure the explanation is NOT returned (error message replaces it)."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    explanation = "I tried to build the chart but something went wrong."
    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(
        code="{bad json",
        data=None,
        output=None,
        response=explanation,
    )
    output, wrapped = await r.render(resp)

    assert output is None
    # On failure, the error message is returned (not the explanation)
    assert wrapped is not None
    assert "Invalid" in wrapped or "structured chart" in wrapped.lower()


@satellite_available
@pytest.mark.asyncio
async def test_renderer_outer_exception_graceful_degradation():
    """An unexpected exception inside render() returns (None, msg), never raises.

    FEAT-224: the renderer reads response.output first (not response.code).
    A broken output property triggers the outer exception handler.
    """
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()

    # Pass a broken response where output raises (not code, which is no longer read).
    class _Broken:
        @property
        def output(self):
            raise RuntimeError("simulated unexpected crash")

    output, wrapped = await r.render(_Broken())  # MUST NOT raise
    assert output is None
    assert wrapped and "unexpected" in wrapped.lower()


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
async def test_renderer_reads_output_first(bar_config_obj, bar_data_df):
    """Renderer reads response.output before falling back to text extraction (FEAT-224).

    Previously tested response.code priority; now verifies response.output priority.
    """
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    # output is set (config object); response text is explanation prose — output wins.
    explanation = "some unrelated text"
    resp = SimpleNamespace(code=None, data=bar_data_df, output=bar_config_obj,
                           response=explanation)
    output, wrapped = await r.render(resp)
    assert output is not None
    # wrapped = the preserved explanation (not None — renderer surfaces it)
    assert wrapped == explanation


@satellite_available
@pytest.mark.asyncio
async def test_renderer_falls_back_to_text_extraction(bar_config_json, bar_data_df):
    """Renderer extracts JSON from message text when code is None."""
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    # Embed the JSON in a markdown code block inside the response text.
    # The same text is also the "explanation" that gets preserved as wrapped.
    text_with_json = f"```json\n{bar_config_json}\n```"
    resp = SimpleNamespace(code=None, data=bar_data_df, output=None, response=text_with_json)
    output, wrapped = await r.render(resp)
    assert output is not None, "Should extract JSON from text"
    # wrapped = the preserved explanation (the same text that held the JSON)
    assert wrapped == text_with_json


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
def test_echarts_unchanged():
    """ECHARTS renderer + prompt resolves unchanged (regression guard)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer, get_output_prompt
    from parrot.outputs.formats.echarts import EChartsRenderer

    assert get_renderer(OutputMode.ECHARTS) is EChartsRenderer
    assert get_output_prompt(OutputMode.ECHARTS) is not None


# ─────────────────────────────────────────────────────────────────────────────
# FEAT-223 TASK-1455 — Deterministic chart tests
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_rows_from_dataframe_not_llm():
    """FEAT-223: Given a DataFrame in response.data, rows come from it — not from cfg.data."""
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"region": ["N", "S", "E"], "revenue": [10, 20, 30]})
    # cfg.data is empty — LLM did not embed rows (correct behavior); FEAT-224: output=
    from parrot.models.outputs import StructuredChartConfig
    cfg_obj = StructuredChartConfig(type="bar", x="region", y=["revenue"], data=[])

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=df, output=cfg_obj, response=None)
    output, wrapped = await r.render(resp)

    assert output is not None
    assert isinstance(resp.data, list) and len(resp.data) == 3
    assert resp.data[0]["region"] == "N"
    assert resp.data[0]["revenue"] == 10


@satellite_available
@pytest.mark.asyncio
async def test_xy_always_real_columns():
    """FEAT-223: x/y in the emitted config are always members of the real column set."""
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"cat": ["A", "B"], "val": [1, 2]})
    # FEAT-224: config via response.output
    from parrot.models.outputs import StructuredChartConfig
    cfg_obj = StructuredChartConfig(type="line", x="cat", y=["val"])

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=df, output=cfg_obj, response=None)
    output, _ = await r.render(resp)

    assert output is not None
    cols = set(resp.data[0].keys())
    assert output["x"] in cols
    assert all(y in cols for y in output["y"])


@satellite_available
@pytest.mark.asyncio
async def test_absent_xy_falls_back_deterministically():
    """FEAT-223: LLM picks absent x/y → first categorical = x, first numeric = y."""
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"grp": ["X", "Y"], "amount": [5, 10]})
    # FEAT-224: config via response.output
    from parrot.models.outputs import StructuredChartConfig
    cfg_obj = StructuredChartConfig(type="bar", x="nonexistent_col", y=["also_missing"])

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=df, output=cfg_obj, response=None)
    output, _ = await r.render(resp)

    assert output is not None
    # grp is the first non-numeric column
    assert output["x"] == "grp"
    # amount is the first numeric non-x column
    assert output["y"] == ["amount"]


@satellite_available
@pytest.mark.asyncio
async def test_negative_values_render():
    """FEAT-223: bar/line charts render correctly with negative values after determinism."""
    import pandas as pd
    from types import SimpleNamespace
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "month": ["Jan", "Feb", "Mar"],
        "profit": [100, -50, 75],
    })
    # FEAT-224: config via response.output
    from parrot.models.outputs import StructuredChartConfig
    cfg_obj = StructuredChartConfig(
        type="bar",
        x="month",
        y=["profit"],
        color_by_sign=True,
    )

    r = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = SimpleNamespace(code=None, data=df, output=cfg_obj, response=None)
    output, _ = await r.render(resp)

    assert output is not None
    assert output["x"] == "month"
    assert output["y"] == ["profit"]
    assert isinstance(resp.data, list) and len(resp.data) == 3
    profits = [row["profit"] for row in resp.data]
    assert -50 in profits


@satellite_available
@pytest.mark.asyncio
async def test_never_raises_on_garbage():
    """FEAT-223: Unusable input degrades gracefully (None, message), never raises."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_CHART)()

    class _Garbage:
        @property
        def code(self):
            raise RuntimeError("completely broken")

    output, msg = await r.render(_Garbage())
    assert output is None
    assert isinstance(msg, str) and msg
