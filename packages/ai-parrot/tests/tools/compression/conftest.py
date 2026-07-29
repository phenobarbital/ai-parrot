"""Shared payload + ToolManager fixtures for the compression test suite."""
import pytest

from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory import WorkingMemoryToolkit


@pytest.fixture
def row_oriented_payload():
    """500 rows x 12 cols, 2 constant columns, 1 all-null column, mixed types."""
    return [
        {
            "store_id": f"S{i:04d}", "revenue": 1000.0 + i, "region": "south",
            "active": True, "notes": None,
            **{f"c{j}": (i * j) % 7 for j in range(7)},
        }
        for i in range(500)
    ]


@pytest.fixture
def heterogeneous_payload():
    """Rows with mostly-disjoint key sets (union/intersection ratio high)."""
    return [{f"k{i}": i, "shared": 1} for i in range(30)]


# -- e2e fixtures (TASK-1958) -------------------------------------------------

def _query_result_payload(rows: list[dict]) -> dict:
    """QueryResult-shaped dict (databasequery/base.py:148); `columns` here
    is the SIBLING QueryResult field (list of column NAMES as strings),
    deliberately left empty in these fixtures — distinct from the nested
    `rows -> {"columns": [...]}` the columnar codec produces after
    compression."""
    return {
        "driver": "pg", "rows": rows, "row_count": len(rows),
        "columns": [], "execution_time_ms": 1.0,
    }


BULKY_PAYLOAD = {"a": 1, "b": None, "rows": [{"x": i, "y": None} for i in range(5)]}


class DQExecuteTool(AbstractTool):
    """Stand-in for `DatabaseQueryToolkit.execute_database_query`,
    registered under the toolkit's REAL runtime name
    (`dq_execute_database_query` — verified: `tool_prefix="dq"` at
    `databasequery/toolkit.py:147`), so it naturally matches the core
    manifest's `columnar`/`NORMAL`/`tee=true` entry (TASK-1954) with zero
    registry overrides."""

    name = "dq_execute_database_query"
    description = "Stand-in DatabaseQueryToolkit.execute_database_query for e2e tests."

    def __init__(self, rows: list[dict], **kwargs):
        super().__init__(**kwargs)
        self._rows = rows

    async def _execute(self, **kwargs):
        return _query_result_payload(self._rows)


class PlainBulkyTool(AbstractTool):
    """Plain `AbstractTool` route (G1's first of two routes)."""

    name = "plain_bulky_tool"
    description = "Plain AbstractTool route, bulky payload with nulls."

    async def _execute(self, **kwargs):
        return dict(BULKY_PAYLOAD)


class BulkyToolkit(AbstractToolkit):
    """`ToolkitTool` route (G1's second route) — identical payload shape
    to :class:`PlainBulkyTool`, so the two routes' compression metadata
    can be compared directly."""

    async def toolkit_bulky_tool(self) -> dict:
        """Return the same bulky payload shape as plain_bulky_tool."""
        return dict(BULKY_PAYLOAD)


def _build_tool_manager(*, with_wm: bool, row_oriented_payload: list[dict]) -> ToolManager:
    tm = ToolManager(include_search_tool=False)
    tm.register_tool(DQExecuteTool(row_oriented_payload))
    tm.register_tool(PlainBulkyTool())
    tm.register_toolkit(BulkyToolkit())
    if with_wm:
        tm.register_toolkit(WorkingMemoryToolkit())
    return tm


@pytest.fixture
def tool_manager_with_wm(row_oriented_payload):
    """ToolManager with a WorkingMemoryToolkit registered (tee-capable)."""
    return _build_tool_manager(with_wm=True, row_oriented_payload=row_oriented_payload)


@pytest.fixture
def tool_manager_without_wm(row_oriented_payload):
    """ToolManager without working memory -> tee degradation path."""
    return _build_tool_manager(with_wm=False, row_oriented_payload=row_oriented_payload)


@pytest.fixture
def compressors_toml(tmp_path):
    """Project-level .parrot/compressors.toml with exact/glob/wildcard entries."""
    d = tmp_path / ".parrot"
    d.mkdir()
    (d / "compressors.toml").write_text(
        '[compressor."dq_execute_database_query"]\n'
        'codec = "columnar"\nlevel = "normal"\ntee = true\n'
        '  [compressor."dq_execute_database_query".params]\n'
        '  min_rows = 20\n'
        '[compressor."execute_db_*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
        '[compressor."*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
    )
    return tmp_path
