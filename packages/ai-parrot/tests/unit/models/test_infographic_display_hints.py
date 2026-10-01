"""Display-hint fields on infographic blocks (FEAT-623, TASK-3994)."""
import pytest
from pydantic import ValidationError

from parrot.models.infographic import (
    ChartBlock,
    ChartDataSeries,
    ColumnDef,
    HeroCardBlock,
    TableBlock,
)


def test_columndef_accepts_type_format():
    col = ColumnDef(header="MRR", type="number", format="currency")
    assert col.type == "number" and col.format == "currency"
    bare = ColumnDef(header="Name")
    assert bare.type is None and bare.format is None


def test_hero_value_str_or_number():
    assert HeroCardBlock(label="R", value="$3.7M").value == "$3.7M"
    assert HeroCardBlock(label="R", value=1203456, format="currency").value == 1203456
    zero = HeroCardBlock(label="R", value=0.0, format="number", unit="visits")
    assert zero.value == 0 and zero.unit == "visits"
    assert HeroCardBlock(label="R").value == ""


def test_hero_format_rejects_unknown():
    with pytest.raises(ValidationError):
        HeroCardBlock(label="R", value=1, format="compact")


def test_series_axis_literal():
    assert ChartDataSeries(name="a", values=[1], axis="right").axis == "right"
    assert ChartDataSeries(name="a", values=[1]).axis is None
    with pytest.raises(ValidationError):
        ChartDataSeries(name="a", values=[1], axis="middle")


def test_chart_y_axis_labels_and_series_axis_survive_normalizer():
    block = ChartBlock(
        chart_type="bar",
        labels=["a", "b"],
        series=[
            {"name": "x", "values": [1, 2]},
            {"name": "y", "data": [3, 4], "axis": "right"},
        ],
        y_axis_labels=["Left", None],
    )
    assert block.series[1].axis == "right"
    assert block.series[1].values == [3, 4]
    assert block.y_axis_labels == ["Left", None]


def test_table_columndef_hints_survive_normalizer():
    block = TableBlock(
        columns=[
            {"header": "MRR", "type": "number", "format": "currency"},
            {"header": "Name"},
        ],
        rows=[[1.5, "a"]],
    )
    assert block.columns[0].type == "number"
    assert block.columns[0].format == "currency"
    assert block.columns[1].type is None


def test_old_payloads_unchanged():
    table = TableBlock(columns=["A", "B"], rows=[["x", "y"]])
    assert table.columns == ["A", "B"]
    dumped = ChartDataSeries(name="n", values=[1]).model_dump()
    assert dumped == {"name": "n", "values": [1], "color": None, "axis": None}
