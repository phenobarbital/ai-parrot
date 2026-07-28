"""Shared payload fixtures for the compression test suite."""
import pytest


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
