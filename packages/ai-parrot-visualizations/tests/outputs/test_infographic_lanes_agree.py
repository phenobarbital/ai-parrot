"""One fixture, two lanes: A2UI envelope props AND infographic-HTML strings agree (FEAT-623)."""

from __future__ import annotations

from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope
from parrot.outputs.a2ui_renderers._table_format import format_cell
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


def _fixture() -> InfographicResponse:
    return InfographicResponse(
        template="basic",
        blocks=[
            {"type": "title", "title": "Hints"},
            {"type": "hero_card", "label": "Revenue", "value": 1203456, "format": "currency"},
            {
                "type": "table",
                "columns": [
                    {"header": "Plan"},
                    {"header": "MRR", "type": "number", "format": "currency"},
                    {"header": "Churn", "type": "number", "format": "percent"},
                ],
                "rows": [["Pro", 1234.5, 0.683]],
            },
            {"type": "progress", "title": "Goal completion", "items": [{"label": "NPS", "value": 90.4, "target": 80}]},
            {
                "type": "chart",
                "chart_type": "bar",
                "labels": ["Jan", "Feb"],
                "series": [{"name": "MRR", "values": [1, 2]}, {"name": "New", "values": [3, 4], "axis": "right"}],
                "y_axis_labels": ["MRR (USD)", "New MRR (USD)"],
            },
        ],
    )


def test_infographic_lanes_agree():
    response = _fixture()
    envelope = infographic_response_to_envelope(response)
    sections = envelope.components[0].model_extra["sections"]
    assert len(sections) == 1
    hero, table, progress, chart = (c["properties"] if "properties" in c else c for c in sections[0]["components"])

    html = InfographicHTMLRenderer().render_to_html(response)

    # Hero: envelope carries the raw number + format; HTML prints the shared formatter's string.
    assert hero["value"] == 1203456 and hero["format"] == "currency"
    expected_hero = format_cell(hero["value"], col_type="number", col_format=hero["format"])
    assert expected_hero == "$1,203,456.00" and expected_hero in html

    # Table: typed columns on the wire; formatted, same strings in HTML.
    assert [(c.get("type"), c.get("format")) for c in table["columns"]] == [
        (None, None),
        ("number", "currency"),
        ("number", "percent"),
    ]
    assert "$1,234.50" in html and "68.3%" in html

    # Progress: ratio + percent in the envelope; HTML shows the goal title and a target marker.
    assert progress["children"][0]["properties"]["text"] == "Goal completion"
    kpi = progress["children"][1]["properties"]["children"][0]["properties"]
    assert kpi["value"] == 0.904 and kpi["format"] == "percent" and kpi["comparisonPeriod"] == "vs 80% target"
    assert "Goal completion" in html and "progress-target" in html

    # Chart: seriesAxes on the wire; second yAxis + yAxisIndex in the ECharts option.
    assert chart["seriesAxes"] == ["left", "right"]
    assert chart["yAxisLabels"] == ["MRR (USD)", "New MRR (USD)"]
    assert '"yAxisIndex":1' in html.replace(" ", "")
    assert "New MRR (USD)" in html
