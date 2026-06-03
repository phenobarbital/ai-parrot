"""Tests for FEAT-218 TASK-1433: PandasAgent producer — STRUCTURED_TABLE end-to-end.

Verifies that a PandasAgent-style response (DataFrame in response.data,
prose in response.response) flows through the STRUCTURED_TABLE renderer
to produce a valid structured-table payload with no HTML.

Note: These tests exercise the formatter → renderer pipeline using a
      minimal AIMessage-like namespace, without instantiating the full
      PandasAgent (which would require a live LLM client).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# ── Satellite path wiring (mirrors test_structured_chart.py) ─────────────────
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_df():
    """A minimal DataFrame that PandasAgent would produce."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "amount": [10.5, 20.0, 30.75],
        "created": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
        "label": ["alpha", "beta", "gamma"],
    })


@pytest.fixture
def pandas_response(sample_df):
    """Minimal AIMessage-like object simulating a PandasAgent response."""
    return SimpleNamespace(
        data=sample_df,
        response="Fetched 3 rows from the orders table.",
        output=None,
        code=None,
        output_mode=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: PandasAgent-style response + STRUCTURED_TABLE renderer
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_structured_table_columns_present(pandas_response):
    """Renderer produces 'columns' list from PandasAgent response."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(pandas_response)

    assert out is not None, "output must not be None"
    assert "columns" in out, "'columns' key must be present"
    col_names = [c["name"] for c in out["columns"]]
    assert "id" in col_names
    assert "amount" in col_names
    assert "created" in col_names
    assert "label" in col_names


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_rows_routed_to_response_data(pandas_response):
    """Rows are routed to response.data as a plain list."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(pandas_response)

    assert out is not None
    assert isinstance(pandas_response.data, list), "response.data must be list after render"
    assert len(pandas_response.data) == 3


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_explanation_reused(pandas_response):
    """Prose explanation from PandasAgent is returned as wrapped."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(pandas_response)

    assert out is not None
    assert wrapped == "Fetched 3 rows from the orders table."


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_no_html(pandas_response):
    """Output contains no HTML markup (not an HTML/Grid.js table)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(pandas_response)

    assert out is not None
    import json
    output_str = json.dumps(out)
    assert "<table" not in output_str.lower()
    assert "<tr" not in output_str.lower()
    assert "gridjs" not in output_str.lower()


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_data_excluded_from_output(pandas_response):
    """'data' key is absent from the output dict."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(pandas_response)

    assert out is not None
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_datetime_serialized_as_iso(pandas_response):
    """Datetime column values are serialized as ISO-8601 strings."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(pandas_response)

    assert out is not None
    assert isinstance(pandas_response.data, list)
    # All 'created' values should be ISO-8601 strings
    for row in pandas_response.data:
        assert isinstance(row["created"], str)
        assert row["created"].startswith("2026-")


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_deterministic_column_types(sample_df):
    """Column types are derived deterministically from the DataFrame dtypes."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    resp = SimpleNamespace(
        data=sample_df,
        response="Fetched data.",
        output=None,
        code=None,
    )
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    col_map = {c["name"]: c["type"] for c in out["columns"]}
    assert col_map["id"] == "integer"
    assert col_map["amount"] == "number"
    assert col_map["created"] == "datetime"
    assert col_map["label"] == "string"
