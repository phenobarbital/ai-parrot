"""Tests for the ``InfographicResponse`` → A2UI v1.0 ``CreateSurface`` adapter
(FEAT-470 TASK-2541).

Exercises the adapter against the REAL :class:`InfographicResponse` model (not
hand-rolled dicts) so a drift in either contract fails here, plus the purity,
sectioning and lossy-degradation rules the module documents.
"""

import json

import pytest
from parrot.models.infographic import InfographicResponse
from parrot.outputs.a2ui.adapters import (
    CHART_TYPE_MAP,
    infographic_response_to_envelope,
)
from parrot.outputs.a2ui.catalog import (
    ProducerOrigin,
    get_component,
    validate_envelope,
)
from parrot.outputs.a2ui.catalog import parrot as _all_parrot_components  # noqa: F401
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.models import Component, CreateSurface


def _response(**overrides) -> InfographicResponse:
    payload = {
        "template": "quarterly",
        "theme": "ocean",
        "blocks": [
            {"type": "title", "title": "Q1 Overview", "subtitle": "Financials"},
            {"type": "summary", "content": "Revenue grew across every region."},
            {"type": "hero_card", "label": "Revenue", "value": "$1.2M", "trend": "up", "trend_value": "+8%"},
            {
                "type": "chart",
                "chart_type": "bar",
                "title": "Revenue by month",
                "labels": ["Jan", "Feb"],
                "series": [
                    {"name": "2026", "values": [10, 20]},
                    {"name": "2025", "values": [8, 15]},
                ],
            },
        ],
    }
    payload.update(overrides)
    return InfographicResponse(**payload)


def _root_component(envelope) -> Component:
    assert len(envelope.components) == 1
    component = envelope.components[0]
    assert component.component == "Infographic"
    return component


def _sections(envelope) -> list:
    return _root_component(envelope).model_extra["sections"]


def _validate_full_tree(envelope):
    """Lower + flatten + validate the WHOLE tree (not just the top-level shell)."""
    component = envelope.components[0]
    tree = get_component("Infographic").component_cls().lower(component, envelope.data_model or {})
    flat = to_components(tree)
    root = Component(id="root2", component="Column", children=[c.id for c in flat])
    surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, *flat])
    validate_envelope(surface)
    return flat


class TestSurfaceShape:
    def test_emits_a_single_validated_infographic_component(self):
        envelope = infographic_response_to_envelope(_response())
        component = _root_component(envelope)
        assert component.model_extra["title"] == "Q1 Overview"
        assert component.model_extra["subtitle"] == "Financials"
        assert component.model_extra["theme"] == "ocean"
        # build_infographic validates; re-assert explicitly for the allowlist.
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)

    def test_adapter_emits_root_and_catalog_id(self):
        envelope = infographic_response_to_envelope(_response())
        assert envelope.components[0].id == "root"
        assert envelope.catalog_id == "https://parrot.dev/catalogs/v1"

    def test_adapter_output_validates(self):
        _validate_full_tree(infographic_response_to_envelope(_response()))

    def test_first_title_block_does_not_become_a_section(self):
        sections = _sections(infographic_response_to_envelope(_response()))
        assert all(s.get("heading") != "Q1 Overview" for s in sections)

    def test_title_falls_back_to_template_then_constant(self):
        no_title = InfographicResponse(template="quarterly", blocks=[{"type": "summary", "content": "x"}])
        assert _root_component(infographic_response_to_envelope(no_title)).model_extra["title"] == "quarterly"

        bare = InfographicResponse(blocks=[{"type": "summary", "content": "x"}])
        assert _root_component(infographic_response_to_envelope(bare)).model_extra["title"] == "Infographic"

    def test_explicit_title_and_theme_override_the_response(self):
        envelope = infographic_response_to_envelope(_response(), title="Override", theme="petrol")
        component = _root_component(envelope)
        assert component.model_extra["title"] == "Override"
        assert component.model_extra["theme"] == "petrol"

    def test_accepts_a_plain_mapping(self):
        envelope = infographic_response_to_envelope(
            {"blocks": [{"type": "hero_card", "label": "Users", "value": "42"}]}
        )
        assert _sections(envelope)[0]["components"][0]["component"] == "KPICard"

    def test_rejects_unsupported_input(self):
        with pytest.raises(TypeError):
            infographic_response_to_envelope(["not", "a", "response"])


class TestPurity:
    def test_same_input_yields_byte_identical_envelopes(self):
        first = infographic_response_to_envelope(_response())
        second = infographic_response_to_envelope(_response())
        assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(
            second.model_dump(mode="json"), sort_keys=True
        )

    def test_adapter_does_not_mutate_the_source_response(self):
        response = _response()
        before = response.model_dump(mode="json")
        infographic_response_to_envelope(response)
        assert response.model_dump(mode="json") == before


class TestSectioning:
    def test_later_title_block_opens_a_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "title", "title": "Doc"},
                    {"type": "title", "title": "Part Two", "subtitle": "Detail"},
                    {"type": "hero_card", "label": "A", "value": "1"},
                ]
            )
        )
        section = _sections(envelope)[0]
        assert section["heading"] == "Part Two"
        assert section["text"] == "Detail"
        assert section["components"][0]["component"] == "KPICard"

    def test_divider_opens_an_anonymous_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "hero_card", "label": "A", "value": "1"},
                    {"type": "divider"},
                    {"type": "hero_card", "label": "B", "value": "2"},
                ]
            )
        )
        sections = _sections(envelope)
        assert len(sections) == 2
        assert "heading" not in sections[1]
        assert sections[1]["components"][0]["properties"]["label"] == "B"

    def test_leading_divider_emits_no_empty_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "divider"},
                    {"type": "hero_card", "label": "A", "value": "1"},
                ]
            )
        )
        assert len(_sections(envelope)) == 1

    def test_untitled_summary_fills_section_text_then_becomes_an_infocard(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "summary", "content": "First"},
                    {"type": "summary", "content": "Second"},
                ]
            )
        )
        section = _sections(envelope)[0]
        assert section["text"] == "First"
        card = section["components"][0]
        assert card["component"] == "InfoCard"
        assert card["properties"]["body"] == "Second"

    def test_titled_summary_always_becomes_an_infocard(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "summary", "title": "Notes", "content": "Body"}])
        )
        section = _sections(envelope)[0]
        assert "text" not in section
        assert section["components"][0]["properties"]["title"] == "Notes"


class TestChartMapping:
    def test_rows_land_in_the_data_model_and_are_bound_by_pointer(self):
        envelope = infographic_response_to_envelope(_response())
        chart = _sections(envelope)[0]["components"][-1]
        assert chart["component"] == "Chart"
        assert chart["properties"]["data"] == {"path": "/charts/chart-0"}
        assert chart["properties"]["x"] == "label"
        assert chart["properties"]["y"] == ["2026", "2025"]
        assert envelope.data_model["charts"]["chart-0"] == [
            {"label": "Jan", "2026": 10, "2025": 8},
            {"label": "Feb", "2026": 20, "2025": 15},
        ]

    @pytest.mark.parametrize(
        "source",
        ["donut", "radar", "gauge", "funnel", "waterfall", "heatmap", "treemap", "area"],
    )
    def test_no_chart_type_is_collapsed_anymore(self, source):
        """FEAT-527: the A2UI Chart schema now accepts every legacy chart_type
        directly, so CHART_TYPE_MAP is the identity map — nothing degrades."""
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": source,
                        "labels": ["a"],
                        "series": [{"name": "s", "values": [1]}],
                    }
                ]
            )
        )
        assert _sections(envelope)[0]["components"][0]["properties"]["type"] == source

    def test_donut_and_radar_are_not_collapsed(self):
        for t in ("donut", "radar", "gauge", "funnel", "waterfall", "heatmap", "treemap"):
            assert CHART_TYPE_MAP[t] == t

    def test_every_mapped_type_is_in_the_a2ui_chart_enum(self):
        allowed = set(get_component("Chart").definition.schema_["properties"]["type"]["enum"])
        assert set(CHART_TYPE_MAP.values()) <= allowed

    def test_series_named_label_does_not_collide_with_the_x_column(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "labels": ["Jan"],
                        "series": [{"name": "label", "values": [7]}],
                    }
                ]
            )
        )
        chart = _sections(envelope)[0]["components"][0]["properties"]
        assert chart["y"] == ["label (2)"]
        assert envelope.data_model["charts"]["chart-0"] == [{"label": "Jan", "label (2)": 7}]

    def test_short_series_pad_with_none(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "line",
                        "labels": ["a", "b", "c"],
                        "series": [{"name": "s", "values": [1]}],
                    }
                ]
            )
        )
        rows = envelope.data_model["charts"]["chart-0"]
        assert [row["s"] for row in rows] == [1, None, None]

    def test_multiple_charts_get_distinct_data_model_keys(self):
        chart = {
            "type": "chart",
            "chart_type": "bar",
            "labels": ["a"],
            "series": [{"name": "s", "values": [1]}],
        }
        envelope = infographic_response_to_envelope(_response(blocks=[chart, chart]))
        assert sorted(envelope.data_model["charts"]) == ["chart-0", "chart-1"]


class TestChartPresentationFieldsForwarded:
    """FEAT-527: presentation fields the Chart schema already accepts are
    forwarded from the block, omitted when the block's value is None."""

    def test_chart_presentation_fields_forwarded(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "layout": "half",
                        "color_by_sign": True,
                        "positive_color": "#0a0",
                        "negative_color": "#a00",
                        "x_axis_label": "Month",
                        "y_axis_label": "Revenue",
                        "description": "Revenue by month",
                        "trendline": True,
                        "x_axis_mode": "time",
                        "labels": ["a"],
                        "series": [{"name": "d", "values": [1]}],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["colorBySign"] is True
        assert props["layout"] == "half"
        assert props["positiveColor"] == "#0a0"
        assert props["negativeColor"] == "#a00"
        assert props["xAxisLabel"] == "Month"
        assert props["yAxisLabel"] == "Revenue"
        assert props["description"] == "Revenue by month"
        # Code-review regression guard: these two were previously always
        # None because ChartBlock had no matching fields — model_dump()
        # silently dropped them before the adapter ever saw them. Now that
        # ChartBlock declares both, prove they round-trip end to end.
        assert props["trendline"] is True
        assert props["xAxisMode"] == "time"
        assert "palette" not in props  # no per-series colours given

    def test_absent_presentation_fields_are_omitted(self):
        # NOTE: color_by_sign/stacked/show_legend default to False/True (not
        # None) on ChartBlock, so they are always forwarded — only fields
        # whose block default is genuinely None are omissible here.
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "labels": ["a"],
                        "series": [{"name": "d", "values": [1]}],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        for key in (
            "positiveColor",
            "negativeColor",
            "layout",
            "xAxisLabel",
            "yAxisLabel",
            "description",
            "palette",
            "trendline",
            "xAxisMode",
        ):
            assert key not in props
        assert props["colorBySign"] is False

    def test_per_series_colors_become_palette(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "labels": ["a"],
                        "series": [
                            {"name": "d1", "values": [1], "color": "#111"},
                            {"name": "d2", "values": [2], "color": "#222"},
                        ],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["palette"] == ["#111", "#222"]


class TestTableMapping:
    def test_columns_and_rows_map_with_total_rows(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "title": "Regions",
                        "columns": ["Region", "Total"],
                        "rows": [["North", 10], ["South", 20]],
                    }
                ]
            )
        )
        table = _sections(envelope)[0]["components"][0]
        assert table["component"] == "DataTable"
        props = table["properties"]
        assert props["columns"] == [
            {"name": "Region", "title": "Region"},
            {"name": "Total", "title": "Total"},
        ]
        assert props["totalRows"] == 2
        assert props["data"] == {"path": "/tables/table-0"}
        assert envelope.data_model["tables"]["table-0"] == [
            {"Region": "North", "Total": 10},
            {"Region": "South", "Total": 20},
        ]

    def test_columndef_objects_use_their_header(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "columns": [{"header": "Region"}, {"header": "Total"}],
                        "rows": [["North", 1]],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert [c["name"] for c in props["columns"]] == ["Region", "Total"]

    def test_ragged_rows_pad_with_none(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "columns": ["A", "B", "C"],
                        "rows": [["only-a"]],
                    }
                ]
            )
        )
        assert envelope.data_model["tables"]["table-0"] == [{"A": "only-a", "B": None, "C": None}]


class TestBlockTypeRemap:
    """FEAT-470 TASK-2541: bullet_list/checklist/image/card_grid/accordion/tab_view
    remap to Basic Catalog primitives instead of the legacy ``Card``-everything shape."""

    def test_hero_card_carries_trend_and_delta(self):
        envelope = infographic_response_to_envelope(_response())
        kpi = _sections(envelope)[0]["components"][0]
        assert kpi["component"] == "KPICard"
        assert kpi["properties"] == {
            "label": "Revenue",
            "value": "$1.2M",
            "delta": "+8%",
            "trend": "up",
        }

    def test_timeline_maps_date_to_timestamp(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "timeline",
                        "title": "Roadmap",
                        "events": [{"date": "2026-01", "title": "Kickoff", "description": "Go"}],
                    }
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["events"] == [{"timestamp": "2026-01", "title": "Kickoff", "description": "Go"}]

    def test_progress_expands_to_one_kpicard_per_item(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "progress",
                        "items": [
                            {"label": "Onboarding", "value": 80},
                            {"label": "Migration", "value": 45},
                        ],
                    }
                ]
            )
        )
        components = _sections(envelope)[0]["components"]
        assert [c["component"] for c in components] == ["KPICard", "KPICard"]
        assert components[0]["properties"]["label"] == "Onboarding"

    def test_bullet_list_maps_to_list_of_text(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "bullet_list", "items": ["one", "two"]}])
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "List"
        assert node["properties"]["direction"] == "vertical"
        children = node["properties"]["children"]
        assert [c["component"] for c in children] == ["Text", "Text"]
        assert [c["properties"]["text"] for c in children] == ["one", "two"]

    def test_bullet_list_columns_recorded_as_metadata_extension(self):
        """FEAT-527: `columns` is presentation-only — metadata.extensions,
        never a visible prop."""
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "bullet_list", "items": ["one", "two"], "columns": 2}])
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["properties"]["metadata"] == {"extensions": {"parrot_columns": 2}}

    def test_bullet_list_omits_metadata_when_columns_absent(self):
        envelope = infographic_response_to_envelope(_response(blocks=[{"type": "bullet_list", "items": ["one"]}]))
        node = _sections(envelope)[0]["components"][0]
        assert "metadata" not in node["properties"]

    def test_hero_card_forwards_icon_color_comparison_period(self):
        """FEAT-527."""
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "hero_card",
                        "label": "Revenue",
                        "value": "$1.2M",
                        "icon": "💰",
                        "color": "#0a0",
                        "comparison_period": "vs Q2",
                    }
                ]
            )
        )
        kpi = _sections(envelope)[0]["components"][0]
        assert kpi["properties"]["icon"] == "💰"
        assert kpi["properties"]["color"] == "#0a0"
        assert kpi["properties"]["comparisonPeriod"] == "vs Q2"

    def test_hero_card_omits_icon_color_comparison_period_when_absent(self):
        envelope = infographic_response_to_envelope(_response())
        kpi = _sections(envelope)[0]["components"][0]
        for key in ("icon", "color", "comparisonPeriod"):
            assert key not in kpi["properties"]

    def test_table_forwards_style(self):
        """FEAT-527."""
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "style": "striped",
                        "columns": [{"key": "k", "label": "K"}],
                        "rows": [["North", 10]],
                    }
                ]
            )
        )
        table = _sections(envelope)[0]["components"][0]
        assert table["component"] == "DataTable"
        assert table["properties"]["style"] == "striped"

    def test_table_omits_style_when_absent(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "table",
                        "columns": [{"key": "k", "label": "K"}],
                        "rows": [["North", 10]],
                    }
                ]
            )
        )
        table = _sections(envelope)[0]["components"][0]
        assert "style" not in table["properties"]

    def test_checklist_maps_to_list_of_checkbox(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "checklist",
                        "items": [
                            {"text": "Done", "checked": True},
                            {"text": "Pending"},
                        ],
                    }
                ]
            )
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "List"
        children = node["properties"]["children"]
        assert [c["component"] for c in children] == ["CheckBox", "CheckBox"]
        assert [c["properties"]["value"] for c in children] == [True, False]
        assert [c["properties"]["label"] for c in children] == ["Done", "Pending"]

    def test_callout_level_becomes_a_badge(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "callout", "level": "warning", "content": "Careful"}])
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "InfoCard"
        props = node["properties"]
        assert props["badge"] == "warning"
        assert props["body"] == "Careful"

    def test_quote_attribution_lands_in_the_footer(self):
        envelope = infographic_response_to_envelope(
            _response(blocks=[{"type": "quote", "text": "Ship it", "author": "Ana", "source": "Retro"}])
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "InfoCard"
        props = node["properties"]
        assert props["body"] == "Ship it"
        assert props["footer"] == "Ana — Retro"
        assert "title" not in props

    def test_image_maps_to_image_primitive(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "image",
                        "url": "https://example.test/a.png",
                        "alt": "Chart",
                        "caption": "Fig 1",
                    }
                ]
            )
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "Image"
        assert node["properties"] == {
            "url": "https://example.test/a.png",
            "fit": "contain",
            "description": "Chart",
        }

    def test_card_grid_maps_to_row_of_infocard(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "card_grid",
                        "columns": 2,
                        "cards": [
                            {"title": "C1", "body": "b1"},
                            {"title": "C2", "body": "b2"},
                        ],
                    },
                ]
            )
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "Row"
        children = node["properties"]["children"]
        assert [c["component"] for c in children] == ["InfoCard", "InfoCard"]
        assert [c["properties"]["title"] for c in children] == ["C1", "C2"]


class TestNewBlockConverters:
    """Tests for the explicit chain/steps/code converters (FEAT-301/2257, FEAT-470)."""

    def test_a2ui_chain_to_infocard(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "chain", "title": "Flow", "nodes": [{"label": "A"}, {"label": "B"}]},
                ]
            )
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "InfoCard"
        props = node["properties"]
        assert props["body"] == "A → B"
        assert props["title"] == "Flow"

    def test_a2ui_chain_vertical_direction_in_subtitle(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "chain", "nodes": [{"label": "A"}], "direction": "vertical"},
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["subtitle"] == "vertical"

    def test_a2ui_chain_horizontal_omits_subtitle(self):
        envelope = infographic_response_to_envelope(_response(blocks=[{"type": "chain", "nodes": [{"label": "A"}]}]))
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert "subtitle" not in props

    def test_a2ui_steps_to_list_of_text(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "steps", "steps": [{"label": "One", "description": "do it"}]},
                ]
            )
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "List"
        texts = [c["properties"]["text"] for c in node["properties"]["children"]]
        assert texts == ["1. One — do it"]

    def test_a2ui_code_to_infocard(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "code", "code": "print(1)", "language": "python"},
                ]
            )
        )
        node = _sections(envelope)[0]["components"][0]
        assert node["component"] == "InfoCard"
        props = node["properties"]
        assert props["body"] == "print(1)"
        assert props["badge"] == "python"

    def test_a2ui_code_omits_badge_without_language(self):
        envelope = infographic_response_to_envelope(_response(blocks=[{"type": "code", "code": "x"}]))
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert "badge" not in props

    def test_only_known_infocard_properties(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "code", "code": "x", "language": "py", "highlight_lines": [1]},
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        allowed = {"title", "subtitle", "body", "image", "badge", "footer"}
        assert set(props) <= allowed

    def test_i18n_title_flattened(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "code", "code": "x", "title": {"en": "Title", "es": "Titulo"}},
                ]
            )
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["title"] == "Title"

    def test_deterministic(self):
        payload = _response(
            blocks=[
                {"type": "chain", "nodes": [{"label": "A"}]},
            ]
        )
        a = infographic_response_to_envelope(payload)
        b = infographic_response_to_envelope(payload)
        assert a.model_dump() == b.model_dump()


class TestMalformedNestedItemsDegradeGracefully:
    """Malformed nested items (raw-dict input path) are skipped, not fatal."""

    def test_steps_with_flat_string_items_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [{"type": "steps", "steps": ["Do it", {"label": "Real"}]}],
            }
        )
        texts = [c["properties"]["text"] for c in _sections(envelope)[0]["components"][0]["properties"]["children"]]
        assert texts == ["1. Real"]

    def test_chain_with_malformed_node_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [{"type": "chain", "nodes": ["oops", {"label": "A"}]}],
            }
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["body"] == "A"

    def test_card_grid_with_malformed_card_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [{"type": "card_grid", "cards": [42, {"title": "Real"}]}],
            }
        )
        children = _sections(envelope)[0]["components"][0]["properties"]["children"]
        assert [c["properties"].get("title") for c in children] == ["Real"]

    def test_timeline_with_malformed_event_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [
                    {
                        "type": "timeline",
                        "events": [
                            "oops",
                            {"date": "2026-01", "title": "Real"},
                        ],
                    }
                ],
            }
        )
        props = _sections(envelope)[0]["components"][0]["properties"]
        assert props["events"] == [{"timestamp": "2026-01", "title": "Real"}]

    def test_progress_with_malformed_item_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [
                    {
                        "type": "progress",
                        "items": [
                            "oops",
                            {"label": "Real", "value": 50},
                        ],
                    }
                ],
            }
        )
        components = _sections(envelope)[0]["components"]
        assert [c["properties"]["label"] for c in components] == ["Real"]

    def test_checklist_with_malformed_item_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [
                    {
                        "type": "checklist",
                        "items": [
                            "oops",
                            {"text": "Real", "checked": True},
                        ],
                    }
                ],
            }
        )
        children = _sections(envelope)[0]["components"][0]["properties"]["children"]
        assert [c["properties"]["label"] for c in children] == ["Real"]

    def test_malformed_top_level_block_is_skipped(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": ["oops", {"type": "hero_card", "label": "Real", "value": "1"}],
            }
        )
        components = _sections(envelope)[0]["components"]
        assert [c["properties"]["label"] for c in components] == ["Real"]

    def test_accordion_with_malformed_item_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [
                    {
                        "type": "accordion",
                        "items": [
                            "oops",
                            {"title": "Real", "content_blocks": []},
                        ],
                    }
                ],
            }
        )
        tabs_node = _sections(envelope)[0]["components"][0]
        assert tabs_node["component"] == "Tabs"
        assert [t["title"] for t in tabs_node["properties"]["tabs"]] == ["Real"]

    def test_tab_view_with_malformed_pane_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [
                    {
                        "type": "tab_view",
                        "tabs": [
                            "oops",
                            {"label": "Real", "blocks": []},
                        ],
                    }
                ],
            }
        )
        tabs_node = _sections(envelope)[0]["components"][0]
        assert [t["title"] for t in tabs_node["properties"]["tabs"]] == ["Real"]

    def test_table_with_malformed_column_does_not_raise(self):
        envelope = infographic_response_to_envelope(
            {
                "blocks": [{"type": "table", "columns": [42, "Real"], "rows": [[1, 2]]}],
            }
        )
        table = _sections(envelope)[0]["components"][0]
        assert [c["name"] for c in table["properties"]["columns"]] == ["column", "Real"]


class TestAllBlocksEnvelope:
    """Full 19-block-type payload lowers without error (FEAT-301/2257, FEAT-470)."""

    def test_a2ui_envelope_new_blocks(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "title", "title": "Test Infographic"},
                    {"type": "hero_card", "label": "Metric", "value": "42"},
                    {"type": "summary", "content": "Summary text"},
                    {"type": "chart", "chart_type": "bar", "labels": ["A"], "series": [{"name": "s", "values": [1]}]},
                    {"type": "bullet_list", "items": ["item 1"]},
                    {"type": "table", "columns": ["A"], "rows": [["1"]]},
                    {"type": "image", "url": "data:image/png;base64,AA==", "alt": "img"},
                    {"type": "quote", "text": "Quote", "author": "Author"},
                    {"type": "callout", "level": "info", "content": "Info"},
                    {"type": "divider"},
                    {"type": "timeline", "events": [{"date": "2026-01-01", "title": "Event"}]},
                    {"type": "progress", "items": [{"label": "Task", "value": "80"}]},
                    {"type": "accordion", "items": [{"title": "Section", "content_blocks": []}]},
                    {"type": "checklist", "items": [{"text": "Done", "checked": True}]},
                    {
                        "type": "tab_view",
                        "tabs": [
                            {"id": "t1", "label": "Tab1", "blocks": []},
                            {"id": "t2", "label": "Tab2", "blocks": []},
                        ],
                    },
                    {"type": "chain", "nodes": [{"label": "A"}, {"label": "B"}]},
                    {"type": "steps", "steps": [{"label": "Step 1", "description": "Do thing"}]},
                    {"type": "code", "code": "print('hello')", "language": "python"},
                    {"type": "card_grid", "cards": [{"title": "Card 1", "body": "Content"}], "columns": 2},
                ]
            )
        )
        assert envelope is not None
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)
        _validate_full_tree(envelope)


class TestTabsNesting:
    """FEAT-470 TASK-2541: accordion/tab_view nest as Tabs within the CURRENT
    section (not flattened into sibling sections) — unless nesting exceeds
    ``_MAX_NESTING_DEPTH``, which degrades to the legacy flatten behavior."""

    def test_accordion_nests_as_tabs_in_current_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "accordion",
                        "title": "Phases",
                        "items": [
                            {
                                "title": "Phase 1",
                                "content_blocks": [{"type": "hero_card", "label": "A", "value": "1"}],
                            },
                            {
                                "title": "Phase 2",
                                "content_blocks": [{"type": "summary", "title": "x", "content": "Later"}],
                            },
                        ],
                    }
                ]
            )
        )
        sections = _sections(envelope)
        assert len(sections) == 1
        tabs_node = sections[0]["components"][0]
        assert tabs_node["component"] == "Tabs"
        tabs = tabs_node["properties"]["tabs"]
        assert [t["title"] for t in tabs] == ["Phase 1", "Phase 2"]
        pane_one = tabs[0]["child"]
        assert pane_one["component"] == "Column"
        assert pane_one["properties"]["children"][0]["component"] == "KPICard"

    def test_tab_view_nests_as_tabs_in_current_section(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {
                        "type": "tab_view",
                        "tabs": [
                            {
                                "id": "a",
                                "label": "Overview",
                                "blocks": [{"type": "hero_card", "label": "A", "value": "1"}],
                            },
                            {"id": "b", "label": "Detail", "blocks": []},
                        ],
                    }
                ]
            )
        )
        tabs_node = _sections(envelope)[0]["components"][0]
        assert tabs_node["component"] == "Tabs"
        assert [t["title"] for t in tabs_node["properties"]["tabs"]] == ["Overview", "Detail"]

    def test_nested_title_block_inside_a_pane_does_not_hijack_the_surface_title(self):
        envelope = infographic_response_to_envelope(
            _response(
                blocks=[
                    {"type": "title", "title": "Real Title"},
                    {
                        "type": "tab_view",
                        "tabs": [
                            {
                                "id": "a",
                                "label": "Tab",
                                "blocks": [{"type": "title", "title": "Nested"}],
                            },
                            {"id": "b", "label": "Other", "blocks": []},
                        ],
                    },
                ]
            )
        )
        assert _root_component(envelope).model_extra["title"] == "Real Title"

    def test_deeply_nested_containers_degrade_to_sibling_sections(self):
        """Beyond _MAX_NESTING_DEPTH, containers fall back to the legacy
        flatten-into-sibling-sections behavior instead of nesting Tabs."""
        # Build a chain of nested tab_view blocks deeper than the cap.
        from parrot.outputs.a2ui.adapters.infographic import _MAX_NESTING_DEPTH

        innermost = {"type": "hero_card", "label": "Deep", "value": "1"}
        blocks = innermost
        for i in range(_MAX_NESTING_DEPTH + 2):
            blocks = {
                "type": "tab_view",
                "tabs": [
                    {"id": f"t{i}a", "label": f"L{i}", "blocks": [blocks]},
                    {"id": f"t{i}b", "label": "Empty", "blocks": []},
                ],
            }

        envelope = infographic_response_to_envelope(_response(blocks=[blocks]))
        # Should not raise, and should validate structurally.
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)


class TestLowering:
    def test_adapted_envelope_lowers_to_a_basic_tree(self):
        envelope = infographic_response_to_envelope(_response())
        component = envelope.components[0]
        tree = get_component("Infographic").component_cls().lower(component, envelope.data_model or {})
        assert tree.component == "Card"
        # Lowering is pure: the nested KPICard/Chart children resolved through
        # their own registered lower() without raising.
        assert tree.child is not None
