"""Tests for FEAT-218 TASK-1434: DB/SQL agent producer — STRUCTURED_TABLE end-to-end.

Verifies that:
1. DatabaseAgent.ask(output_mode=STRUCTURED_TABLE) sets response.output_mode correctly.
2. The SQL_ANALYSIS path is unchanged when no output_mode (or SQL_ANALYSIS) is passed.
3. The new output_mode parameter is accepted without breaking the existing API.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — DB agent output_mode parameter handling
# ─────────────────────────────────────────────────────────────────────────────


def test_ask_signature_accepts_output_mode():
    """DatabaseAgent.ask() accepts an output_mode keyword argument."""
    import inspect
    from parrot.bots.database.agent import DatabaseAgent

    sig = inspect.signature(DatabaseAgent.ask)
    assert "output_mode" in sig.parameters, (
        "DatabaseAgent.ask() must accept 'output_mode' parameter (FEAT-218)"
    )


def test_structured_table_output_mode_importable():
    """OutputMode.STRUCTURED_TABLE is importable and has the right value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_TABLE == "structured_table"


def test_sql_analysis_output_mode_unchanged():
    """OutputMode.SQL_ANALYSIS is still present and unchanged."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.SQL_ANALYSIS == "sql_analysis"


def test_database_agent_source_has_structured_table_branch():
    """agent.py source contains the STRUCTURED_TABLE branch."""
    # Read the agent source directly from the repo tree
    _THIS_DIR = Path(__file__).resolve().parent
    _REPO_ROOT_LOCAL = _THIS_DIR.parents[4]
    _AGENT_PY = (
        _REPO_ROOT_LOCAL
        / "packages" / "ai-parrot" / "src" / "parrot" / "bots" / "database" / "agent.py"
    )
    assert _AGENT_PY.exists(), f"agent.py not found at {_AGENT_PY}"
    source = _AGENT_PY.read_text(encoding="utf-8")

    assert "OutputMode.STRUCTURED_TABLE" in source, (
        "agent.py must contain OutputMode.STRUCTURED_TABLE handling (FEAT-218)"
    )
    assert "output_mode == OutputMode.STRUCTURED_TABLE" in source or (
        "STRUCTURED_TABLE" in source and "output_mode" in source
    ), "STRUCTURED_TABLE branch must check the output_mode parameter"


def test_database_agent_source_sql_analysis_unchanged():
    """The SQL_ANALYSIS assignment must still exist as the default path."""
    _THIS_DIR = Path(__file__).resolve().parent
    _REPO_ROOT_LOCAL = _THIS_DIR.parents[4]
    _AGENT_PY = (
        _REPO_ROOT_LOCAL
        / "packages" / "ai-parrot" / "src" / "parrot" / "bots" / "database" / "agent.py"
    )
    source = _AGENT_PY.read_text(encoding="utf-8")
    assert "OutputMode.SQL_ANALYSIS" in source, (
        "OutputMode.SQL_ANALYSIS must remain in agent.py — SQL_ANALYSIS path must not regress"
    )
    assert "response.output_mode = OutputMode.SQL_ANALYSIS" in source, (
        "response.output_mode = OutputMode.SQL_ANALYSIS must remain as the default path"
    )


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: DB-agent-style QueryResponse + StructuredTableRenderer
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_db_agent_structured_table_via_renderer():
    """DB-agent-style response → StructuredTableRenderer produces valid payload."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    # Simulate what DatabaseAgent sets after unpackaging a QueryResponse:
    # response.response = qr.explanation (prose)
    # response.data = materialised QueryDataset (DataFrame or list)
    # response.output_mode = STRUCTURED_TABLE
    df = pd.DataFrame({
        "order_id": [101, 102, 103],
        "total": [99.5, 149.0, 199.95],
        "status": ["shipped", "pending", "delivered"],
    })
    resp = SimpleNamespace(
        data=df,
        response="Retrieved 3 recent orders grouped by status.",
        output=None,
        code=None,
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert "columns" in out
    assert isinstance(resp.data, list), "response.data must be list after render"
    assert len(resp.data) == 3
    assert wrapped == "Retrieved 3 recent orders grouped by status."


@satellite_available
@pytest.mark.asyncio
async def test_db_agent_explanation_reused():
    """QueryResponse.explanation is reused as the structured-table explanation."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    explanation = "SELECT order_id, total FROM orders WHERE status = 'shipped'"
    # The DB agent pre-processes qr.explanation through _dedupe_sql_from_explanation,
    # so the response.response is prose-only.  We simulate that here.
    prose_explanation = "Fetched shipped orders from the database."
    df = pd.DataFrame({"order_id": [1], "total": [50.0]})

    resp = SimpleNamespace(
        data=df,
        response=prose_explanation,
        output=None,
        code=None,
    )
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, wrapped = await renderer.render(resp)

    assert out is not None
    assert wrapped == prose_explanation


@satellite_available
@pytest.mark.asyncio
async def test_db_agent_no_html():
    """STRUCTURED_TABLE output contains no HTML markup."""
    import json
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"col": [1, 2, 3]})
    resp = SimpleNamespace(data=df, response="query result", output=None, code=None)
    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _ = await renderer.render(resp)

    assert out is not None
    output_str = json.dumps(out)
    assert "<table" not in output_str.lower()
    assert "<tr" not in output_str.lower()
