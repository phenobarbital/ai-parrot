"""Tests for FEAT-218 TASK-1431: StructuredTableRenderer + dispatch wiring.

Tests:
  - get_renderer(STRUCTURED_TABLE) resolves to StructuredTableRenderer.
  - Output dump excludes data; rows routed to response.data.
  - explanation reused from response.response.
  - LLM-refine never changes a hard base type (deterministic wins).
  - Row-limit applied; total_rows / truncated set.
  - Malformed input → (None, msg), never raises.
  - LLM-refine failure → deterministic-only schema.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# ── Satellite path wiring ──────────────────────────────────────────────────────
# Add ai-parrot-visualizations/src to sys.path so the PEP 420 namespace merge
# can discover the satellite renderer modules (e.g. structured_table.py).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed",
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_response(*, data=None, response=None, code=None, output=None):
    """Create a minimal AIMessage-like namespace."""
    return SimpleNamespace(data=data, response=response, code=code, output=output)


def _sample_df() -> pd.DataFrame:
    """Return a small test DataFrame with mixed dtypes."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "amount": [10.5, 20.0, 30.75],
        "label": ["a", "b", "c"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch resolution
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
def test_dispatch_resolves():
    """get_renderer(STRUCTURED_TABLE) resolves to StructuredTableRenderer."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer
    from parrot.outputs.formats.structured_table import StructuredTableRenderer

    assert get_renderer(OutputMode.STRUCTURED_TABLE) is StructuredTableRenderer


@satellite_available
def test_system_prompt_registered():
    """A system prompt is registered for STRUCTURED_TABLE."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_output_prompt

    prompt = get_output_prompt(OutputMode.STRUCTURED_TABLE)
    assert prompt is not None
    assert "format" in prompt.lower() or "structured" in prompt.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Data routing + output exclusion
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_routes_rows_and_excludes_data():
    """Output excludes 'data'; rows are routed to response.data."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = _sample_df()
    resp = _make_response(data=df, response="how it was built")
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None, "output must not be None on success"
    assert "data" not in out, "data key must be excluded from output"
    assert isinstance(resp.data, list), "response.data must be a list after render"
    assert len(resp.data) == 3, "all 3 rows must be present"
    assert wrapped == "how it was built", "explanation must be preserved"


@satellite_available
@pytest.mark.asyncio
async def test_output_contains_columns():
    """Output dict contains a 'columns' key with per-column entries."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = _sample_df()
    resp = _make_response(data=df)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    assert "columns" in out
    col_names = [c["name"] for c in out["columns"]]
    assert "id" in col_names
    assert "amount" in col_names
    assert "label" in col_names


@satellite_available
@pytest.mark.asyncio
async def test_column_types_deterministic():
    """Base column types are derived deterministically from the DataFrame."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "int_col": pd.array([1, 2], dtype="int64"),
        "float_col": [1.5, 2.5],
        "bool_col": [True, False],
        "str_col": ["x", "y"],
    })
    resp = _make_response(data=df)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    col_map = {c["name"]: c["type"] for c in out["columns"]}
    assert col_map["int_col"] == "integer"
    assert col_map["float_col"] == "number"
    assert col_map["bool_col"] == "boolean"
    assert col_map["str_col"] == "string"


# ─────────────────────────────────────────────────────────────────────────────
# Explanation handling
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_explanation_reused():
    """explanation from response.response is returned as wrapped."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = _sample_df()
    explanation = "Fetched from sales table, grouped by month."
    resp = _make_response(data=df, response=explanation)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert wrapped == explanation


@satellite_available
@pytest.mark.asyncio
async def test_explanation_absent_is_none():
    """When response.response is None, wrapped is None (no raise)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = _sample_df()
    resp = _make_response(data=df, response=None)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert wrapped is None


# ─────────────────────────────────────────────────────────────────────────────
# Row-limit + truncation
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_row_limit_applied():
    """row_limit caps output rows; total_rows and truncated are correct."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"a": list(range(10))})
    resp = _make_response(data=df)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp, row_limit=3)

    assert out is not None
    assert out["total_rows"] == 10
    assert out["truncated"] is True
    assert isinstance(resp.data, list)
    assert len(resp.data) == 3


@satellite_available
@pytest.mark.asyncio
async def test_no_truncation_when_under_limit():
    """When rows <= row_limit, truncated is False."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"a": [1, 2, 3]})
    resp = _make_response(data=df)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp, row_limit=1000)

    assert out is not None
    assert out["total_rows"] == 3
    assert out["truncated"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Graceful degradation
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_graceful_on_bad_input():
    """Malformed input → (None, error_msg), never raises."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, msg = await renderer.render(object())  # MUST NOT raise

    assert out is None
    assert isinstance(msg, str) and msg


@satellite_available
@pytest.mark.asyncio
async def test_graceful_on_empty_response():
    """Response with no data → (None, msg), never raises."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    resp = _make_response(data=None, response=None)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, msg = await renderer.render(resp)

    assert out is None
    assert isinstance(msg, str) and msg


@satellite_available
@pytest.mark.asyncio
async def test_outer_exception_graceful_degradation():
    """An unexpected exception inside render() returns (None, msg), never raises."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()

    class _Broken:
        @property
        def data(self):
            raise RuntimeError("simulated crash")

    out, msg = await renderer.render(_Broken())
    assert out is None
    assert msg and ("unexpected" in msg.lower() or "simulated" in msg.lower() or msg)


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic wins — LLM-refine conflict
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_deterministic_wins_on_hard_type():
    """LLM hint for a hard-typed column (datetime, number) is ignored."""
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "amount": [10.5, 20.0],
        "created": pd.to_datetime(["2026-01-01", "2026-02-01"]),
    })
    # Simulate LLM trying to annotate a "number" column (hard type) — should be ignored
    # and trying to annotate "created" (datetime, hard type) — also ignored.
    hints = json.dumps({"amount": "currency", "created": "date"})
    resp = _make_response(data=df, code=hints)

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    col_map = {c["name"]: c for c in out["columns"]}

    # "amount" is a number (hard type) → LLM cannot add format hint
    assert col_map["amount"]["type"] == "number"
    assert col_map["amount"].get("format") is None, (
        "LLM must not annotate hard-typed 'number' column"
    )

    # "created" is datetime (hard type) → LLM cannot change it
    assert col_map["created"]["type"] == "datetime"


@satellite_available
@pytest.mark.asyncio
async def test_llm_refine_adds_format_to_string_column():
    """LLM hint for a string column (ambiguous) is accepted."""
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"email_addr": ["a@b.com", "c@d.com"]})
    hints = json.dumps({"email_addr": "email"})
    resp = _make_response(data=df, code=hints)

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    col_map = {c["name"]: c for c in out["columns"]}
    assert col_map["email_addr"]["type"] == "string"
    assert col_map["email_addr"].get("format") == "email"


@satellite_available
@pytest.mark.asyncio
async def test_llm_refine_failure_falls_back():
    """Invalid refine JSON → deterministic-only schema returned, no raise."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = _sample_df()
    resp = _make_response(data=df, code="{invalid json {{{{")

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    # Must still return a valid structured table (deterministic fallback)
    assert out is not None
    assert "columns" in out


# ─────────────────────────────────────────────────────────────────────────────
# DataFrame in response.data (pre-existing) → replaced by canonical list
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_llm_refine_accepts_id_hint_on_integer_column():
    """LLM 'id' or 'code' format hint on an integer column is accepted (not blocked).

    Regression test for the bug where 'integer' was in _HARD_TYPES, causing
    format hints on integer columns to be silently discarded.
    """
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "user_id": pd.array([1, 2, 3], dtype="int64"),
        "product_code": pd.array([101, 202, 303], dtype="int64"),
    })
    hints = json.dumps({"user_id": "id", "product_code": "code"})
    resp = _make_response(data=df, code=hints)

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    col_map = {c["name"]: c for c in out["columns"]}

    # Base type must remain "integer" — LLM cannot change it
    assert col_map["user_id"]["type"] == "integer"
    assert col_map["product_code"]["type"] == "integer"

    # Format hints MUST be applied (integer is not hard-typed for format hints)
    assert col_map["user_id"].get("format") == "id", (
        "Expected 'id' format hint to be applied to integer column user_id"
    )
    assert col_map["product_code"].get("format") == "code", (
        "Expected 'code' format hint to be applied to integer column product_code"
    )


@satellite_available
@pytest.mark.asyncio
async def test_dataframe_response_data_replaced():
    """Pre-existing pd.DataFrame in response.data is replaced by a plain list."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    raw_df = pd.DataFrame({"col_a": range(50), "col_b": range(50)})
    resp = _make_response(data=raw_df, response="explanation")
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert isinstance(resp.data, list), "response.data must be plain list after render"
    assert len(resp.data) == 50
