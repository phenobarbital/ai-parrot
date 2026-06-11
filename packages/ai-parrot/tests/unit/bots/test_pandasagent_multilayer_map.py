"""Unit tests for PandasAgent's multi-layer STRUCTURED_MAP fallback.

Regression coverage for the bug where the agent produced SEVERAL result
DataFrames in one turn (e.g. one layer per distance band so each could be
colored differently). ``_inject_multi_data_from_variables`` then sets
``response.data`` to a list of ``DatasetResult`` dicts, and the single-DataFrame
STRUCTURED_MAP fallback skipped it — leaving the renderer to reject the list
("response.data must be a SpatialResult, got list").

These tests exercise the pure helper ``_spatial_result_from_datasets``, which
merges the per-dataset payloads into one multi-layer ``SpatialResult``.
"""
import logging
import types

import pytest

try:
    from parrot.bots.data import PandasAgent
except Exception:  # pragma: no cover - env-dependent
    PandasAgent = None


pytestmark = pytest.mark.skipif(
    PandasAgent is None, reason="parrot.bots.data not importable in this environment"
)


def _bind():
    """Bind the multi-layer helpers to a minimal object with a logger.

    ``_spatial_result_from_datasets`` only touches ``self.logger`` and (for the
    flat-list fallback) ``self._spatial_result_from_dataframe``.
    """
    ns = types.SimpleNamespace()
    ns.logger = logging.getLogger("test_multilayer_map")
    ns._spatial_result_from_dataframe = types.MethodType(
        PandasAgent._spatial_result_from_dataframe, ns
    )
    ns._spatial_result_from_datasets = types.MethodType(
        PandasAgent._spatial_result_from_datasets, ns
    )
    return ns


def _dataset(name, rows):
    """Build a DatasetResult-shaped dict (the shape _inject_multi produces)."""
    return {
        "name": name,
        "variable": name,
        "data": rows,
        "shape": (len(rows), len(rows[0]) if rows else 0),
        "columns": list(rows[0].keys()) if rows else [],
    }


# ---------------------------------------------------------------------------
# Happy path — multiple mappable datasets become multiple layers
# ---------------------------------------------------------------------------

def test_multi_dataset_builds_multilayer_result():
    ns = _bind()
    datasets = [
        _dataset("band_0_20", [
            {"name": "K1", "latitude": 33.4, "longitude": -112.0, "dist": 5},
            {"name": "K2", "latitude": 33.5, "longitude": -112.1, "dist": 12},
        ]),
        _dataset("band_20_40", [
            {"name": "K3", "latitude": 33.7, "longitude": -112.3, "dist": 30},
        ]),
    ]

    result = ns._spatial_result_from_datasets(datasets)

    assert result is not None
    assert set(result.layers.keys()) == {"band_0_20", "band_20_40"}
    assert len(result.layers["band_0_20"].features) == 2
    assert len(result.layers["band_20_40"].features) == 1
    # Layer discriminator is preserved.
    assert result.layers["band_0_20"].layer == "band_0_20"


def test_unmappable_dataset_is_skipped_others_kept():
    """A dataset without coordinates is dropped; mappable ones survive."""
    ns = _bind()
    datasets = [
        _dataset("geo", [{"name": "K1", "latitude": 33.4, "longitude": -112.0}]),
        _dataset("no_geo", [{"name": "X", "revenue": 100}]),  # no lat/lon
    ]

    result = ns._spatial_result_from_datasets(datasets)

    assert result is not None
    assert set(result.layers.keys()) == {"geo"}
    assert len(result.layers["geo"].features) == 1


# ---------------------------------------------------------------------------
# Flat list fallback — a list of plain row dicts becomes a single layer
# ---------------------------------------------------------------------------

def test_flat_row_list_becomes_single_layer():
    ns = _bind()
    rows = [
        {"name": "K1", "latitude": 33.4, "longitude": -112.0},
        {"name": "K2", "latitude": 33.5, "longitude": -112.1},
    ]

    result = ns._spatial_result_from_datasets(rows)

    assert result is not None
    total = sum(len(lyr.features) for lyr in result.layers.values())
    assert total == 2


# ---------------------------------------------------------------------------
# Degenerate inputs — never raise, return None
# ---------------------------------------------------------------------------

def test_empty_list_returns_none():
    ns = _bind()
    assert ns._spatial_result_from_datasets([]) is None


def test_no_mappable_dataset_returns_none():
    ns = _bind()
    datasets = [_dataset("no_geo", [{"name": "X", "revenue": 100}])]
    assert ns._spatial_result_from_datasets(datasets) is None


def test_dataset_with_empty_rows_returns_none():
    ns = _bind()
    datasets = [_dataset("empty", [])]
    assert ns._spatial_result_from_datasets(datasets) is None
