"""Rich DataTable tests: formatting, alignment, truncation, threshold
(FEAT-493, TASK-2711)."""

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers._table_format import (
    format_cell,
    format_cell_html,
    is_numeric_column,
)
from parrot.outputs.a2ui_renderers.interactive_html import (
    InteractiveHTMLRenderer,
)
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer


class TestFormatCell:
    @pytest.mark.parametrize(
        "value,col_type,col_format,expected_fragment",
        [
            (1234567, "integer", None, "1,234,567"),
            (1234.5, "number", "currency", "1,234"),
            (0.427, "number", "percent", "%"),
            ("Sales", "string", None, "Sales"),
            ("90210", "string", None, "90210"),  # a typed string is never grouped
            (None, "number", None, ""),
        ],
    )
    def test_formatting(self, value, col_type, col_format, expected_fragment):
        assert expected_fragment in format_cell(value, col_type=col_type, col_format=col_format)

    def test_pure_no_state(self):
        """Same inputs, same output, no setup required."""
        assert format_cell(1, col_type="integer", col_format=None) == format_cell(
            1, col_type="integer", col_format=None
        )

    def test_is_numeric_column(self):
        assert is_numeric_column("integer")
        assert is_numeric_column("number")
        assert is_numeric_column("duration")
        assert not is_numeric_column("string")
        assert not is_numeric_column(None)

    def test_format_cell_html_numeric_carries_raw_data_v(self):
        td = format_cell_html(1234567, col_type="integer", col_format=None)
        assert td == '<td class="num" data-v="1234567">1,234,567</td>'

    def test_format_cell_html_string_plain(self):
        td = format_cell_html("Sales", col_type="string", col_format=None)
        assert td == "<td>Sales</td>"

    def test_format_cell_html_escapes(self):
        td = format_cell_html("<script>alert(1)</script>", col_type="string", col_format=None)
        assert "<script>" not in td
        assert "&lt;script&gt;" in td


def _table_envelope(*, columns, rows, title=None, total_rows=None, truncated=False, extra_props=None) -> CreateSurface:
    props = {"columns": columns, "data": {"path": "/rows"}}
    if title is not None:
        props["title"] = title
    if total_rows is not None:
        props["totalRows"] = total_rows
    if truncated:
        props["truncated"] = True
    if extra_props:
        props.update(extra_props)
    return CreateSurface(
        surfaceId="s",
        catalogId="c",
        components=[Component(id="root", component="DataTable", **props)],
        dataModel={"rows": rows},
    )


RENDERERS = [InteractiveHTMLRenderer, SSRHTMLRenderer]


@pytest.mark.parametrize("renderer_cls", RENDERERS)
class TestRichTableMarkup:
    async def test_numeric_columns_formatted_and_aligned(self, renderer_cls):
        env = _table_envelope(
            columns=[{"name": "region", "type": "string"}, {"name": "rev", "type": "integer"}],
            rows=[{"region": "EU", "rev": 1234567}],
        )
        doc = (await renderer_cls().render(env)).content.decode()
        assert "1,234,567" in doc
        assert 'class="num"' in doc or "a2ui-cell num" in doc

    async def test_raw_value_in_data_v(self, renderer_cls):
        env = _table_envelope(
            columns=[{"name": "rev", "type": "integer"}],
            rows=[{"rev": 1234567}],
        )
        doc = (await renderer_cls().render(env)).content.decode()
        assert 'data-v="1234567"' in doc

    async def test_string_column_not_numeric(self, renderer_cls):
        env = _table_envelope(
            columns=[{"name": "zip", "type": "string"}],
            rows=[{"zip": "90210"}],
        )
        doc = (await renderer_cls().render(env)).content.decode()
        assert "90210" in doc
        assert 'data-v="90210"' not in doc

    async def test_truncation_notice_rendered(self, renderer_cls):
        env = _table_envelope(
            columns=[{"name": "region", "type": "string"}],
            rows=[{"region": "EU"}, {"region": "APAC"}],
            total_rows=10,
            truncated=True,
        )
        doc = (await renderer_cls().render(env)).content.decode()
        assert "showing 2 of 10 rows" in doc

    async def test_no_truncation_notice_when_not_truncated(self, renderer_cls):
        env = _table_envelope(
            columns=[{"name": "region", "type": "string"}],
            rows=[{"region": "EU"}],
        )
        doc = (await renderer_cls().render(env)).content.decode()
        assert "a2ui-table-notice" not in doc


class TestPaginationThreshold:
    def _rows(self, n):
        return [{"region": f"R{i}"} for i in range(n)]

    async def test_no_pager_below_threshold(self):
        # Checked against the concrete rendered elements, not a bare
        # substring — `_BEHAVIOR_JS` always embeds the literal
        # `[data-table-search]` selector text regardless of row count.
        env = _table_envelope(columns=[{"name": "region", "type": "string"}], rows=self._rows(8))
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert "<input" not in doc
        assert 'class="a2ui-table-pager"' not in doc

    async def test_pager_above_threshold(self):
        env = _table_envelope(columns=[{"name": "region", "type": "string"}], rows=self._rows(101))
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert '<input type="search"' in doc
        assert 'class="a2ui-table-pager"' in doc


class TestTotalAndGroupRows:
    async def test_total_row_class(self):
        env = _table_envelope(
            columns=[{"name": "region", "type": "string"}, {"name": "rev", "type": "integer"}],
            rows=[{"region": "EU", "rev": 10}, {"region": "Total", "rev": 10, "_rowType": "total"}],
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert 'class="total-row"' in doc

    async def test_group_row_class(self):
        env = _table_envelope(
            columns=[{"name": "region", "type": "string"}],
            rows=[{"region": "EMEA", "_rowType": "group"}, {"region": "EU"}],
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert 'class="group-row"' in doc


class TestSSRWithoutJS:
    async def test_ssr_output_formatted_without_js(self):
        env = _table_envelope(
            columns=[{"name": "region", "type": "string"}, {"name": "rev", "type": "integer"}],
            rows=[{"region": "EU", "rev": 1234567}],
        )
        doc = (await SSRHTMLRenderer().render(env)).content.decode()
        assert "1,234,567" in doc
        assert "<script" not in doc


class TestExistingSortHooksPreserved:
    """Guard: test_interactive_html.py's pre-existing table assertions still hold."""

    async def test_sort_hooks_and_plain_cells_unmodified(self):
        env = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="root",
                    component="DataTable",
                    title="Ledger",
                    columns=[{"name": "division", "title": "Division"}, {"name": "rev"}],
                    data={"path": "/rows"},
                )
            ],
            dataModel={"rows": [{"division": "Sales", "rev": 100}, {"division": "Ops", "rev": 50}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()

        assert "data-sort-table" in doc
        assert 'data-sort-key="division"' in doc
        assert 'data-sort-key="rev"' in doc
        assert "Sales" in doc and "Ops" in doc
        assert "<table" in doc
