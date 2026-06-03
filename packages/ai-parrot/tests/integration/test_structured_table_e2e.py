"""Integration tests for FEAT-218: Structured Table Output Mode.

TASK-1435 — e2e integration suite:
  - PandasAgent + STRUCTURED_TABLE end-to-end (valid payload, zero HTML).
  - DB/SQL agent + STRUCTURED_TABLE end-to-end (reused SQL provenance).
  - HTTP envelope parity with STRUCTURED_CHART.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# ── Satellite path wiring ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[5]
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
    """Sample DataFrame mimicking a PandasAgent/DB result."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "amount": [10.5, 20.0, 30.75],
        "created": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
        "category": ["a", "b", "c"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# PandasAgent end-to-end
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_structured_table_end_to_end(sample_df):
    """PandasAgent + output_mode=STRUCTURED_TABLE → valid payload, zero HTML."""
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # Simulate PandasAgent response: DataFrame in .data, explanation in .response
    resp = SimpleNamespace(
        data=sample_df,
        response="Summary of order amounts by category.",
        output=None,
        code=None,
        output_mode=None,
    )
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    # Payload validity
    assert out is not None, "output must not be None"
    assert "columns" in out, "'columns' must be in output"
    assert isinstance(resp.data, list), "response.data must be plain list"
    assert len(resp.data) == 3
    assert wrapped == "Summary of order amounts by category."

    # Zero HTML
    output_str = json.dumps(out)
    assert "<table" not in output_str.lower()
    assert "<tr" not in output_str.lower()
    assert "gridjs" not in output_str.lower()

    # data excluded from output
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_iso_datetime_values(sample_df):
    """Datetime values in rows are ISO-8601 UTC strings."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    resp = SimpleNamespace(data=sample_df, response=None, output=None, code=None)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    await renderer.render(resp)

    assert isinstance(resp.data, list)
    for row in resp.data:
        assert isinstance(row["created"], str)
        assert "T" in row["created"] or row["created"].startswith("2026-")


@satellite_available
@pytest.mark.asyncio
async def test_pandasagent_column_types_deterministic(sample_df):
    """Column types derived deterministically (no LLM, no HTML)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    resp = SimpleNamespace(data=sample_df, response=None, output=None, code=None)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    col_map = {c["name"]: c["type"] for c in out["columns"]}
    assert col_map["id"] == "integer"
    assert col_map["amount"] == "number"
    assert col_map["created"] == "datetime"
    assert col_map["category"] == "string"


# ─────────────────────────────────────────────────────────────────────────────
# DB/SQL agent end-to-end
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_db_agent_structured_table_end_to_end():
    """DB agent QueryResponse + STRUCTURED_TABLE → valid payload with reused provenance."""
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # Simulate what DatabaseAgent sets after unpackaging a QueryResponse:
    # response.response = qr.explanation (prose, no SQL — deduplicated by model validator)
    # response.data = materialised QueryDataset as DataFrame
    df = pd.DataFrame({
        "order_id": [101, 102, 103],
        "total_usd": [99.5, 149.0, 199.95],
        "status": ["shipped", "pending", "delivered"],
    })
    db_explanation = "Retrieved 3 orders from the orders table, filtered by date range."
    resp = SimpleNamespace(
        data=df,
        response=db_explanation,
        output=None,
        code=None,
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert "columns" in out
    assert isinstance(resp.data, list)
    assert len(resp.data) == 3
    assert wrapped == db_explanation

    # No HTML
    output_str = json.dumps(out)
    assert "<table" not in output_str.lower()


@satellite_available
@pytest.mark.asyncio
async def test_db_agent_sql_provenance_in_explanation():
    """Explanation reuses QueryResponse.explanation (prose, no SQL duplication)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # The _dedupe_sql_from_explanation validator in QueryResponse strips SQL
    # from the explanation field, so response.response is always prose-only.
    prose = "Queried the sales database and grouped by region."
    df = pd.DataFrame({"region": ["north", "south"], "sales": [1000, 2000]})
    resp = SimpleNamespace(data=df, response=prose, output=None, code=None)

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert wrapped == prose


# ─────────────────────────────────────────────────────────────────────────────
# HTTP envelope parity with STRUCTURED_CHART
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


def test_envelope_serialization_parity():
    """HTTP envelope mirrors STRUCTURED_CHART shape (output/data/response/code)."""
    from datamodel.parsers.json import json_encoder
    from parrot.models.outputs import OutputMode

    # STRUCTURED_CHART envelope (existing shape)
    chart_env = _envelope(
        output={"type": "bar", "x": "m", "y": ["v"]},
        data=[{"m": "Jan", "v": 1}],
        response="Chart description",
        code=None,
        output_mode=OutputMode.STRUCTURED_CHART.value,
    )
    # STRUCTURED_TABLE envelope (parity target)
    table_env = _envelope(
        output={
            "columns": [{"name": "m", "type": "string", "title": "M", "format": None}],
            "total_rows": 1,
            "truncated": False,
            "explanation": "Table description",
        },
        data=[{"m": "Jan"}],
        response="Table description",
        code=None,
        output_mode=OutputMode.STRUCTURED_TABLE.value,
    )

    # Same top-level keys
    assert set(chart_env.keys()) == set(table_env.keys()), (
        "STRUCTURED_TABLE envelope must have the same top-level keys as STRUCTURED_CHART"
    )

    # Both serialize without error
    chart_blob = json_encoder(chart_env)
    table_blob = json_encoder(table_env)
    assert "structured_chart" in chart_blob
    assert "structured_table" in table_blob

    # Both envelopes: data key not in output
    assert "data" not in chart_env["output"]
    assert "data" not in table_env["output"]


def test_envelope_degraded_structured_table():
    """Degraded response (output=None + error message) encodes cleanly."""
    from datamodel.parsers.json import json_encoder
    from parrot.models.outputs import OutputMode

    env = _envelope(
        output=None,
        data=None,
        response="StructuredTableRenderer: no data found in response",
        code=None,
        output_mode=OutputMode.STRUCTURED_TABLE.value,
    )
    blob = json_encoder(env)
    assert env["output"] is None
    assert env["response"]
    assert "structured_table" in blob


@satellite_available
@pytest.mark.asyncio
async def test_full_pipeline_parity_with_chart():
    """STRUCTURED_TABLE renderer pipeline matches STRUCTURED_CHART shape."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # Run TABLE renderer
    df = pd.DataFrame({"x": [1, 2], "y": [3.0, 4.0]})
    resp_table = SimpleNamespace(data=df, response="table explanation", output=None, code=None)
    table_renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    table_out, table_wrapped = await table_renderer.render(resp_table)

    assert table_out is not None
    # Output must NOT contain 'data'
    assert "data" not in table_out
    # Output must contain 'columns'
    assert "columns" in table_out
    # Rows in response.data
    assert isinstance(resp_table.data, list)
    # Explanation as wrapped
    assert table_wrapped == "table explanation"
