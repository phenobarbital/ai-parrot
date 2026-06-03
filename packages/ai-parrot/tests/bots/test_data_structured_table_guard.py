"""Tests for FEAT-218 TASK-1432: data.py override-guard for STRUCTURED_TABLE.

Verifies that the FEAT-215 override-guard (which skips overwriting response.data
for STRUCTURED_CHART) has been extended to also skip for STRUCTURED_TABLE.

The guard lives at bots/data.py:~1620-1630.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# Locate data.py relative to this test file's tree root.
# When running from the worktree, the source tree is under:
#   packages/ai-parrot/src/parrot/bots/data.py
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parents[3]  # tests/bots → tests → ai-parrot → packages → repo root
_DATA_PY = _REPO_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "bots" / "data.py"


def _read_data_py() -> str:
    """Read data.py source from the repo tree (worktree-aware path resolution)."""
    assert _DATA_PY.exists(), f"data.py not found at {_DATA_PY}"
    return _DATA_PY.read_text(encoding="utf-8")


def test_guard_skips_structured_table():
    """data.py guard condition includes STRUCTURED_TABLE."""
    source = _read_data_py()
    assert "OutputMode.STRUCTURED_TABLE" in source, (
        "OutputMode.STRUCTURED_TABLE must appear in bots/data.py "
        "(override-guard extension is missing)"
    )
    assert "output_mode != OutputMode.STRUCTURED_TABLE" in source, (
        "The guard condition 'output_mode != OutputMode.STRUCTURED_TABLE' "
        "must exist in bots/data.py"
    )


def test_guard_condition_adjacent_to_structured_chart():
    """The STRUCTURED_TABLE guard is adjacent to the STRUCTURED_CHART guard."""
    source = _read_data_py()
    chart_pos = source.find("output_mode != OutputMode.STRUCTURED_CHART")
    table_pos = source.find("output_mode != OutputMode.STRUCTURED_TABLE")

    assert chart_pos != -1, "STRUCTURED_CHART guard must be present"
    assert table_pos != -1, "STRUCTURED_TABLE guard must be present"
    # They must be close together (within 400 chars) in the same if-block
    assert abs(chart_pos - table_pos) < 400, (
        "STRUCTURED_TABLE guard must be adjacent to STRUCTURED_CHART guard "
        f"(chart_pos={chart_pos}, table_pos={table_pos})"
    )


def test_output_mode_structured_table_importable():
    """OutputMode.STRUCTURED_TABLE is importable (sanity check)."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_TABLE == "structured_table"


def test_guard_skips_structured_chart_still():
    """Regression: STRUCTURED_CHART guard must still be present after modification."""
    source = _read_data_py()
    assert "output_mode != OutputMode.STRUCTURED_CHART" in source, (
        "STRUCTURED_CHART guard must NOT be removed by FEAT-218 change"
    )
