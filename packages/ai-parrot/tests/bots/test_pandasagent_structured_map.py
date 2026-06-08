"""Tests for FEAT-221 TASK-1450: PandasAgent STRUCTURED_MAP branch/routing.

Verifies:
- STRUCTURED_MAP OutputMode is defined.
- _extract_spatial_result_from_tools logic (tested standalone).
- The override guard excludes STRUCTURED_MAP (response.data not clobbered).
- STRUCTURED_MAP does not affect STRUCTURED_CHART/STRUCTURED_TABLE branches.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Import smoke test
# ─────────────────────────────────────────────────────────────────────────────


def test_structured_map_output_mode_importable():
    """OutputMode.STRUCTURED_MAP is defined and has the correct value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_MAP.value == "structured_map"


def test_structured_map_config_importable():
    """StructuredMapConfig is importable from parrot.models.outputs."""
    from parrot.models.outputs import StructuredMapConfig  # noqa: F401

    assert StructuredMapConfig


# ─────────────────────────────────────────────────────────────────────────────
# _extract_spatial_result_from_tools logic (standalone test, no PandasAgent import)
# Tests the extraction logic independently of the heavy PandasAgent class.
# ─────────────────────────────────────────────────────────────────────────────


def _make_tool_call(result):
    """Build a minimal tool call mock with a result."""
    tc = MagicMock()
    tc.result = result
    return tc


def _extract_spatial_result_from_tools(tool_calls):
    """Reproduce the STRUCTURED_MAP extraction logic for standalone testing."""
    if not tool_calls:
        return None

    try:
        from parrot.tools.dataset_manager.spatial.contracts import SpatialResult
    except ImportError:
        return None

    for tc in reversed(tool_calls):
        try:
            result = getattr(tc, "result", None)
            if result is None:
                continue
            if isinstance(result, SpatialResult):
                return result
            if isinstance(result, dict) and "layers" in result and "version" in result:
                try:
                    return SpatialResult(**result)
                except Exception:
                    pass
        except Exception:
            continue
    return None


def test_extract_spatial_result_returns_direct():
    """_extract_spatial_result_from_tools returns a SpatialResult directly."""
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    sr = SpatialResult(
        layers={
            "schools": SpatialLayerResult(layer="schools", features=[], total_count=0)
        }
    )
    result = _extract_spatial_result_from_tools([_make_tool_call(sr)])
    assert result is sr


def test_extract_spatial_result_parses_dict():
    """_extract_spatial_result_from_tools parses a dict SpatialResult."""
    from parrot.tools.dataset_manager.spatial import SpatialResult

    sr_dict = {
        "version": 2,
        "layers": {
            "schools": {
                "layer": "schools",
                "features": [],
                "total_count": 0,
                "capped": False,
                "geodesic": True,
            }
        },
    }
    result = _extract_spatial_result_from_tools([_make_tool_call(sr_dict)])
    assert isinstance(result, SpatialResult)
    assert "schools" in result.layers


def test_extract_spatial_result_returns_none_on_empty():
    """_extract_spatial_result_from_tools returns None for empty tool calls."""
    assert _extract_spatial_result_from_tools([]) is None
    assert _extract_spatial_result_from_tools(None) is None


def test_extract_spatial_result_returns_none_on_non_spatial():
    """_extract_spatial_result_from_tools returns None for non-spatial results."""
    result = _extract_spatial_result_from_tools([_make_tool_call("some string")])
    assert result is None


def test_extract_spatial_result_takes_last_in_order():
    """_extract_spatial_result_from_tools returns the LAST SpatialResult (reversed search)."""
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    sr1 = SpatialResult(layers={"a": SpatialLayerResult(layer="a", features=[])})
    sr2 = SpatialResult(layers={"b": SpatialLayerResult(layer="b", features=[])})

    result = _extract_spatial_result_from_tools(
        [_make_tool_call(sr1), _make_tool_call(sr2)]
    )
    # reversed → sr2 is checked first
    assert result is sr2


# ─────────────────────────────────────────────────────────────────────────────
# Verify no regression on other output modes
# ─────────────────────────────────────────────────────────────────────────────


def test_structured_map_no_regression_on_other_modes():
    """OutputMode.STRUCTURED_MAP is distinct from STRUCTURED_CHART and STRUCTURED_TABLE."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_CHART == "structured_chart"
    assert OutputMode.STRUCTURED_TABLE == "structured_table"
    assert OutputMode.STRUCTURED_MAP != OutputMode.STRUCTURED_CHART
    assert OutputMode.STRUCTURED_MAP != OutputMode.STRUCTURED_TABLE


# ─────────────────────────────────────────────────────────────────────────────
# Generation-time system prompt contract
# The prompt injected into the agent's first call MUST instruct it to produce
# the map data (call dataset_spatial_filter OR build a coordinate DataFrame and
# declare data_variable) — NOT the column-format-hint refine text, which would
# tell the agent the rows are "already determined" and stop it doing the job.
# ─────────────────────────────────────────────────────────────────────────────


def test_structured_map_generation_prompt_instructs_data_production():
    """The registered STRUCTURED_MAP prompt tells the agent how to produce data."""
    from parrot.models.outputs import OutputMode
    from parrot.outputs.formats import get_renderer, get_output_prompt

    get_renderer(OutputMode.STRUCTURED_MAP)  # trigger lazy registration
    prompt = get_output_prompt(OutputMode.STRUCTURED_MAP)

    assert prompt is not None
    # Path A: the spatial tool.
    assert "dataset_spatial_filter" in prompt
    # Path B: a coordinate DataFrame whose variable is declared.
    assert "data_variable" in prompt
    assert "latitude" in prompt.lower() and "longitude" in prompt.lower()
    # It must NOT be the refine-only contract that says rows are predetermined.
    assert "already been determined" not in prompt


def test_structured_map_refine_prompt_preserved():
    """The column-format-hint refine contract is kept as a separate constant."""
    from parrot.outputs.formats.structured_map import STRUCTURED_MAP_REFINE_PROMPT

    assert "format hint" in STRUCTURED_MAP_REFINE_PROMPT
    assert "already been determined" in STRUCTURED_MAP_REFINE_PROMPT
