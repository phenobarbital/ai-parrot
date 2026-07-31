"""Unit tests for AC 1.5 element models."""
import pytest
from pydantic import ValidationError


class TestTextBlock:
    def test_minimal(self):
        from parrot.outputs.cards.elements import TextBlock
        tb = TextBlock(text="hello")
        assert tb.element_type == "TextBlock"
        assert tb.text == "hello"
        assert tb.wrap is True
        assert tb.is_visible is True

    def test_all_properties(self):
        from parrot.outputs.cards.elements import TextBlock
        tb = TextBlock(
            text="title",
            weight="Bolder",
            size="Large",
            color="Good",
            font_type="Monospace",
            is_subtle=True,
            horizontal_alignment="Center",
            spacing="Medium",
            separator=True,
            max_lines=3,
            id="tb1",
            is_visible=False,
        )
        assert tb.weight == "Bolder"
        assert tb.id == "tb1"
        assert tb.is_visible is False

    def test_invalid_weight_rejected(self):
        from parrot.outputs.cards.elements import TextBlock
        with pytest.raises(ValidationError):
            TextBlock(text="x", weight="SuperBold")


class TestImage:
    def test_minimal(self):
        from parrot.outputs.cards.elements import Image
        img = Image(url="https://example.com/img.png")
        assert img.element_type == "Image"
        assert img.url == "https://example.com/img.png"
        assert img.alt_text == ""

    def test_data_uri(self):
        from parrot.outputs.cards.elements import Image
        img = Image(url="data:image/png;base64,abc123", alt_text="chart")
        assert img.url.startswith("data:image/")


class TestTable:
    def test_structure(self):
        from parrot.outputs.cards.elements import (
            Table, TableColumnDefinition, TableRow, TableCell, TextBlock,
        )
        table = Table(
            columns=[TableColumnDefinition(width="1"), TableColumnDefinition(width="2")],
            rows=[
                TableRow(cells=[
                    TableCell(items=[TextBlock(text="a")]),
                    TableCell(items=[TextBlock(text="b")]),
                ]),
            ],
        )
        assert table.element_type == "Table"
        assert table.first_row_as_header is True
        assert len(table.rows) == 1
        assert len(table.rows[0].cells) == 2

    def test_empty_table(self):
        from parrot.outputs.cards.elements import Table
        table = Table(columns=[], rows=[])
        assert table.rows == []


class TestContainer:
    def test_with_children(self):
        from parrot.outputs.cards.elements import Container, TextBlock
        c = Container(
            items=[TextBlock(text="inner")],
            style="Emphasis",
            id="c1",
            is_visible=False,
        )
        assert c.element_type == "Container"
        assert len(c.items) == 1
        assert c.is_visible is False


class TestColumnSet:
    def test_with_columns(self):
        from parrot.outputs.cards.elements import ColumnSet, Column, TextBlock
        cs = ColumnSet(
            columns=[
                Column(width="stretch", items=[TextBlock(text="col1")]),
                Column(width="auto", items=[TextBlock(text="col2")]),
            ],
        )
        assert cs.element_type == "ColumnSet"
        assert len(cs.columns) == 2


class TestFactSet:
    def test_facts(self):
        from parrot.outputs.cards.elements import FactSet, Fact
        fs = FactSet(facts=[
            Fact(title="Revenue", value="$1M"),
            Fact(title="Growth", value="+12%"),
        ])
        assert fs.element_type == "FactSet"
        assert len(fs.facts) == 2
