"""Tests for issue #1269: DatabaseAgent STRUCTURED_TABLE renderer + artifact minting.

Verifies that DatabaseAgent.ask(output_mode=STRUCTURED_TABLE):
1. Invokes StructuredTableRenderer (response.output becomes a typed config dict).
2. Populates response.a2ui_envelope via the renderer's _emit_a2ui_envelope.
3. Mints a response.artifacts[] entry via attach_structured_artifact.
4. Degrades gracefully to SQL_ANALYSIS when the renderer fails.

These tests exercise the REAL code path in DatabaseAgent.ask() — not the
isolated renderer unit tests in test_db_agent_structured_table.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from parrot.bots.data import PandasTable
from parrot.bots.database import DatabaseAgent
from parrot.bots.database.models import QueryDataset, QueryResponse
from parrot.models import AIMessage
from parrot.models.outputs import OutputMode

# ── Satellite path wiring ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_qr_with_data() -> QueryResponse:
    """Build a QueryResponse with inline tabular data (3 rows)."""
    table = PandasTable(
        columns=["order_id", "total", "status"],
        rows=[
            [101, 99.5, "shipped"],
            [102, 149.0, "pending"],
            [103, 199.95, "delivered"],
        ],
    )
    dataset = QueryDataset(
        data=table,
        columns=["order_id", "total", "status"],
        row_count=3,
    )
    return QueryResponse(
        explanation="Retrieved 3 recent orders grouped by status.",
        query="SELECT order_id, total, status FROM orders LIMIT 3",
        data=dataset,
    )


def _mock_llm_returning(qr: QueryResponse) -> MagicMock:
    """Create a mock LLM client that returns an AIMessage wrapping *qr*."""
    client = MagicMock()
    response = MagicMock(
        spec=AIMessage,
        is_structured=True,
        output=qr,
        response="ok",
        data=None,
        session_id=None,
        output_mode=None,
        artifacts=[],
        artifact_id=None,
        a2ui_envelope=None,
        code=None,
        content=None,
    )
    client.ask = AsyncMock(return_value=response)
    return client


# ── Tests ──────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_ask_structured_table_invokes_renderer_and_mints_artifact(
    fake_postgres_toolkit,
):
    """Issue #1269: ask(output_mode=STRUCTURED_TABLE) must invoke the renderer.

    After the fix, the renderer converts response.output from a QueryResponse
    BaseModel into a dict with 'columns', sets response.a2ui_envelope, and
    attach_structured_artifact() successfully mints an artifacts[] entry.
    """
    qr = _make_qr_with_data()
    mock_llm = _mock_llm_returning(qr)

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    agent._llm = mock_llm

    msg = await agent.ask(
        "list orders",
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    # 1. output_mode is STRUCTURED_TABLE
    assert msg.output_mode == OutputMode.STRUCTURED_TABLE

    # 2. response.output is now a dict (StructuredTableConfig minus data)
    assert isinstance(msg.output, dict), (
        f"response.output should be a dict after renderer, got {type(msg.output)}"
    )
    assert "columns" in msg.output, "Renderer must produce a 'columns' key"

    # 3. response.data is now canonical list[dict] rows (not a DataFrame)
    assert isinstance(msg.data, list), (
        f"response.data should be list[dict] after renderer, got {type(msg.data)}"
    )
    assert len(msg.data) == 3
    assert msg.data[0]["order_id"] == 101

    # 4. An artifact was minted
    assert len(msg.artifacts) >= 1, "attach_structured_artifact must mint an artifact"
    art = msg.artifacts[0]
    assert art["type"] == "table"
    assert "artifactId" in art

    # 5. artifact_id was set
    assert msg.artifact_id is not None


@satellite_available
@pytest.mark.asyncio
async def test_ask_structured_table_sets_a2ui_envelope(
    fake_postgres_toolkit,
):
    """The renderer's _emit_a2ui_envelope populates response.a2ui_envelope."""
    qr = _make_qr_with_data()
    mock_llm = _mock_llm_returning(qr)

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    agent._llm = mock_llm

    msg = await agent.ask(
        "list orders",
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    # a2ui_envelope should be populated by the renderer
    assert msg.a2ui_envelope is not None, (
        "Renderer must populate response.a2ui_envelope via _emit_a2ui_envelope"
    )
    assert "createSurface" in msg.a2ui_envelope


@satellite_available
@pytest.mark.asyncio
async def test_ask_structured_table_v2_artifact_has_surface_id(
    fake_postgres_toolkit,
):
    """With a2ui_envelope present, the artifact uses the v2 schema (surfaceId)."""
    qr = _make_qr_with_data()
    mock_llm = _mock_llm_returning(qr)

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    agent._llm = mock_llm

    msg = await agent.ask(
        "list orders",
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    assert len(msg.artifacts) >= 1
    art = msg.artifacts[0]
    assert "surfaceId" in art, "v2 artifact must have surfaceId"
    assert art.get("schemaVersion") == 2
    assert art["surfaceId"] == art["artifactId"]


@satellite_available
@pytest.mark.asyncio
async def test_ask_structured_table_degrades_on_renderer_failure(
    fake_postgres_toolkit,
):
    """When the renderer fails, the mode degrades to SQL_ANALYSIS."""
    qr = _make_qr_with_data()
    # Sabotage data so the renderer returns (None, error_msg)
    qr.data.data = None
    qr.data.row_count = 0
    mock_llm = _mock_llm_returning(qr)

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    agent._llm = mock_llm

    msg = await agent.ask(
        "list orders",
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    # Should degrade to SQL_ANALYSIS — not crash
    assert msg.output_mode == OutputMode.SQL_ANALYSIS


@satellite_available
@pytest.mark.asyncio
async def test_ask_structured_table_preserves_explanation(
    fake_postgres_toolkit,
):
    """The renderer's explanation is preserved in response.response."""
    qr = _make_qr_with_data()
    mock_llm = _mock_llm_returning(qr)

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    agent._llm = mock_llm

    msg = await agent.ask(
        "list orders",
        output_mode=OutputMode.STRUCTURED_TABLE,
    )

    assert msg.response == "Retrieved 3 recent orders grouped by status."


@pytest.mark.asyncio
async def test_sql_analysis_path_unchanged(
    fake_postgres_toolkit,
):
    """Default path (no output_mode) still produces SQL_ANALYSIS."""
    qr = _make_qr_with_data()
    mock_llm = _mock_llm_returning(qr)

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])
    await agent.configure()
    agent._llm = mock_llm

    msg = await agent.ask("list orders")

    # Default path: SQL_ANALYSIS, no artifact
    assert msg.output_mode == OutputMode.SQL_ANALYSIS
    assert len(msg.artifacts) == 0
