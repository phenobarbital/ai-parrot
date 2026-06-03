"""Tests for FEAT-218: StructuredTableConfig + OutputMode.STRUCTURED_TABLE.

TASK-1429: OutputMode.STRUCTURED_TABLE enum member + TableColumn + StructuredTableConfig.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — OutputMode.STRUCTURED_TABLE enum member
# ─────────────────────────────────────────────────────────────────────────────


def test_enum_member():
    """OutputMode.STRUCTURED_TABLE exists with the correct string value."""
    from parrot.models.outputs import OutputMode

    assert OutputMode.STRUCTURED_TABLE == "structured_table"
    assert OutputMode("structured_table") is OutputMode.STRUCTURED_TABLE


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — TableColumn model
# ─────────────────────────────────────────────────────────────────────────────


def test_table_column_basic():
    """TableColumn accepts name, type, title and optional format."""
    from parrot.models.outputs import TableColumn

    col = TableColumn(name="amount", type="number", title="Amount")
    assert col.name == "amount"
    assert col.type == "number"
    assert col.title == "Amount"
    assert col.format is None


def test_table_column_with_format():
    """TableColumn accepts a format hint."""
    from parrot.models.outputs import TableColumn

    col = TableColumn(name="price", type="number", title="Price", format="currency")
    assert col.format == "currency"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — StructuredTableConfig model + dump exclusion
# ─────────────────────────────────────────────────────────────────────────────


def test_data_excluded_on_dump():
    """model_dump(by_alias=True, exclude={'data'}) omits the data rows."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="a", type="number", title="A")],
        data=[{"a": 1}],
    )
    out = cfg.model_dump(by_alias=True, exclude={"data"})
    assert "data" not in out
    assert out["columns"][0]["name"] == "a"


def test_data_accessible_on_model():
    """data is accessible on the model instance even though excluded from dump."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="a", type="integer", title="A")],
        data=[{"a": 1}, {"a": 2}],
    )
    assert len(cfg.data) == 2
    assert cfg.data[0]["a"] == 1


def test_defaults():
    """explanation, total_rows, truncated default to None/False."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="x", type="string", title="X")],
        data=[{"x": "hello"}],
    )
    assert cfg.explanation is None
    assert cfg.total_rows is None
    assert cfg.truncated is False


def test_all_fields_set():
    """StructuredTableConfig accepts all optional fields."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="id", type="integer", title="ID")],
        data=[{"id": 1}],
        explanation="Fetched from orders table.",
        total_rows=1000,
        truncated=True,
    )
    assert cfg.explanation == "Fetched from orders table."
    assert cfg.total_rows == 1000
    assert cfg.truncated is True


def test_mode_json_dump_excludes_data():
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


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — @model_validator column-name check
# ─────────────────────────────────────────────────────────────────────────────


def test_validator_rejects_unknown_column():
    """column.name absent from non-empty data[0] raises ValidationError."""
    from pydantic import ValidationError
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    with pytest.raises((ValidationError, ValueError)):
        StructuredTableConfig(
            columns=[TableColumn(name="missing", type="string", title="X")],
            data=[{"a": 1}],
        )


def test_validator_accepts_matching_columns():
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


def test_validator_empty_data_skips_check():
    """Empty data list does not trigger column-name validation."""
    from parrot.models.outputs import StructuredTableConfig, TableColumn

    cfg = StructuredTableConfig(
        columns=[TableColumn(name="anything", type="any", title="Anything")],
        data=[],
    )
    assert cfg.data == []


# ─────────────────────────────────────────────────────────────────────────────
# TASK-1429 — Import smoke test
# ─────────────────────────────────────────────────────────────────────────────


def test_importable():
    """from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn works."""
    from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn  # noqa: F401

    assert OutputMode.STRUCTURED_TABLE
    assert StructuredTableConfig
    assert TableColumn
