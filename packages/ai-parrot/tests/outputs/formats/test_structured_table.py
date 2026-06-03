"""Tests for FEAT-218: Structured Table Output Mode.

TASK-1435: Full test suite cloned from test_structured_chart.py (521 lines),
adapted for STRUCTURED_TABLE:
  TASK-1429 — OutputMode.STRUCTURED_TABLE enum member
  TASK-1429 — TableColumn + StructuredTableConfig model + validators
  TASK-1431 — StructuredTableRenderer + dispatch + system-prompt
  TASK-1435 — data-exclusion + routing, explanation-as-wrapped, graceful
               degradation, envelope serialization regression
  TASK-1430 — dtype→vocabulary map, deterministic-wins conflict
  TASK-1431 — row-limit/truncation
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

# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — OutputMode.STRUCTURED_TABLE enum member
# ─────────────────────────────────────────────────────────────────────────────


def test_outputmode_has_structured_table():
    """OutputMode.STRUCTURED_TABLE exists with the correct string value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_TABLE.value == "structured_table"
    assert OutputMode("structured_table") is OutputMode.STRUCTURED_TABLE


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — TableColumn model tests
# ─────────────────────────────────────────────────────────────────────────────


def test_table_column_required_fields():
    """TableColumn requires name, type, title."""
    from parrot.models.outputs import TableColumn

    col = TableColumn(name="amount", type="number", title="Amount")
    assert col.name == "amount"
    assert col.type == "number"
    assert col.title == "Amount"
    assert col.format is None


def test_table_column_optional_format():
    """TableColumn accepts optional format hint."""
    from parrot.models.outputs import TableColumn

    col = TableColumn(name="price", type="number", title="Price", format="currency")
    assert col.format == "currency"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — StructuredTableConfig model + validators
# ─────────────────────────────────────────────────────────────────────────────


def test_structured_table_config_basic():
    """StructuredTableConfig accepts columns + data and validates correctly."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="a", type="integer", title="A")],
        data=[{"a": 1}],
    )
    assert len(cfg.columns) == 1
    assert len(cfg.data) == 1


def test_structured_table_config_defaults():
    """explanation, total_rows, truncated have sensible defaults."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="x", type="string", title="X")],
        data=[{"x": "v"}],
    )
    assert cfg.explanation is None
    assert cfg.total_rows is None
    assert cfg.truncated is False


def test_structured_table_config_all_fields():
    """StructuredTableConfig accepts all optional fields."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="id", type="integer", title="ID")],
        data=[{"id": 1}],
        explanation="Fetched from orders table.",
        total_rows=500,
        truncated=True,
    )
    assert cfg.explanation == "Fetched from orders table."
    assert cfg.total_rows == 500
    assert cfg.truncated is True


def test_structured_table_config_data_excluded_from_dump():
    """model_dump(by_alias=True, exclude={'data'}) omits the data rows."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="a", type="number", title="A")],
        data=[{"a": 1.5}],
    )
    out = cfg.model_dump(by_alias=True, exclude={"data"})
    assert "data" not in out
    assert out["columns"][0]["name"] == "a"


def test_structured_table_config_mode_json_dump():
    """model_dump(mode='json', by_alias=True, exclude={'data'}) — renderer pattern."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="v", type="number", title="V", format="percent")],
        data=[{"v": 0.5}],
        total_rows=1,
        truncated=False,
    )
    dumped = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
    assert "data" not in dumped
    assert dumped["columns"][0]["format"] == "percent"
    assert dumped["truncated"] is False


def test_structured_table_config_validator_rejects_unknown_column():
    """column.name absent from non-empty data[0] raises ValidationError."""
    from pydantic import ValidationError
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    with pytest.raises((ValidationError, ValueError)):
        StructuredTableConfig(
            columns=[TableColumn(name="missing", type="string", title="X")],
            data=[{"a": 1}],
        )


def test_structured_table_config_empty_data_skips_validator():
    """Empty data list does not trigger column-name validation."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="anything", type="any", title="Anything")],
        data=[],
    )
    assert cfg.data == []


def test_structured_table_config_multiple_columns():
    """All column.name values present in data[0] → no error."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[
            TableColumn(name="id", type="integer", title="ID"),
            TableColumn(name="name", type="string", title="Name"),
        ],
        data=[{"id": 1, "name": "Alice"}],
    )
    assert len(cfg.columns) == 2


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1431 — StructuredTableRenderer + dispatch + prompt
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
def test_get_renderer_resolves_structured_table():
    """get_renderer(STRUCTURED_TABLE) returns StructuredTableRenderer."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer
    from parrot.outputs.formats.structured_table import StructuredTableRenderer

    assert get_renderer(OutputMode.STRUCTURED_TABLE) is StructuredTableRenderer


@satellite_available
def test_system_prompt_registered_for_structured_table():
    """A system prompt is registered for STRUCTURED_TABLE."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_output_prompt

    prompt = get_output_prompt(OutputMode.STRUCTURED_TABLE)
    assert prompt is not None
    assert len(prompt) > 50  # non-trivial prompt


@satellite_available
@pytest.mark.asyncio
async def test_renderer_output_excludes_data():
    """Valid DataFrame: output lacks data key, response.data carries rows."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    resp = SimpleNamespace(data=df, output=None, response="some explanation", code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    output, wrapped = await r.render(resp)

    assert output is not None
    assert "data" not in output, "data key must be excluded from output"
    assert isinstance(resp.data, list)
    assert len(resp.data) == 2


@satellite_available
@pytest.mark.asyncio
async def test_renderer_rows_win_over_dataframe():
    """Pre-existing pd.DataFrame in response.data is replaced by plain list."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    raw_df = pd.DataFrame({"col_a": range(10), "col_b": range(10)})
    resp = SimpleNamespace(data=raw_df, output=None, response=None, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    output, wrapped = await r.render(resp)

    assert output is not None
    assert isinstance(resp.data, list), "response.data must be a plain list"
    assert len(resp.data) == 10


@satellite_available
@pytest.mark.asyncio
async def test_renderer_preserves_explanation_as_wrapped():
    """Explanation from response.response is returned as wrapped."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    explanation = "For Q1 2026, here is the data from orders."
    df = pd.DataFrame({"x": [1, 2]})
    resp = SimpleNamespace(data=df, output=None, response=explanation, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    output, wrapped = await r.render(resp)

    assert output is not None
    assert wrapped == explanation


@satellite_available
@pytest.mark.asyncio
async def test_renderer_explanation_absent_is_none():
    """When response.response is None, wrapped is None."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"x": [1]})
    resp = SimpleNamespace(data=df, output=None, response=None, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    output, wrapped = await r.render(resp)

    assert output is not None
    assert wrapped is None


@satellite_available
@pytest.mark.asyncio
async def test_renderer_graceful_degradation_bad_input():
    """Completely broken object → (None, msg), no raise."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    output, wrapped = await r.render(object())

    assert output is None
    assert isinstance(wrapped, str) and wrapped


@satellite_available
@pytest.mark.asyncio
async def test_renderer_graceful_on_empty_response():
    """Response with no data → (None, msg), no raise."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    resp = SimpleNamespace(data=None, output=None, response=None, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    output, wrapped = await r.render(resp)

    assert output is None
    assert isinstance(wrapped, str) and wrapped


@satellite_available
@pytest.mark.asyncio
async def test_renderer_outer_exception_graceful():
    """Unexpected exception → (None, msg), never raises."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    r = get_renderer(OutputMode.STRUCTURED_TABLE)()

    class _Broken:
        @property
        def data(self):
            raise RuntimeError("simulated crash")

    output, wrapped = await r.render(_Broken())
    assert output is None
    assert wrapped and isinstance(wrapped, str)


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1430 — dtype→vocabulary map (via renderer)
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_dtype_vocabulary_via_renderer():
    """Renderer uses correct storage vocabulary for each dtype."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "int_col": pd.array([1, 2], dtype="int64"),
        "float_col": [1.5, 2.5],
        "bool_col": [True, False],
        "str_col": ["x", "y"],
        "dt_col": pd.to_datetime(["2026-01-01", "2026-02-01"]),
    })
    resp = SimpleNamespace(data=df, output=None, response=None, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await r.render(resp)

    assert out is not None
    col_map = {c["name"]: c["type"] for c in out["columns"]}
    assert col_map["int_col"] == "integer"
    assert col_map["float_col"] == "number"
    assert col_map["bool_col"] == "boolean"
    assert col_map["str_col"] == "string"
    assert col_map["dt_col"] == "datetime"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1431 — deterministic-wins conflict
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_deterministic_wins_conflict():
    """LLM hint for a hard-typed (number/datetime) column is ignored."""
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({
        "price": [10.5, 20.0],
        "ts": pd.to_datetime(["2026-01-01", "2026-02-01"]),
    })
    # LLM tries to annotate "price" (number, hard type) — should be ignored.
    hints = json.dumps({"price": "currency", "ts": "date"})
    resp = SimpleNamespace(data=df, output=None, response=None, code=hints)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await r.render(resp)

    assert out is not None
    col_map = {c["name"]: c for c in out["columns"]}
    # Hard types must not be annotated by LLM
    assert col_map["price"]["type"] == "number"
    assert col_map["price"].get("format") is None
    assert col_map["ts"]["type"] == "datetime"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1431 — row-limit / truncation
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_row_limit_and_truncated_signal():
    """Row-limit is applied; total_rows and truncated are set correctly."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"a": list(range(20))})
    resp = SimpleNamespace(data=df, output=None, response=None, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await r.render(resp, row_limit=5)

    assert out is not None
    assert out["total_rows"] == 20
    assert out["truncated"] is True
    assert isinstance(resp.data, list) and len(resp.data) == 5


@satellite_available
@pytest.mark.asyncio
async def test_no_truncation_when_within_limit():
    """When rows <= row_limit, truncated is False."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"a": [1, 2, 3]})
    resp = SimpleNamespace(data=df, output=None, response=None, code=None)
    r = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await r.render(resp, row_limit=1000)

    assert out is not None
    assert out["truncated"] is False
    assert out["total_rows"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1435 — envelope serialization regression
# ─────────────────────────────────────────────────────────────────────────────


def _envelope(output, data, response, code, output_mode):
    """Mirror the fields assembled by handlers/agent.py."""
    return {
        "output": output,
        "data": data,
        "response": response,
        "output_mode": output_mode,
        "code": str(code) if code else None,
    }


def test_envelope_serializes_structured_table():
    """Config in output (no data key), rows in data, code null → encoder happy."""
    from datamodel.parsers.json import json_encoder
    from parrot.models.outputs import OutputMode

    cfg = {
        "columns": [{"name": "a", "type": "integer", "title": "A", "format": None}],
        "total_rows": 1,
        "truncated": False,
    }
    env = _envelope(
        output=cfg,
        data=[{"a": 1}],
        response="explanation text",
        code=None,
        output_mode=OutputMode.STRUCTURED_TABLE.value,
    )
    blob = json_encoder(env)
    assert env["code"] is None
    assert "data" not in env["output"]
    assert "structured_table" in blob


def test_envelope_serializes_degraded_structured_table():
    """Degraded response (output=None + response message) encodes cleanly."""
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
    _ = blob


def test_envelope_parity_with_structured_chart():
    """STRUCTURED_TABLE envelope shape mirrors STRUCTURED_CHART (same keys)."""
    from datamodel.parsers.json import json_encoder
    from parrot.models.outputs import OutputMode

    chart_env = _envelope(
        output={"type": "bar", "x": "m", "y": ["v"]},
        data=[{"m": "Jan", "v": 1}],
        response=None,
        code=None,
        output_mode=OutputMode.STRUCTURED_CHART.value,
    )
    table_env = _envelope(
        output={"columns": [{"name": "m", "type": "string", "title": "M"}], "total_rows": 1, "truncated": False},
        data=[{"m": "Jan"}],
        response=None,
        code=None,
        output_mode=OutputMode.STRUCTURED_TABLE.value,
    )
    # Both envelopes must have the same top-level keys
    assert set(chart_env.keys()) == set(table_env.keys())

    # Both must serialize without error
    assert json_encoder(chart_env)
    assert json_encoder(table_env)


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1435 — TABLE (HTML) regression guard
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
def test_table_renderer_unchanged():
    """OutputMode.TABLE renderer is still TableRenderer (no regression)."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer
    from parrot.outputs.formats.table import TableRenderer

    assert get_renderer(OutputMode.TABLE) is TableRenderer


def test_table_output_mode_value_unchanged():
    """OutputMode.TABLE value is still 'table'."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.TABLE.value == "table"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1435 — Import smoke test
# ─────────────────────────────────────────────────────────────────────────────


def test_suite_covers_core_contract():
    """Minimum gate: OutputMode.STRUCTURED_TABLE is importable and correct."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_TABLE == "structured_table"


def test_full_import_chain():
    """All public FEAT-218 symbols are importable."""
    from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn  # noqa: F401

    assert OutputMode.STRUCTURED_TABLE
    assert StructuredTableConfig
    assert TableColumn
